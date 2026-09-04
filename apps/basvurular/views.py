"""Bayi tarafındaki başvuru akışı: yeni başvuru, liste, detay."""

import mimetypes
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render

from apps.basvurular.forms import BasvuruFormu
from apps.basvurular.models import Basvuru, BasvuruBelgesi, BasvuruDurumu
from apps.basvurular.validators import SATIR_ICI_GOSTERILEBILIR
from apps.bayi.yetki import bayi_gerekli
from apps.katalog.models import BasvuruKategorisi, Kampanya, Tarife


@login_required
@bayi_gerekli
def kategori_sec(request):
    """Hangi başvuru tipinin girileceğini seçtiren ekran."""
    return render(
        request,
        "basvurular/kategori_sec.html",
        {"kategoriler": BasvuruKategorisi.objects.filter(aktif=True).order_by("sira", "ad")},
    )


@login_required
@bayi_gerekli
def yeni(request, kategori):
    """Seçilen kategoriye göre kurulan başvuru formu."""
    kategori = get_object_or_404(
        BasvuruKategorisi.objects.prefetch_related("alanlar"), slug=kategori, aktif=True
    )

    cuzdan = getattr(request.user, "cuzdan", None)
    if cuzdan and not cuzdan.islem_yapabilir:
        messages.error(
            request,
            "Hesabın şu an başvuru girişine kapalı. Bayi temsilcinle görüşmen gerekiyor.",
        )
        return redirect("bayi:panel")

    if request.method == "POST":
        form = BasvuruFormu(request.POST, request.FILES, kategori=kategori, bayi=request.user)
        if form.is_valid():
            basvuru = form.kaydet(request.user)
            messages.success(
                request, f"Başvuru alındı. Takip numaran: {basvuru.referans_no}"
            )
            return redirect("basvurular:detay", referans=basvuru.referans_no)
    else:
        form = BasvuruFormu(kategori=kategori, bayi=request.user)

    return render(request, "basvurular/yeni.html", {"form": form, "kategori": kategori})


@login_required
def tarife_secenekleri(request):
    """HTMX: operatör seçilince o operatöre ait tarifeleri döndürür."""
    kategori_slug = request.GET.get("kategori")
    operator_id = request.GET.get("operator")

    tarifeler = Tarife.objects.none()
    if kategori_slug and operator_id:
        tarifeler = Tarife.objects.filter(
            kategori__slug=kategori_slug, operator_id=operator_id, aktif=True
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
@bayi_gerekli
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
def detay(request, referans):
    # Başvuruyu getiren bayi ve işlemi üstlenen tedarikçi görebilir.
    basvuru = get_object_or_404(
        Basvuru.objects.select_related("kategori", "operator", "tarife", "kampanya", "durum")
        .prefetch_related("belgeler", "durum_gecmisi__yeni_durum", "kategori__alanlar")
        .filter(Q(bayi=request.user) | Q(tedarikci=request.user)),
        referans_no=referans,
    )

    etiketler = {alan.kod: alan.etiket for alan in basvuru.kategori.alanlar.all()}
    ek_satirlar = [
        (etiketler.get(kod, kod), deger) for kod, deger in (basvuru.ek_bilgiler or {}).items()
    ]

    return render(
        request,
        "basvurular/detay.html",
        {
            "basvuru": basvuru,
            "ek_satirlar": ek_satirlar,
            # Tedarikçi işlemi görür ama kimlik görüntülerini görmez.
            "belgeler_gorunur": basvuru.bayi_id == request.user.id,
        },
    )


@login_required
def belge(request, referans, alan_kodu):
    """Başvuru belgesini izin kontrolünden geçirerek sunar.

    Kimlik ve pasaport görüntüleri kişisel veridir; MEDIA_URL üzerinden
    doğrudan erişime açılmaz. Yalnızca başvuruyu giren bayi ve yetkili
    personel görüntüleyebilir.
    """
    kayit = get_object_or_404(
        BasvuruBelgesi.objects.select_related("basvuru"),
        basvuru__referans_no=referans,
        alan_kodu=alan_kodu,
    )

    # Kimlik görüntüleri yalnızca başvuruyu getiren bayiye ve personele açık.
    # Tedarikçi işlemin bilgilerini görür ama kimlik fotoğraflarını görmez;
    # gerekirse bu kural burada gevşetilir.
    if not request.user.is_staff and kayit.basvuru.bayi_id != request.user.id:
        raise Http404

    if not kayit.dosya:
        raise Http404

    try:
        akis = kayit.dosya.open("rb")
    except FileNotFoundError as hata:
        raise Http404("Belge dosyası bulunamadı.") from hata

    # Yükleme anında doğrulama yapılıyor; burada ikinci katman savunma var.
    # Bilinen güvenli resim türleri dışındaki her şey gömülü gösterilmez,
    # indirilir: aksi hâlde belgeyi açan personelin oturumunda betik çalışabilir.
    tip, _ = mimetypes.guess_type(kayit.dosya.name)
    gomulu_gosterilebilir = tip in SATIR_ICI_GOSTERILEBILIR

    yanit = FileResponse(
        akis,
        filename=Path(kayit.dosya.name).name,
        as_attachment=not gomulu_gosterilebilir,
        content_type=tip if gomulu_gosterilebilir else "application/octet-stream",
    )
    # Tarayıcı ve ara sunucular kişisel veriyi paylaşımlı önbelleğe almasın.
    yanit["Cache-Control"] = "private, max-age=300"
    yanit["X-Content-Type-Options"] = "nosniff"
    # Dosya bir şekilde gömülü açılsa bile betik çalıştıramasın.
    yanit["Content-Security-Policy"] = "sandbox; default-src 'none'; img-src 'self'"
    return yanit
