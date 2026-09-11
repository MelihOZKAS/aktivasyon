"""Bayinin hakedişiyle ürün alabildiği mağaza.

Bayi kazandığı parayı cüzdanında görüyor ama harcayabileceği tek yer
başvuru bedeliydi. Mağaza o parayı ürüne çevirir: bayi ürünü görür,
fiyatını bilir, siparişi verir ve tutar o anda bakiyesinden düşer.

**Stok tutulmaz.** Ürünler bayiye elden teslim ediliyor; kaç adet kaldığını
sistemin bilmesi gerekmiyor ve tutulmayan bir sayı yanlış olurdu. Satılmasını
istemediğin ürünü "Aktif"ten çıkarırsın.
"""

from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils.crypto import get_random_string

from apps.katalog.models import ZamanDamgali
from apps.katalog.utils import kucult, turkce_slug

SIFIR = Decimal("0.00")


def referans_no_uret():
    """İnsan okunabilir, tahmin edilemez sipariş referansı.

    Başvuru ve destek talebindeki kuralın aynısı: adres sayaçla değil
    referansla kurulur, kimse komşusunun siparişini id artırarak bulmasın.
    """
    return get_random_string(8, allowed_chars="ABCDEFGHJKLMNPQRSTUVWXYZ23456789")


class Urun(ZamanDamgali):
    """Mağazada satılan ürün.

    Fiyat tektir: bayi grubuna göre kademe yok. Tarifelerdeki kural motoru
    burada gereksiz — satılan şey bir hizmet değil, rafta duran bir ürün.
    """

    ad = models.CharField("Ürün Adı", max_length=200, unique=True)
    slug = models.SlugField("Kısa Ad", max_length=220, unique=True, blank=True)
    aciklama = models.TextField(
        "Açıklama",
        blank=True,
        help_text="Bayi ürün sayfasında görür. Kutu içeriği, model, renk…",
    )
    gorsel = models.ImageField(
        "Görsel",
        upload_to="urun/%Y/%m/",
        blank=True,
        null=True,
        help_text="Mağaza listesinde ve ürün sayfasında gösterilir.",
    )
    fiyat = models.DecimalField(
        "Satış Fiyatı",
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text="Bayinin bakiyesinden düşülecek tutar.",
    )
    sira = models.PositiveIntegerField(
        "Sıra", default=0, help_text="Mağazadaki yeri. Küçük sayı önce gelir."
    )
    aktif = models.BooleanField(
        "Aktif",
        default=True,
        help_text=(
            "Kapatılırsa ürün mağazada hiç görünmez ve sipariş edilemez. "
            "Verilmiş siparişler yerinde kalır."
        ),
    )

    class Meta:
        verbose_name = "Ürün"
        verbose_name_plural = "Ürünler"
        ordering = ["sira", "ad"]

    def __str__(self):
        return self.ad

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = turkce_slug(self.ad)
        # Diğer görseller gibi küçültülüp WebP'ye çevrilir.
        self.gorsel = kucult(self.gorsel)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("magaza:urun", args=[self.slug])


class SiparisDurumu(models.TextChoices):
    """Sipariş üç durumludur.

    Kargo yok — ürünler bayiye uğrandığında elden veriliyor — bu yüzden
    "Hazırlanıyor / Kargoda / Dağıtımda" gibi ara durumlar takip edilecek
    bir şey anlatmıyor. Ödeme bildirimindeki gibi küçük ve sabit bir küme.
    """

    VERILDI = "verildi", "Sipariş verildi"
    TESLIM = "teslim", "Teslim edildi"
    IPTAL = "iptal", "İptal edildi"


class Siparis(ZamanDamgali):
    """Bayinin bakiyesiyle verdiği ürün siparişi.

    **Para siparişin iptal edilmemiş olmasına bağlıdır.** Sipariş verilir
    verilmez tutar bakiyeden düşer; İptal'e çekilince ters kayıtla geri
    döner, İptal'den çıkarılırsa yeniden kesilir. Başvurudaki kuralın
    aynısı: yanlış işlemin düzeltmesi de sadece durumu değiştirmektir.

    Ürün adı ve birim fiyat sipariş anında kopyalanır: ürünün fiyatı sonra
    değişse de bayinin ödediği tutar kayıtta doğru kalır.
    """

    referans_no = models.CharField(
        "Referans No", max_length=12, unique=True, default=referans_no_uret, editable=False
    )
    bayi = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Bayi",
        related_name="siparisler",
        on_delete=models.PROTECT,
    )
    urun = models.ForeignKey(
        Urun,
        verbose_name="Ürün",
        related_name="siparisler",
        null=True,
        blank=True,
        # Ürün kataloğdan kaldırılsa da sipariş geçmişi durur; ne alındığı
        # `urun_adi` alanında yazılı.
        on_delete=models.SET_NULL,
    )
    urun_adi = models.CharField("Ürün Adı", max_length=200)
    adet = models.PositiveIntegerField("Adet", default=1, validators=[MinValueValidator(1)])
    birim_fiyat = models.DecimalField("Birim Fiyat", max_digits=12, decimal_places=2)
    tutar = models.DecimalField("Toplam Tutar", max_digits=12, decimal_places=2)
    durum = models.CharField(
        "Durum", max_length=20, choices=SiparisDurumu.choices, default=SiparisDurumu.VERILDI
    )
    bayi_notu = models.CharField(
        "Bayi Notu",
        max_length=255,
        blank=True,
        help_text="Bayinin sipariş verirken yazdığı not.",
    )
    yonetim_notu = models.CharField(
        "Yönetim Notu",
        max_length=255,
        blank=True,
        help_text="Bayi sipariş listesinde görür. İptal sebebi buraya yazılır.",
    )
    para_islendi = models.BooleanField("Para İşlendi", default=False, editable=False)
    para_surumu = models.PositiveIntegerField(
        "Para İşlem Sürümü",
        default=0,
        editable=False,
        help_text=(
            "Sipariş her iptal edildiğinde artar. Defterdeki tekillik anahtarı "
            "bu sayıyı içerir; iptal edilip yeniden açılan siparişin ikinci "
            "hareketi aynı anahtara çarpıp sessizce yutulmasın."
        ),
    )
    islem_anahtari = models.CharField(
        "İşlem Anahtarı",
        max_length=64,
        unique=True,
        null=True,
        blank=True,
        editable=False,
        help_text=(
            "Sipariş formunda gizli alanda taşınır: sayfa yenilenince aynı "
            "sipariş ikinci kez açılmaz."
        ),
    )

    class Meta:
        verbose_name = "Sipariş"
        verbose_name_plural = "Siparişler"
        ordering = ["-olusturma_tarihi"]
        indexes = [
            models.Index(fields=["durum", "-olusturma_tarihi"]),
            models.Index(fields=["bayi", "-olusturma_tarihi"]),
        ]

    def __str__(self):
        return f"{self.referans_no} · {self.urun_adi} ×{self.adet}"

    @property
    def iptal_mi(self):
        return self.durum == SiparisDurumu.IPTAL

    @property
    def bekliyor(self):
        """Henüz teslim edilmemiş, iptal de edilmemiş sipariş."""
        return self.durum == SiparisDurumu.VERILDI

    @property
    def esim_mi(self):
        """eSIM siparişinin sağlayıcı tarafı `esim.Teslimat` kaydındadır."""
        return hasattr(self, "esim")

    @property
    def esim_yukleme_mi(self):
        """Satılmış eSIM'e yükleme; sağlayıcıda geri alınamaz, iptal yönetim kararıdır."""
        return hasattr(self, "esim_yukleme")
