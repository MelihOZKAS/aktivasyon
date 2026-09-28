"""Bayi tarafı: kategori, paket, yükleme ve işlemin sonucu.

`/kontor/…` ve oyunlar için `/oyun/…` altında, `@bayi_gerekli` ile
korunur. İki bölüm aynı görünümleri kullanır; `oyun` URL'den gelir ve
yalnızca hangi kategorilerin listeleneceğini belirler. Kategori yanlış
bölümün adresinden istenirse doğrusuna yönlenir. Akış tezgâhtaki sırayla
aynıdır: operatörü/oyunu seç → paketi seç → numarayı yaz → yükle. Yükleme
basılınca bayi sağlayıcıyı beklemez; işlem sayfasına düşer, sayfa sonucu
kendisi sorar.
"""

from functools import wraps
from urllib.parse import urlencode
from uuid import uuid4

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from apps.bayi.telefon import normalize
from apps.bayi.yetki import bayi_gerekli
from apps.finans.services import SiparisVerilemez
from apps.kontor.models import Islem, IslemDurumu, Kategori, Paket
from apps.kontor.sorgu import SorguHatasi
from apps.kontor.services import (
    fiyatlandir,
    numarayi_sorgula,
    isle,
    kategori_listesi,
    satistaki_paketler,
    yukleme_baslat,
)

SON_ISLEM_ADEDI = 5

# Sağlayıcıyla konuşan görünümler istek transaction'ının dışında çalışır
# (`ATOMIC_REQUESTS` açık). Gönderim kaydı ağa çıkmadan **commit edilmeli**:
# istek boyunca açık kalan bir transaction'da süreç düşerse kayıt da
# kaybolur ve işçi aynı işlemi ikinci kez gönderirdi. Sahiplik (kilit)
# de ancak commit edilince diğer süreçlere görünür.
atomik_degil = transaction.non_atomic_requests


def _bakiye(request):
    cuzdan = getattr(request.user, "cuzdan", None)
    return cuzdan.bakiye if cuzdan else 0


def _islemler(request):
    return Islem.objects.filter(bayi=request.user).select_related(
        "siparis", "kategori", "kategori__operator"
    )


@login_required
@bayi_gerekli
def kategoriler(request, oyun=False):
    return render(
        request,
        "kontor/kategoriler.html",
        {
            "oyun": oyun,
            "kategoriler": kategori_listesi(oyun=oyun),
            "bakiye": _bakiye(request),
            "son_islemler": _islemler(request).filter(kategori__oyun=oyun)[:SON_ISLEM_ADEDI],
        },
    )


class _YanlisBolum(Exception):
    def __init__(self, kategori):
        self.kategori = kategori


def _satistaki_kategori(slug, oyun=False):
    kategori_kaydi = get_object_or_404(Kategori.objects.select_related("operator"), slug=slug, aktif=True)
    if kategori_kaydi.oyun != oyun:
        raise _YanlisBolum(kategori_kaydi)
    return kategori_kaydi


def _bolum(gorunum):
    """Kategori öbür bölümdeyse (oyun ↔ kontör) doğru adrese yönlendirir."""

    @wraps(gorunum)
    def sarmalayici(request, *args, **kwargs):
        try:
            return gorunum(request, *args, **kwargs)
        except _YanlisBolum as hata:
            return redirect(hata.kategori.get_absolute_url())

    return sarmalayici


@login_required
@bayi_gerekli
@_bolum
def kategori(request, slug, oyun=False):
    kategori_kaydi = _satistaki_kategori(slug, oyun)
    paketler = satistaki_paketler(kategori_kaydi, request.user)
    return render(
        request,
        "kontor/kategori.html",
        {
            "kategori": kategori_kaydi,
            "paketler": paketler,
            "bakiye": _bakiye(request),
            "tavsiye_var": any(p.tavsiye for p in paketler),
        },
    )


@login_required
@bayi_gerekli
@_bolum
def sorgu(request, slug, oyun=False):
    """HTMX: numaranın alabileceği paketler. Salt okuma, para oynamaz."""
    kategori_kaydi = _satistaki_kategori(slug, oyun)
    baglam = {"kategori": kategori_kaydi, "bakiye": _bakiye(request)}
    try:
        baglam.update(
            numarayi_sorgula(
                kategori_kaydi,
                request.GET.get("hedef", ""),
                request.user,
                yenile=request.GET.get("yenile") == "1",
            )
        )
    except SorguHatasi as hata:
        baglam["hata"] = str(hata)
    return render(request, "kontor/parca_sorgu.html", baglam)


