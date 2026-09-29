"""Kontör, paket ve oyun pini satışı.

Bayi müşterisinin hattına TL/paket ya da oyun hesabına pin yükler. İşi biz
yapmıyoruz: işlem, anlaştığımız bir **sağlayıcıya** (Znet/Gencan, Teknografi,
kntryeni…) iletilir, sağlayıcı yükler, biz sonucunu sorarız.

**Her istek canlı paradır.** Sağlayıcıya giden her gönderim onun
bakiyesinden düşer. Bu yüzden aynı işlem aynı sağlayıcıya **hiçbir zaman
kendiliğinden ikinci kez gönderilmez**: gönderim ağa çıkmadan önce
`Deneme` kaydı olarak yazılır, cevabı anlaşılamazsa işlem askıya alınır ve
yönetici karar verir. Yalnızca sağlayıcı açıkça reddederse (işlem orada
hiç açılmadı) sıradaki sağlayıcıya geçilir.

Katalog veridir: kategori (Vodafone TL, Turkcell Paket, PUBG Mobile UC…),
paket, paketin hangi sağlayıcılara hangi sırayla gideceği ve her
sağlayıcıdan alışı (`Rota`), bayinin kontör fiyat grubu (`FiyatGrubu`:
Perakende, Toptan…) panelden girilir. Bayinin fiyatı saklanmaz, alıştan
grubun oranıyla hesaplanır.

Para `magaza.Siparis` üzerinden yürür — eSIM'deki gibi: işlem açılınca
tutar bakiyeden düşer, borca yazılmaz; iptal olursa ters kayıtla döner.
"""

import hashlib
import hmac
import secrets
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.urls import reverse

from apps.katalog.models import ZamanDamgali
from apps.katalog.utils import kucult, turkce_slug
from apps.kontor.saglayicilar import saglayici_secenekleri, saglayici_sinifi
from apps.kontor.sorgu import kaynak_secenekleri

SIFIR = Decimal("0.00")


class Saglayici(ZamanDamgali):
    """İşlemi ilettiğimiz bayi sistemi. Adres ve şifre burada, kodda değil."""

    ad = models.CharField("Ad", max_length=100, unique=True)
    tur = models.CharField(
        "Yazılımı",
        max_length=30,
        choices=saglayici_secenekleri,
        help_text="Hangi protokolle konuşulacağı. Yeni bir yazılım türü kodla eklenir.",
    )
    adres = models.CharField(
        "Site Adresi",
        max_length=200,
        help_text="Alan adı (ornek-kontor.com) ya da http(s):// ile tam adres.",
    )
    bayi_kodu = models.CharField(
        "Bayi Kodu",
        max_length=100,
        blank=True,
        help_text="Teknografi ister; Znet/Gencan yalnızca fiyat listesi çekerken kullanır, kntryeni hiç kullanmaz.",
    )
    kullanici_adi = models.CharField("Kullanıcı Adı", max_length=100)
    sifre = models.CharField("Şifre", max_length=200)
    ref_sayaci = models.PositiveBigIntegerField(
        "Sıradaki Referans No",
        default=1000,
        help_text=(
            "Sağlayıcıya giden tekil numara buradan artarak verilir. Sağlayıcı aynı "
            "numarayı ikinci kez kabul etmez: eski sistemde bu hesapla işlem yapıldıysa "
            "oradaki sayının üstünde bir değerle başlatın."
        ),
    )
    aktif = models.BooleanField(
        "Aktif",
        default=True,
        help_text="Kapatılırsa hiçbir işlem bu sağlayıcıya gönderilmez; sıradaki denenir.",
    )
    son_liste_cekme = models.DateTimeField(
        "Fiyat Listesi Çekildi", null=True, blank=True, editable=False
    )

    class Meta:
        verbose_name = "Kontör Sağlayıcısı"
        verbose_name_plural = "Kontör Sağlayıcıları"
        ordering = ["ad"]

    def __str__(self):
        return self.ad

    def adaptor(self):
        return saglayici_sinifi(self.tur)(self)

    @property
    def denenmedi(self):
        try:
            return saglayici_sinifi(self.tur).denenmedi
        except Exception:
            return False

    @property
    def paket_listesi_var(self):
        try:
            return saglayici_sinifi(self.tur).paket_listesi_var
        except Exception:
            return False

    def yeni_ref(self):
        """Sayaçtan bir numara ayırır; iki süreç aynı numarayı alamaz."""
        guncellenen = type(self).objects.filter(pk=self.pk).update(ref_sayaci=F("ref_sayaci") + 1)
        if not guncellenen:
            raise Saglayici.DoesNotExist
        self.refresh_from_db(fields=["ref_sayaci"])
        return str(self.ref_sayaci - 1)


