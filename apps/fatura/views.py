"""Bayi tarafı: kurum seç → numara → sorgu → fatura seç → öde.

Sorgu robotta yapılır; bayinin sayfası sonucu HTMX ile birkaç saniyede bir
sorar. Ödeme açılınca tutar bakiyeden düşer; yönetim sağlayıcıda ödeyip
"Ödendi" der, bayi sonucu ödeme sayfasında görür.
"""

import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode
from uuid import uuid4

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.bayi.dekont import firma
from apps.bayi.yetki import bayi_gerekli
from apps.fatura import sepet as fatura_sepeti
from apps.fatura.models import Kategori, Kurum, Odeme, OdemeDurumu, Sorgu
from apps.fatura.services import (
    ODEME_SURESI,
    dekont_ozeti,
    fatura_tutari,
    fiyat_grubu,
    grup_tutarlari,
    hizmet_bedeli,
    kapali_mesaji,
    sabit_fiyat,
    odeme_baslat,
    odenmis_faturalar,
    robot_cevrimici_mi,
    sabit_odeme_baslat,
    satistaki_kurum,
    sepeti_ode,
    sorgu_baslat,
    suresi_dolanlari_kapat,
    vade_durumu,
)
from apps.finans.services import SiparisVerilemez
from apps.magaza.models import Siparis

SON_ODEME_ADEDI = 5
# Bir dekontta en çok bu kadar ödeme: Ödemelerim'in bir sayfası.
SEPET_SINIRI = 30


def _bakiye(request):
    cuzdan = getattr(request.user, "cuzdan", None)
    return cuzdan.bakiye if cuzdan else Decimal("0")


def _kurum(request, kod):
    """Bayinin fiyat grubunda açık kurum; sorgusuz kalem fiyatı yoksa görünmez."""
    kurum = satistaki_kurum(kod, fiyat_grubu(request.user))
    if kurum is None:
        raise Http404("Kurum bulunamadı.")
    return kurum


@login_required
@bayi_gerekli
def index(request):
    """Bölümler (GSM, İnternet, Elektrik…) ve içlerinde kurumlar, tek kolonda."""
    grup = fiyat_grubu(request.user)
    kurumlar = list(Kurum.objects.bayiye_acik(grup).select_related("kategori", "operator"))
    # Kartta sorgusuz kalemin fiyatı: müşteri fiyatı, yoksa bayinin grubundaki fiyat.
    tutarlar = grup_tutarlari(grup, kurumlar)
    for k in kurumlar:
        if not k.sorgulu:
            k.gosterim_fiyati = k.tavsiye or sabit_fiyat(k, grup, tutarlar)
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
            "sepet_adedi": len(fatura_sepeti.kalemler(request)),
        },
    )


@login_required
@bayi_gerekli
def kurum(request, kod):
    kurum_kaydi = _kurum(request, kod)
    bakiye = _bakiye(request)
    fiyat = None if kurum_kaydi.sorgulu else sabit_fiyat(kurum_kaydi, fiyat_grubu(request.user))
    return render(
        request,
        "fatura/kurum.html",
        {
            "kurum": kurum_kaydi,
            "bakiye": bakiye,
            "numara": request.GET.get("numara", "")[:40],
            "robot_acik": robot_cevrimici_mi() if kurum_kaydi.sorgulu else True,
            "kapali_mesaji": kapali_mesaji() if kurum_kaydi.sorgulu else "",
            "fiyat": fiyat,
            "kazanc": (kurum_kaydi.tavsiye - fiyat) if fiyat and kurum_kaydi.tavsiye else None,
            "yeterli": kurum_kaydi.sorgulu or bakiye >= (fiyat or 0),
            "islem_anahtari": uuid4().hex,
            "sepet_adedi": len(fatura_sepeti.kalemler(request)),
        },
    )


def _geri_forma(kurum_kaydi, numara):
    return redirect(f"{kurum_kaydi.get_absolute_url()}?{urlencode({'numara': (numara or '').strip()[:40]})}")


