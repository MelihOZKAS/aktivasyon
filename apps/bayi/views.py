"""Bayi paneli: giriş, gösterge paneli ve cüzdan."""

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from urllib.parse import quote
from django.views.decorators.http import require_POST

from apps.basvurular.models import Basvuru, BasvuruDurumu
from apps.bayi.models import Duyuru
from apps.finans.models import Banka, CuzdanHareketi, HareketTipi
from apps.katalog.models import BasvuruKategorisi

# Bir başvurunun yolculuğu: giriş ekranında ve ana sayfada aynı anlatı.
ASAMALAR = [
    {"ad": "Başvuru alındı", "seviye": 1, "renk": "#64748b", "not": "Bayi formu doldurdu", "tutar": ""},
    {"ad": "İşleme alındı", "seviye": 3, "renk": "#3b82f6", "not": "Operasyon evrakı kontrol ediyor", "tutar": ""},
    {"ad": "Hat aktif", "seviye": 5, "renk": "#15A34A", "not": "Hakediş cüzdana işlendi", "tutar": "+175,00 ₺"},
]

ADIMLAR = [
    {
        "baslik": "Bayi başvuruyu girer",
        "metin": "Kategoriyi seçer, form kendini o kategoriye göre kurar. Kimlik "
                 "fotoğrafını telefonun kamerasıyla doğrudan çeker.",
        "seviye": 1,
        "renk": "#64748b",
    },
    {
        "baslik": "Operasyon işler",
        "metin": "Başvuru kuyruğa düşer. Evrak eksikse bayi anında görür, "
                 "tamamlar. Her durum değişimi kayda geçer.",
        "seviye": 3,
        "renk": "#3b82f6",
    },
    {
        "baslik": "Para kendiliğinden işler",
        "metin": "Hat aktifleşince ücret kuralları çalışır: hat ücreti kesilir, "
                 "hakediş cüzdana yatar. Elle bakiye girilmez.",
        "seviye": 5,
        "renk": "#0FD9C0",
    },
]

OZELLIKLER = [
    {
        "baslik": "Esnek başvuru tipleri",
        "metin": "Kategori, tarife ve kampanya birer kayıt. Yeni bir hat tipi "
                 "eklemek için yazılım güncellemesi beklemezsin.",
    },
    {
        "baslik": "Kural tabanlı hakediş",
        "metin": "Hangi kategoride, hangi operatörde, hangi bayi grubuna ne "
                 "ödeneceğini kural olarak tanımlarsın. Gerisi otomatik.",
    },
    {
        "baslik": "Bakiye ve borç limiti",
        "metin": "Her bayinin bakiyesi ve borcu ayrı. Borçlanma varsayılan "
                 "olarak kapalıdır; açtığın bayiye girdiğin tutar kadar limit tanınır.",
    },
    {
        "baslik": "Değişmez defter",
        "metin": "Her para hareketi tekil anahtarla kaydedilir. Aynı işlem "
                 "iki kez işlenemez, her kuruşun kaynağı bellidir.",
    },
]


def anasayfa(request):
    """Kamuya açık tanıtım sayfası."""
    if request.user.is_authenticated:
        return redirect("bayi:panel")

    kategoriler = (
        BasvuruKategorisi.objects.filter(aktif=True)
        .annotate(alan_sayisi=Count("alanlar", filter=Q(alanlar__aktif=True)))
        .order_by("sira", "ad")[:8]
    )

    return render(
        request,
        "bayi/anasayfa.html",
        {
            "kategoriler": kategoriler,
            "asamalar": ASAMALAR,
            "adimlar": ADIMLAR,
            "ozellikler": OZELLIKLER,
        },
    )


class GirisView(LoginView):
    """Sistemin tek giriş kapısı: hem bayi hem yönetici buradan girer."""

    template_name = "bayi/giris.html"
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "asamalar": ASAMALAR}

    def get_success_url(self):
        hedef = self.get_redirect_url()
        if hedef:
            return hedef
        # Yönetici girişte doğrudan yönetim paneline düşsün.
        if self.request.user.is_staff:
            return reverse("admin:index")
        return reverse("bayi:panel")