class SaglayiciPaketi(models.Model):
    """Sağlayıcının fiyat listesindeki bir satır; her çekişte yenilenir.

    Yalnızca bilgi: yönetici hangi kodun ne fiyata olduğunu görür, rota
    alış fiyatları buradan güncellenir. Satış buna bağlı değildir.
    """

    saglayici = models.ForeignKey(
        Saglayici, verbose_name="Sağlayıcı", related_name="liste", on_delete=models.CASCADE
    )
    kod = models.CharField("Ürün Kodu", max_length=60)
    ad = models.CharField("Ad", max_length=200)
    fiyat = models.DecimalField("Alış", max_digits=12, decimal_places=2)
    operator = models.CharField("Operatör", max_length=60, blank=True)
    tip = models.CharField("Tip", max_length=60, blank=True)
    cekilme = models.DateTimeField("Çekildi", auto_now=True)

    class Meta:
        verbose_name = "Sağlayıcı Fiyatı"
        verbose_name_plural = "Sağlayıcı Fiyat Listeleri"
        ordering = ["saglayici", "operator", "ad"]
        constraints = [
            models.UniqueConstraint(fields=["saglayici", "kod"], name="kontor_saglayici_paket_kod")
        ]

    def __str__(self):
        return f"{self.saglayici} · {self.ad}"


class Hedef(models.TextChoices):
    """Yüklemenin neye yapıldığı; kategori bazında veridir."""

    TELEFON = "telefon", "Telefon numarası"
    HESAP = "hesap", "Oyuncu / hesap numarası"
    YOK = "yok", "Hedef yok (pin kodu döner)"


class Kategori(ZamanDamgali):
    """Vodafone TL, Turkcell Paket, PUBG Mobile UC…

    Bayi önce kategoriyi seçer. Operatör varsa kart marka rengini taşır.
    **Oyun kategorileri ayrı bölümdedir** (`oyun`): bayi menüsünde "Oyun &
    Pin" altında, `/oyun/…` adresinde, logosuyla listelenir; kontör
    listesine karışmaz. Satış, para ve sağlayıcı kuralları ikisinde aynıdır —
    ayrılan yalnızca vitrin.
    """

    ad = models.CharField("Ad", max_length=120, unique=True)
    slug = models.SlugField("Kısa Ad", max_length=140, unique=True, blank=True)
    oyun = models.BooleanField(
        "Oyun / E-pin",
        default=False,
        help_text=(
            "İşaretlenirse bayi menüsünde kontörden ayrı “Oyun & Pin” bölümünde görünür. "
            "Pin satışında “Yükleme Nereye”yi “Hedef yok”, oyuncu ID ile yüklemede "
            "“Oyuncu / hesap numarası” seçin."
        ),
    )
    gorsel = models.ImageField(
        "Logo",
        upload_to="oyun/",
        blank=True,
        null=True,
        help_text="Oyun kartında gösterilir (kare, sade logo). Küçültülüp WebP'ye çevrilir.",
    )
    operator = models.ForeignKey(
        "katalog.Operator",
        verbose_name="Operatör",
        related_name="kontor_kategorileri",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="Oyun ve pin kategorilerinde boş bırakılır.",
    )
    hedef = models.CharField(
        "Yükleme Nereye",
        max_length=10,
        choices=Hedef.choices,
        default=Hedef.TELEFON,
        help_text=(
            "Telefon: 10 haneli cep numarası istenir. Hesap: oyuncu ID gibi serbest metin. "
            "Hedef yok: pin satışı; kod sağlayıcının cevabıyla bayiye gösterilir."
        ),
    )
    hedef_etiketi = models.CharField(
        "Hedef Etiketi",
        max_length=60,
        blank=True,
        help_text="Formda kutunun üstünde yazan. Boşsa “Telefon numarası” / “Oyuncu ID”.",
    )
    api_operator = models.CharField(
        "Operatör Kodu",
        max_length=40,
        blank=True,
        help_text=(
            "Protokoldeki operatör adı (vodafone, turkcell, avea…). Bayilerin programlarından "
            "gelen istek kategoriyi bununla bulur; sağlayıcıya da rotada ayrı yazılmadıysa bu gider."
        ),
    )
    api_tip = models.CharField(
        "Tip Kodu",
        max_length=40,
        blank=True,
        help_text="Protokoldeki tip (ses, tam, tl…). Operatör koduyla birlikte kategoriyi belirler.",
    )
    sorgu_kaynagi = models.CharField(
        "Numara Sorgusu",
        max_length=40,
        blank=True,
        choices=kaynak_secenekleri,
        help_text=(
            "Seçilirse bayi numarayı yazıp bu numaranın alabileceği paketleri görür. "
            "Kaynaklar apps/kontor/sorgu/ klasöründeki dosyalardır. Sorgu satışı "
            "durdurmaz: cevap gelmezse paketler yine seçilebilir."
        ),
    )
    sorgu_sahibi_goster = models.BooleanField(
        "Hat Sahibini Göster",
        default=True,
        help_text=(
            "Sorgu sonucunun üstünde hat sahibinin maskeli adı (Ah*** Yı***) yazar; bayi "
            "yanlış numarayı yüklemeden önce müşteriye teyit eder. Ad hiçbir yere kaydedilmez. "
            "Kapatılırsa kaynağa hiç sorulmaz."
        ),
    )
    aciklama = models.TextField("Açıklama", blank=True, help_text="Bayi paket listesinin üstünde görür.")
    sira = models.PositiveIntegerField("Sıra", default=0)
    aktif = models.BooleanField("Aktif", default=True)

    class Meta:
        verbose_name = "Kontör Kategorisi"
        verbose_name_plural = "Kontör Kategorileri"
        ordering = ["sira", "ad"]
        constraints = [
            models.UniqueConstraint(
                fields=["api_operator", "api_tip"],
                condition=~Q(api_operator=""),
                name="kontor_kategori_api_kodu",
            )
        ]

    def __str__(self):
        return self.ad

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = turkce_slug(self.ad)
        self.gorsel = kucult(self.gorsel)
        self.api_operator = self.api_operator.strip().lower()
        self.api_tip = self.api_tip.strip().lower()
        super().save(*args, **kwargs)

    def validate_constraints(self, exclude=None):
        # Ham kısıt adı yöneticiye bir şey anlatmıyor; çakışanı adıyla söyle.
        if self.api_operator:
            cakisan = (
                Kategori.objects.filter(
                    api_operator=self.api_operator.strip().lower(),
                    api_tip=self.api_tip.strip().lower(),
                )
                .exclude(pk=self.pk)
                .first()
            )
            if cakisan:
                raise ValidationError(
                    {
                        "api_tip": f"Bu operatör ve tip kodu “{cakisan}” kategorisinde kullanılıyor. "
                        "Bayi programından gelen istek hangisine gideceğini bilemez."
                    }
                )
        super().validate_constraints(exclude=(exclude or set()) | {"api_operator", "api_tip"})

    # Oyun ve kontör aynı görünümleri kullanır, adresleri ayrıdır
    # (/oyun/pubg-mobile/, /kontor/vodafone-paket/). Şablonlar adresi
    # buradan alır, `{% url %}` ile kurmaz — hangi bölüm olduğunu bilmesinler.

    def get_absolute_url(self):
        return reverse("kontor:oyun" if self.oyun else "kontor:kategori", args=[self.slug])

    @property
    def sorgu_url(self):
        return reverse("kontor:oyun-sorgu" if self.oyun else "kontor:sorgu", args=[self.slug])

    @property
    def liste_url(self):
        return reverse("kontor:oyunlar" if self.oyun else "kontor:kategoriler")

    @property
    def bolum_adi(self):
        return "Oyun & Pin" if self.oyun else "Kontör"

    @property
    def hedef_basligi(self):
        if self.hedef_etiketi:
            return self.hedef_etiketi
        return {Hedef.TELEFON: "Telefon numarası", Hedef.HESAP: "Oyuncu ID"}.get(self.hedef, "")


