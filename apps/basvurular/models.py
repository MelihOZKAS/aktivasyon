"""Başvurular: tek Basvuru modeli, dinamik ek alanlar ve belgeler.

Eski sistemdeki 7 ayrı başvuru modelinin (Evrak, KontorluYeniHat,
FaturaliYeniHat, Sebekeici, internet, EvrakPass, EvrakPassYeni) tamamı
buradaki tek modelde toplanmıştır.
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.crypto import get_random_string

from apps.katalog.models import (
    BasvuruKategorisi,
    Kampanya,
    MusteriTipi,
    Operator,
    Tarife,
    ZamanDamgali,
)

SIFIR = Decimal("0.00")


class KimlikTipi(models.TextChoices):
    TC = "tc", "T.C. Kimlik"
    PASAPORT = "pasaport", "Pasaport"


class BasvuruDurumu(ZamanDamgali):
    """Başvuru durumları da veridir; yeni durum eklemek admin işidir.

    `hakedis_tetikler` işaretli bir duruma geçildiğinde ücret kuralları
    çalışır ve cüzdan hareketleri oluşur.
    """

    ad = models.CharField("Durum Adı", max_length=100, unique=True)
    slug = models.SlugField("Kısa Ad", max_length=120, unique=True)
    renk = models.CharField(
        "Renk",
        max_length=7,
        default="#64748b",
        help_text="Panelde rozet rengi. Örn: #16a34a",
    )
    ikon = models.CharField("İkon", max_length=50, default="schedule")
    aciklama = models.CharField("Açıklama", max_length=255, blank=True)

    baslangic_durumu = models.BooleanField(
        "Başlangıç Durumu",
        default=False,
        help_text="Yeni başvurular bu durumla açılır. Yalnızca bir durum işaretlenmelidir.",
    )
    hakedis_tetikler = models.BooleanField(
        "Para Hareketini Tetikler",
        default=False,
        help_text="Bu duruma geçildiğinde ücret kuralları işler ve cüzdan güncellenir.",
    )
    olumsuz_sonuc = models.BooleanField(
        "Olumsuz Sonuç",
        default=False,
        help_text="İptal/hatalı gibi durumlar. Daha önce işlenmiş para hareketleri geri alınır.",
    )
    bayi_duzenleyebilir = models.BooleanField(
        "Bayi Düzenleyebilir",
        default=False,
        help_text="Eksik evrak gibi durumlarda bayinin başvuruyu güncellemesine izin verir.",
    )
    bildirim_gonder = models.BooleanField(
        "Telegram Bildirimi Gönder",
        default=False,
        help_text="Bu duruma geçildiğinde operasyon grubuna mesaj atılır.",
    )
    sinyal_seviyesi = models.PositiveSmallIntegerField(
        "Sinyal Seviyesi",
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="Bayi panelinde 5 çubuklu sinyal göstergesinde kaç çubuk dolu görünsün (1-5).",
    )
    sira = models.PositiveIntegerField("Sıra", default=0)
    aktif = models.BooleanField("Aktif", default=True)

    class Meta:
        verbose_name = "Başvuru Durumu"
        verbose_name_plural = "Başvuru Durumları"
        ordering = ["sira", "ad"]

    def __str__(self):
        return self.ad


def referans_no_uret():
    """İnsan okunabilir, tahmin edilemez başvuru referansı."""
    return get_random_string(10, allowed_chars="ABCDEFGHJKLMNPQRSTUVWXYZ23456789")


class Basvuru(ZamanDamgali):
    bayi = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Bayi",
        related_name="basvurular",
        on_delete=models.PROTECT,
    )
    referans_no = models.CharField(
        "Referans No",
        max_length=12,
        unique=True,
        default=referans_no_uret,
        editable=False,
    )

    kategori = models.ForeignKey(
        BasvuruKategorisi,
        verbose_name="Kategori",
        related_name="basvurular",
        on_delete=models.PROTECT,
    )
    operator = models.ForeignKey(
        Operator,
        verbose_name="Operatör",
        related_name="basvurular",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    tarife = models.ForeignKey(
        Tarife,
        verbose_name="Tarife",
        related_name="basvurular",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    kampanya = models.ForeignKey(
        Kampanya,
        verbose_name="Kampanya",
        related_name="basvurular",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )

    # --- Her başvuruda ortak olan çekirdek alanlar (indexlenebilir) ---
    musteri_tipi = models.CharField(
        "Müşteri Tipi", max_length=10, choices=MusteriTipi.choices, default=MusteriTipi.TURK
    )
    kimlik_tipi = models.CharField(
        "Kimlik Tipi",
        max_length=10,
        choices=KimlikTipi.choices,
        default=KimlikTipi.TC,
        blank=True,
    )
    # Bu alanlar aranabilir olsun diye gerçek kolon; hangisinin sorulacağına
    # kategori karar verdiği için hepsi boş bırakılabilir.
    kimlik_no = models.CharField("Kimlik / Pasaport No", max_length=50, blank=True)
    isim = models.CharField("İsim", max_length=100, blank=True)
    soyisim = models.CharField("Soyisim", max_length=100, blank=True)
    irtibat = models.CharField("İrtibat Numarası", max_length=20, blank=True)
    numara = models.CharField(
        "İşlem Yapılacak Numara",
        max_length=20,
        blank=True,
        help_text="Taşıma ve şebeke içi işlemlerde doldurulur.",
    )
    adres = models.TextField("Adres", blank=True)

    # --- Kategoriye özel alanlar (KategoriAlani tanımlarına göre) ---
    ek_bilgiler = models.JSONField("Ek Bilgiler", default=dict, blank=True)

    # --- Durum ve operasyon ---
    durum = models.ForeignKey(
        BasvuruDurumu,
        verbose_name="Durum",
        related_name="basvurular",
        on_delete=models.PROTECT,
    )
    bayi_aciklamasi = models.TextField("Bayi Açıklaması", blank=True)
    operasyon_notu = models.TextField(
        "Operasyon Notu", blank=True, help_text="Bayiye gösterilmez."
    )

    # --- Tedarikçi (işlemi satın alan taraf; operasyon elle atar) ---
    tedarikci = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Tedarikçi",
        related_name="ustlendigi_basvurular",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        help_text="İşlemi satın alan taraf. Boşsa işlem henüz satılmamıştır.",
    )

    # --- Para (durum tetiklendiğinde doldurulan anlık değerler) ---
    tahsil_edilen = models.DecimalField(
        "Bayiden Tahsilat", max_digits=12, decimal_places=2, default=SIFIR
    )
    hakedis = models.DecimalField(
        "Bayiye Hakediş", max_digits=12, decimal_places=2, default=SIFIR
    )
    tedarikci_geliri = models.DecimalField(
        "Tedarikçi Geliri", max_digits=12, decimal_places=2, default=SIFIR
    )
    para_islendi = models.BooleanField("Para İşlendi", default=False, editable=False)
    tedarikci_islendi = models.BooleanField(
        "Tedarikçi Bedeli İşlendi", default=False, editable=False
    )
    sonuclanma_tarihi = models.DateTimeField("Sonuçlanma Tarihi", null=True, blank=True)

    class Meta:
        verbose_name = "Başvuru"
        verbose_name_plural = "Başvurular"
        ordering = ["-olusturma_tarihi"]
        indexes = [
            models.Index(fields=["bayi", "-olusturma_tarihi"]),
            models.Index(fields=["tedarikci", "-olusturma_tarihi"]),
            models.Index(fields=["durum", "-olusturma_tarihi"]),
            models.Index(fields=["kategori", "-olusturma_tarihi"]),
            models.Index(fields=["kimlik_no"]),
            models.Index(fields=["numara"]),
        ]

    def __str__(self):
        return f"{self.referans_no} · {self.isim} {self.soyisim}"

    @property
    def ad_soyad(self):
        return f"{self.isim} {self.soyisim}".strip() or self.referans_no

    @property
    def net_tutar(self):
        """Bayi açısından net etki: hakediş eksi tahsilat."""
        return self.hakedis - self.tahsil_edilen

    @property
    def kar(self):
        """Firmanın bu işlemden kazancı.

        Tedarikçiden aldığımız bedel ve bayiden kestiğimiz ücret gelirdir;
        bayiye ödediğimiz hakediş giderdir.
        """
        return self.tedarikci_geliri + self.tahsil_edilen - self.hakedis

    def clean(self):
        if self.kategori_id and self.tarife_id:
            if self.tarife.kategori_id != self.kategori_id:
                raise ValidationError({"tarife": "Seçilen tarife bu kategoriye ait değil."})
        if self.tarife_id and self.kampanya_id:
            if self.kampanya.tarife_id != self.tarife_id:
                raise ValidationError({"kampanya": "Seçilen kampanya bu tarifeye ait değil."})
        if self.kategori_id and self.kategori.tarife_zorunlu and not self.tarife_id:
            raise ValidationError({"tarife": "Bu kategoride tarife seçimi zorunludur."})


class BasvuruBelgesi(models.Model):
    """Başvuruya yüklenen dosyalar. Hangi form alanına ait olduğu `alan_kodu` ile bağlanır."""

    basvuru = models.ForeignKey(
        Basvuru,
        verbose_name="Başvuru",
        related_name="belgeler",
        on_delete=models.CASCADE,
    )
    alan_kodu = models.SlugField("Alan Kodu", max_length=60)
    etiket = models.CharField("Etiket", max_length=150, blank=True)
    dosya = models.FileField("Dosya", upload_to="basvuru/%Y/%m/")
    yuklenme_tarihi = models.DateTimeField("Yüklenme Tarihi", auto_now_add=True)

    class Meta:
        verbose_name = "Başvuru Belgesi"
        verbose_name_plural = "Başvuru Belgeleri"
        ordering = ["basvuru", "alan_kodu"]
        constraints = [
            models.UniqueConstraint(
                fields=["basvuru", "alan_kodu"], name="basvuru_belge_alani_benzersiz"
            )
        ]

    def __str__(self):
        return f"{self.basvuru.referans_no} · {self.etiket or self.alan_kodu}"

    def get_absolute_url(self):
        """Belgeye erişim her zaman izin kontrolünden geçer.

        Kimlik ve pasaport görüntüleri doğrudan MEDIA_URL üzerinden
        sunulmaz; yalnızca başvurunun sahibi bayi ve yetkili personel
        görebilir.
        """
        from django.urls import reverse

        return reverse(
            "basvurular:belge", args=[self.basvuru.referans_no, self.alan_kodu]
        )

    @property
    def resim_mi(self):
        return self.dosya.name.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif"))


class DurumGecmisi(models.Model):
    """Başvurunun durum değişim kaydı. Kim, ne zaman, neyi değiştirdi."""

    basvuru = models.ForeignKey(
        Basvuru,
        verbose_name="Başvuru",
        related_name="durum_gecmisi",
        on_delete=models.CASCADE,
    )
    onceki_durum = models.ForeignKey(
        BasvuruDurumu,
        verbose_name="Önceki Durum",
        related_name="+",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    yeni_durum = models.ForeignKey(
        BasvuruDurumu,
        verbose_name="Yeni Durum",
        related_name="+",
        on_delete=models.PROTECT,
    )
    aciklama = models.CharField("Açıklama", max_length=255, blank=True)
    degistiren = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Değiştiren",
        related_name="durum_degisiklikleri",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    tarih = models.DateTimeField("Tarih", auto_now_add=True)

    class Meta:
        verbose_name = "Durum Geçmişi"
        verbose_name_plural = "Durum Geçmişi"
        ordering = ["-tarih", "-id"]

    def __str__(self):
        return f"{self.basvuru.referans_no}: {self.yeni_durum.ad}"