def yonetim_girisi(request):
    """Django admin'in kendi giriş formunu tek kapıya yönlendirir.

    Girişi olmayan kullanıcı /giris-yap ekranına gider. Girişi olan ama yetkisi
    olmayan bayi, sonsuz yönlendirme döngüsüne düşmesin diye kendi paneline
    açık bir mesajla gönderilir.
    """
    # `next` dışarıdan geliyor; doğrulanmazsa kullanıcı başka bir siteye
    # yönlendirilebilir (kimlik avı). Yalnızca kendi sunucumuza izin ver.
    hedef = request.GET.get("next") or ""
    if not url_has_allowed_host_and_scheme(
        hedef, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        hedef = reverse("admin:index")

    if request.user.is_authenticated:
        if request.user.is_staff:
            return redirect(hedef)
        messages.error(request, "Yönetim paneline erişim yetkin yok.")
        return redirect("bayi:panel")

    return redirect(f"{reverse('bayi:giris')}?next={quote(hedef)}")


@require_POST
def cikis(request):
    logout(request)
    return redirect("bayi:giris")


def _kategori_hakedisleri(kullanici):
    """Her kategori için bu bayinin kazanabileceği hakediş aralığını çıkarır.

    Operatöre göre tutar değişiyorsa tek bir sayı göstermek yanıltıcı olur;
    o yüzden en düşük ve en yüksek birlikte döner.
    """
    from apps.finans.models import KuralYonu, UcretKurali

    cuzdan = getattr(kullanici, "cuzdan", None)
    grup_id = cuzdan.grup_id if cuzdan else None

    kurallar = (
        UcretKurali.objects.filter(
            aktif=True,
            yon=KuralYonu.HAKEDIS,
            kategori__isnull=False,
            tarife__isnull=True,
            kampanya__isnull=True,
        )
        .filter(Q(bayi__isnull=True) | Q(bayi=kullanici))
        .filter(Q(bayi_grubu__isnull=True) | Q(bayi_grubu_id=grup_id))
    )

    # Kategori + operatör kırılımında en spesifik kuralı seç, sonra aralığı bul.
    en_iyi = {}
    for kural in kurallar:
        anahtar = (kural.kategori_id, kural.operator_id)
        mevcut = en_iyi.get(anahtar)
        if mevcut is None or (kural.ozgulluk, kural.oncelik) > (mevcut.ozgulluk, mevcut.oncelik):
            en_iyi[anahtar] = kural

    araliklar = {}
    for (kategori_id, _), kural in en_iyi.items():
        alt, ust = araliklar.get(kategori_id, (kural.tutar, kural.tutar))
        araliklar[kategori_id] = (min(alt, kural.tutar), max(ust, kural.tutar))
    return araliklar


def _durum_dagilimi(kullanici):
    """Bayinin başvurularının durumlara göre dağılımı.

    Panelde sinyal çubuklarıyla gösterilir; her satır o duruma filtrelenmiş
    listeye götürür. Amaç tek bakışta "kaç iş nerede takılı" sorusunu
    cevaplamak.
    """
    sayilar = dict(
        Basvuru.objects.filter(bayi=kullanici)
        .values_list("durum_id")
        .annotate(adet=Count("id"))
        .values_list("durum_id", "adet")
    )
    if not sayilar:
        return []

    return [
        {"durum": durum, "adet": sayilar[durum.pk]}
        for durum in BasvuruDurumu.objects.filter(pk__in=sayilar, aktif=True).order_by("sira")
    ]


@login_required
def panel(request):
    cuzdan = getattr(request.user, "cuzdan", None)

    ayin_basi = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    aylik_hakedis = 0
    if cuzdan:
        aylik_hakedis = (
            CuzdanHareketi.objects.filter(
                cuzdan=cuzdan, tip=HareketTipi.HAKEDIS, tarih__gte=ayin_basi
            ).aggregate(toplam=Sum("tutar"))["toplam"]
            or 0
        )

    araliklar = _kategori_hakedisleri(request.user)
    kategoriler = list(
        BasvuruKategorisi.objects.filter(aktif=True)
        .prefetch_related("operatorler")
        .order_by("sira", "ad")
    )
    for kategori in kategoriler:
        aralik = araliklar.get(kategori.pk)
        kategori.hakedis_alt, kategori.hakedis_ust = aralik if aralik else (None, None)
        kategori.gecerli = kategori.gecerli_operatorler()

    return render(
        request,
        "bayi/panel.html",
        {
            "kategoriler": kategoriler,
            "son_basvurular": (
                Basvuru.objects.filter(bayi=request.user)
                .select_related("kategori", "operator", "durum")
                .order_by("-olusturma_tarihi")[:6]
            ),
            "duyurular": Duyuru.objects.filter(aktif=True)[:3],
            "aylik_hakedis": aylik_hakedis,
            "durum_dagilimi": _durum_dagilimi(request.user),
        },
    )


@login_required
def cuzdan_gorunumu(request):
    cuzdan = getattr(request.user, "cuzdan", None)

    hareketler = CuzdanHareketi.objects.none()
    if cuzdan:
        hareketler = (
            CuzdanHareketi.objects.filter(cuzdan=cuzdan)
            .select_related("basvuru", "banka")
            .order_by("-tarih", "-id")
        )

    # Filtrede yalnızca bu bayide gerçekten geçen tipler listelensin; boş dönecek
    # seçenekler hem gereksiz hem de bayinin görmediği durumları ima eder.
    gecen_tipler = set(hareketler.values_list("tip", flat=True).distinct())
    hareket_tipleri = [(d, e) for d, e in HareketTipi.choices if d in gecen_tipler]

    tip = request.GET.get("tip") or ""
    if tip:
        hareketler = hareketler.filter(tip=tip)

    sayfalayici = Paginator(hareketler, 30)

    return render(
        request,
        "bayi/cuzdan.html",
        {
            "sayfa": sayfalayici.get_page(request.GET.get("sayfa")),
            "bankalar": Banka.objects.filter(aktif=True, bayiye_gorunur=True),
            "hareket_tipleri": hareket_tipleri,
            "secili_tip": tip,
        },
    )
