"""Bayi tarafı: profil bilgileri, SIM kart stoğu ve duyurular."""

from django.conf import settings
from django.db import models
from django.utils import timezone

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
    kapali_kategoriler = models.ManyToManyField(
        "katalog.BasvuruKategorisi",
        verbose_name="Bu bayiye kapalı başvuru tipleri",
        related_name="kapali_bayiler",
        blank=True,
        help_text=(
            "İşaretlenen tip bu bayiye hiç gösterilmez: kategori ekranında, "
            "panelde, tarife kataloğunda ve hakediş sayfasında çıkmaz; "
            "adresini elle yazsa da form açılmaz. Boş bırakılırsa hepsi "
            "açıktır."
        ),
    )

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
    tekrar Beklemede'ye döner. Arızalı her aşamadan işaretlenebilir ve
    oradan geri dönüş yoktur: bozuk kart stoğa da bayiye de girmez, üç
    adımlık arıza takibiyle kapanır (`SimKart.acik_ariza_isleri`).
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

    # --- arıza takibi (yalnızca Arızalı kartta anlamlı) ---
    # Bozuk kart üç adımda kapanır: bayiden alınır, yerine bayiye stoktan
    # kart verilir, operatörden değişimi gelir. Para hiç oynamaz: bayi
    # kartın parasını zaten ödedi, ona para değil kart borçluyuz. Bayi
    # tarafı ile operatör tarafı birbirinden bağımsız iki iştir; ikisi de
    # tarihle kapanır.
    ariza_tarihi = models.DateTimeField(
        "Arızalı İşaretlendi", null=True, blank=True, editable=False
    )
    ariza_bildiren = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Arızayı Bildiren",
        related_name="+",
        null=True,
        blank=True,
        editable=False,
        on_delete=models.SET_NULL,
    )
    iade_alinma_tarihi = models.DateTimeField(
        "Bayiden Alındı",
        null=True,
        blank=True,
        help_text="Bozuk kartın elimize geçtiği gün. Boşsa kart hâlâ bayide.",
    )
    yerine_verilen = models.OneToOneField(
        "self",
        verbose_name="Yerine Verilen Kart",
        related_name="yerine_gectigi",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="Bayiye bu kartın yerine stoktan zimmetlenen kart.",
    )
    degisim_tarihi = models.DateTimeField(
        "Operatörden Değişimi Geldi",
        null=True,
        blank=True,
        help_text=(
            "Operatörün bozuk kartın yerine verdiği kartın geldiği gün. "
            "Yeni kart ayrıca kayıt açılmaz; “Toplu ekle” ile stoğa girer."
        ),
    )

    objects = SimKartYoneticisi()

    @property
    def arizali(self):
        return self.durum == SimKartDurumu.ARIZALI

    @property
    def acik_ariza_isleri(self):
        """Arızalı kartta henüz yapılmamış adımlar, ekran sırasıyla.

        Kart stoktayken bozulduysa (bayisi yok) yerine kart verilecek kimse
        yoktur; o adım hiç sayılmaz.
        """
        if not self.arizali:
            return []
        isler = []
        if self.bayi_id and self.iade_alinma_tarihi is None:
            isler.append("Bayiden alınmadı")
        if self.bayi_id and self.yerine_verilen_id is None:
            isler.append("Yerine kart verilmedi")
        if self.degisim_tarihi is None:
            isler.append("Operatörden değişimi bekleniyor")
        return isler

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
        # Arızalı işareti hangi yoldan konursa konsun (form, toplu işlem,
        # servis) tarihi damgalanır; takip listesi bu tarihe göre sıralanır.
        if self.arizali and self.ariza_tarihi is None:
            self.ariza_tarihi = timezone.now()
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


class GenelAyarlar(ZamanDamgali):
    """Sitenin kamuya açık iletişim bilgileri — tek kayıt.

    Telefon ve e-posta şablona gömülü olsaydı değiştirmek yazılım
    güncellemesi gerektirirdi; bayiye içerik gösteren her alan gibi bu da
    admin'den girilir.

    Tek satır tutulur: `pk` her kayıtta 1'e sabitlenir, ikinci bir ayar
    kaydı açılamaz. Boş bırakılan alan sitede hiç görünmez — yarım bir
    iletişim kutusu göstermektense hiç göstermemek yeğdir.
    """

    TEKIL_PK = 1

    telefon = models.CharField(
        "İletişim Telefonu",
        max_length=30,
        blank=True,
        help_text="Sitede tıklanabilir olarak görünür. Örn: 0850 123 45 67",
    )
    eposta = models.EmailField(
        "İletişim E-postası",
        blank=True,
        help_text="Sitede tıklanabilir olarak görünür.",
    )
    # eSIM alışları USD; satış fiyatı bu kurla hesaplanır. Sıfırsa eSIM
    # satışı kapalıdır. `manage.py kur_guncelle` TCMB'den çeker.
    usd_kuru = models.DecimalField(
        "USD Kuru (₺)",
        max_digits=10,
        decimal_places=4,
        default=0,
        help_text=(
            "1 dolar kaç lira. eSIM paketlerinin satış fiyatı bu kurla hesaplanır; "
            "sıfırsa eSIM satışı kapalıdır. eSIM paket listesindeki düğme TCMB'den çeker."
        ),
    )
    usd_kuru_tarihi = models.DateTimeField("Kur Güncelleme Tarihi", null=True, blank=True)
    # Bayinin müşteriye kârı burada DEĞİL, bayi grubundadır (`BayiGrubu.esim_kar_orani`):
    # bir süre burada ikinci bir oran vardı, yönetici "bayiye göre girmek daha mantıklı"
    # dedi ve iki yerde iki yüzde birbirine karıştı.

    class Meta:
        verbose_name = "Genel Ayar"
        verbose_name_plural = "Genel Ayarlar"

    def __str__(self):
        return "Genel Ayarlar"

    def save(self, *args, **kwargs):
        """Kayıt her zaman tek satırdır: `pk` 1'e sabitlenir.

        İkinci bir ayar kaydı açılamaz; hangisinin geçerli olduğu sorusu hiç
        doğmasın. Kayıt açmanın doğru yolu `getir()`; `objects.create()`
        ikinci kez çağrılırsa tekil anahtara çarpar ve bu sessiz kalmaktan
        iyidir.
        """
        self.pk = self.TEKIL_PK
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Ayar kaydı silinmez; alanları boşaltmak yeter."""
        return 0, {}

    @classmethod
    def getir(cls):
        """Var olan kaydı verir; yoksa boş bir tane açar."""
        kayit, _ = cls.objects.get_or_create(pk=cls.TEKIL_PK)
        return kayit

    @property
    def iletisim_var(self):
        return bool(self.telefon or self.eposta)

    @property
    def telefon_baglantisi(self):
        """`tel:` bağlantısı için sadeleştirilmiş numara."""
        return "".join(k for k in self.telefon if k.isdigit() or k == "+")


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