class PaketSorgusu(models.QuerySet):
    def satista(self):
        """Aktif, kategorisi açık ve en az bir aktif sağlayıcıya yolu olan paketler."""
        return self.filter(
            aktif=True,
            kategori__aktif=True,
            rotalar__aktif=True,
            rotalar__saglayici__aktif=True,
        ).distinct()


class FiyatGrubu(ZamanDamgali):
    """Bayinin kontör fiyat kademesi: Perakende, Toptan…

    Bayinin ödeyeceği tutar paket paket girilmez; paketin alışından grubun
    oranıyla hesaplanır: `alış × (1 + oran/100) + ek tutar`. Alış değişince
    (elle ya da **Fiyat listesini çek** ile) bütün grupların fiyatı kendiliğinden
    değişir. Başvuru fiyatlarındaki bayi grubundan bağımsızdır: kontörde
    toptan çalışan bayi başvuruda başka kademede olabilir.
    """

    ad = models.CharField("Grup Adı", max_length=100, unique=True)
    # Genel kural isteğe bağlıdır: ikisi de boşsa kendi kuralı (net fiyat,
    # alış + %, alış + ₺) olmayan paket bu gruba **satılmaz**. Bir süre 0
    # varsayılandı ve kuralsız paket alış fiyatına, kârsız satılıyordu.
    oran = models.DecimalField(
        "Kuralsız paket: alışın üstüne (%)",
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(SIFIR)],
        help_text="İsteğe bağlı. Boşsa (ek tutar da boşsa) fiyatı yazılmamış paket bu gruba satılmaz.",
    )
    ek_tutar = models.DecimalField(
        "Kuralsız paket: ek tutar (₺)",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(SIFIR)],
        help_text="İsteğe bağlı; yüzdenin üstüne eklenir.",
    )
    varsayilan = models.BooleanField(
        "Varsayılan",
        default=False,
        help_text=(
            "Grubu seçilmemiş bayi bu grubun fiyatını öder. Yalnızca bir grup "
            "varsayılan olabilir; hiçbiri değilse grupsuz bayi paketin kendi "
            "satış fiyatını öder."
        ),
    )
    aciklama = models.CharField("Açıklama", max_length=255, blank=True)

    class Meta:
        verbose_name = "Kontör Fiyat Grubu"
        verbose_name_plural = "Kontör Fiyat Grupları"
        ordering = ["ad"]
        constraints = [
            models.UniqueConstraint(
                fields=["varsayilan"], condition=Q(varsayilan=True), name="kontor_tek_varsayilan_grup"
            )
        ]

    def __str__(self):
        return self.ad

    def validate_constraints(self, exclude=None):
        if self.varsayilan:
            diger = FiyatGrubu.objects.filter(varsayilan=True).exclude(pk=self.pk).first()
            if diger:
                raise ValidationError(
                    {"varsayilan": f"“{diger}” zaten varsayılan. Önce onun kutusunu kapatın."}
                )
        super().validate_constraints(exclude=(exclude or set()) | {"varsayilan"})

    @property
    def genel_kural_var(self):
        return self.oran is not None or self.ek_tutar is not None

    def fiyat(self, alis):
        """Kuralsız paketin fiyatı: genel kural yoksa ya da alış yoksa `None` (satılmaz)."""
        if alis is None or not self.genel_kural_var:
            return None
        return (alis * (1 + (self.oran or 0) / 100) + (self.ek_tutar or 0)).quantize(Decimal("0.01"), ROUND_HALF_UP)

    @classmethod
    def varsayilani(cls):
        return cls.objects.filter(varsayilan=True).first()


