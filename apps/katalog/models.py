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
        # Logo da diğer görseller gibi küçültülüp WebP'ye çevrilir.
        self.logo = kucult(self.logo)
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
            models.Q(kategoriler=self) | models.Q(tarifeler__kategoriler=self,
                                                  tarifeler__aktif=True)
        ).distinct()
        return secilenler if secilenler.exists() else Operator.objects.filter(aktif=True)


class Tarife(ZamanDamgali):
    """Kategori + operatör altındaki tarife.

    Eski sistemdeki 8 ayrı tarife modeli (Türk/Yabancı × 4 başvuru tipi)
    tek modelde toplanmıştır; ayrım artık `musteri_tipi` alanındadır.
    """

    kategoriler = models.ManyToManyField(
        BasvuruKategorisi,
        verbose_name="Kategoriler",
        related_name="tarifeler",
        help_text=(
            "Aynı tarife birden çok kategoride geçerli olabilir. Operatör aynı "
            "paketi hem numara taşımada hem yeni hatta veriyorsa hepsini işaretleyin; "
            "tarifeyi ikinci kez açmak gerekmez."
        ),
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
    kisa_aciklama = models.CharField(
        "Kısa Açıklama / Uyarı",
        max_length=300,
        blank=True,
        help_text=(
            "Bayi bu tarifeyi başvuruda seçtiği anda karşısına açılır. "
            "Atlanmaması gereken bir şey varsa buraya yazın; boş bırakılırsa "
            "hiçbir şey açılmaz."
        ),
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
        ordering = ["operator", "sira", "ad"]
        # Tekillik kısıtı bilinçli olarak yok.
        #
        # Eski kısıt (kategori, operatör, ad) bir kategoride aynı tarifenin
        # iki kez açılmasını engelliyordu. Kategori çoğullaşınca bunun
        # veritabanı karşılığı (operatör, ad) olurdu; ama o kısıt, aynı adı
        # farklı kategorilerde taşıyan mevcut tarifelerin birleştirilmesini
        # şart koşar. Tarifelerin kendi para kuralları var: birleştirmek
        # hangi fiyatın kalacağına karar vermek demek. Bu, migration'ın
        # vereceği bir karar değil — yönetici iki tarifeyi tek tarifede
        # toplamak isterse kategorileri işaretleyip diğerini kendisi kapatır.


    def __str__(self):
        # Kategoriler de yazılır: seçim kutularında hangi kategoriye ait
        # olduğu görünmeden yanlış tarife seçilebiliyordu.
        return f"{self.kategori_adlari} · {self.operator.ad} · {self.ad}"

    @property
    def kategori_adlari(self):
        """Tarifenin geçerli olduğu kategoriler, tek satırda."""
        adlar = [kategori.ad for kategori in self.kategoriler.all()]
        return ", ".join(adlar) if adlar else "kategorisiz"

    def save(self, *args, **kwargs):
        self.gorsel = kucult(self.gorsel)
        super().save(*args, **kwargs)


class Kampanya(ZamanDamgali):
    """Tarifenin altındaki alt kampanya. Tarih aralığı dolunca kendiliğinden düşer.

    Görseli ve açıklaması yoktur: kampanya bayiye gösterilen bir içerik değil,
    başvuru girilirken yapılan bir seçimdir. Formda adıyla listelenir, o kadar.
    Anlatılacak bir şey varsa tarifenin açıklamasına yazılır.
    """

    tarife = models.ForeignKey(
        Tarife,
        verbose_name="Tarife",
        related_name="kampanyalar",
        on_delete=models.CASCADE,
    )
    ad = models.CharField("Kampanya Adı", max_length=200)
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
        help_text=(
            "Verinin saklanacağı anahtar; bayiye gösterilmez. Kategoride "
            "benzersiz olmalı. Türkçe harf ve boşluk kullanmayın. "
            "Örn: sim_imei, kimlik_on_cocuk"
        ),
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
    etiket = models.CharField(
        "Etiket",
        max_length=150,
        help_text=(
            "Bayinin formda gördüğü başlık. Başvuru detayında ve yönetim "
            "panelinde de bu ad görünür. Örn: Kimlik Ön Yüz"
        ),
    )
    tip = models.CharField(
        "Alan Tipi",
        max_length=20,
        choices=AlanTipi.choices,
        default=AlanTipi.METIN,
        help_text=(
            "Formda hangi kutunun çıkacağı. Resim seçilirse telefonda "
            "doğrudan kamera açılır; SIM Kart seçilirse bayinin stoğundaki "
            "kartlar listelenir. Resim ve Dosya alanları çekirdek alan olamaz."
        ),
    )
    grup = models.CharField(
        "Bölüm Başlığı",
        max_length=100,
        blank=True,
        help_text=(
            "Formda başlık olarak çıkar; aynı başlığı taşıyan alanlar birlikte "
            "gruplanır. Boş bırakılırsa alan “Başvuru detayları” altına düşer. "
            "Kimlik görselleri için “Belgeler” yazın."
        ),
    )
    zorunlu = models.BooleanField(
        "Zorunlu",
        default=False,
        help_text="Açıksa bayi bu alanı doldurmadan başvuruyu gönderemez.",
    )
    yardim_metni = models.CharField(
        "Yardım Metni",
        max_length=255,
        blank=True,
        help_text="Formda kutunun altında küçük gri yazı olarak görünür.",
    )
    placeholder = models.CharField(
        "Placeholder",
        max_length=150,
        blank=True,
        help_text=(
            "Kutu boşken içinde soluk görünen örnek metin. Yazılınca kaybolur; "
            "yardım metninin yerini tutmaz."
        ),
    )
    secenekler = models.TextField(
        "Seçenekler",
        blank=True,
        help_text=(
            "Yalnızca Seçim tipinde kullanılır: her satıra bir seçenek yazın. "
            "Bayi bunlardan birini seçer."
        ),
    )
    dogrulama_deseni = models.CharField(
        "Doğrulama Deseni",
        max_length=255,
        blank=True,
        help_text=(
            "İsteğe bağlı. Girilen değer bu kalıba uymazsa form reddedilir. "
            "Örn: 11 hane rakam için ^[0-9]{11}$"
        ),
    )
    min_uzunluk = models.PositiveIntegerField(
        "Min. Uzunluk",
        null=True,
        blank=True,
        help_text="Girilen metin bu kadar karakterden kısaysa form reddedilir.",
    )
    max_uzunluk = models.PositiveIntegerField(
        "Maks. Uzunluk",
        null=True,
        blank=True,
        help_text="Kutuya bu sayıdan fazla karakter yazılamaz.",
    )
    kosul_alani = models.ForeignKey(
        "self",
        verbose_name="Koşul Alanı",
        related_name="kosullu_alanlar",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text=(
            "Bu alan formda hep görünmesin, yalnızca başka bir alan belirli "
            "bir değerdeyken çıksın istiyorsanız o alanı seçin. Boşsa alan "
            "her zaman görünür."
        ),
    )
    kosul_degeri = models.CharField(
        "Koşul Değeri",
        max_length=150,
        blank=True,
        help_text="Koşul alanı bu değerdeyken bu alan görünür.",
    )
    sira = models.PositiveIntegerField(
        "Sıra",
        default=0,
        help_text="Formdaki yeri. Küçük sayı önce gelir.",
    )
    aktif = models.BooleanField(
        "Aktif",
        default=True,
        help_text=(
            "Kapatılırsa alan formda hiç sorulmaz. Bu kategoride gereksiz "
            "alanları silmek yerine kapatın; eski başvurulardaki değerleri durur."
        ),
    )

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
                {
                    "cekirdek_alan": (
                        "Görsel ve dosya alanları çekirdek alan olamaz; değerleri "
                        "başvurunun kolonuna yazılamaz. İkinci bir kimlik görseli "
                        "ekliyorsanız bu kutuyu boş bırakın."
                    )
                }
            )

        # Ham kısıt hatası ("kategori_cekirdek_alan_benzersiz ihlal edildi")
        # yöneticiye ne yapacağını söylemiyordu. Çakışan alanı adıyla göster.
        if self.cekirdek_alan and self.kategori_id:
            cakisan = (
                KategoriAlani.objects.filter(
                    kategori_id=self.kategori_id, cekirdek_alan=self.cekirdek_alan
                )
                .exclude(pk=self.pk)
                .first()
            )
            if cakisan is not None:
                raise ValidationError(
                    {
                        "cekirdek_alan": (
                            f"“{self.get_cekirdek_alan_display()}” bu kategoride "
                            f"zaten “{cakisan.etiket}” alanında kullanılıyor. Aynı "
                            "çekirdek alan iki kez sorulamaz — bu ek bir alansa "
                            "kutuyu boş bırakın."
                        )
                    }
                )

        if self.kod and self.kategori_id:
            ayni_kod = (
                KategoriAlani.objects.filter(kategori_id=self.kategori_id, kod=self.kod)
                .exclude(pk=self.pk)
                .first()
            )
            if ayni_kod is not None:
                raise ValidationError(
                    {
                        "kod": (
                            f"Bu kategoride “{ayni_kod.etiket}” alanı da aynı kodu "
                            "kullanıyor. Alan kodu kategoride benzersiz olmalı."
                        )
                    }
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
