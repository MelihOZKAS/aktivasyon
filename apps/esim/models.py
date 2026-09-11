"""eSIM satışı: sağlayıcı, ülke, paket ve teslimat.

Bayi mağazadan yurt dışı internet paketi (eSIM) satar. Paketler sağlayıcının
API'sinden çekilir, alış fiyatı USD olarak durur; satış fiyatı **kur × alış
× (1 + kâr oranı)** ile o anda hesaplanır — kur değişince bütün fiyatlar
kendiliğinden değişir, tek tek güncellenmez.

**Birden çok sağlayıcı olabilir** (`Saglayici`). Aynı ülke, aynı hacim ve
aynı süredeki paketlerden yalnızca **alışı en ucuz olan** bayiye gösterilir;
sipariş de o sağlayıcıya gider. Sağlayıcı seçimi böylece elle değil
fiyatla yapılır.

Sipariş ve para `magaza.Siparis` üzerinden yürür — eSIM de mağazadan alınan
bir üründür, cüzdan kuralları (bakiyeden düşer, borca yazılmaz, iptalde ters
kayıt) aynen geçerlidir. `Teslimat` o siparişin sağlayıcı tarafını tutar:
sipariş numarası, ICCID, aktivasyon kodu, durum.
"""

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from django.core.validators import MinValueValidator
from django.db import models

from apps.esim.saglayicilar import saglayici_secenekleri, saglayici_sinifi
from apps.esim.ulkeler import bayrak
from apps.katalog.models import ZamanDamgali

SIFIR = Decimal("0.00")
YUZ = Decimal(100)
GB = 1024**3
MB = 1024**2


def tam_lira(tutar):
    """Küsurat atılır: 41,53 → 41. eSIM'de her fiyat bu kuraldan geçer.

    Yarım yukarı değil, aşağı: bayi 41,53'ü 42 değil 41 görsün istendi;
    tavsiye fiyatı da aynı kuralla kesilir, iki rakam birbirini tutar.
    """
    return Decimal(tutar).quantize(Decimal("1"), rounding=ROUND_DOWN)


def satis_fiyati_hesapla(alis_usd, kar_orani, kur, grup_orani=None):
    """Alış (USD) → bayiye satış (₺), tam lira.

    Önce bizim fiyat: alış × kur × (1 + kâr%), küsurat atılır. Bayi
    grubunun farkı varsa **o fiyatın üzerine** eklenir ve yine küsurat
    atılır (34 ₺, +%10 → 37 ₺). Kur sıfırsa fiyat da sıfırdır — satış
    kapalı demektir, servis bunu ayrıca denetler.
    """
    fiyat = tam_lira(Decimal(alis_usd) * Decimal(kur) * (Decimal(1) + Decimal(kar_orani) / YUZ))
    if grup_orani:
        fiyat = tam_lira(fiyat * (Decimal(1) + Decimal(grup_orani) / YUZ))
    return fiyat


def tavsiye_fiyati_hesapla(satis, tavsiye_orani):
    """Bayinin müşteriye satacağı tavsiye fiyat: bizden aldığı × (1 + oran), tam lira."""
    return tam_lira(Decimal(satis) * (Decimal(1) + Decimal(tavsiye_orani) / YUZ))


def hacim_metni(bayt):
    """1073741824 → "1 GB", 524288000 → "500 MB", 1610612736 → "1,5 GB"."""
    if not bayt:
        return "—"
    if bayt >= GB:
        gb = Decimal(bayt) / GB
        if gb == gb.to_integral_value():
            return f"{int(gb)} GB"
        return f"{gb.quantize(Decimal('0.1'))}".replace(".", ",") + " GB"
    return f"{int(round(bayt / MB))} MB"