class Paket(ZamanDamgali):
    """Satılan tek şey: 100 TL, Kolay Paket 15, 660 UC…"""

    kategori = models.ForeignKey(
        Kategori, verbose_name="Kategori", related_name="paketler", on_delete=models.PROTECT
    )
    kod = models.CharField(
        "Kupür / Ürün Kodu",
        max_length=40,
        help_text=(
            "Bayi programları paketi bu kodla ister (kontor=100). Sağlayıcıya rotada "
            "ayrı kod yazılmadıysa bu gider."
        ),
    )
    ad = models.CharField("Ad", max_length=150)
    aciklama = models.CharField("Açıklama", max_length=255, blank=True)
    dakika = models.PositiveIntegerField("Dakika", default=0)
    internet_mb = models.PositiveIntegerField("İnternet (MB)", default=0)
    sms = models.PositiveIntegerField("SMS", default=0)
    gun = models.PositiveIntegerField("Gün", default=0)
    satis_fiyati = models.DecimalField(
        "Grupsuz Bayiye Satış",
        max_digits=12,
        decimal_places=2,
        default=SIFIR,
        validators=[MinValueValidator(SIFIR)],
        help_text=(
            "Yalnızca kontör fiyat grubu olmayan bayi için (varsayılan grup da "
            "yoksa). Gruptaki bayinin fiyatı alıştan hesaplanır."
        ),
    )
    tavsiye_fiyati = models.DecimalField(
        "Tavsiye Satış",
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(SIFIR)],
        help_text=(
            "Bayinin müşteriye söyleyeceği fiyat — çoğu zaman operatörün liste fiyatı. "
            "Doluysa bayi ekranında büyük rakam budur; bayinin alışı ve kazancı göz "
            "düğmesiyle açılır. Operatör sorgusunda görülen fiyattan doldurulabilir."
        ),
    )
    sira = models.PositiveIntegerField("Sıra", default=0)
    aktif = models.BooleanField("Aktif", default=True)

    objects = PaketSorgusu.as_manager()

    class Meta:
        verbose_name = "Kontör Paketi"
        verbose_name_plural = "Kontör Paketleri"
        ordering = ["kategori__sira", "kategori__ad", "sira", "satis_fiyati", "ad"]
        constraints = [
            models.UniqueConstraint(fields=["kategori", "kod"], name="kontor_paket_kod")
        ]

    def __str__(self):
        return f"{self.kategori} · {self.ad}"

    def validate_constraints(self, exclude=None):
        if self.kategori_id and self.kod:
            cakisan = (
                Paket.objects.filter(kategori_id=self.kategori_id, kod=self.kod.strip())
                .exclude(pk=self.pk)
                .first()
            )
            if cakisan:
                raise ValidationError(
                    {"kod": f"Bu kategoride “{cakisan.ad}” aynı kodu kullanıyor."}
                )
        super().validate_constraints(exclude=(exclude or set()) | {"kategori", "kod"})

    def save(self, *args, **kwargs):
        self.kod = self.kod.strip()
        super().save(*args, **kwargs)

    def ilk_alis(self):
        """Sıradaki ilk açık sağlayıcının alışı — grup fiyatı bundan hesaplanır.

        `rotalar__saglayici` önceden getirildiyse ek sorgu atmaz.
        """
        for rota in self.rotalar.all():
            if rota.aktif and rota.saglayici.aktif:
                return rota.alis_fiyati
        return None

    def get_absolute_url(self):
        ad = "kontor:oyun-paket" if self.kategori.oyun else "kontor:paket"
        return reverse(ad, args=[self.kategori.slug, self.kod])

    @property
    def yukle_url(self):
        ad = "kontor:oyun-yukle" if self.kategori.oyun else "kontor:yukle"
        return reverse(ad, args=[self.kategori.slug, self.kod])

    @property
    def icerik(self):
        """"1000 DK · 15 GB · 30 gün" — boş alanlar yazılmaz."""
        parcalar = []
        if self.dakika:
            parcalar.append(f"{self.dakika:,} DK".replace(",", "."))
        if self.internet_mb:
            gb = Decimal(self.internet_mb) / 1000
            parcalar.append(
                f"{gb.normalize():f} GB".replace(".", ",") if self.internet_mb >= 1000 else f"{self.internet_mb} MB"
            )
        if self.sms:
            parcalar.append(f"{self.sms:,} SMS".replace(",", "."))
        if self.gun:
            parcalar.append(f"{self.gun} gün")
        return " · ".join(parcalar)


