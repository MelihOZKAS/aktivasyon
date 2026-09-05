"""Bayi tarafı: profil bilgileri, SIM kart stoğu ve duyurular."""

from django.conf import settings
from django.db import models

from apps.bayi.telefon import normalize
from apps.katalog.models import Operator, ZamanDamgali


class BayiProfili(ZamanDamgali):
    """Kullanıcıya bağlı firma bilgileri. Cüzdan ayrı modelde tutulur.

    Roller birbirini dışlamaz: bir firma hem bayi (başvuru getirir, hakediş
    alır) hem tedarikçi (işlemi satın alır, bize öder) olabilir.
    """

    kullanici = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name="Kullanıcı",
        related_name="bayi_profili",
        on_delete=models.CASCADE,
    )
    bayi_mi = models.BooleanField(
        "Bayi",
        default=True,
        help_text="Başvuru girebilir, tamamlanan işlemlerden hakediş alır.",
    )
    tedarikci_mi = models.BooleanField(
        "Tedarikçi",
        default=False,
        help_text="Kendisine atanan işlemleri satın alır; bedeli hesabından düşülür.",
    )
    unvan = models.CharField("Firma Ünvanı", max_length=200, blank=True)
    yetkili_adi = models.CharField("Yetkili Adı", max_length=150, blank=True)
    telefon = models.CharField("Telefon", max_length=20, blank=True)
    adres = models.TextField("Adres", blank=True)
    sehir = models.CharField("Şehir", max_length=80, blank=True)
    vergi_dairesi = models.CharField("Vergi Dairesi", max_length=120, blank=True)
    vergi_no = models.CharField("Vergi / TC No", max_length=20, blank=True)
    notlar = models.TextField("Notlar", blank=True, help_text="Bayiye gösterilmez.")

    class Meta:
        verbose_name = "Bayi Profili"
        verbose_name_plural = "Bayi Profilleri"
        ordering = ["kullanici__username"]

    def __str__(self):
        return self.unvan or self.kullanici.get_username()

    def save(self, *args, **kwargs):
        self.telefon = normalize(self.telefon)
        super().save(*args, **kwargs)

    @property
    def rol_adi(self):
        if self.bayi_mi and self.tedarikci_mi:
            return "Bayi ve Tedarikçi"
        if self.tedarikci_mi:
            return "Tedarikçi"
        return "Bayi"


class SimKartDurumu(models.TextChoices):
    """SIM kartın yaşam döngüsü.

    Beklemede → Bayiye Atandı → Kullanıldı. Bayiden geri alınan kart
    tekrar Beklemede'ye döner. Arızalı her aşamadan işaretlenebilir.
    """

    BEKLEMEDE = "beklemede", "Beklemede"
    ATANDI = "atandi", "Bayiye Atandı"
    KULLANILDI = "kullanildi", "Kullanıldı"
    ARIZALI = "arizali", "Arızalı"


class SimKartYoneticisi(models.Manager):
    def bayinin_stogu(self, bayi):
        """Bayinin şu an işlem yapabileceği SIM kartlar."""
        return self.filter(bayi=bayi, durum=SimKartDurumu.ATANDI)


