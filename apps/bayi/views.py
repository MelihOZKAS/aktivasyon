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
from apps.bayi.forms import BayiBasvuruFormu
from apps.bayi.models import Duyuru
from apps.bayi.yetki import bayi_gerekli, baslangic_sayfasi, tedarikci_gerekli
from apps.bildirim.telegram import bayi_basvurusu_bildir
from apps.finans.models import Banka, CuzdanHareketi, HareketTipi
from apps.katalog.models import BasvuruKategorisi, Operator, Tarife

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
        # Girişteki yönlendirmeyle aynı mantık.
        return redirect(baslangic_sayfasi(request.user))

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
        # Yönetici yönetim paneline, sadece-tedarikçi kendi paneline düşer.
        return reverse(baslangic_sayfasi(self.request.user))


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
@bayi_gerekli
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
def tarifeler(request):
    """Bayinin göreceği tarife kataloğu.

    Operatör başlıkları altında akordiyon olarak açılır; her tarifenin
    altında yönetimin girdiği açıklama, görsel ve geçerli kampanyalar
    görünür.
    """
    # Bayi müşteriye anlatırken önce operatörü seçiyor; sekmeler ona göre.
    operatorler = (
        Operator.objects.filter(aktif=True, tarifeler__aktif=True)
        .distinct()
        .order_by("sira", "ad")
    )

    secili_slug = request.GET.get("operator") or ""
    secili = None
    if secili_slug:
        secili = operatorler.filter(slug=secili_slug).first()
    if secili is None:
        secili = operatorler.first()

    tarifeler_listesi = []
    if secili:
        tarifeler_listesi = (
            Tarife.objects.filter(operator=secili, aktif=True)
            .select_related("kategori")
            .prefetch_related("kampanyalar")
            .order_by("kategori__sira", "kategori__ad", "sira", "ad")
        )
        for tarife in tarifeler_listesi:
            tarife.gecerli_kampanyalar = [
                k for k in tarife.kampanyalar.all() if k.su_an_gecerli
            ]

    return render(
        request,
        "bayi/tarifeler.html",
        {
            "operatorler": operatorler,
            "secili": secili,
            "tarifeler": tarifeler_listesi,
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


def bayi_basvurusu(request):
    """Bayi olmak isteyenlerin iletişim bilgisi bıraktığı kamuya açık form."""
    if request.method == "POST":
        form = BayiBasvuruFormu(request.POST)
        if form.is_valid():
            if not form.bot_doldurdu:
                basvuru = form.save()
                bayi_basvurusu_bildir(basvuru)
            # Bot da olsa insan da olsa aynı ekranı görür; ayrım ele verilmez.
            return render(request, "bayi/basvuru_alindi.html")
    else:
        form = BayiBasvuruFormu()

    return render(request, "bayi/bayi_basvurusu.html", {"form": form})


@login_required
@bayi_gerekli
def hakedisler(request):
    """Bayinin hangi işten ne kazanacağını açıkça gösteren sayfa.

    Kuralları burada da `uygun_kurallari_bul` mantığıyla değil, katalog
    üzerinden geziyoruz: bayi tarife tarife ne alacağını görmeli.
    """
    from apps.finans.models import KuralYonu, UcretKurali

    cuzdan = getattr(request.user, "cuzdan", None)
    grup_id = cuzdan.grup_id if cuzdan else None

    # Bu bayiyi ilgilendiren kurallar: herkese açık olanlar, grubuna ait
    # olanlar ve yalnızca ona tanımlananlar.
    kurallar = list(
        UcretKurali.objects.filter(
            aktif=True, yon__in=[KuralYonu.HAKEDIS, KuralYonu.TAHSILAT]
        )
        .filter(Q(bayi__isnull=True) | Q(bayi=request.user))
        .filter(Q(bayi_grubu__isnull=True) | Q(bayi_grubu_id=grup_id))
        .filter(tedarikci__isnull=True)
        .select_related("kategori", "operator", "tarife", "kampanya")
    )

    def en_uygun(yon, kategori, operator=None, tarife=None):
        """Verilen kapsam için geçerli kuralı seçer: en spesifik olan kazanır."""
        secilen = None
        for kural in kurallar:
            if kural.yon != yon:
                continue
            if kural.kategori_id not in (None, kategori.pk):
                continue
            if operator and kural.operator_id not in (None, operator.pk):
                continue
            if not operator and kural.operator_id is not None:
                continue
            if tarife and kural.tarife_id not in (None, tarife.pk):
                continue
            if not tarife and kural.tarife_id is not None:
                continue
            if secilen is None or (kural.ozgulluk, kural.oncelik) > (
                secilen.ozgulluk, secilen.oncelik
            ):
                secilen = kural
        return secilen

    satirlar = []
    kategoriler = (
        BasvuruKategorisi.objects.filter(aktif=True)
        .prefetch_related("tarifeler__operator")
        .order_by("sira", "ad")
    )

    for kategori in kategoriler:
        tarifeler = [t for t in kategori.tarifeler.all() if t.aktif]
        kalemler = []

        for tarife in sorted(
            tarifeler, key=lambda t: (t.operator.sira, t.operator.ad, t.sira, t.ad)
        ):
            hakedis = en_uygun(KuralYonu.HAKEDIS, kategori, tarife.operator, tarife)
            ucret = en_uygun(KuralYonu.TAHSILAT, kategori, tarife.operator, tarife)
            if hakedis is None and ucret is None:
                continue
            kalemler.append(
                {
                    "ad": tarife.ad,
                    "operator": tarife.operator,
                    "hakedis": hakedis.tutar if hakedis else None,
                    "ucret": ucret.tutar if ucret else None,
                    "net": (hakedis.tutar if hakedis else 0) - (ucret.tutar if ucret else 0),
                }
            )

        # Tarife bazında kural yoksa kategori genelindeki kuralı göster.
        if not kalemler:
            hakedis = en_uygun(KuralYonu.HAKEDIS, kategori)
            ucret = en_uygun(KuralYonu.TAHSILAT, kategori)
            if hakedis is None and ucret is None:
                continue
            kalemler.append(
                {
                    "ad": "Tüm tarifeler",
                    "operator": None,
                    "hakedis": hakedis.tutar if hakedis else None,
                    "ucret": ucret.tutar if ucret else None,
                    "net": (hakedis.tutar if hakedis else 0) - (ucret.tutar if ucret else 0),
                }
            )

        satirlar.append({"kategori": kategori, "kalemler": kalemler})

    return render(request, "bayi/hakedisler.html", {"satirlar": satirlar})


@login_required
@tedarikci_gerekli
def tedarikci_panel(request):
    """Tedarikçinin üstlendiği işlemler ve hesap durumu."""
    cuzdan = getattr(request.user, "cuzdan", None)

    basvurular = (
        Basvuru.objects.filter(tedarikci=request.user)
        .select_related("kategori", "operator", "tarife", "durum", "bayi")
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
            | Q(numara__icontains=arama)
        )

    ayin_basi = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    aylik_gider = (
        Basvuru.objects.filter(
            tedarikci=request.user,
            tedarikci_islendi=True,
            olusturma_tarihi__gte=ayin_basi,
        ).aggregate(toplam=Sum("tedarikci_geliri"))["toplam"]
        or 0
    )

    sayfalayici = Paginator(basvurular, 25)

    return render(
        request,
        "bayi/tedarikci_panel.html",
        {
            "sayfa": sayfalayici.get_page(request.GET.get("sayfa")),
            "toplam": sayfalayici.count,
            "aylik_gider": aylik_gider,
            "durumlar": BasvuruDurumu.objects.filter(aktif=True).order_by("sira"),
            "secili_durum": secili_durum,
            "arama": arama,
        },
    )