@require_POST
@login_required
@bayi_gerekli
def sorgula(request, kod):
    kurum_kaydi = _kurum(request, kod)
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
    kurum_kaydi = _kurum(request, kod)
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
    hizmet = hizmet_bedeli(kurum_kaydi, fiyat_grubu(request.user))
    odenmis = odenmis_faturalar(kurum_kaydi, sorgu.numara) if sorgu.faturalar else set()
    satirlar = []
    bugun = timezone.localdate()
    # Sorgudan sonra bayinin grubundaki rakam silindiyse ödenemez tutar
    # gösterilmez; ekran "satışta değil" der (ödeme zaten reddeder).
    for f in sorgu.faturalar if hizmet is not None else []:
        bedel = fatura_tutari(f)
        satirlar.append({
            **f,
            "bayi_tutari": kurum_kaydi.bayi_tutari(bedel, hizmet),
            "musteri_tutari": kurum_kaydi.musteri_tutari(bedel),
            "odendi": f["fatura_no"] in odenmis,
            "vade": vade_durumu(f.get("son_odeme_tarihi"), bugun),
        })
    eski = bool(sorgu.sonuc_tarihi and timezone.now() - sorgu.sonuc_tarihi > ODEME_SURESI)
    return {
        "sorgu": sorgu,
        "kurum": kurum_kaydi,
        "satirlar": satirlar,
        "odenebilir": [s for s in satirlar if not s["odendi"]],
        "tavsiye_var": bool(kurum_kaydi.tavsiye),
        "satista": hizmet is not None,
        "eski": eski,
        "bakiye": _bakiye(request),
        "islem_anahtari": uuid4().hex,
        "sepet_adedi": len(fatura_sepeti.kalemler(request)),
        "sepette": {no for ref, no in fatura_sepeti.kalemler(request) if ref == sorgu.referans_no},
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


# -- Sepet ---------------------------------------------------------------
#
# Müşterinin birkaç kurumdaki faturası tek seferde ödenir (`apps/fatura/sepet.py`).
# Sepet oturumdadır; tutar her zaman sorgunun kaydından okunur.


@require_POST
@login_required
@bayi_gerekli
def sepete_ekle(request, referans):
    sorgu_kaydi = _sorgu(request, referans)
    try:
        eklenen = fatura_sepeti.ekle(request, sorgu_kaydi, request.POST.getlist("fatura"))
    except SiparisVerilemez as hata:
        messages.error(request, str(hata))
        return redirect(sorgu_kaydi)
    adet = len(fatura_sepeti.kalemler(request))
    messages.success(
        request,
        f"{sorgu_kaydi.kurum.ad}: {eklenen} fatura sepete eklendi (sepette {adet}). "
        "Başka kurumu seç ya da sepete geçip hepsini öde.",
    )
    return redirect("fatura:index")


def _para(deger):
    """Formdan gelen tutar ("1.250,50", "1.000", "1250.5") → Decimal; okunamazsa None.

    Virgül varsa noktalar binliktir; virgülsüz "1.000" da binliktir (bayi
    bin lirayı böyle yazar), "1250.5" ise kuruştur.
    """
    metin = str(deger or "").strip().replace(" ", "")
    if "," in metin or re.fullmatch(r"\d{1,3}(\.\d{3})+", metin):
        metin = metin.replace(".", "").replace(",", ".")
    try:
        tutar = Decimal(metin).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None
    return tutar if tutar.is_finite() and tutar >= 0 else None


@login_required
@bayi_gerekli
def sepet(request):
    """Sepetteki faturalar, toplam ve para üstü; "Hepsini öde" tek seferde öder."""
    ozet = fatura_sepeti.ozet(request.user, fatura_sepeti.kalemler(request))
    bakiye = _bakiye(request)
    return render(
        request,
        "fatura/sepet.html",
        {
            **ozet,
            "bakiye": bakiye,
            "yetmiyor": ozet["bayi_toplam"] > bakiye,
            "tavsiye_var": any(g["kurum"].tavsiye for g in ozet["gruplar"]),
            "islem_anahtari": uuid4().hex,
        },
    )


@require_POST
@login_required
@bayi_gerekli
def sepetten_cikar(request):
    fatura_sepeti.cikar(request, request.POST.get("sorgu", ""), request.POST.get("fatura", ""))
    return redirect("fatura:sepet")


def _sepet_sonucuna(odemeler, alinan):
    sorgu = [("odeme", o.referans_no) for o in odemeler]
    if alinan is not None:
        sorgu.append(("alinan", str(alinan)))
    return redirect(f"{reverse('fatura:sepet-tamam')}?{urlencode(sorgu)}")


@require_POST
@login_required
@bayi_gerekli
def sepet_ode(request):
    """Sepeti öder: hepsi ya da hiçbiri. Aynı form ikinci kez gelirse açılanları gösterir."""
    anahtar = (request.POST.get("islem_anahtari") or "").strip()[:32]
    alinan = _para(request.POST.get("alinan"))
    kalemler = fatura_sepeti.kalemler(request)
    if not kalemler:
        # Ödenmiş sepetin formu yeniden geldi (geri tuşu, çift dokunuş).
        onceki = list(
            Odeme.objects.filter(bayi=request.user, siparis__islem_anahtari__startswith=f"{anahtar}:")
            .select_related("siparis")
        ) if anahtar else []
        if onceki:
            return _sepet_sonucuna(onceki, alinan)
        messages.error(request, "Sepet boş.")
        return redirect("fatura:sepet")
    ozet = fatura_sepeti.ozet(request.user, kalemler)
    if ozet["sorunlu"]:
        messages.error(request, "Sepette ödenemeyecek fatura var; işaretli satırları çıkar ya da yeniden sorgula.")
        return redirect("fatura:sepet")
    try:
        odemeler = sepeti_ode(request.user, kalemler, anahtar=anahtar or None)
    except IntegrityError:
        return redirect("fatura:sepet")
    except SiparisVerilemez as hata:
        messages.error(request, str(hata))
        return redirect("fatura:sepet")
    fatura_sepeti.bosalt(request)
    return _sepet_sonucuna(odemeler, alinan)


@login_required
@bayi_gerekli
def sepet_tamam(request):
    """Ödenen sepet: ödemelerin durumu, alınan ve para üstü, tek dekont."""
    referanslar = list(dict.fromkeys(r.strip() for r in request.GET.getlist("odeme") if r.strip()))
    odemeler = list(
        Odeme.objects.filter(bayi=request.user, siparis__referans_no__in=referanslar[:SEPET_SINIRI])
        .select_related("siparis", "kurum")
        .order_by("olusturma_tarihi", "pk")
    )
    if not odemeler:
        raise Http404("Ödeme bulunamadı.")
    # Ekran müşteriye dönük: satırlarda ve toplamda dekonttaki rakam, bayinin alışı değil.
    satirlar = [(o, dekont_ozeti(o)["toplam"]) for o in odemeler]
    musteri = sum((t for o, t in satirlar if o.durum != OdemeDurumu.IPTAL), Decimal("0"))
    alinan = _para(request.GET.get("alinan"))
    dekontlu = [o for o in odemeler if o.durum != OdemeDurumu.IPTAL]
    sorgu = [("odeme", o.referans_no) for o in dekontlu]
    if alinan is not None:
        sorgu.append(("alinan", str(alinan)))
    return render(
        request,
        "fatura/sepet_tamam.html",
        {
            "satirlar": satirlar,
            "musteri_toplam": musteri,
            "alinan": alinan,
            "para_ustu": alinan - musteri if alinan is not None and alinan >= musteri else None,
            "dekont_url": f"{reverse('fatura:dekont')}?{urlencode(sorgu)}" if dekontlu else "",
            "suruyor": any(o.bekliyor for o in odemeler),
        },
    )


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


def _dekont(request, odemeler, geri):
    bloklar = [dekont_ozeti(odeme) for odeme in odemeler]
    toplam = sum((b["toplam"] for b in bloklar), Decimal("0"))
    # Sepetten gelince müşteriden alınan ve para üstü de fişe yazılır;
    # kayıtta tutulmaz, yalnızca bu baskı içindir.
    alinan = _para(request.GET.get("alinan"))
    if alinan is not None and alinan < toplam:
        alinan = None
    return render(
        request,
        "fatura/dekont.html",
        {
            "bloklar": bloklar,
            "toplam": toplam,
            "alinan": alinan,
            "para_ustu": alinan - toplam if alinan is not None else None,
            "referans": ", ".join(o.referans_no for o in odemeler),
            "firma": firma(request.user),
            "geri": geri,
        },
    )


@login_required
@bayi_gerekli
def odeme_dekont(request, referans):
    """Tek ödemenin dekontu; ödemedeki bütün faturalar bir arada.

    Ödeme sürerken de verilir (durum "Ödeniyor" yazar): ödemeyi yönetim elle
    yapar, sürebilir, müşteri tezgâhta fiş bekliyor. İptal edilen ödemenin
    dekontu yoktur — para bayiye döndü.
    """
    odeme = _odeme(request, referans)
    if odeme.durum == OdemeDurumu.IPTAL:
        raise Http404("İptal edilen ödemenin dekontu verilmez.")
    return _dekont(request, [odeme], odeme.get_absolute_url())


@login_required
@bayi_gerekli
def dekont(request):
    """Sepet: Ödemelerim'de işaretlenen ödemeler tek dekontta, tek toplamla.

    Müşteri birkaç faturasını (elektrik, su, telefon) birlikte ödetiyor;
    her ödeme ayrı kayıttır ama müşteriye tek fiş verilir. Başkasının ya da
    iptal edilmiş ödeme sessizce düşer.
    """
    referanslar = list(dict.fromkeys(r.strip() for r in request.GET.getlist("odeme") if r.strip()))
    odemeler = list(
        Odeme.objects.filter(bayi=request.user, siparis__referans_no__in=referanslar[:SEPET_SINIRI])
        .exclude(durum=OdemeDurumu.IPTAL)
        .select_related("siparis", "kurum")
        .order_by("olusturma_tarihi", "pk")
    )
    if not odemeler:
        raise Http404("Dekonta eklenecek ödeme yok.")
    return _dekont(request, odemeler, reverse("fatura:odemeler"))


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