class SimKart(ZamanDamgali):
    """Bayilere zimmetlenen SIM kart / IMEI stoğu.

    Bir bayi yalnızca kendisine atanmış ve stokta görünen SIM kartlarla
    başvuru girebilir. Atama ve geri alma yönetim panelinden yapılır.
    """

    bayi = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Bayi",
        related_name="sim_kartlar",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    operator = models.ForeignKey(
        Operator,
        verbose_name="Operatör",
        related_name="sim_kartlar",
        # Operatör kart eklenirken zorunludur: kartın hangi şebekeye ait
        # olduğu bilinmezse başvuru formundaki stok kutusu onu doğru
        # operatöre süzemez ve SIM alacağı kimden beklendiği de yazılamaz.
        # `null=True` yalnızca operatör kaydı silinirse kartlar da silinmesin
        # diye durur (SET_NULL); form boş bırakmaya izin vermez.
        null=True,
        blank=False,
        on_delete=models.SET_NULL,
    )
    imei = models.CharField("SIM / IMEI", max_length=40, unique=True)
    durum = models.CharField(
        "Durum",
        max_length=20,
        choices=SimKartDurumu.choices,
        default=SimKartDurumu.BEKLEMEDE,
    )
    basvuru = models.ForeignKey(
        "basvurular.Basvuru",
        verbose_name="Kullanıldığı Başvuru",
        related_name="sim_kartlar",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    aciklama = models.CharField("Açıklama", max_length=255, blank=True)

    objects = SimKartYoneticisi()

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.durum == SimKartDurumu.ATANDI and not self.bayi_id:
            raise ValidationError(
                {"bayi": "“Bayiye Atandı” durumu için bir bayi seçilmelidir."}
            )
        if self.durum == SimKartDurumu.BEKLEMEDE and self.bayi_id:
            raise ValidationError(
                {"durum": "Bayisi olan kart “Beklemede” olamaz; “Bayiye Atandı” seçin."}
            )

    def save(self, *args, **kwargs):
        # Zimmet ile durum her zaman tutarlı kalsın: elle düzenlemede de,
        # toplu işlemde de aynı kural geçerli.
        if self.durum in {SimKartDurumu.BEKLEMEDE, SimKartDurumu.ATANDI}:
            self.durum = SimKartDurumu.ATANDI if self.bayi_id else SimKartDurumu.BEKLEMEDE
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "SIM Kart"
        verbose_name_plural = "SIM Kart Stoğu"
        ordering = ["-olusturma_tarihi"]
        indexes = [
            models.Index(fields=["bayi", "durum"]),
            models.Index(fields=["imei"]),
        ]

    def __str__(self):
        return self.imei


class Duyuru(ZamanDamgali):
    """Bayi panelinde gösterilen duyurular."""

    baslik = models.CharField("Başlık", max_length=200)
    icerik = models.TextField("İçerik")
    onemli = models.BooleanField(
        "Önemli", default=False, help_text="Panelin en üstünde vurgulu gösterilir."
    )
    yayin_tarihi = models.DateTimeField("Yayın Tarihi", null=True, blank=True)
    aktif = models.BooleanField("Aktif", default=True)

    class Meta:
        verbose_name = "Duyuru"
        verbose_name_plural = "Duyurular"
        ordering = ["-onemli", "-olusturma_tarihi"]

    def __str__(self):
        return self.baslik


class BayiBasvuruDurumu(models.TextChoices):
    YENI = "yeni", "Yeni"
    GORUSULDU = "gorusuldu", "Görüşüldü"
    ONAYLANDI = "onaylandi", "Onaylandı"
    REDDEDILDI = "reddedildi", "Reddedildi"


class BayiBasvurusu(ZamanDamgali):
    """Bayi olmak isteyenlerin bıraktığı iletişim talebi.

    Kamuya açık sayfadan doldurulur; hesap açma işini yönetim yapar.
    """

    isim = models.CharField("İsim", max_length=100)
    soyisim = models.CharField("Soyisim", max_length=100)
    irtibat = models.CharField("İrtibat Numarası", max_length=20)
    durum = models.CharField(
        "Durum",
        max_length=20,
        choices=BayiBasvuruDurumu.choices,
        default=BayiBasvuruDurumu.YENI,
    )
    parola_ozeti = models.CharField(
        "Parola Özeti",
        max_length=128,
        blank=True,
        editable=False,
        help_text=(
            "Başvuran kendi parolasını seçer. Burada yalnızca özeti durur; "
            "düz metin hiçbir yerde saklanmaz ve kimse göremez."
        ),
    )
    notlar = models.TextField("Notlar", blank=True, help_text="Başvurana gösterilmez.")
    bayi_grubu = models.ForeignKey(
        "finans.BayiGrubu",
        verbose_name="Fiyat Kademesi",
        related_name="bayi_basvurulari",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text=(
            "Hesap açılırken cüzdana yazılır. Bayinin hangi fiyat listesinden "
            "hakediş alacağını bu belirler; başvurana sorulmaz, yönetim seçer."
        ),
    )
    olusturulan_kullanici = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Açılan Hesap",
        related_name="kaynak_basvurusu",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    class Meta:
        verbose_name = "Bayi Başvurusu"
        verbose_name_plural = "Bayi Başvuruları"
        ordering = ["-olusturma_tarihi"]
        indexes = [models.Index(fields=["durum", "-olusturma_tarihi"])]

    def __str__(self):
        return f"{self.isim} {self.soyisim}".strip()

    def save(self, *args, **kwargs):
        # Numara kullanıcı adı olacak; form dışından (admin, betik, içe
        # aktarma) gelse de tek biçimde saklanır.
        self.irtibat = normalize(self.irtibat)
        super().save(*args, **kwargs)

    @property
    def ad_soyad(self):
        return f"{self.isim} {self.soyisim}".strip()

    @property
    def kullanici_adi(self):
        """Hesap açılırsa kullanıcı adı telefon numarası olur.

        Bayi zaten numarasını biliyor; ayrıca bir kullanıcı adı uydurup
        telefonla bildirmek gerekmiyor.

        Numara burada bir kez daha tek biçime indirilir: normalleştirme
        gelmeden önce alınmış eski başvurularda `irtibat` "05435609672"
        olarak durabilir. O hâliyle hesap açılırsa bayi numarasını
        `5435609672` diye yazar ve giremez.
        """
        return normalize(self.irtibat)

    @property
    def parolasini_secti(self):
        """Başvuran kendi parolasını seçmiş mi?

        Seçmediyse hesap girişe kapalı açılır; yönetici bunu hesabı açmadan
        önce görmeli, bayi giriş ekranında öğrenmemeli.
        """
        return bool(self.parola_ozeti)


class DetayGorunumTercihi(ZamanDamgali):
    """Bayinin başvuru detayında hangi alanları görmek istediği.

    Kapatılan alanların anahtarı saklanır, açık olanlar değil: kategoriye
    sonradan eklenen bir alan kendiliğinden görünür olsun, bayi listeyi
    yeniden gözden geçirmek zorunda kalmasın.
    """

    kullanici = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name="Kullanıcı",
        related_name="detay_tercihi",
        on_delete=models.CASCADE,
    )
    gizli_alanlar = models.JSONField("Gizlenen Alanlar", default=list, blank=True)
    admin_gizli_alanlar = models.JSONField(
        "Yönetim Panelinde Gizlenen Alanlar",
        default=list,
        blank=True,
        help_text=(
            "Başvuru detayında bu kullanıcıya gösterilmeyecek alanlar. "
            "Yalnızca görünümü etkiler; gizlenen alanın değeri korunur."
        ),
    )

    class Meta:
        verbose_name = "Başvuru Detayı Görünümü"
        verbose_name_plural = "Başvuru Detayı Görünümleri"

    def __str__(self):
        return f"{self.kullanici.get_username()} · {len(self.gizli_alanlar)} alan gizli"