class Rota(models.Model):
    """Paketin hangi sağlayıcıya, hangi sırayla ve hangi kodla gideceği.

    Eski sistemde api1/api2/api3 olarak paketin üstündeydi. Sıra küçükten
    büyüğe denenir; biri açıkça reddederse sıradakine geçilir. Kod, operatör
    ve tip boşsa paketin/kategorinin kendi kodları gider — çoğu sağlayıcı
    aynı kupürü kullanıyor, her satırı doldurmak gerekmesin.
    """

    paket = models.ForeignKey(Paket, verbose_name="Paket", related_name="rotalar", on_delete=models.CASCADE)
    saglayici = models.ForeignKey(
        Saglayici, verbose_name="Sağlayıcı", related_name="rotalar", on_delete=models.PROTECT
    )
    sira = models.PositiveSmallIntegerField("Sıra", default=1)
    uzak_kod = models.CharField("Sağlayıcıdaki Kodu", max_length=60, blank=True)
    uzak_operator = models.CharField("Operatör", max_length=60, blank=True)
    uzak_tip = models.CharField("Tip", max_length=60, blank=True)
    alis_fiyati = models.DecimalField(
        "Alış",
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=(
            "Bu sağlayıcıdan maliyet. Sağlayıcı cevapta tutar vermezse kâr bununla "
            "hesaplanır; fiyat listesi çekilebilen sağlayıcıda kendiliğinden güncellenir."
        ),
    )
    aktif = models.BooleanField("Aktif", default=True)

    class Meta:
        verbose_name = "Sağlayıcı Sırası"
        verbose_name_plural = "Sağlayıcı Sırası"
        ordering = ["sira", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["paket", "saglayici"], name="kontor_rota_tekil")
        ]

    def __str__(self):
        return f"{self.sira}. {self.saglayici}"

    def validate_constraints(self, exclude=None):
        if self.paket_id and self.saglayici_id:
            if Rota.objects.filter(paket_id=self.paket_id, saglayici_id=self.saglayici_id).exclude(pk=self.pk).exists():
                raise ValidationError(
                    {"saglayici": "Bu sağlayıcı paketin sırasında zaten var; bir paket bir sağlayıcıya bir kez gider."}
                )
        super().validate_constraints(exclude=(exclude or set()) | {"paket", "saglayici"})

    @property
    def gidecek_kod(self):
        return self.uzak_kod or self.paket.kod

    @property
    def gidecek_operator(self):
        return self.uzak_operator or self.paket.kategori.api_operator

    @property
    def gidecek_tip(self):
        return self.uzak_tip or self.paket.kategori.api_tip


class FiyatYontemi(models.TextChoices):
    NET = "net", "Net fiyat"
    YUZDE = "yuzde", "Alış + %"
    TUTAR = "tutar", "Alış + ₺"


