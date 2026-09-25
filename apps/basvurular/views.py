"""Bayi tarafındaki başvuru akışı: yeni başvuru, liste, detay."""

import mimetypes
from decimal import Decimal
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.basvurular.forms import BasvuruFormu
from apps.basvurular.detay_alanlari import detay_satirlari, gizli_alanlar
from apps.basvurular.models import Basvuru, BasvuruBelgesi, BasvuruDurumu
from apps.basvurular.validators import SATIR_ICI_GOSTERILEBILIR
from apps.bayi.kategoriler import acik_kategoriler, kategori_acik_mi
from apps.bayi.telefon import normalize
from apps.bayi.yetki import bayi_gerekli
from apps.bayi.templatetags.panel import para
from apps.finans.services import en_dusuk_basvuru_bedeli, operator_bedelleri
from apps.katalog.models import BasvuruKategorisi, Kampanya, Tarife


def _bakiye(kullanici):
    cuzdan = getattr(kullanici, "cuzdan", None)
    return cuzdan.bakiye if cuzdan else Decimal("0.00")


def _turkce_liste(adlar):
    """["Turkcell", "Vodafone"] -> "Turkcell ve Vodafone"."""
    adlar = list(adlar)
    if len(adlar) < 2:
        return "".join(adlar)
    return f"{', '.join(adlar[:-1])} ve {adlar[-1]}"


def _karsilanamayan_operatorler(kullanici, kategori):
    """Bayinin bakiyesinin yetmediği operatörler.

    Fiyat operatöre göre değiştiği için kapı da operatör kırılımında
    çalışır: bakiyesi Vodafone'a yetip Turkcell'e yetmeyen bayi forma
    girebilmeli, ama hangisini seçemeyeceğini baştan bilmeli.
    """
    bakiye = _bakiye(kullanici)
    return [
        operator
        for operator, tutar in operator_bedelleri(kullanici, kategori)
        if tutar > bakiye
    ]


@login_required
@bayi_gerekli
def kategori_sec(request):
    """Hangi başvuru tipinin girileceğini seçtiren ekran.

    Bayiden tahsil edilen bir bedeli olan kategoriler, bakiye yetmiyorsa
    kapalı gösterilir: bayi forma girip bütün alanları doldurduktan sonra
    "bakiyen yetmiyor" duvarına çarpmasın.

    Yöneticinin bu bayiye kapattığı tipler ise hiç listelenmez. Bakiye
    yetersizliği geçicidir — para yatınca açılır, o yüzden sebebiyle
    gösterilir; kapatma yönetimin kararıdır ve bayinin yapabileceği bir şey
    yoktur, kapalı bir kart göstermek boşuna umut olurdu.
    """
    bakiye = _bakiye(request.user)
    kategoriler = list(
        acik_kategoriler(
            request.user,
            BasvuruKategorisi.objects.filter(aktif=True).order_by("sira", "ad"),
        )
    )
    for kategori in kategoriler:
        kategori.gereken_bedel = en_dusuk_basvuru_bedeli(request.user, kategori)
        kategori.bakiye_yetersiz = kategori.gereken_bedel > bakiye
        # Fiyat operatöre göre değişiyor; kartta hepsi ayrı ayrı yazılır.
        kategori.bedeller = [
            {"operator": operator, "tutar": tutar, "yetersiz": tutar > bakiye}
            for operator, tutar in operator_bedelleri(request.user, kategori)
            if tutar > 0
        ]

    return render(
        request,
        "basvurular/kategori_sec.html",
        {
            "kategoriler": kategoriler,
            "bakiye": bakiye,
            # Liste boşsa sebebi ayırt edilsin: sistemde hiç tip yok mu,
            # yoksa hepsi bu bayiye mi kapatılmış?
            "hepsi_kapali": (
                not kategoriler
                and BasvuruKategorisi.objects.filter(aktif=True).exists()
            ),
        },
    )


