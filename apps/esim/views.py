"""Bayi tarafı: ülke listesi, paketler, satın alma ve eSIM teslim sayfası.

Mağazadan ayrı bir bölümdür (`/esim/…`), `@bayi_gerekli` ile korunur.
Fiyatlar her açılışta kurla hesaplanır; kur ya da aktif sağlayıcı yoksa
bölüm kapalı görünür, sebebini yazar.
"""

from uuid import uuid4

import segno
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from apps.bayi.yetki import bayi_gerekli
from apps.bildirim.telegram import siparis_bildir
from apps.esim.models import Paket, Teslimat, Ulke
from apps.esim.rapor import bayi_aylik_ozet
from apps.esim.saglayicilar import SaglayiciHatasi
from apps.esim.services import (
    KurTanimsiz,
    bayi_tavsiye_orani,
    bolgesel_paketler,
    durumu_sorgula,
    esim_siparisi_ver,
    esim_yukle,
    fiyatlandir,
    kur_getir,
    musteri_etiketle,
    profili_getir,
    saglayici_var_mi,
    ulke_listesi,
    ulke_paketleri,
    yukleme_paketleri,
)
from apps.finans.services import SiparisVerilemez
from apps.magaza.models import Siparis


def _bakiye(request):
    cuzdan = getattr(request.user, "cuzdan", None)
    return cuzdan.bakiye if cuzdan else 0


def _kapali(request, sebep):
    return render(request, "esim/kapali.html", {"sebep": sebep})


def _kur_ya_da_kapali(request):
    """Kur ve sağlayıcı yoksa bayi boş liste değil, sebebini görür."""
    if not saglayici_var_mi():
        return None, _kapali(request, "eSIM satışı henüz açılmadı.")
    try:
        return kur_getir(), None
    except KurTanimsiz:
        return None, _kapali(request, "eSIM fiyatları şu an hesaplanamıyor; kısa süre sonra yeniden dene.")


# Ülke listesinin altındaki "son eSIM'lerin" kutusu; tamamı ayrı sayfada.
SON_SIPARIS_ADEDI = 5


def _esim_siparisleri(request):
    """eSIM satışları ve yüklemeleri; ikisi de bu bölümün siparişi."""
    return (
        Siparis.objects.filter(bayi=request.user)
        .filter(Q(esim__isnull=False) | Q(esim_yukleme__isnull=False))
        .select_related("esim", "esim_yukleme", "esim_yukleme__teslimat", "esim_yukleme__teslimat__siparis")
        .order_by("-olusturma_tarihi")
    )


@login_required
@bayi_gerekli
def ulkeler(request):
    kur, kapali = _kur_ya_da_kapali(request)
    if kapali:
        return kapali
    return render(
        request,
        "esim/ulkeler.html",
        {
            "ulkeler": ulke_listesi(kur, bayi_tavsiye_orani(request.user)),
            "bakiye": _bakiye(request),
            "son_siparisler": _esim_siparisleri(request)[:SON_SIPARIS_ADEDI],
            "aylik": bayi_aylik_ozet(request.user),
        },
    )


@login_required
@bayi_gerekli
def siparisler(request):
    """Bayinin bütün eSIM siparişleri; mağazanın listesinden ayrı.

    Müşteri "paketim bitti" diye arayınca bayi adıyla, telefonuyla ya da
    ICCID'siyle bulur; `q` hepsinde arar.
    """
    siparisler_qs = _esim_siparisleri(request)
    q = (request.GET.get("q") or "").strip()
    if q:
        from apps.bayi.telefon import normalize

        siparisler_qs = siparisler_qs.filter(
            Q(esim__musteri_adi__icontains=q)
            | Q(esim__musteri_telefonu__icontains=normalize(q))
            | Q(esim__iccid__icontains=q)
            | Q(esim_yukleme__teslimat__musteri_adi__icontains=q)
            | Q(esim_yukleme__teslimat__musteri_telefonu__icontains=normalize(q))
            | Q(esim_yukleme__teslimat__iccid__icontains=q)
            | Q(referans_no__iexact=q)
            | Q(urun_adi__icontains=q)
        )
    sayfalayici = Paginator(siparisler_qs, 20)
    return render(
        request,
        "esim/siparisler.html",
        {
            "sayfa": sayfalayici.get_page(request.GET.get("sayfa")),
            "q": q,
            "aylik": bayi_aylik_ozet(request.user),
        },
    )