class PaketFiyati(models.Model):
    """Bu pakette bu grubun kendi kuralı; girilmeyen paket grubun oranından hesaplanır.

    Yönetici paket paket seçer: net fiyat (444,15 — alışa bakılmaz), alışın
    üstüne yüzde ya da alışın üstüne sabit tutar.
    """

    paket = models.ForeignKey(Paket, verbose_name="Paket", related_name="grup_fiyatlari", on_delete=models.CASCADE)
    grup = models.ForeignKey(
        FiyatGrubu, verbose_name="Fiyat Grubu", related_name="paket_fiyatlari", on_delete=models.CASCADE
    )
    yontem = models.CharField("Yöntem", max_length=10, choices=FiyatYontemi.choices, default=FiyatYontemi.NET)
    deger = models.DecimalField(
        "Değer", max_digits=12, decimal_places=2, validators=[MinValueValidator(SIFIR)],
        help_text="Net fiyatta satış tutarı; Alış + % yöntemde yüzde; Alış + ₺ yöntemde eklenen tutar.",
    )

    class Meta:
        verbose_name = "Grup Fiyatı"
        verbose_name_plural = "Bayi Grubuna Göre Fiyat"
        constraints = [
            models.UniqueConstraint(fields=["paket", "grup"], name="kontor_paket_grup_fiyat")
        ]

    def __str__(self):
        return f"{self.grup}: {self.get_yontem_display()} {self.deger}"

    def hesapla(self, alis):
        """Bayinin ödeyeceği; alışa dayanan yöntemde alış yoksa `None`."""
        if self.yontem == FiyatYontemi.NET:
            return self.deger
        if alis is None:
            return None
        if self.yontem == FiyatYontemi.YUZDE:
            tutar = alis * (1 + self.deger / 100)
        else:
            tutar = alis + self.deger
        return tutar.quantize(Decimal("0.01"), ROUND_HALF_UP)


class GorulenPaket(models.Model):
    """Numara sorgusunda görülen bir paket; yeni paketi yakalamak için.

    Operatör yeni bir paket çıkardığında bunu ancak bir bayi sorgu yaptığında
    görürdük, o da ekranda kalıp kaybolurdu. Sorgu her taze cevapta
    (önbellekten değil) paketleri buraya yazar: ilk ve son görülme, fiyat
    değişimi. Kataloğumuzda karşılığı olmayan "yenidir"; yönetim listesinde
    **Kataloğa ekle** ile paket açılır ya da **Yok say** ile rozetten düşer.
    Ek istek atılmaz, bayilerin zaten yaptığı sorgulardan beslenir. Hat
    sahibine ya da numaraya dair hiçbir şey burada durmaz.
    """

    kaynak = models.CharField("Sorgu Kaynağı", max_length=40)
    kod = models.CharField("Paket ID", max_length=60)
    kategori = models.ForeignKey(
        Kategori,
        verbose_name="Kategori",
        related_name="gorulen_paketler",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="En son hangi kategorinin sorgusunda görüldüğü; Kataloğa ekle buraya açar.",
    )
    ad = models.CharField("Ad", max_length=200, blank=True)
    aciklama = models.TextField("Açıklama", blank=True)
    fiyat = models.DecimalField("Operatör Fiyatı", max_digits=12, decimal_places=2, null=True, blank=True)
    onceki_fiyat = models.DecimalField(
        "Önceki Fiyat", max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Fiyat değiştiyse bir önceki değer.",
    )
    fiyat_degisme = models.DateTimeField("Fiyat Değişti", null=True, blank=True)
    ilk_gorulme = models.DateTimeField("İlk Görülme", auto_now_add=True)
    son_gorulme = models.DateTimeField("Son Görülme")
    gorulme_sayisi = models.PositiveIntegerField("Görülme", default=1)
    yok_say = models.BooleanField(
        "Yok Say",
        default=False,
        help_text="Kataloğa eklenmeyecek; yeni paket rozetinde sayılmaz.",
    )

    class Meta:
        verbose_name = "Görülen Paket"
        verbose_name_plural = "Operatörde Görülen Paketler"
        ordering = ["-ilk_gorulme"]
        constraints = [
            models.UniqueConstraint(fields=["kaynak", "kod"], name="kontor_gorulen_paket_kod")
        ]

    def __str__(self):
        return f"{self.ad or self.kod} ({self.kod})"

    def katalogdaki(self):
        if self.kategori_id is None:
            return None
        return Paket.objects.filter(kategori_id=self.kategori_id, kod=self.kod).first()


class IslemDurumu(models.TextChoices):
    SIRADA = "sirada", "Sırada"
    ISLEMDE = "islemde", "İşlemde"
    BASARILI = "basarili", "Yüklendi"
    ASKIDA = "askida", "Askıda"
    IPTAL = "iptal", "İptal edildi"


# Sonuçlanmamış durumlar: para bayiden düşülü, iş sürüyor ya da karar bekliyor.
ACIK_DURUMLAR = (IslemDurumu.SIRADA, IslemDurumu.ISLEMDE, IslemDurumu.ASKIDA)


