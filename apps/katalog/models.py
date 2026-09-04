"""Katalog: operatörler, başvuru kategorileri, tarifeler, kampanyalar ve
kategorilere bağlı dinamik form alanları.

Buradaki her şey veridir. Yeni bir başvuru tipi eklemek için kod yazmak
gerekmez; admin panelinden kategori açıp alanlarını tanımlamak yeterlidir.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from apps.katalog.utils import kucult, turkce_slug


class MusteriTipi(models.TextChoices):
    TURK = "turk", "Türk Vatandaşı"
    YABANCI = "yabanci", "Yabancı Uyruklu"
    HEPSI = "hepsi", "Her İkisi"


class ZamanDamgali(models.Model):
    """Oluşturma/güncelleme zamanı tutan soyut taban model."""

    olusturma_tarihi = models.DateTimeField("Oluşturma Tarihi", auto_now_add=True)
    guncelleme_tarihi = models.DateTimeField("Güncelleme Tarihi", auto_now=True)

    class Meta:
        abstract = True


class Operator(ZamanDamgali):
    ad = models.CharField("Operatör Adı", max_length=100, unique=True)
    slug = models.SlugField("Kısa Ad", max_length=120, unique=True, blank=True)
    logo = models.ImageField("Logo", upload_to="operator/", blank=True, null=True)
    renk = models.CharField(
        "Marka Rengi",
        max_length=7,
        default="#6366f1",
        help_text="Panelde rozet rengi olarak kullanılır. Örn: #e30613",
    )
    sira = models.PositiveIntegerField("Sıra", default=0)
    aktif = models.BooleanField("Aktif", default=True)

    class Meta:
        verbose_name = "Operatör"
        verbose_name_plural = "Operatörler"
        ordering = ["sira", "ad"]

    def __str__(self):
        return self.ad

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = turkce_slug(self.ad)
        super().save(*args, **kwargs)


class BasvuruKategorisi(ZamanDamgali):
    """Ana başvuru tipi: Kontörlü Yeni Hat, Faturalı Yeni Hat, MNT, ADSL...

    Eski sistemdeki 7 ayrı başvuru modelinin yerini alır.
    """

    ad = models.CharField("Kategori Adı", max_length=150, unique=True)
    slug = models.SlugField("Kısa Ad", max_length=170, unique=True, blank=True)
    aciklama = models.TextField("Açıklama", blank=True)
    ikon = models.CharField(
        "İkon",
        max_length=50,
        default="description",
        help_text="Material Symbols ikon adı. Örn: sim_card, router, swap_horiz",
    )
    operatorler = models.ManyToManyField(
        Operator,
        verbose_name="Geçerli Operatörler",
        related_name="kategoriler",
        blank=True,
        help_text="Boş bırakılırsa tüm aktif operatörler seçilebilir.",
    )
    musteri_tipi = models.CharField(
        "Müşteri Tipi",
        max_length=10,
        choices=MusteriTipi.choices,
        default=MusteriTipi.HEPSI,
    )
    tarife_zorunlu = models.BooleanField(
        "Tarife Seçimi Zorunlu",
        default=True,
        help_text="Pasaportlu işlemler gibi tarifesiz kategorilerde kapatın.",
    )
    sim_karsiligi_gerekir = models.BooleanField(
        "SIM Karşılığı Takip Edilsin",
        default=False,
        help_text=(
            "Bu tip aktivasyon fiziksel SIM tüketiyorsa açın. Tamamlanan her "
            "işlem için operatörden alınacak yeni SIM takibe girer."
        ),
    )
    sira = models.PositiveIntegerField("Sıra", default=0)
    aktif = models.BooleanField("Aktif", default=True)

    class Meta:
        verbose_name = "Başvuru Kategorisi"
        verbose_name_plural = "Başvuru Kategorileri"
        ordering = ["sira", "ad"]

    def __str__(self):
        return self.ad

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = turkce_slug(self.ad)
        super().save(*args, **kwargs)

    def gecerli_operatorler(self):
        """Bu kategoride başvuru girilebilecek operatörler.

        Kategoriye bağlanmış operatörlerin yanında, bu kategoride aktif
        tarifesi olan operatörler de listeye girer. Aksi hâlde tarife
        tanımlayıp operatörü listeye eklemeyi unutan yönetici, tarifesini
        formda göremezdi.

        Hiçbiri yoksa tüm aktif operatörler gösterilir.
        """
        secilenler = Operator.objects.filter(aktif=True).filter(
            models.Q(kategoriler=self) | models.Q(tarifeler__kategori=self,
                                                  tarifeler__aktif=True)
        ).distinct()
        return secilenler if secilenler.exists() else Operator.objects.filter(aktif=True)


class Tarife(ZamanDamgali):
    """Kategori + operatör altındaki tarife.

    Eski sistemdeki 8 ayrı tarife modeli (Türk/Yabancı × 4 başvuru tipi)
    tek modelde toplanmıştır; ayrım artık `musteri_tipi` alanındadır.
    """

    kategori = models.ForeignKey(
        BasvuruKategorisi,
        verbose_name="Kategori",
        related_name="tarifeler",
        on_delete=models.CASCADE,
    )
    operator = models.ForeignKey(
        Operator,
        verbose_name="Operatör",
        related_name="tarifeler",
        on_delete=models.CASCADE,
    )
    ad = models.CharField("Tarife Adı", max_length=200)
    musteri_tipi = models.CharField(
        "Müşteri Tipi",
        max_length=10,
        choices=MusteriTipi.choices,
        default=MusteriTipi.HEPSI,
    )
    aciklama = models.TextField(
        "Açıklama",
        blank=True,
        help_text="Bayi tarife sayfasında bu tarifenin altında görünür.",
    )
    gorsel = models.ImageField(
        "Görsel",
        upload_to="tarife/%Y/%m/",
        blank=True,
        null=True,
        help_text="Operatörün tarife görseli. Bayi tarife sayfasında gösterilir.",
    )
    sira = models.PositiveIntegerField("Sıra", default=0)
    aktif = models.BooleanField("Aktif", default=True)

    class Meta:
        verbose_name = "Tarife"
        verbose_name_plural = "Tarifeler"
        ordering = ["kategori", "operator", "sira", "ad"]
        constraints = [
            models.UniqueConstraint(
                fields=["kategori", "operator", "ad"],
                name="tarife_kategori_operator_ad_benzersiz",
            )
        ]

    def __str__(self):
        # Kategori de yazılır: seçim kutularında hangi kategoriye ait olduğu
        # görünmeden yanlış tarife seçilebiliyordu.
        return f"{self.kategori.ad} · {self.operator.ad} · {self.ad}"

    def save(self, *args, **kwargs):
        self.gorsel = kucult(self.gorsel)
        super().save(*args, **kwargs)


class Kampanya(ZamanDamgali):
    """Tarifenin altındaki alt kampanya. Tarih aralığı dolunca kendiliğinden düşer."""

    tarife = models.ForeignKey(
        Tarife,
        verbose_name="Tarife",
        related_name="kampanyalar",
        on_delete=models.CASCADE,
    )
    ad = models.CharField("Kampanya Adı", max_length=200)
    aciklama = models.TextField(
        "Açıklama", blank=True, help_text="Bayi tarife sayfasında görünür."
    )
    gorsel = models.ImageField(
        "Görsel", upload_to="kampanya/%Y/%m/", blank=True, null=True
    )
    baslangic_tarihi = models.DateField("Başlangıç Tarihi", null=True, blank=True)
    bitis_tarihi = models.DateField("Bitiş Tarihi", null=True, blank=True)
    sira = models.PositiveIntegerField("Sıra", default=0)
    aktif = models.BooleanField("Aktif", default=True)

    class Meta:
        verbose_name = "Kampanya"
        verbose_name_plural = "Kampanyalar"
        ordering = ["tarife", "sira", "ad"]

    def __str__(self):
        return f"{self.tarife.ad} · {self.ad}"

    def save(self, *args, **kwargs):
        self.gorsel = kucult(self.gorsel)
        super().save(*args, **kwargs)

    def clean(self):
        if (
            self.baslangic_tarihi
            and self.bitis_tarihi
            and self.bitis_tarihi < self.baslangic_tarihi
        ):
            raise ValidationError(
                {"bitis_tarihi": "Bitiş tarihi başlangıç tarihinden önce olamaz."}
            )

    @property
    def su_an_gecerli(self):
        """Kampanya bugün itibarıyla yayında mı?"""
        if not self.aktif:
            return False
        bugun = timezone.localdate()
        if self.baslangic_tarihi and bugun < self.baslangic_tarihi:
            return False
        if self.bitis_tarihi and bugun > self.bitis_tarihi:
            return False
        return True


class CekirdekAlan(models.TextChoices):
    """Başvuruda gerçek kolonu olan alanlar.

    Bu alanlar aranabilir ve indekslidir; değerleri JSON'a değil kendi
    kolonlarına yazılır. Hangi kategoride görüneceğine, ne yazacağına ve
    zorunlu olup olmadığına yine admin karar verir.
    """

    ISIM = "isim", "İsim"
    SOYISIM = "soyisim", "Soyisim"
    KIMLIK_TIPI = "kimlik_tipi", "Kimlik Tipi"
    KIMLIK_NO = "kimlik_no", "Kimlik / Pasaport No"
    IRTIBAT = "irtibat", "İletişim Numarası"
    NUMARA = "numara", "İşlem Yapılacak Numara"
    ADRES = "adres", "Adres"


class AlanTipi(models.TextChoices):
    METIN = "metin", "Metin"
    UZUN_METIN = "uzun_metin", "Uzun Metin"
    SAYI = "sayi", "Sayı"
    TUTAR = "tutar", "Tutar"
    TARIH = "tarih", "Tarih"
    TELEFON = "telefon", "Telefon"
    EPOSTA = "eposta", "E-posta"
    SECIM = "secim", "Açılır Liste"
    ONAY = "onay", "Evet / Hayır"
    DOSYA = "dosya", "Dosya"
    RESIM = "resim", "Resim"
    SIM_KART = "sim_kart", "SIM Kart (bayinin stoğundan)"


class KategoriAlani(ZamanDamgali):
    """Kategoriye sorulacak ek form alanı.

    Formu bu tablo çizer. Yeni bir soru eklemek = yeni bir kayıt.
    Her başvuruda ortak olan alanlar (isim, kimlik no, irtibat...) burada
    tanımlanmaz; onlar Basvuru modelinde gerçek kolon olarak durur.
    """

    kategori = models.ForeignKey(
        BasvuruKategorisi,
        verbose_name="Kategori",
        related_name="alanlar",
        on_delete=models.CASCADE,
    )
    kod = models.SlugField(
        "Alan Kodu",
        max_length=60,
        help_text="Veride saklanacak anahtar. Örn: sim_imei, modem_istegi",
    )
    cekirdek_alan = models.CharField(
        "Çekirdek Alan",
        max_length=20,
        choices=CekirdekAlan.choices,
        blank=True,
        help_text=(
            "Doldurulursa değer başvurunun kendi kolonuna yazılır ve aranabilir "
            "olur. Boş bırakılırsa alan bu kategoriye özel ek bilgi olarak saklanır."
        ),
    )
    etiket = models.CharField("Etiket", max_length=150)
    tip = models.CharField("Alan Tipi", max_length=20, choices=AlanTipi.choices, default=AlanTipi.METIN)
    grup = models.CharField(
        "Bölüm Başlığı",
        max_length=100,
        blank=True,
        help_text="Aynı başlığı taşıyan alanlar formda birlikte gruplanır.",
    )
    zorunlu = models.BooleanField("Zorunlu", default=False)
    yardim_metni = models.CharField("Yardım Metni", max_length=255, blank=True)
    placeholder = models.CharField("Placeholder", max_length=150, blank=True)
    secenekler = models.TextField(
        "Seçenekler",
        blank=True,
        help_text="Açılır liste için her satıra bir seçenek yazın.",
    )
    dogrulama_deseni = models.CharField(
        "Doğrulama Deseni",
        max_length=255,
        blank=True,
        help_text="Opsiyonel regex. Örn: ^[0-9]{11}$",
    )
    min_uzunluk = models.PositiveIntegerField("Min. Uzunluk", null=True, blank=True)
    max_uzunluk = models.PositiveIntegerField("Maks. Uzunluk", null=True, blank=True)
    kosul_alani = models.ForeignKey(
        "self",
        verbose_name="Koşul Alanı",
        related_name="kosullu_alanlar",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="Bu alan yalnızca seçilen alan belirli bir değerdeyse görünür.",
    )
    kosul_degeri = models.CharField("Koşul Değeri", max_length=150, blank=True)
    sira = models.PositiveIntegerField("Sıra", default=0)
    aktif = models.BooleanField("Aktif", default=True)

    class Meta:
        verbose_name = "Kategori Alanı"
        verbose_name_plural = "Kategori Form Alanları"
        ordering = ["kategori", "sira", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["kategori", "kod"], name="kategori_alan_kodu_benzersiz"
            ),
            # Aynı çekirdek alan bir kategoride iki kez sorulmasın.
            models.UniqueConstraint(
                fields=["kategori", "cekirdek_alan"],
                condition=models.Q(cekirdek_alan__gt=""),
                name="kategori_cekirdek_alan_benzersiz",
            ),
        ]

    def __str__(self):
        return f"{self.kategori.ad} · {self.etiket}"

    def clean(self):
        if self.cekirdek_alan and self.dosya_mi:
            raise ValidationError(
                {"tip": "Çekirdek alanlar dosya tipinde olamaz."}
            )

    @property
    def cekirdek_mi(self):
        return bool(self.cekirdek_alan)

    @property
    def secenek_listesi(self):
        return [s.strip() for s in self.secenekler.splitlines() if s.strip()]

    @property
    def dosya_mi(self):
        return self.tip in {AlanTipi.DOSYA, AlanTipi.RESIM}