@login_required
@bayi_gerekli
def yeni(request, kategori):
    """Seçilen kategoriye göre kurulan başvuru formu."""
    kategori = get_object_or_404(
        BasvuruKategorisi.objects.prefetch_related("alanlar"), slug=kategori, aktif=True
    )

    # Kapalı tip listede hiç görünmüyor; buraya ancak adres elle yazılarak
    # gelinir. Sessizce 404 vermek yerine sebebi söylenir: bayi "sistem
    # bozuk" sanıp destek açmasın.
    if not kategori_acik_mi(request.user, kategori):
        messages.error(
            request,
            f"“{kategori.ad}” başvuruları hesabına kapalı. "
            "Açtırmak için yöneticinle iletişime geç.",
        )
        return redirect("basvurular:kategori-sec")

    cuzdan = getattr(request.user, "cuzdan", None)
    if cuzdan and not cuzdan.islem_yapabilir:
        messages.error(
            request,
            "Hesabın şu an başvuru girişine kapalı. Bayi temsilcinle görüşmen gerekiyor.",
        )
        return redirect("bayi:panel")

    # Bedeli olan bir işlem, parası olmayana verilmez. Kategorinin en ucuz
    # seçeneğini bile karşılayamıyorsa form hiç açılmaz; formu doldurup
    # sonunda duvara çarpmak en can sıkıcı yol.
    gereken = en_dusuk_basvuru_bedeli(request.user, kategori)
    if gereken > _bakiye(request.user):
        messages.error(
            request,
            f"“{kategori.ad}” için bakiyen yetersiz. Gereken {para(gereken)} ₺, "
            f"bakiyen {para(_bakiye(request.user))} ₺. "
            "Bakiye yüklemek için yöneticinle iletişime geç.",
        )
        return redirect("basvurular:kategori-sec")

    if request.method == "POST":
        form = BasvuruFormu(request.POST, request.FILES, kategori=kategori, bayi=request.user)
        if form.is_valid():
            try:
                basvuru = form.kaydet(request.user)
            except ValidationError as hata:
                form.add_error(None, hata)
            else:
                messages.success(
                    request, f"Başvuru alındı. Takip numaran: {basvuru.referans_no}"
                )
                return redirect("basvurular:detay", referans=basvuru.referans_no)
    else:
        form = BasvuruFormu(kategori=kategori, bayi=request.user)

    # Karşılanamayan operatör varsa bayi formu doldurmadan önce bilsin;
    # bilgileri iki kez girmek zorunda kalmasın.
    yetersizler = _karsilanamayan_operatorler(request.user, kategori)

    return render(
        request,
        "basvurular/yeni.html",
        {
            "form": form,
            "kategori": kategori,
            "yetersiz_operatorler": _turkce_liste(o.ad for o in yetersizler),
        },
    )