class Kanal(models.TextChoices):
    PANEL = "panel", "Panel"
    API = "api", "Bayi programı"


class Islem(ZamanDamgali):
    """Bir yükleme. Parası `siparis`te, sağlayıcı tarafı `denemeler`de.

    Durumlar:
      · **Sırada** — açıldı, para düştü, henüz bir sağlayıcıda değil.
      · **İşlemde** — bir sağlayıcı kabul etti, sonucu soruluyor.
      · **Yüklendi** — sağlayıcı başarılı dedi; sipariş teslim.
      · **Askıda** — bir sağlayıcının cevabı anlaşılamadı. Yüklenmiş de
        olabilir, olmamış da; kendiliğinden hiçbir şey yapılmaz, para
        düşülü kalır, yönetici karar verir.
      · **İptal** — hiçbir sağlayıcı yükleyemedi ya da yönetici iptal etti;
        tutar bayiye döndü.
    """

    siparis = models.OneToOneField(
        "magaza.Siparis", verbose_name="Sipariş", related_name="kontor", on_delete=models.PROTECT
    )
    bayi = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Bayi", related_name="kontor_islemleri", on_delete=models.PROTECT
    )
    paket = models.ForeignKey(
        Paket, verbose_name="Paket", related_name="islemler", null=True, blank=True, on_delete=models.SET_NULL
    )
    kategori = models.ForeignKey(
        Kategori, verbose_name="Kategori", related_name="islemler", null=True, blank=True, on_delete=models.SET_NULL
    )
    paket_adi = models.CharField("Paket", max_length=200)
    hedef = models.CharField("Numara / Hesap", max_length=64, blank=True, db_index=True)
    tavsiye_fiyati = models.DecimalField(
        "Tavsiye Satış",
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="İşlem anında bayiye gösterilen müşteri fiyatı; paketin fiyatı sonra değişse de kalır.",
    )
    kanal = models.CharField("Kanal", max_length=10, choices=Kanal.choices, default=Kanal.PANEL)
    bayi_ref = models.CharField(
        "Bayinin Referansı",
        max_length=64,
        blank=True,
        help_text="Bayi programının gönderdiği tekil numara; sonucu bununla sorar.",
    )
    durum = models.CharField(
        "Durum", max_length=10, choices=IslemDurumu.choices, default=IslemDurumu.SIRADA, db_index=True
    )
    sonuc_mesaji = models.TextField(
        "Sonuç",
        blank=True,
        help_text="Bayiye gösterilir: sağlayıcının mesajı, pin kodu ya da iptal sebebi.",
    )
    saglayici = models.ForeignKey(
        Saglayici,
        verbose_name="Sağlayıcı",
        related_name="islemler",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        help_text="İşlemin şu an bulunduğu ya da yüklendiği sağlayıcı.",
    )
    alis_tutari = models.DecimalField("Alış", max_digits=12, decimal_places=2, null=True, blank=True)
    sonuc_tarihi = models.DateTimeField("Sonuç Tarihi", null=True, blank=True)
    son_sorgu = models.DateTimeField("Son Sorgu", null=True, blank=True, editable=False)
    # Aynı işlemi iki süreç (işçi, bayinin sayfası, bayi programının sorgusu)
    # aynı anda yürütmesin. Uzun süren veritabanı kilidi yerine süreli bir
    # sahiplik: HTTP beklerken satır kilitli kalmaz.
    kilit_bitis = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "Kontör İşlemi"
        verbose_name_plural = "Kontör İşlemleri"
        ordering = ["-olusturma_tarihi"]
        indexes = [
            models.Index(fields=["durum", "olusturma_tarihi"]),
            models.Index(fields=["bayi", "-olusturma_tarihi"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["bayi", "bayi_ref"], condition=~Q(bayi_ref=""), name="kontor_islem_bayi_ref"
            )
        ]

    def __str__(self):
        return f"{self.siparis.referans_no} · {self.hedef or '—'} · {self.paket_adi}"

    def get_absolute_url(self):
        return reverse("kontor:islem", args=[self.siparis.referans_no])

    @property
    def acik(self):
        return self.durum in ACIK_DURUMLAR

    @property
    def tutar(self):
        return self.siparis.tutar

    @property
    def kar(self):
        if self.durum != IslemDurumu.BASARILI or self.alis_tutari is None:
            return None
        return self.siparis.tutar - self.alis_tutari


class DenemeDurumu(models.TextChoices):
    GONDERILIYOR = "gonderiliyor", "Gönderiliyor"
    ISLEMDE = "islemde", "İşlemde"
    BASARILI = "basarili", "Başarılı"
    REDDEDILDI = "reddedildi", "Reddedildi"
    BELIRSIZ = "belirsiz", "Cevap belirsiz"


class Deneme(models.Model):
    """İşlemin bir sağlayıcıya bir kez gönderilişi.

    **Ağa çıkmadan önce yazılır.** Sunucu gönderim sırasında düşerse kayıt
    "Gönderiliyor"da kalır; bir sonraki tur onu görür ve işlemi askıya
    alır — yeniden göndermez. Sağlayıcının ham cevabı olduğu gibi saklanır,
    yönetici neye göre karar verildiğini görsün.
    """

    islem = models.ForeignKey(Islem, verbose_name="İşlem", related_name="denemeler", on_delete=models.CASCADE)
    saglayici = models.ForeignKey(
        Saglayici, verbose_name="Sağlayıcı", related_name="denemeler", on_delete=models.PROTECT
    )
    ref = models.CharField("Bizim Referans", max_length=40)
    uzak_ref = models.CharField("Sağlayıcının İşlem No", max_length=64, blank=True)
    uzak_kod = models.CharField("Giden Kod", max_length=60, blank=True)
    uzak_operator = models.CharField("Giden Operatör", max_length=60, blank=True)
    uzak_tip = models.CharField("Giden Tip", max_length=60, blank=True)
    durum = models.CharField(
        "Durum", max_length=15, choices=DenemeDurumu.choices, default=DenemeDurumu.GONDERILIYOR
    )
    elle = models.BooleanField(
        "Elle Gönderildi",
        default=False,
        help_text="Yönetici askıdaki işlemi bilerek bu sağlayıcıya gönderdi.",
    )
    gonderim_cevabi = models.TextField("Gönderim Cevabı", blank=True)
    sonuc_cevabi = models.TextField("Son Sorgu Cevabı", blank=True)
    alis = models.DecimalField("Alış", max_digits=12, decimal_places=2, null=True, blank=True)
    olusturma_tarihi = models.DateTimeField("Gönderildi", auto_now_add=True)
    guncelleme_tarihi = models.DateTimeField("Güncellendi", auto_now=True)

    class Meta:
        verbose_name = "Gönderim"
        verbose_name_plural = "Gönderimler"
        ordering = ["olusturma_tarihi", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["saglayici", "ref"], name="kontor_deneme_ref")
        ]

    def __str__(self):
        return f"{self.saglayici} · {self.ref}"


