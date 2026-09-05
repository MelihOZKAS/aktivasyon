"""Finans: bayi grupları, cüzdan, değişmez defter kayıtları ve ücret kuralları.

Para mantığının tamamı `UcretKurali` tablosunda veri olarak durur. Yeni bir
ücret ya da hakediş tanımlamak için kod değiştirmek gerekmez.
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from apps.katalog.models import (
    BasvuruKategorisi,
    Kampanya,
    Operator,
    Tarife,
    ZamanDamgali,
)

SIFIR = Decimal("0.00")


class BayiGrubu(ZamanDamgali):
    """Fiyat kademesi. Ücret kuralları grup bazında tanımlanabilir."""

    ad = models.CharField("Grup Adı", max_length=100, unique=True)
    aciklama = models.TextField("Açıklama", blank=True)
    aktif = models.BooleanField("Aktif", default=True)

    class Meta:
        verbose_name = "Bayi Grubu"
        verbose_name_plural = "Bayi Grupları"
        ordering = ["ad"]

    def __str__(self):
        return self.ad


class Banka(ZamanDamgali):
    """Bayilerin bakiye yüklemesi için kullanılan banka hesapları."""

    banka_adi = models.CharField("Banka Adı", max_length=100)
    hesap_sahibi = models.CharField("Hesap Sahibi", max_length=150)
    iban = models.CharField("IBAN", max_length=34, unique=True)
    sube_kodu = models.CharField("Şube Kodu", max_length=20, blank=True)
    hesap_numarasi = models.CharField("Hesap Numarası", max_length=50, blank=True)
    aciklama = models.TextField("Açıklama", blank=True)
    bakiye = models.DecimalField("Banka Bakiyesi", max_digits=14, decimal_places=2, default=SIFIR)
    bayiye_gorunur = models.BooleanField(
        "Bayiye Görünür",
        default=True,
        help_text="Kapalıysa bu hesap bayi panelinde listelenmez.",
    )
    aktif = models.BooleanField("Aktif", default=True)

    class Meta:
        verbose_name = "Banka Hesabı"
        verbose_name_plural = "Banka Hesapları"
        ordering = ["banka_adi"]

    def __str__(self):
        return f"{self.banka_adi} · {self.hesap_sahibi}"


class Cuzdan(ZamanDamgali):
    """Bayinin bakiye ve borç durumu.

    Borç için üst sınır yoktur: bakiye yetmediğinde kalan tutar borca yazılır.
    Kimin ne kadar borçlanacağı yönetim tarafında izlenir; işlem girişini
    tamamen durdurmak gerekirse `islem_yapabilir` kapatılır.

    Bu modelin kendi `save()` metodu para hareketi yapmaz. Bakiye yalnızca
    `apps.finans.services` içindeki atomik fonksiyonlar üzerinden değişir.
    """

    bayi = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name="Bayi",
        related_name="cuzdan",
        on_delete=models.CASCADE,
    )
    grup = models.ForeignKey(
        BayiGrubu,
        verbose_name="Bayi Grubu",
        related_name="cuzdanlar",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    bakiye = models.DecimalField("Bakiye", max_digits=12, decimal_places=2, default=SIFIR)
    borc = models.DecimalField("Borç", max_digits=12, decimal_places=2, default=SIFIR)
    islem_yapabilir = models.BooleanField(
        "İşlem Yapabilir",
        default=True,
        help_text="Kapatılırsa bayi yeni başvuru gönderemez.",
    )

    class Meta:
        verbose_name = "Cüzdan"
        verbose_name_plural = "Cüzdanlar"
        ordering = ["bayi__username"]

    def __str__(self):
        return f"{self.bayi.get_username()} · {self.bakiye} ₺"



class CuzdanIslemi(models.TextChoices):
    """Yöneticinin cüzdana elle yapabileceği işlemler.

    İlk üçü para *ekler*; farkları paranın hangi haneye yazıldığı. Sonuncusu
    ters yöndedir: bayiyle çalışmaya son verilince bakiyesi ödenip düşülür.
    Defterde hepsinin ayrı hareket tipi ve yapan kullanıcısı durur.
    """

    KREDI = "kredi", "Hem borç hem bakiye ekle (açık hesap)"
    BORC = "borc", "Sadece borç arttır"
    TAHSILAT = "tahsilat", "Tahsilat — bakiyeyi arttırır, borç varsa önce onu kapatır"
    IADE = "iade", "Bakiye düşür — bayiye para öde"


class HareketTipi(models.TextChoices):
    YUKLEME = "yukleme", "Bakiye Yükleme"
    TAHSILAT = "tahsilat", "İşlem Ücreti Tahsilatı"
    HAKEDIS = "hakedis", "Hakediş"
    TEDARIKCI_BEDELI = "tedarikci_bedeli", "Tedarikçiden Tahsilat"
    BORC_EKLE = "borc_ekle", "Borç Ekleme"
    BORC_TAHSIL = "borc_tahsil", "Borç Tahsilatı"
    IADE = "iade", "Bayiye İade / Ödeme"
    DUZELTME = "duzeltme", "Manuel Düzeltme"
    IPTAL = "iptal", "İptal / Ters Kayıt"


class CuzdanHareketi(models.Model):
    """Değişmez defter kaydı. Oluşturulduktan sonra düzenlenmez.

    `idempotency_anahtari` sayesinde aynı olay iki kez işlenemez; eski
    sistemdeki "kaydet'e iki kere basınca para iki kere işliyor" hatası
    yapısal olarak imkânsızdır.
    """

    cuzdan = models.ForeignKey(
        Cuzdan,
        verbose_name="Cüzdan",
        related_name="hareketler",
        on_delete=models.CASCADE,
    )
    tip = models.CharField("Hareket Tipi", max_length=20, choices=HareketTipi.choices)
    tutar = models.DecimalField("İşlem Tutarı", max_digits=12, decimal_places=2)

    onceki_bakiye = models.DecimalField("Önceki Bakiye", max_digits=12, decimal_places=2)
    sonraki_bakiye = models.DecimalField("Sonraki Bakiye", max_digits=12, decimal_places=2)
    onceki_borc = models.DecimalField("Önceki Borç", max_digits=12, decimal_places=2)
    sonraki_borc = models.DecimalField("Sonraki Borç", max_digits=12, decimal_places=2)

    basvuru = models.ForeignKey(
        "basvurular.Basvuru",
        verbose_name="Kaynak Başvuru",
        related_name="cuzdan_hareketleri",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    kural = models.ForeignKey(
        "finans.UcretKurali",
        verbose_name="Uygulanan Kural",
        related_name="hareketler",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    banka = models.ForeignKey(
        Banka,
        verbose_name="Banka",
        related_name="hareketler",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    ters_kayit = models.OneToOneField(
        "self",
        verbose_name="Ters Kaydı",
        related_name="iptal_edilen",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="Bu hareket iptal edildiyse, iptal kaydını gösterir.",
    )

    giris_bedeli = models.BooleanField(
        "Giriş Bedeli Hareketi",
        default=False,
        help_text=(
            "Başvuru girilirken alınan bedel. Yalnızca başvuru olumsuz "
            "sonuçlanınca iade edilir; ara durumlarda geri alınmaz."
        ),
    )
    idempotency_anahtari = models.CharField(
        "Tekillik Anahtarı",
        max_length=255,
        unique=True,
        help_text="Aynı olayın iki kez işlenmesini engeller.",
    )
    aciklama = models.CharField("Açıklama", max_length=255, blank=True)
    olusturan = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="İşlemi Yapan",
        related_name="olusturdugu_hareketler",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    tarih = models.DateTimeField("Tarih", auto_now_add=True)

    class Meta:
        verbose_name = "Cüzdan Hareketi"
        verbose_name_plural = "Cüzdan Hareketleri"
        ordering = ["-tarih", "-id"]
        indexes = [
            models.Index(fields=["cuzdan", "-tarih"]),
            models.Index(fields=["tip", "-tarih"]),
        ]

    def __str__(self):
        return f"{self.get_tip_display()} · {self.tutar} ₺"


class KuralYonu(models.TextChoices):
    """Paranın üç yönü. Etiketler yöneticinin kendi diliyle yazılmıştır:
    "yön" ve "hakediş" soyut kalıyordu, alış/satış herkesin bildiği şey."""

    ANA_HAKEDIS = "tedarikci_geliri", "Alışım (operatörden ya da tedarikçiden)"
    HAKEDIS = "hakedis", "Bayiye ödenecek (bayi fiyat listesi)"
    TAHSILAT = "tahsilat", "Bayiden tahsil edilecek"


# Otomatik kural adında kullanılır; uzun etiketler ada sığmıyor.
KISA_YON = {
    KuralYonu.TAHSILAT: "bayiden tahsilat",
    KuralYonu.HAKEDIS: "bayiye ödenen",
    KuralYonu.ANA_HAKEDIS: "alışım",
}


class UcretKurali(ZamanDamgali):
    """Tüm para mantığının tek kaynağı.

    Kapsam alanları (kategori/operatör/tarife/kampanya/grup/bayi) boş
    bırakıldığında "hepsi" anlamına gelir. Bir başvuru için en spesifik
    eşleşen kural uygulanır; eşitlik durumunda `oncelik` belirler.
    """

    ad = models.CharField(
        "Kural Adı",
        max_length=200,
        blank=True,
        help_text="Boş bırakılırsa kapsamdan üretilir (ör. “Red 20 GB · bayiye hakediş”).",
    )
    yon = models.CharField("Yön", max_length=20, choices=KuralYonu.choices)
    tutar = models.DecimalField(
        "Tutar",
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(SIFIR)],
        help_text="Bayiden alınacak ya da bayiye verilecek sabit tutar (₺).",
    )

    kategori = models.ForeignKey(
        BasvuruKategorisi,
        verbose_name="Kategori",
        related_name="ucret_kurallari",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    operator = models.ForeignKey(
        Operator,
        verbose_name="Operatör",
        related_name="ucret_kurallari",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    tarife = models.ForeignKey(
        Tarife,
        verbose_name="Tarife",
        related_name="ucret_kurallari",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    kampanya = models.ForeignKey(
        Kampanya,
        verbose_name="Kampanya",
        related_name="ucret_kurallari",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    bayi_grubu = models.ForeignKey(
        BayiGrubu,
        verbose_name="Bayi Grubu",
        related_name="ucret_kurallari",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    bayi = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Tek Bayi",
        related_name="ozel_ucret_kurallari",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        help_text="Yalnızca bu bayiye özel bir istisna tanımlamak için kullanın.",
    )
    tedarikci = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Tek Tedarikçi",
        related_name="ozel_tedarikci_kurallari",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        help_text=(
            "Ana hakediş kuralları için: tutar tedarikçiden tedarikçiye "
            "değiştiğinde her biri için ayrı kural tanımlayın. Operatörden "
            "alınan tutar için bu alanı boş bırakıp Operatör alanını doldurun."
        ),
    )

    tetikleyici_durum = models.ForeignKey(
        "basvurular.BasvuruDurumu",
        verbose_name="Tetikleyici Durum",
        related_name="ucret_kurallari",
        on_delete=models.PROTECT,
        help_text="Başvuru bu duruma geçtiğinde kural işler. Genellikle 'Aktif'.",
    )

    baslangic_tarihi = models.DateField("Başlangıç Tarihi", null=True, blank=True)
    bitis_tarihi = models.DateField("Bitiş Tarihi", null=True, blank=True)
    oncelik = models.IntegerField(
        "Öncelik",
        default=0,
        help_text="Eşit özgüllükte birden fazla kural eşleşirse yüksek olan kazanır.",
    )
    aktif = models.BooleanField("Aktif", default=True)

    class Meta:
        verbose_name = "Ücret Kuralı"
        verbose_name_plural = "Ücret ve Hakediş Kuralları"
        ordering = ["-oncelik", "ad"]

    def __str__(self):
        return f"{self.ad} ({self.get_yon_display()} · {self.tutar} ₺)"

    def save(self, *args, **kwargs):
        # Ad yalnızca listede kuralı tanımak için var. Tarife sayfasından iki
        # rakam girmeye gelen yönetici bir de ad uydurmak zorunda kalmasın.
        if not self.ad:
            kapsam = (
                self.kampanya or self.tarife or self.bayi_grubu
                or self.operator or self.kategori
            )
            kisa = KISA_YON.get(self.yon, self.yon)
            self.ad = (f"{kapsam} · {kisa}" if kapsam else f"Tüm başvurular · {kisa}")[:200]
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
        if (
            self.tarife
            and self.kategori
            and not self.tarife.kategoriler.filter(pk=self.kategori_id).exists()
        ):
            raise ValidationError(
                {"tarife": "Seçilen tarife, seçilen kategoriye ait değil."}
            )
        if self.kampanya and self.tarife and self.kampanya.tarife_id != self.tarife_id:
            raise ValidationError(
                {"kampanya": "Seçilen kampanya, seçilen tarifeye ait değil."}
            )

    @property
    def ozgulluk(self):
        """Kural ne kadar dar kapsamlı? Yüksek olan daha spesifiktir."""
        return sum(
            agirlik
            for alan_id, agirlik in (
                (self.bayi_id, 32),
                (self.tedarikci_id, 32),
                (self.kampanya_id, 16),
                (self.tarife_id, 8),
                (self.bayi_grubu_id, 4),
                (self.operator_id, 2),
                (self.kategori_id, 1),
            )
            if alan_id is not None
        )