@login_required
@bayi_gerekli
def bolgesel(request):
    kur, kapali = _kur_ya_da_kapali(request)
    if kapali:
        return kapali
    return render(
        request,
        "esim/ulke.html",
        {
            "baslik": "Bölgesel ve global paketler",
            "tekil": [],
            "bolgesel": bolgesel_paketler(kur, bayi_tavsiye_orani(request.user)),
            "bakiye": _bakiye(request),
        },
    )


@login_required
@bayi_gerekli
def ulke(request, kod):
    kur, kapali = _kur_ya_da_kapali(request)
    if kapali:
        return kapali
    ulke_kaydi = get_object_or_404(Ulke, kod=kod.upper(), aktif=True)
    tekil, bolgesel_liste = ulke_paketleri(ulke_kaydi, kur, bayi_tavsiye_orani(request.user))
    return render(
        request,
        "esim/ulke.html",
        {
            "ulke": ulke_kaydi,
            "baslik": f"{ulke_kaydi.bayrak} {ulke_kaydi.ad}",
            "tekil": tekil,
            "bolgesel": bolgesel_liste,
            "bakiye": _bakiye(request),
        },
    )


BOLGESEL = "bolgesel"


def _paket_bul(kod, pk):
    """Paket adresi ülke üzerinden kurulur; bölgesel liste için sanal kod.

    Bölgesel sayfada tek bir ülke yok; adres `bolgesel/<pk>/` olur ve paket
    yalnızca çok ülkeli olmasıyla doğrulanır.
    """
    paketler = Paket.objects.satilabilir().select_related("saglayici")
    if kod.lower() == BOLGESEL:
        return None, get_object_or_404(paketler, pk=pk, ulke_sayisi__gt=1)
    ulke_kaydi = get_object_or_404(Ulke, kod=kod.upper(), aktif=True)
    return ulke_kaydi, get_object_or_404(paketler, pk=pk, ulkeler=ulke_kaydi)


@login_required
@bayi_gerekli
def paket(request, kod, pk):
    """Paket sayfası: ne alındığı, fiyatı, bakiye ve satın alma düğmesi.

    Listedeki tek tıkla para düşmesin; bayi ne aldığını burada bir kez daha
    görür. Ürün sayfasındaki kuralın aynısı: bakiye yetmiyorsa düğme
    kapanmaz, sebebi yazılır.
    """
    kur, kapali = _kur_ya_da_kapali(request)
    if kapali:
        return kapali
    ulke_kaydi, paket_kaydi = _paket_bul(kod, pk)
    fiyatlandir([paket_kaydi], kur, bayi_tavsiye_orani(request.user))
    bakiye = _bakiye(request)
    return render(
        request,
        "esim/paket.html",
        {
            "ulke": ulke_kaydi,
            "kod": kod.lower(),
            "paket": paket_kaydi,
            "ulkeler": paket_kaydi.ulkeler.filter(aktif=True) if paket_kaydi.bolgesel else [],
            "bakiye": bakiye,
            "yeterli": bakiye >= paket_kaydi.satis,
            "islem_anahtari": uuid4().hex,
        },
    )


@login_required
@bayi_gerekli
def satin_al(request, kod, pk):
    if request.method != "POST":
        return redirect("esim:paket", kod=kod, pk=pk)

    _, paket_kaydi = _paket_bul(kod, pk)
    try:
        teslimat = esim_siparisi_ver(
            request.user,
            paket_kaydi,
            anahtar=(request.POST.get("islem_anahtari") or "").strip()[:64] or None,
        )
    except SiparisVerilemez as hata:
        messages.error(request, str(hata))
        return redirect("esim:paket", kod=kod, pk=pk)

    if teslimat.durum == "hata":
        messages.error(
            request,
            "Sağlayıcı siparişi kabul etmedi; tutar bakiyene geri yazıldı. "
            f"Sebep: {teslimat.hata}",
        )
    else:
        siparis_bildir(teslimat.siparis)
    return redirect("esim:siparis", referans=teslimat.siparis.referans_no)


def _teslimat(request, referans):
    """Bayi yalnızca kendi eSIM'ini görür; başkasınınki 404."""
    siparis = get_object_or_404(
        Siparis.objects.select_related("esim", "esim__saglayici", "esim__paket"),
        referans_no=referans,
        bayi=request.user,
    )
    try:
        return siparis.esim
    except Teslimat.DoesNotExist:
        raise Http404("Bu sipariş bir eSIM değil.")