class Saglayici(ZamanDamgali):
    """Paketleri aldığımız API. Anahtarlar burada durur, kodda değil."""

    ad = models.CharField("Ad", max_length=100, unique=True)
    tur = models.CharField(
        "Sağlayıcı",
        max_length=30,
        choices=saglayici_secenekleri,
        help_text="Hangi API ile konuşulacağı. Yeni bir sağlayıcı türü yazılımla eklenir.",
    )
    erisim_kodu = models.CharField(
        "Erişim Kodu",
        max_length=200,
        help_text="Sağlayıcının panelinden alınan API anahtarı (AccessCode).",
    )
    gizli_anahtar = models.CharField(
        "Gizli Anahtar",
        max_length=200,
        blank=True,
        help_text="Varsa istekler bununla imzalanır (SecretKey). Boş bırakılabilir.",
    )
    varsayilan_kar_orani = models.DecimalField(
        "Varsayılan Kâr Oranı (%)",
        max_digits=6,
        decimal_places=2,
        default=Decimal("50.00"),
        validators=[MinValueValidator(SIFIR)],
        help_text=(
            "Bu sağlayıcının paketlerine uygulanan kâr oranı. Eşitlemede yeni gelen "
            "paketlere yazılır; sonradan değiştirince listedeki “Fiyatları güncelle” "
            "düğmesi bütün paketleri bu orana çeker."
        ),
    )
    aktif = models.BooleanField(
        "Aktif",
        default=True,
        help_text="Kapatılırsa bu sağlayıcının hiçbir paketi satılmaz, kayıtlar durur.",
    )
    son_esitleme = models.DateTimeField("Son Eşitleme", null=True, blank=True, editable=False)
    son_bakiye_usd = models.DecimalField(
        "Sağlayıcıdaki Bakiye ($)",
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        editable=False,
    )
    son_bakiye_tarihi = models.DateTimeField(null=True, blank=True, editable=False)
    # OAuth ile çalışan sağlayıcı (Airalo) her istekte yeni jeton almaz;
    # jeton burada durur, süresi dolunca adaptör yeniler.
    oturum_anahtari = models.TextField("Oturum Jetonu", blank=True, editable=False)
    oturum_bitis = models.DateTimeField("Jeton Bitişi", null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "eSIM Sağlayıcısı"
        verbose_name_plural = "eSIM Sağlayıcıları"
        ordering = ["ad"]

    def __str__(self):
        return self.ad

    def adaptor(self):
        return saglayici_sinifi(self.tur)(self)

    @property
    def denenmedi(self):
        """Adaptör belgeden yazıldı, canlı anahtarla doğrulanmadı."""
        try:
            return saglayici_sinifi(self.tur).denenmedi
        except Exception:
            return False


class Ulke(models.Model):
    """Paketin geçerli olduğu ülke. Sağlayıcı ISO koduyla gönderir, ad Türkçe."""

    kod = models.CharField("ISO Kodu", max_length=2, primary_key=True)
    ad = models.CharField("Ad", max_length=100)
    aktif = models.BooleanField(
        "Aktif",
        default=True,
        help_text="Kapatılırsa bu ülkenin paketleri bayiye gösterilmez.",
    )

    class Meta:
        verbose_name = "Ülke"
        verbose_name_plural = "Ülkeler"
        ordering = ["ad"]

    def __str__(self):
        return self.ad

    @property
    def bayrak(self):
        return bayrak(self.kod)

    @property
    def slug(self):
        return self.kod.lower()


class PaketSorgusu(models.QuerySet):
    def satilabilir(self):
        return self.filter(aktif=True, saglayicida_var=True, saglayici__aktif=True)


class Paket(ZamanDamgali):
    """Sağlayıcının kataloğundaki bir paket.

    Sağlayıcıdan gelen alanlar (ad, hacim, süre, alış) eşitlemede yazılır,
    elle değiştirilmez. Yönetimin kararı iki alandır: **kâr oranı** ve
    **aktif**. Sağlayıcının listesinden düşen paket silinmez,
    `saglayicida_var` kapanır — verilmiş siparişler ona bağlı.
    """

    saglayici = models.ForeignKey(
        Saglayici, verbose_name="Sağlayıcı", related_name="paketler", on_delete=models.CASCADE
    )
    kod = models.CharField("Paket Kodu", max_length=50)
    slug = models.CharField("Sağlayıcı Kısa Adı", max_length=80, blank=True)
    ad = models.CharField("Ad", max_length=200)
    aciklama = models.TextField("Açıklama", blank=True)
    ulkeler = models.ManyToManyField(Ulke, verbose_name="Ülkeler", related_name="paketler")
    kapsam = models.CharField(
        "Kapsam",
        max_length=800,
        help_text="Ülke kodları, sıralı ve virgüllü. Aynı kapsamdaki paketler karşılaştırılır.",
    )
    ulke_sayisi = models.PositiveIntegerField("Ülke Sayısı", default=1)
    hacim_bayt = models.BigIntegerField("Hacim (bayt)")
    sure_gun = models.PositiveIntegerField("Süre (gün)")
    hiz = models.CharField("Hız", max_length=30, blank=True)
    operatorler = models.CharField("Operatörler", max_length=255, blank=True)
    alis_usd = models.DecimalField("Alış ($)", max_digits=10, decimal_places=4)
    kar_orani = models.DecimalField(
        "Kâr Oranı (%)",
        max_digits=6,
        decimal_places=2,
        default=SIFIR,
        validators=[MinValueValidator(SIFIR)],
        help_text="Alışın üzerine eklenecek yüzde. 88 → alış × 1,88.",
    )
    aktif = models.BooleanField("Aktif", default=True)
    saglayicida_var = models.BooleanField(
        "Sağlayıcıda Var",
        default=True,
        editable=False,
        help_text="Son eşitlemede sağlayıcının listesinde bulunmayan paket satılmaz.",
    )
    son_gorulme = models.DateTimeField("Son Görülme", null=True, blank=True, editable=False)

    objects = PaketSorgusu.as_manager()

    class Meta:
        verbose_name = "eSIM Paketi"
        verbose_name_plural = "eSIM Paketleri"
        # Tek ülkeli paketler önce: yönetici listeyi ülke ülke okur, bölgeseller sonda.
        ordering = ["ulke_sayisi", "kapsam", "hacim_bayt", "sure_gun", "alis_usd"]
        constraints = [
            models.UniqueConstraint(fields=["saglayici", "kod"], name="esim_paket_saglayici_kod"),
        ]
        indexes = [models.Index(fields=["aktif", "saglayicida_var"])]

    def __str__(self):
        return self.ad

    @property
    def hacim(self):
        return hacim_metni(self.hacim_bayt)

    @property
    def bolgesel(self):
        return self.ulke_sayisi > 1

    @property
    def satilabilir(self):
        return self.aktif and self.saglayicida_var and self.saglayici.aktif

    def alis_tl(self, kur):
        return (self.alis_usd * Decimal(kur)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def satis_fiyati(self, kur, grup_orani=None):
        """Paketin oranıyla bizim fiyat; grup farkı varsa üzerine."""
        return satis_fiyati_hesapla(self.alis_usd, self.kar_orani, kur, grup_orani)


class TeslimatDurumu(models.TextChoices):
    BEKLIYOR = "bekliyor", "Sağlayıcıya iletiliyor"
    HAZIRLANIYOR = "hazirlaniyor", "Profil hazırlanıyor"
    HAZIR = "hazir", "Hazır"
    IPTAL = "iptal", "İptal edildi"
    HATA = "hata", "Hata"


class Teslimat(ZamanDamgali):
    """Bir eSIM siparişinin sağlayıcı tarafı.

    Para `siparis` üzerinde; burada sağlayıcıyla yazışmanın izi durur.
    Sipariş verildiğinde `bekliyor`, sağlayıcı kabul edince `hazirlaniyor`,
    profil gelince `hazir` — o anda sipariş de "teslim edildi" olur. Sağlayıcı
    reddederse `hata`: para bayiye kendiliğinden iade edilir, sebep burada.
    """

    siparis = models.OneToOneField(
        "magaza.Siparis", verbose_name="Sipariş", related_name="esim", on_delete=models.CASCADE
    )
    saglayici = models.ForeignKey(
        Saglayici, verbose_name="Sağlayıcı", related_name="teslimatlar", on_delete=models.PROTECT
    )
    paket = models.ForeignKey(
        Paket,
        verbose_name="Paket",
        related_name="teslimatlar",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    paket_kodu = models.CharField("Paket Kodu", max_length=50)
    islem_no = models.CharField(
        "İşlem No",
        max_length=50,
        unique=True,
        help_text="Sağlayıcıya gönderilen tekil anahtar; aynı anahtar ikinci sipariş açmaz.",
    )
    saglayici_siparis_no = models.CharField("Sağlayıcı Sipariş No", max_length=50, blank=True)
    esim_no = models.CharField("Sağlayıcı eSIM No", max_length=50, blank=True)
    iccid = models.CharField("ICCID", max_length=30, blank=True)
    ac = models.CharField("Aktivasyon Kodu (LPA)", max_length=255, blank=True)
    qr_url = models.URLField("QR Görseli", blank=True)
    kisa_url = models.URLField("Kısa Bağlantı", blank=True)
    apn = models.CharField("APN", max_length=60, blank=True)
    durum = models.CharField(
        "Durum", max_length=20, choices=TeslimatDurumu.choices, default=TeslimatDurumu.BEKLIYOR
    )
    hata = models.TextField("Hata", blank=True)
    alis_usd = models.DecimalField("Alış ($)", max_digits=10, decimal_places=4)
    kur = models.DecimalField("Kur", max_digits=10, decimal_places=4)
    alis_tl = models.DecimalField("Alış (₺)", max_digits=12, decimal_places=2)
    kar_orani = models.DecimalField(
        "Uygulanan Kâr Oranı (%)",
        max_digits=6,
        decimal_places=2,
        default=SIFIR,
        help_text="Sipariş anında bayinin grubundan ya da paketten alınan oran.",
    )
    grup_orani = models.IntegerField(
        "Uygulanan Grup Farkı (%)",
        null=True,
        blank=True,
        help_text="Sipariş anında bayi grubundan gelen fark; boşsa fark yoktu.",
    )
    tavsiye_fiyati = models.DecimalField(
        "Tavsiye Edilen Satış (₺)",
        max_digits=12,
        decimal_places=2,
        default=SIFIR,
        help_text="Sipariş anında bayiye gösterilen “müşteriye şu fiyata sat” rakamı; 0 ise gösterilmedi.",
    )
    # Bayi eSIM'i müşterisine satar, müşteri aylar sonra "paketim bitti" diye
    # arar; bayi hangi eSIM olduğunu adla ya da telefonla bulur. İkisi de
    # bayinin kendi notu, sağlayıcıya gitmez.
    musteri_adi = models.CharField("Müşteri Adı", max_length=120, blank=True)
    musteri_telefonu = models.CharField("Müşteri Telefonu", max_length=30, blank=True)
    son_sorgu = models.DateTimeField("Son Sorgu", null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "eSIM Teslimatı"
        verbose_name_plural = "eSIM Teslimatları"
        ordering = ["-olusturma_tarihi"]

    def __str__(self):
        return f"{self.siparis.referans_no} · {self.paket_kodu}"

    @property
    def hazir(self):
        return self.durum == TeslimatDurumu.HAZIR

    @property
    def bekliyor(self):
        return self.durum in (TeslimatDurumu.BEKLIYOR, TeslimatDurumu.HAZIRLANIYOR)

    @property
    def iptal_edilebilir(self):
        """Kullanılmamış profil sağlayıcıda iptal edilip iade alınabilir."""
        return self.hazir and bool(self.esim_no or self.iccid)

    @property
    def kar(self):
        """İade edilmiş (hata/iptal) teslimatta ne satış ne alış kaldı: kâr sıfır."""
        if self.durum in (TeslimatDurumu.HATA, TeslimatDurumu.IPTAL):
            return SIFIR
        return self.siparis.tutar - self.alis_tl

    # LPA dizgisi "LPA:1$smdp.adres$KOD" biçimindedir; iPhone'da elle kurulum
    # iki parçayı ayrı ister.
    @property
    def smdp_adresi(self):
        parcalar = self.ac.split("$")
        return parcalar[1] if len(parcalar) >= 2 else ""

    @property
    def aktivasyon_kodu(self):
        parcalar = self.ac.split("$")
        return parcalar[2] if len(parcalar) >= 3 else ""


class YuklemeDurumu(models.TextChoices):
    BEKLIYOR = "bekliyor", "Sağlayıcıya iletiliyor"
    TAMAM = "tamam", "Yüklendi"
    HATA = "hata", "Hata"
    IPTAL = "iptal", "İptal edildi"


class Yukleme(ZamanDamgali):
    """Satılmış bir eSIM'e sonradan yüklenen paket (top-up).

    Para yine `magaza.Siparis` üzerinden: bakiyeden anında düşer, sağlayıcı
    reddederse iade edilir. Sağlayıcıda yükleme geri alınamaz; iptal yalnızca
    yönetimin bilinçli kararıyla (mağaza siparişi gibi) yapılır.
    """

    teslimat = models.ForeignKey(
        Teslimat, verbose_name="eSIM", related_name="yuklemeler", on_delete=models.CASCADE
    )
    siparis = models.OneToOneField(
        "magaza.Siparis", verbose_name="Sipariş", related_name="esim_yukleme", on_delete=models.CASCADE
    )
    paket_kodu = models.CharField("Yükleme Paketi Kodu", max_length=50)
    paket_adi = models.CharField("Paket", max_length=200)
    hacim_bayt = models.BigIntegerField("Hacim (bayt)", default=0)
    sure_gun = models.PositiveIntegerField("Süre (gün)", default=0)
    islem_no = models.CharField("İşlem No", max_length=50, unique=True)
    saglayici_yukleme_no = models.CharField("Sağlayıcı Yükleme No", max_length=50, blank=True)
    durum = models.CharField(
        "Durum", max_length=20, choices=YuklemeDurumu.choices, default=YuklemeDurumu.BEKLIYOR
    )
    hata = models.TextField("Hata", blank=True)
    alis_usd = models.DecimalField("Alış ($)", max_digits=10, decimal_places=4)
    kur = models.DecimalField("Kur", max_digits=10, decimal_places=4)
    alis_tl = models.DecimalField("Alış (₺)", max_digits=12, decimal_places=2)
    kar_orani = models.DecimalField("Uygulanan Kâr Oranı (%)", max_digits=6, decimal_places=2, default=SIFIR)
    grup_orani = models.IntegerField("Uygulanan Grup Farkı (%)", null=True, blank=True)
    toplam_hacim_bayt = models.BigIntegerField("Yükleme Sonrası Toplam Hacim", default=0)
    son_kullanma = models.CharField("Yeni Son Kullanma", max_length=40, blank=True)

    class Meta:
        verbose_name = "eSIM Yüklemesi"
        verbose_name_plural = "eSIM Yüklemeleri"
        ordering = ["-olusturma_tarihi"]

    def __str__(self):
        return f"{self.siparis.referans_no} · {self.paket_adi}"

    @property
    def hacim(self):
        return hacim_metni(self.hacim_bayt)

    @property
    def kar(self):
        if self.durum in (YuklemeDurumu.HATA, YuklemeDurumu.IPTAL):
            return SIFIR
        return self.siparis.tutar - self.alis_tl
