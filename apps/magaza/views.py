"""Bayi mağazası.

Bayi kazandığı parayı burada ürüne çevirir. Ekranlar `@bayi_gerekli` ile
korunur: tedarikçi rolü bu bölümü görmez.
"""

from uuid import uuid4

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render

from apps.bayi.yetki import bayi_gerekli
from apps.bildirim.telegram import siparis_bildir
from apps.finans.services import SiparisVerilemez
from apps.magaza.models import Siparis, Urun
from apps.magaza.services import siparis_olustur

# Mağaza sayfasının altındaki "son siparişlerin" kutusu. Tamamı ayrı sayfada.
SON_SIPARIS_ADEDI = 5


def _cuzdan(request):
    return getattr(request.user, "cuzdan", None)


@login_required
@bayi_gerekli
def magaza(request):
    """Ürün listesi ve bayinin son siparişleri tek ekranda.

    Siparişler ayrı bir menü maddesi değil: menü sırası bilinçli ve kısa
    tutuluyor, listeye buradan bakılır.
    """
    cuzdan = _cuzdan(request)
    bakiye = cuzdan.bakiye if cuzdan else 0

    return render(
        request,
        "magaza/liste.html",
        {
            "urunler": Urun.objects.filter(aktif=True),
            "bakiye": bakiye,
            # eSIM siparişleri kendi bölümünde listelenir.
            "son_siparisler": Siparis.objects.filter(
                bayi=request.user, esim__isnull=True, esim_yukleme__isnull=True
            )[:SON_SIPARIS_ADEDI],
        },
    )


@login_required
@bayi_gerekli
def urun(request, slug):
    """Ürün sayfası: açıklama, fiyat ve satın alma kutusu."""
    urun_kaydi = get_object_or_404(Urun, slug=slug, aktif=True)
    cuzdan = _cuzdan(request)
    bakiye = cuzdan.bakiye if cuzdan else 0

    return render(
        request,
        "magaza/urun.html",
        {
            "urun": urun_kaydi,
            "bakiye": bakiye,
            "yeterli": bakiye >= urun_kaydi.fiyat,
            # Sayfa yenilenince aynı sipariş ikinci kez açılmasın: anahtar
            # formda gizli alanda taşınır.
            "islem_anahtari": uuid4().hex,
        },
    )


@login_required
@bayi_gerekli
def satin_al(request, slug):
    """Siparişi açar ve tutarı bakiyeden düşer. Yalnızca POST."""
    if request.method != "POST":
        return redirect("magaza:urun", slug=slug)

    urun_kaydi = get_object_or_404(Urun, slug=slug, aktif=True)

    try:
        adet = int(request.POST.get("adet") or 1)
    except ValueError:
        adet = 0
    if adet < 1:
        messages.error(request, "Adet en az 1 olmalı.")
        return redirect("magaza:urun", slug=slug)

    try:
        siparis = siparis_olustur(
            request.user,
            urun_kaydi,
            adet,
            bayi_notu=(request.POST.get("bayi_notu") or "").strip()[:255],
            anahtar=(request.POST.get("islem_anahtari") or "").strip()[:64] or None,
        )
    except SiparisVerilemez as hata:
        messages.error(request, str(hata))
        return redirect("magaza:urun", slug=slug)

    siparis_bildir(siparis)
    messages.success(
        request,
        f"Siparişin alındı ({siparis.referans_no}). {siparis.tutar} ₺ "
        "bakiyenden düşüldü; ürün elden teslim edilecek.",
    )
    return redirect("magaza:siparislerim")


@login_required
@bayi_gerekli
def siparislerim(request):
    """Bayinin bütün siparişleri."""
    sayfalayici = Paginator(
        Siparis.objects.filter(bayi=request.user, esim__isnull=True, esim_yukleme__isnull=True), 20
    )
    return render(
        request,
        "magaza/siparislerim.html",
        {"sayfa": sayfalayici.get_page(request.GET.get("sayfa"))},
    )