def _qr(teslimat):
    """Aktivasyon kodundan QR: sağlayıcının görseline bağımlı kalınmaz."""
    if not teslimat.ac:
        return ""
    return segno.make(teslimat.ac, error="m").svg_data_uri(scale=6, border=2, dark="#111")


@login_required
@bayi_gerekli
def siparis(request, referans):
    teslimat = _teslimat(request, referans)
    if teslimat.bekliyor:
        teslimat = profili_getir(teslimat)
    return render(
        request,
        "esim/siparis.html",
        {
            "teslimat": teslimat,
            "siparis": teslimat.siparis,
            "qr": _qr(teslimat),
            "yuklemeler": teslimat.yuklemeler.select_related("siparis"),
        },
    )


@login_required
@bayi_gerekli
def siparis_durum(request, referans):
    """HTMX: profil hazır mı? Hazırsa sayfa kendini yeniler."""
    teslimat = _teslimat(request, referans)
    if teslimat.bekliyor:
        teslimat = profili_getir(teslimat)
    return render(
        request,
        "esim/parca_durum.html",
        {"teslimat": teslimat, "siparis": teslimat.siparis, "qr": _qr(teslimat)},
    )


@login_required
@bayi_gerekli
def etiket(request, referans):
    """Bayi eSIM'e müşteri adı/telefonu yazar; sonra listede arayıp bulur."""
    teslimat = _teslimat(request, referans)
    if request.method == "POST":
        musteri_etiketle(
            teslimat, ad=request.POST.get("musteri_adi", ""), telefon=request.POST.get("musteri_telefonu", "")
        )
        messages.success(request, "Müşteri bilgisi kaydedildi.")
    return redirect("esim:siparis", referans=referans)


@login_required
@bayi_gerekli
def yukle(request, referans):
    """Satılmış eSIM'e paket yükleme: liste sağlayıcıdan gelir, POST ile yüklenir.

    Satıştaki kuralların aynısı: bakiyesi yetmeyen paket sebebiyle kapalı,
    tutar bakiyeden anında düşer, sağlayıcı reddederse geri döner.
    """
    teslimat = _teslimat(request, referans)
    if not teslimat.hazir:
        messages.error(request, "Yalnızca hazır (teslim edilmiş) eSIM'e yükleme yapılır.")
        return redirect("esim:siparis", referans=referans)

    kur, kapali = _kur_ya_da_kapali(request)
    if kapali:
        return kapali

    if request.method == "POST":
        try:
            yukleme = esim_yukle(
                request.user,
                teslimat,
                (request.POST.get("paket") or "").strip()[:50],
                anahtar=(request.POST.get("islem_anahtari") or "").strip()[:64] or None,
            )
        except SiparisVerilemez as hata:
            messages.error(request, str(hata))
            return redirect("esim:yukle", referans=referans)
        if yukleme.durum == "hata":
            messages.error(
                request,
                f"Sağlayıcı yüklemeyi kabul etmedi; tutar bakiyene geri yazıldı. Sebep: {yukleme.hata}",
            )
        else:
            messages.success(
                request,
                f"{yukleme.paket_adi} yüklendi; {yukleme.siparis.tutar} ₺ bakiyenden düşüldü.",
            )
        return redirect("esim:siparis", referans=referans)

    try:
        paketler = yukleme_paketleri(teslimat, request.user, kur)
        sebep = ""
    except SaglayiciHatasi as hata:
        paketler, sebep = [], str(hata)
    return render(
        request,
        "esim/yukle.html",
        {
            "teslimat": teslimat,
            "siparis": teslimat.siparis,
            "paketler": paketler,
            "sebep": sebep,
            "bakiye": _bakiye(request),
            "islem_anahtari": uuid4().hex,
        },
    )


@login_required
@bayi_gerekli
def kurulum(request, referans):
    """Bayi "müşteri okuttu mu, bağlandı mı" diye sağlayıcıya sorar. POST."""
    teslimat = _teslimat(request, referans)
    if request.method == "POST":
        teslimat = durumu_sorgula(teslimat)
        if teslimat.hatta_baglandi:
            messages.success(request, "Telefona kuruldu ve hat bağlandı; paket kullanımda.")
        elif teslimat.telefona_kuruldu:
            messages.warning(
                request,
                "Profil telefona kuruldu ama hat henüz ağa bağlanmadı. Telefonda hat açık ve "
                "Veri Dolaşımı açık olmalı; 1–2 dakika bekleyip uçak modunu aç-kapa.",
            )
        else:
            messages.info(request, "QR henüz bir telefona okutulmamış.")
    return redirect("esim:siparis", referans=referans)
