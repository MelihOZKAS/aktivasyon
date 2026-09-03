"""Bayi tarafındaki başvuru akışı: yeni başvuru, liste, detay."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from apps.basvurular.forms import BasvuruFormu
from apps.basvurular.models import Basvuru, BasvuruDurumu
from apps.finans.services import YetersizBakiye
from apps.katalog.models import BasvuruKategorisi, Kampanya, Tarife


@login_required
def yeni(request):
    """Kategori seçimi ve seçilen kategoriye göre kurulan başvuru formu."""
    kategoriler = BasvuruKategorisi.objects.filter(aktif=True).order_by("sira", "ad")
    kategori_id = request.POST.get("kategori") or request.GET.get("kategori")

    if not kategori_id:
        return render(
            request,
            "basvurular/kategori_sec.html",
            {"kategoriler": kategoriler},
        )

    kategori = get_object_or_404(
        BasvuruKategorisi.objects.prefetch_related("alanlar"), pk=kategori_id, aktif=True
    )

    cuzdan = getattr(request.user, "cuzdan", None)
    if cuzdan and not cuzdan.islem_yapabilir:
        messages.error(
            request,
            "Hesabın şu an başvuru girişine kapalı. Bayi temsilcinle görüşmen gerekiyor.",
        )
        return redirect("bayi:panel")

    if request.method == "POST":
        form = BasvuruFormu(request.POST, request.FILES, kategori=kategori)
        if form.is_valid():
            try:
                basvuru = form.kaydet(request.user)
            except YetersizBakiye as hata:
                messages.error(request, str(hata))
            else:
                messages.success(
                    request,
                    f"Başvuru alındı. Takip numaran: {basvuru.referans_no}",
                )
                return redirect("basvurular:detay", pk=basvuru.pk)
    else:
        form = BasvuruFormu(kategori=kategori)

    return render(
        request,
        "basvurular/yeni.html",
        {"form": form, "kategori": kategori, "kategoriler": kategoriler},
    )


@login_required
def tarife_secenekleri(request):
    """HTMX: operatör seçilince o operatöre ait tarifeleri döndürür."""
    kategori_id = request.GET.get("kategori")
    operator_id = request.GET.get("operator")

    tarifeler = Tarife.objects.none()
    if kategori_id and operator_id:
        tarifeler = Tarife.objects.filter(
            kategori_id=kategori_id, operator_id=operator_id, aktif=True
        ).order_by("sira", "ad")

    return render(request, "basvurular/parca_tarife.html", {"tarifeler": tarifeler})


@login_required
def kampanya_secenekleri(request):
    """HTMX: tarife seçilince o tarifenin geçerli kampanyalarını döndürür."""
    tarife_id = request.GET.get("tarife")

    kampanyalar = []
    if tarife_id:
        kampanyalar = [
            k
            for k in Kampanya.objects.filter(tarife_id=tarife_id, aktif=True).order_by(
                "sira", "ad"
            )
            if k.su_an_gecerli
        ]

    return render(request, "basvurular/parca_kampanya.html", {"kampanyalar": kampanyalar})


@login_required
def liste(request):
    """Bayinin kendi başvuruları; durum ve arama ile filtrelenir."""
    basvurular = (
        Basvuru.objects.filter(bayi=request.user)
        .select_related("kategori", "operator", "tarife", "durum")
        .order_by("-olusturma_tarihi")
    )

    secili_durum = request.GET.get("durum") or ""
    if secili_durum:
        basvurular = basvurular.filter(durum__slug=secili_durum)

    arama = (request.GET.get("q") or "").strip()
    if arama:
        basvurular = basvurular.filter(
            Q(referans_no__icontains=arama)
            | Q(isim__icontains=arama)
            | Q(soyisim__icontains=arama)
            | Q(kimlik_no__icontains=arama)
            | Q(numara__icontains=arama)
            | Q(irtibat__icontains=arama)
        )

    sayfalayici = Paginator(basvurular, 25)
    sayfa = sayfalayici.get_page(request.GET.get("sayfa"))

    baglam = {
        "sayfa": sayfa,
        "durumlar": BasvuruDurumu.objects.filter(aktif=True).order_by("sira"),
        "secili_durum": secili_durum,
        "arama": arama,
        "toplam": sayfalayici.count,
    }

    # HTMX ile geldiyse yalnızca tabloyu yenile.
    if request.headers.get("HX-Request"):
        return render(request, "basvurular/parca_liste.html", baglam)
    return render(request, "basvurular/liste.html", baglam)


@login_required
def detay(request, pk):
    basvuru = get_object_or_404(
        Basvuru.objects.select_related("kategori", "operator", "tarife", "kampanya", "durum")
        .prefetch_related("belgeler", "durum_gecmisi__yeni_durum", "kategori__alanlar"),
        pk=pk,
        bayi=request.user,
    )

    etiketler = {alan.kod: alan.etiket for alan in basvuru.kategori.alanlar.all()}
    ek_satirlar = [
        (etiketler.get(kod, kod), deger) for kod, deger in (basvuru.ek_bilgiler or {}).items()
    ]

    return render(
        request,
        "basvurular/detay.html",
        {"basvuru": basvuru, "ek_satirlar": ek_satirlar},
    )
