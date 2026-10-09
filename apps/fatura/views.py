"""Bayi tarafı: kurum seç → numara → sorgu → fatura seç → öde.

Sorgu robotta yapılır; bayinin sayfası sonucu HTMX ile birkaç saniyede bir
sorar. Ödeme açılınca tutar bakiyeden düşer; yönetim sağlayıcıda ödeyip
"Ödendi" der, bayi sonucu ödeme sayfasında görür.
"""

from decimal import Decimal
from urllib.parse import urlencode
from uuid import uuid4

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.bayi.yetki import bayi_gerekli
from apps.fatura.models import Kategori, Kurum, Odeme, Sorgu
from apps.fatura.services import (
    ODEME_SURESI,
    kapali_mesaji,
    odeme_baslat,
    odenmis_faturalar,
    robot_cevrimici_mi,
    sabit_odeme_baslat,
    satistaki_kurum,
    sorgu_baslat,
    suresi_dolanlari_kapat,
)
from apps.finans.services import SiparisVerilemez
from apps.magaza.models import Siparis

SON_ODEME_ADEDI = 5


def _bakiye(request):
    cuzdan = getattr(request.user, "cuzdan", None)
    return cuzdan.bakiye if cuzdan else Decimal("0")


def _kurum(kod):
    kurum = satistaki_kurum(kod)
    if kurum is None:
        raise Http404("Kurum bulunamadı.")
    return kurum


@login_required
@bayi_gerekli
def index(request):
    """Bölümler (GSM, İnternet, Elektrik…) ve içlerinde kurumlar, tek kolonda."""
    kurumlar = list(Kurum.objects.satista().select_related("kategori", "operator"))
    bolumler = []
    for kategori in Kategori.objects.filter(aktif=True):
        icindekiler = [k for k in kurumlar if k.kategori_id == kategori.pk]
        if icindekiler:
            bolumler.append((kategori.ad, icindekiler))
    digerleri = [k for k in kurumlar if k.kategori_id is None]
    if digerleri:
        bolumler.append(("Diğer", digerleri))
    return render(
        request,
        "fatura/index.html",
        {
            "bolumler": bolumler,
            "bakiye": _bakiye(request),
            "son_odemeler": Odeme.objects.filter(bayi=request.user).select_related("siparis")[:SON_ODEME_ADEDI],
        },
    )


@login_required
@bayi_gerekli
def kurum(request, kod):
    kurum_kaydi = _kurum(kod)
    bakiye = _bakiye(request)
    return render(
        request,
        "fatura/kurum.html",
        {
            "kurum": kurum_kaydi,
            "bakiye": bakiye,
            "numara": request.GET.get("numara", "")[:40],
            "robot_acik": robot_cevrimici_mi() if kurum_kaydi.sorgulu else True,
            "kapali_mesaji": kapali_mesaji() if kurum_kaydi.sorgulu else "",
            "yeterli": kurum_kaydi.sorgulu or bakiye >= (kurum_kaydi.bayi_fiyati or 0),
            "islem_anahtari": uuid4().hex,
        },
    )


def _geri_forma(kurum_kaydi, numara):
    return redirect(f"{kurum_kaydi.get_absolute_url()}?{urlencode({'numara': (numara or '').strip()[:40]})}")


@require_POST
@login_required
@bayi_gerekli
def sorgula(request, kod):
    kurum_kaydi = _kurum(kod)
    numara = request.POST.get("numara", "")
    try:
        sorgu = sorgu_baslat(request.user, kurum_kaydi, numara)
    except SiparisVerilemez as hata:
        messages.error(request, str(hata))
        return _geri_forma(kurum_kaydi, numara)
    return redirect(sorgu)


@require_POST
@login_required
@bayi_gerekli
def ode(request, kod):
    """Sorgusuz kalem (HGS 100 TL gibi): sabit fiyatı bakiyeden öder."""
    kurum_kaydi = _kurum(kod)
    numara = request.POST.get("numara", "")
    anahtar = (request.POST.get("islem_anahtari") or "").strip()[:64]
    try:
        odeme = sabit_odeme_baslat(request.user, kurum_kaydi, numara, anahtar=anahtar)
    except IntegrityError:
        # Aynı form ikinci kez geldi: tekil anahtara çarptı, para bir kez düştü.
        return _anahtarla_bul(request, anahtar)
    except SiparisVerilemez as hata:
        messages.error(request, str(hata))
        return _geri_forma(kurum_kaydi, numara)
    return redirect(odeme)