def _paket(kategori_kaydi, kod):
    return get_object_or_404(
        Paket.objects.satista().select_related("kategori"), kategori=kategori_kaydi, kod=kod
    )


@login_required
@bayi_gerekli
@_bolum
def paket(request, slug, kod, oyun=False):
    """Numaranın yazıldığı ve ödemenin onaylandığı sayfa.

    Listede tek dokunuşla para düşmesin: bayi ne yüklediğini, fiyatını ve
    numarayı burada bir kez daha görür. Bakiye yetmiyorsa düğme gizlenmez,
    sebebi yazılır.
    """
    kategori_kaydi = _satistaki_kategori(slug, oyun)
    paket_kaydi = fiyatlandir([_paket(kategori_kaydi, kod)], request.user)[0]
    bakiye = _bakiye(request)
    return render(
        request,
        "kontor/paket.html",
        {
            "kategori": kategori_kaydi,
            "paket": paket_kaydi,
            "bakiye": bakiye,
            "yeterli": paket_kaydi.fiyat > 0 and bakiye >= paket_kaydi.fiyat,
            "islem_anahtari": uuid4().hex,
            "hedef": request.GET.get("hedef", "")[:64],
        },
    )


@atomik_degil
@login_required
@bayi_gerekli
@_bolum
def yukle(request, slug, kod, oyun=False):
    kategori_kaydi = _satistaki_kategori(slug, oyun)
    paket_kaydi = _paket(kategori_kaydi, kod)
    if request.method != "POST":
        return redirect(paket_kaydi.get_absolute_url())
    hedef = request.POST.get("hedef", "")
    anahtar = (request.POST.get("islem_anahtari") or "").strip()[:64] or None
    try:
        islem = yukleme_baslat(request.user, paket_kaydi, hedef, anahtar=anahtar)
    except IntegrityError:
        # Aynı form iki kez geldi ve ikincisi tekil anahtara çarptı: yeni işlem
        # açılmadı, para bir kez düştü. Bayi var olan işleme gider.
        mevcut = Islem.objects.filter(bayi=request.user, siparis__islem_anahtari=anahtar).first()
        if anahtar and mevcut is not None:
            return redirect("kontor:islem", referans=mevcut.siparis.referans_no)
        raise
    except SiparisVerilemez as hata:
        messages.error(request, str(hata))
        # Yazdığı numara kaybolmasın; bayi düzeltip yeniden basar.
        return redirect(f"{paket_kaydi.get_absolute_url()}?{urlencode({'hedef': hedef.strip()[:64]})}")
    return redirect("kontor:islem", referans=islem.siparis.referans_no)


def _islem(request, referans):
    return get_object_or_404(
        _islemler(request).select_related("paket"), siparis__referans_no=referans
    )


def _guncel(islem):
    """Açık işlemde sağlayıcıya sorar (en sık `SORGU_ARALIGI`'nda bir)."""
    if islem.durum in (IslemDurumu.SIRADA, IslemDurumu.ISLEMDE):
        return isle(islem.pk) or islem
    return islem


@atomik_degil
@login_required
@bayi_gerekli
def islem(request, referans):
    islem_kaydi = _guncel(_islem(request, referans))
    return render(request, "kontor/islem.html", {"islem": islem_kaydi})


@atomik_degil
@login_required
@bayi_gerekli
def islem_durum(request, referans):
    """HTMX: sonuç geldi mi? Geldiyse kutu yenilenir ve sorgu durur."""
    islem_kaydi = _guncel(_islem(request, referans))
    return render(request, "kontor/parca_durum.html", {"islem": islem_kaydi})


@login_required
@bayi_gerekli
def islemler(request):
    """Bayinin bütün yüklemeleri; numarayla, referansla ya da paket adıyla aranır."""
    sorgu = _islemler(request)
    q = (request.GET.get("q") or "").strip()
    if q:
        sorgu = sorgu.filter(
            Q(hedef__icontains=normalize(q))
            | Q(siparis__referans_no__iexact=q)
            | Q(paket_adi__icontains=q)
            | Q(bayi_ref=q)
        )
    durum = request.GET.get("durum", "")
    if durum in IslemDurumu.values:
        sorgu = sorgu.filter(durum=durum)
    return render(
        request,
        "kontor/islemler.html",
        {
            "sayfa": Paginator(sorgu, 25).get_page(request.GET.get("sayfa")),
            "q": q,
            "durum": durum,
            "durumlar": IslemDurumu.choices,
        },
    )