@login_required
def tarife_secenekleri(request):
    """HTMX: operatör seçilince o operatöre ait tarifeleri döndürür."""
    kategori_slug = request.GET.get("kategori")
    operator_id = request.GET.get("operator")

    tarifeler = Tarife.objects.none()
    if kategori_slug and operator_id:
        tarifeler = Tarife.objects.filter(
            kategoriler__slug=kategori_slug, operator_id=operator_id, aktif=True
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

    return render(
        request,
        "basvurular/parca_kampanya.html",
        {"kampanyalar": kampanyalar, "tarife_secildi": bool(tarife_id)},
    )


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
            | Q(aktif_numara__icontains=normalize(arama))
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

    # Satırlar tek yerde üretilir; ayar kutusundaki seçenekler de aynı
    # listeden gelir. Kategoriye alan eklenince ikisi birden büyür.
    bayi_gorunumu = request.user.id == basvuru.bayi_id
    tedarikci_gorunumu = request.user.id == basvuru.tedarikci_id

    # Tedarikçi işlemi üstlenir, müşteriyle ilgilenir; başvuruyu hangi
    # bayinin getirdiği onun işi değil.
    tum_satirlar = detay_satirlari(
        basvuru, tedarikci_gorunumu=tedarikci_gorunumu and not bayi_gorunumu
    )
    gizli = gizli_alanlar(request.user)

    return render(
        request,
        "basvurular/detay.html",
        {
            "basvuru": basvuru,
            "satirlar": [s for s in tum_satirlar if s["anahtar"] not in gizli],
            "tum_satirlar": tum_satirlar,
            "gizli_alanlar": gizli,
            # Başvuruyu getiren bayi ve işlemi üstlenen tedarikçi görebilir.
            "belgeler_gorunur": request.user.id
            in {basvuru.bayi_id, basvuru.tedarikci_id},
            "bayi_gorunumu": bayi_gorunumu,
            "tedarikci_gorunumu": tedarikci_gorunumu,
            # Aktivasyonu tedarikçi yapıyor; sonucu da o bildirir.
            "durum_secenekleri": (
                _tedarikci_durumlari() if tedarikci_gorunumu and not basvuru.sonuclandi_mi else []
            ),
            # Bozuk kartı tedarikçi bildirir (yönetim de admin'den); bayi
            # değil. Bayi yalnızca yerine yenisini takar.
            "sim_bozuk_kartlar": (
                list(basvuru.kullanilan_simler)
                if tedarikci_gorunumu and not basvuru.sonuclandi_mi
                else []
            ),
            # Eksik Evrak: bayi neyin eksik olduğunu görür, düzeltip yeniden gönderir.
            "duzeltme_acik": bayi_gorunumu and basvuru.bayi_duzeltebilir,
            "yonetim_notu": basvuru.son_yonetim_notu if bayi_gorunumu else "",
            # Bayi kendi listesine, tedarikçi kendi paneline döner: karşı
            # tarafın ekranı rol kontrolünden geçemez.
            "geri_url": "basvurular:liste" if bayi_gorunumu else "bayi:tedarikci-panel",
        },
    )


def _tedarikci_durumlari():
    """Tedarikçinin seçebileceği durumlar.

    Hangi durumlar olduğu veridir (`BasvuruDurumu.tedarikci_secebilir`);
    listeyi koda gömmek yeni bir durum eklendiğinde yazılım değişikliği
    gerektirirdi.
    """
    return BasvuruDurumu.objects.filter(aktif=True, tedarikci_secebilir=True).order_by(
        "sira", "ad"
    )


@login_required
@require_POST
def durum_bildir(request, referans):
    """Tedarikçi üstlendiği işlemin sonucunu kendisi yazar.

    Aktivasyonu fiilen tedarikçi yapıyor: hattı açan da, operatörden ret
    yiyen de o. Sonucu yöneticiye telefonla bildirip beklemek, günlük işte
    tek elle yapılan şeyin durum değiştirmek olduğu bir sistemde fazladan
    bir durak.

    Sonuçlanmış başvuruya dokunamaz. Para işlendikten sonra durumu geri
    çekmek ters kayıt demektir; yanlış onayın düzeltmesi yönetim kararıdır
    ve tedarikçi kendi ödediği bedeli tek başına geri alamamalı.
    """
    basvuru = get_object_or_404(
        Basvuru.objects.select_related("durum"),
        referans_no=referans,
        tedarikci=request.user,
    )

    if basvuru.sonuclandi_mi:
        messages.error(
            request,
            "Bu işlem sonuçlandı; durumunu artık yalnızca yönetim değiştirebilir.",
        )
        return redirect("basvurular:detay", referans=referans)

    durum = _tedarikci_durumlari().filter(pk=request.POST.get("durum") or 0).first()
    if durum is None:
        messages.error(request, "Geçerli bir durum seç.")
        return redirect("basvurular:detay", referans=referans)

    if durum.pk == basvuru.durum_id:
        messages.info(request, f"Başvuru zaten “{durum.ad}” durumunda.")
        return redirect("basvurular:detay", referans=referans)

    basvuru.durum = durum
    # Kimin yazdığı ve notu durum geçmişine düşsün.
    basvuru._degistiren = request.user
    basvuru._aciklama = (request.POST.get("aciklama") or "").strip()[:255]
    basvuru.save(update_fields=["durum", "guncelleme_tarihi"])

    messages.success(request, f"Durum “{durum.ad}” olarak güncellendi.")
    return redirect("basvurular:detay", referans=referans)


@login_required
@require_POST
def sim_bozuk(request, referans):
    """Tedarikçi aktivasyonda bozuk çıkan kartı bildirir.

    Kart arızalıya düşer, başvuru bayinin düzenleyebildiği duruma çekilir;
    bayi stoğundan yeni kart takar. Para hiç oynamaz — iade edip yeniden
    tahsil etmek kartın o günkü fiyatını araya sokardı.
    """
    from apps.basvurular.services import SimDegisimiHatasi, sim_bozuk_bildir

    basvuru = get_object_or_404(
        Basvuru.objects.select_related("durum"),
        referans_no=referans,
        tedarikci=request.user,
    )
    kart = basvuru.kullanilan_simler.filter(pk=request.POST.get("kart") or 0).first()
    if kart is None:
        messages.error(request, "Bu başvuruda takılı bir SIM kart bulunamadı.")
        return redirect("basvurular:detay", referans=referans)

    try:
        sim_bozuk_bildir(
            basvuru,
            kart,
            bildiren=request.user,
            aciklama=(request.POST.get("aciklama") or "").strip()[:200],
        )
    except SimDegisimiHatasi as hata:
        messages.error(request, str(hata))
    else:
        messages.success(
            request,
            f"{kart.imei} arızalı işaretlendi; bayi yeni kart seçince başvuru sana geri döner.",
        )
    return redirect("basvurular:detay", referans=referans)


@login_required
@bayi_gerekli
def duzelt(request, referans):
    """Bayi, düzenleyebildiği durumdaki başvurusunu düzeltip yeniden gönderir.

    Eksik evrak, yanlış girilmiş alan, bozuk çıkan SIM — hepsi aynı ekran.
    Hat bilgileri kilitli (fiyat oradan çıkıyor), bakiye kapısı işlemez
    (iş zaten satın alındı). Gönderince başvuru bildirim öncesi durumuna
    döner ve geçmişe neyin değiştiği düşer.
    """

    from apps.basvurular.forms import BasvuruDuzeltmeFormu
    from apps.basvurular.services import SimDegisimiHatasi

    basvuru = get_object_or_404(
        Basvuru.objects.select_related("durum", "operator", "tarife", "kampanya", "kategori")
        .prefetch_related("belgeler", "kategori__alanlar"),
        referans_no=referans,
        bayi=request.user,
    )
    if not basvuru.bayi_duzeltebilir:
        messages.error(request, "Bu başvuru şu an düzeltmeye açık değil.")
        return redirect("basvurular:detay", referans=referans)

    if request.method == "POST":
        form = BasvuruDuzeltmeFormu(request.POST, request.FILES, basvuru=basvuru)
        if form.is_valid():
            try:
                form.kaydet_duzeltme(request.user)
            except (ValidationError, SimDegisimiHatasi) as hata:
                form.add_error(None, hata)
            else:
                messages.success(
                    request,
                    f"Düzeltmen alındı; başvuru “{basvuru.durum.ad}” durumunda işleme geri döndü.",
                )
                return redirect("basvurular:detay", referans=referans)
    else:
        form = BasvuruDuzeltmeFormu(basvuru=basvuru)

    return render(
        request,
        "basvurular/duzelt.html",
        {"form": form, "basvuru": basvuru, "kategori": basvuru.kategori,
         "yonetim_notu": basvuru.son_yonetim_notu},
    )


@login_required
def detay_gorunumu_ayarla(request, referans):
    """Bayi detay ekranında hangi alanları göreceğini kendisi seçer.

    Kapatılanlar saklanır, açık olanlar değil: kategoriye sonradan eklenen
    bir alan kendiliğinden görünür olsun, bayi listeyi yeniden gözden
    geçirmek zorunda kalmasın.
    """
    from apps.bayi.models import DetayGorunumTercihi

    basvuru = get_object_or_404(
        Basvuru.objects.select_related("kategori").filter(
            Q(bayi=request.user) | Q(tedarikci=request.user)
        ),
        referans_no=referans,
    )

    if request.method == "POST":
        acik = set(request.POST.getlist("alan"))
        # Kutuda hiç çizilmeyen satır "kapatıldı" sayılmamalı: tedarikçiye
        # gösterilmeyen bayi satırları listeye buradan da girmez.
        gizli = [
            satir["anahtar"]
            for satir in detay_satirlari(
                basvuru,
                tedarikci_gorunumu=(
                    request.user.id == basvuru.tedarikci_id
                    and request.user.id != basvuru.bayi_id
                ),
            )
            if satir["anahtar"] not in acik
        ]
        tercih, _ = DetayGorunumTercihi.objects.get_or_create(kullanici=request.user)
        tercih.gizli_alanlar = gizli
        tercih.save(update_fields=["gizli_alanlar", "guncelleme_tarihi"])
        messages.success(request, "Görünüm ayarların kaydedildi.")

    return redirect("basvurular:detay", referans=referans)


def _belge_kaydi(request, referans, alan_kodu):
    kayit = get_object_or_404(
        BasvuruBelgesi.objects.select_related("basvuru"),
        basvuru__referans_no=referans,
        alan_kodu=alan_kodu,
    )

    # Başvuruyu getiren bayi, işlemi üstlenen tedarikçi ve personel görebilir.
    # Tedarikçi aktivasyonu fiilen kendisi yaptığı için kimlik bilgilerini
    # operatör sistemine oradan giriyor; erişimi işin gereği.
    ilgili = {kayit.basvuru.bayi_id, kayit.basvuru.tedarikci_id}
    if not request.user.is_staff and request.user.id not in ilgili:
        raise Http404

    if not kayit.dosya:
        raise Http404
    return kayit


@login_required
def belge_goster(request, referans, alan_kodu):
    """Kimlik görüntüsünü sitenin içinde, bir sayfada gösterir.

    Dosyanın kendisine gitmek telefonda ve bazı tarayıcılarda görüntüyü
    cihaza indiriyordu; kişisel veri bayinin, tedarikçinin ya da personelin
    telefonunda birikmesin. Hem bayi/tedarikçi detayı hem yönetim paneli
    buraya bağlanır.
    """
    from django.urls import reverse

    kayit = _belge_kaydi(request, referans, alan_kodu)
    if not kayit.resim_mi:
        return redirect(kayit.get_absolute_url())

    if request.user.is_staff:
        geri = reverse("admin:basvurular_basvuru_change", args=[kayit.basvuru_id])
    else:
        geri = reverse("basvurular:detay", args=[referans])

    yanit = render(
        request,
        "basvurular/belge_goster.html",
        {"belge": kayit, "basvuru": kayit.basvuru, "geri": geri},
    )
    yanit["Cache-Control"] = "private, no-store"
    return yanit


@login_required
def belge(request, referans, alan_kodu):
    """Başvuru belgesini izin kontrolünden geçirerek sunar.

    Kimlik ve pasaport görüntüleri kişisel veridir; MEDIA_URL üzerinden
    doğrudan erişime açılmaz. Yalnızca başvuruyu giren bayi ve yetkili
    personel görüntüleyebilir.
    """
    kayit = _belge_kaydi(request, referans, alan_kodu)

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
    if gomulu_gosterilebilir:
        # Resme dosya adı verilmez: "inline; filename=…" başlığını gören bazı
        # telefon tarayıcıları görüntüyü göstermek yerine cihaza indiriyordu.
        yanit["Content-Disposition"] = "inline"
    # Tarayıcı ve ara sunucular kişisel veriyi paylaşımlı önbelleğe almasın.
    yanit["Cache-Control"] = "private, max-age=300"
    yanit["X-Content-Type-Options"] = "nosniff"
    # Dosya bir şekilde gömülü açılsa bile betik çalıştıramasın.
    yanit["Content-Security-Policy"] = "sandbox; default-src 'none'; img-src 'self'"
    return yanit