def _anahtarla_bul(request, anahtar):
    siparis = Siparis.objects.filter(bayi=request.user, islem_anahtari=anahtar, fatura__isnull=False).first()
    if not anahtar or siparis is None:
        raise Http404("Ödeme bulunamadı.")
    return redirect(siparis.fatura)


# -- Sorgu ---------------------------------------------------------------


def _sorgu(request, referans):
    return get_object_or_404(
        Sorgu.objects.select_related("kurum", "kurum__operator"), bayi=request.user, referans_no=referans
    )


def _sorgu_baglami(request, sorgu):
    """Sonuç ekranı: her faturaya bayinin ödeyeceği ve müşteri fiyatı eklenir."""
    kurum_kaydi = sorgu.kurum
    odenmis = odenmis_faturalar(kurum_kaydi, sorgu.numara) if sorgu.faturalar else set()
    satirlar = []
    for f in sorgu.faturalar:
        toplam = Decimal(f["toplam_tutar"])
        satirlar.append({
            **f,
            "bayi_tutari": kurum_kaydi.bayi_tutari(toplam),
            "musteri_tutari": kurum_kaydi.musteri_tutari(toplam),
            "odendi": f["fatura_no"] in odenmis,
        })
    eski = bool(sorgu.sonuc_tarihi and timezone.now() - sorgu.sonuc_tarihi > ODEME_SURESI)
    return {
        "sorgu": sorgu,
        "kurum": kurum_kaydi,
        "satirlar": satirlar,
        "odenebilir": [s for s in satirlar if not s["odendi"]],
        "tavsiye_var": kurum_kaydi.tavsiye_ek > 0,
        "eski": eski,
        "bakiye": _bakiye(request),
        "islem_anahtari": uuid4().hex,
    }


@login_required
@bayi_gerekli
def sorgu(request, referans):
    suresi_dolanlari_kapat()
    sorgu_kaydi = _sorgu(request, referans)
    return render(request, "fatura/sorgu.html", _sorgu_baglami(request, sorgu_kaydi))


@login_required
@bayi_gerekli
def sorgu_durum(request, referans):
    """HTMX: sonuç geldi mi? Geldiyse kutu yenilenir, yoklama durur."""
    suresi_dolanlari_kapat()
    sorgu_kaydi = _sorgu(request, referans)
    return render(request, "fatura/parca_sorgu.html", _sorgu_baglami(request, sorgu_kaydi))


@require_POST
@login_required
@bayi_gerekli
def sorgu_ode(request, referans):
    sorgu_kaydi = _sorgu(request, referans)
    anahtar = (request.POST.get("islem_anahtari") or "").strip()[:64]
    try:
        odeme = odeme_baslat(request.user, sorgu_kaydi, request.POST.getlist("fatura"), anahtar=anahtar)
    except IntegrityError:
        return _anahtarla_bul(request, anahtar)
    except SiparisVerilemez as hata:
        messages.error(request, str(hata))
        return redirect(sorgu_kaydi)
    return redirect(odeme)


# -- Ödeme ---------------------------------------------------------------


def _odeme(request, referans):
    return get_object_or_404(
        Odeme.objects.select_related("siparis", "kurum"), bayi=request.user, siparis__referans_no=referans
    )


@login_required
@bayi_gerekli
def odeme(request, referans):
    return render(request, "fatura/odeme.html", {"odeme": _odeme(request, referans)})


@login_required
@bayi_gerekli
def odeme_durum(request, referans):
    return render(request, "fatura/parca_odeme.html", {"odeme": _odeme(request, referans)})


@login_required
@bayi_gerekli
def odemeler(request):
    """Bayinin bütün fatura ödemeleri; numara, abone ya da referansla aranır."""
    sorgu_qs = Odeme.objects.filter(bayi=request.user).select_related("siparis")
    q = (request.GET.get("q") or "").strip()[:40]
    if q:
        sorgu_qs = sorgu_qs.filter(
            Q(numara__icontains=q.replace(" ", ""))
            | Q(abone_adi__icontains=q)
            | Q(kurum_adi__icontains=q)
            | Q(siparis__referans_no__iexact=q)
        )
    sayfa = Paginator(sorgu_qs, 30).get_page(request.GET.get("sayfa"))
    return render(request, "fatura/odemeler.html", {"sayfa": sayfa, "odemeler": sayfa.object_list, "q": q})