def api_anahtari_ozeti(anahtar):
    return hashlib.sha256((anahtar or "").encode()).hexdigest()


class ApiErisimi(ZamanDamgali):
    """Bayinin kendi kontör programından bize bağlanma izni.

    Program Znet protokolüyle `bayi_kodu` ve `sifre` gönderir. Şifre hesap
    parolası **değildir**: ayrı üretilir, bir kez gösterilir ve yalnızca
    özeti saklanır. Hesap parolası programın ayar dosyasında düz metin
    durmasın; sızarsa panel değil yalnızca bu kapı açılır ve yeni şifre
    üretmek onu kapatır.

    Özet SHA-256'dır, parola özeti (PBKDF2) değil: şifre insanın seçtiği
    bir kelime değil, 16 karakterlik rastgele bir anahtardır ve program
    her sorguda gönderir — her istekte yarım saniye yakmanın getirisi yok.
    """

    kullanici = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name="Bayi",
        related_name="kontor_api",
        on_delete=models.CASCADE,
    )
    bayi_kodu = models.CharField(
        "Bayi Kodu",
        max_length=64,
        unique=True,
        help_text="Programa yazılacak kullanıcı kodu. Boş bırakılırsa bayinin telefon numarası olur.",
        blank=True,
    )
    anahtar_ozeti = models.CharField(max_length=64, blank=True, editable=False)
    aktif = models.BooleanField("Aktif", default=True)
    son_kullanim = models.DateTimeField("Son İstek", null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "Bayi API Erişimi"
        verbose_name_plural = "Bayi API Erişimleri"
        ordering = ["bayi_kodu"]

    def __str__(self):
        return self.bayi_kodu

    def save(self, *args, **kwargs):
        if not self.bayi_kodu:
            self.bayi_kodu = self.kullanici.get_username()
        self.bayi_kodu = self.bayi_kodu.strip()
        super().save(*args, **kwargs)

    def yeni_anahtar(self):
        """Yeni şifre üretir, özetini yazar ve düz hâlini **bir kez** döndürür."""
        anahtar = secrets.token_urlsafe(12)
        self.anahtar_ozeti = api_anahtari_ozeti(anahtar)
        self.save(update_fields=["anahtar_ozeti", "guncelleme_tarihi"])
        return anahtar

    def anahtar_dogru_mu(self, anahtar):
        if not self.anahtar_ozeti or not anahtar:
            return False
        return hmac.compare_digest(self.anahtar_ozeti, api_anahtari_ozeti(anahtar))
