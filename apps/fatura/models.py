"""Fatura tahsilatı: kurumlar, sorgular, ödemeler ve sorgu robotları.

Sorgu bizde yapılmaz. Sağlayıcının (Kontorbizde) API'si yok; sorguyu
laptopta çalışan robot yapar (`znetfaturasorgu/`), gerçek tarayıcıda
gerçek sayfayı sürerek. Django bekleyen sorguyu kuyruğa koyar, robot
"bana iş ver" der, sonucu geri yazar. Sözleşme: znetfaturasorgu/DJANGO_API.md.

Para kontördeki gibi `magaza.Siparis` üzerinden yürür: ödeme açılınca tutar
bakiyeden düşer, borca yazılmaz, iptalde ters kayıtla döner. Ödemeyi
sağlayıcıda **yönetim elle yapar** ve "Ödendi" der; robot ödeme yapmaz.
"""

import hashlib
import hmac
import secrets
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone

from apps.katalog.models import ZamanDamgali
from apps.kontor.models import FiyatGrubu
from apps.katalog.utils import turkce_slug
from apps.magaza.models import referans_no_uret

SIFIR = Decimal("0.00")

# Robot bu süre içinde nabız atmadıysa çevrimdışı sayılır; bayi sorgu
# açamaz, kuyruğa iş yığılıp kimse bakmadan beklemesin. Robot boşken 5 sn'de
# bir sorar ama bir sorguyu işlerken (en çok ~35 sn) susar; sınır bundan
# geniş olmalı, yoksa uzun bir sorgu sırasında başka bayi "kapalı" görürdü.
CEVRIMICI_SURESI = timedelta(seconds=60)


class Kategori(ZamanDamgali):
    """Bayinin fatura ekranındaki bölüm: GSM, İnternet, Elektrik, HGS…

    Sağlayıcının kendi kategori kodları karışık (Vodafone "Hatay
    Faturaları" sekmesinde duruyor); bayiye gösterilen gruplama bizimdir,
    veridir. Kurum hangi bölümde duracağını buradan alır.
    """

    ad = models.CharField("Ad", max_length=80, unique=True)
    slug = models.SlugField("Kısa Ad", max_length=90, unique=True, blank=True)
    sira = models.PositiveIntegerField("Sıra", default=0)
    aktif = models.BooleanField("Aktif", default=True)

    class Meta:
        verbose_name = "Fatura Kategorisi"
        verbose_name_plural = "Fatura Kategorileri"
        ordering = ["sira", "ad"]

    def __str__(self):
        return self.ad

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = turkce_slug(self.ad)
        super().save(*args, **kwargs)


class KurumSorgusu(models.QuerySet):
    def bayiye_acik(self, grup):
        """Bu fiyat grubundaki bayiye satılan kurumlar — kontördeki kuralın aynısı.

        Grup varsa yalnızca o grupta rakamı yazılı kurum satılır (sorgulu
        kurumda 0 da geçerli rakamdır: fatura tutarı aynen; sorgusuz kalemde
        net fiyat 0'dan büyük olmalı). Grup yoksa (varsayılan grup da yoksa)
        kurumun kendi rakamı geçerlidir, paketin `satis_fiyati` gibi.
        """
        if grup is None:
            fiyatli = models.Q(sorgulu=True) | models.Q(sorgulu=False, bayi_fiyati__gt=0)
        else:
            fiyatli = models.Q(grup_fiyatlari__grup=grup) & (
                models.Q(sorgulu=True) | models.Q(grup_fiyatlari__tutar__gt=0)
            )
        return (
            self.filter(aktif=True)
            .filter(fiyatli)
            # Kapatılan kategori bölümüyle birlikte gizlenir; kategorisizler "Diğer".
            .filter(models.Q(kategori__isnull=True) | models.Q(kategori__aktif=True))
            .distinct()
        )


class Kurum(ZamanDamgali):
    """Faturası ödenen kurum: Turkcell, Vodafone, TOROSLAR ELEKTRİK, HGS…

    `kod` robotun tekil kimliğidir (`vodafone`, `100-tl-yukle-plaka`).
    Sağlayıcının `api_adi`'si tekil değil — 171 dört "TL Yükle"de tekrar
    ediyor — o yüzden kurum adından türetilen kod kullanılır; robot sorgu
    anında bu kodu sağlayıcıdaki güncel token'a kendisi çevirir. Django
    token tutmaz.

    Numara kuralı (hane sayısı, yalnızca rakam) sağlayıcının kendi alan
    tanımından gelir, robot katalogla yollar; yönetim değiştirebilir.
    """

    kod = models.CharField(
        "Robot Kodu",
        max_length=80,
        unique=True,
        help_text="Robotun bu kurumu tanıdığı tekil kod (vodafone, turkcell…). Değiştirme.",
    )
    ad = models.CharField("Kurum Adı", max_length=120)
    kategori = models.ForeignKey(
        Kategori,
        verbose_name="Kategori",
        related_name="kurumlar",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="Boşsa bayi ekranında “Diğer” altında durur.",
    )
    operator = models.ForeignKey(
        "katalog.Operator",
        verbose_name="Operatör",
        related_name="fatura_kurumlari",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="Seçilirse kartta operatörün marka rengi görünür.",
    )
    sorgulu = models.BooleanField(
        "Sorgulu",
        default=True,
        help_text=(
            "Açıksa bayi numarayı yazınca fatura sorgulanır, çıkan faturalardan "
            "seçip öder. Kapalıysa (HGS 100 TL gibi) sorgu yoktur; bayi aşağıdaki "
            "sabit fiyatı öder."
        ),
    )
    alan_etiketi = models.CharField(
        "Numara Alanının Adı", max_length=60, default="Abone No",
        help_text="Bayinin formunda kutunun üstünde yazar: Telefon Numarası, Abone No, Plaka…",
    )
    min_hane = models.PositiveSmallIntegerField("En Az Hane", default=1)
    max_hane = models.PositiveSmallIntegerField("En Çok Hane", default=20)
    sadece_rakam = models.BooleanField(
        "Yalnızca Rakam", default=True,
        help_text="Açıksa numaraya harf yazılamaz (telefon, abone no). Plakada kapalı.",
    )
    aciklama = models.CharField(
        "Bayiye Açıklama", max_length=255, blank=True,
        help_text="Formun altında yazar: “Başında 0 olmadan yazın” gibi.",
    )
    # Bayinin ödeyeceği kontördeki gibi **fiyat grubunun sayfasından** girilir
    # (Kontör → Fiyat Grupları → grup → Fatura tablosu, `GrupFiyati`).
    # Aşağıdaki iki alan yalnızca hiç varsayılan fiyat grubu yokken geçerlidir
    # (paketin `satis_fiyati` gibi); o zaman formda görünürler.
    hizmet_bedeli = models.DecimalField(
        "Hizmet Bedeli (fatura başına)",
        max_digits=10, decimal_places=2, default=SIFIR,
        help_text=(
            "Yalnızca fiyat grubu yokken: sorgulu kurumda bayi sağlayıcının toplamı + "
            "bunu öder. Gruplar varsa grubun sayfasından girilir."
        ),
    )
    bayi_fiyati = models.DecimalField(
        "Bayi Fiyatı", max_digits=10, decimal_places=2, null=True, blank=True,
        help_text=(
            "Yalnızca fiyat grubu yokken: sorgusuz kalemde bayinin ödeyeceği. "
            "Gruplar varsa grubun sayfasından girilir."
        ),
    )
    tavsiye = models.DecimalField(
        "Müşteriye", max_digits=10, decimal_places=2, null=True, blank=True,
        help_text=(
            "Bayinin müşteriye söyleyeceği (kontördeki tavsiye satış gibi; gruba göre "
            "değişmez). Sorgulu kurumda fatura tutarının üstüne eklenen tutar, "
            "sorgusuz kalemde müşteri fiyatı."
        ),
    )
    alis_fiyati = models.DecimalField(
        "Alışımız", max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Sorgusuz kurumda sağlayıcıya ödediğimiz; yalnızca kâr hesabı için.",
    )
    sira = models.PositiveIntegerField("Sıra", default=0)
    aktif = models.BooleanField("Aktif", default=True)

    objects = KurumSorgusu.as_manager()

    class Meta:
        verbose_name = "Fatura Kurumu"
        verbose_name_plural = "Fatura Kurumları"
        ordering = ["sira", "ad"]

    def __str__(self):
        return self.ad

    def clean(self):
        super().clean()
        if self.min_hane and self.max_hane and self.min_hane > self.max_hane:
            raise ValidationError({"max_hane": "En çok hane, en az haneden küçük olamaz."})

    def get_absolute_url(self):
        return reverse("fatura:kurum", args=[self.kod])

    def numarayi_dogrula(self, numara):
        """Bayinin yazdığı numarayı temizler ve kurala uyduğunu denetler.

        Boşluk ve ayraçlar atılır; telefon alanında baştaki 0 da (bayi
        "0532…" yazabilir, sağlayıcı 10 hane istiyor). Kurala uymayan numara
        sorguya hiç gitmez: robotu boşuna meşgul etmesin.
        """
        temiz = "".join((numara or "").split()).replace("-", "").replace("(", "").replace(")", "")
        if self.sadece_rakam:
            if temiz.startswith("+90"):
                temiz = temiz[3:]
            if not temiz.isdigit():
                raise ValidationError(f"{self.alan_etiketi} yalnızca rakam olmalı.")
            if len(temiz) == self.max_hane + 1 and temiz.startswith("0"):
                temiz = temiz[1:]
        else:
            temiz = temiz.upper()
        if not temiz:
            raise ValidationError(f"{self.alan_etiketi} boş olamaz.")
        if not (self.min_hane <= len(temiz) <= self.max_hane):
            if self.min_hane == self.max_hane:
                kural = f"{self.max_hane} hane"
            else:
                kural = f"{self.min_hane}–{self.max_hane} hane"
            raise ValidationError(f"{self.alan_etiketi} {kural} olmalı; {len(temiz)} hane yazıldı.")
        return temiz

    # -- Sorgulu kurumda fatura başına tutarlar -----------------------------
    # Taban faturanın kendi bedelidir (`services.fatura_tutari`), sağlayıcının
    # işlem bedeli katılmış "Toplam Tutar" değil.
    def bayi_tutari(self, fatura_tutari, hizmet=None):
        """Bayinin bir fatura için ödeyeceği: fatura bedeli + grubun hizmet bedeli.

        `hizmet` bayinin grubundaki rakamdır (`services.hizmet_bedeli`);
        verilmezse kurumun kendi hizmet bedeli (fiyat grubu yokken).
        """
        hizmet = self.hizmet_bedeli if hizmet is None else hizmet
        return (Decimal(str(fatura_tutari)) + hizmet).quantize(Decimal("0.01"))

    def musteri_tutari(self, fatura_tutari):
        """Müşteriye söylenecek: fatura bedeli + müşteriye ek. Gruba göre değişmez."""
        return (Decimal(str(fatura_tutari)) + (self.tavsiye or SIFIR)).quantize(Decimal("0.01"))


class FaturaFiyatGrubu(FiyatGrubu):
    """Kontörün fiyat grupları, faturanın menüsünde (Fatura → Fiyat Grupları).

    Yeni tablo değil, aynı gruplar (vekil model): Perakende, Toptan… hem
    kontörde hem faturada aynıdır, bayi ikisinde de cüzdanındaki grubu öder.
    Ayrı giriş yeri, çünkü "Fatura'ya bastım kontör fiyatları geliyor":
    grubun sayfası burada yalnızca fatura kurumlarını gösterir, kontörde
    yalnızca paketleri. Düzen ikisinde aynıdır.
    """

    class Meta:
        proxy = True
        verbose_name = "Fiyat Grubu"
        verbose_name_plural = "Fiyat Grupları"


class GrupFiyati(models.Model):
    """Kurumun bir kontör fiyat grubundaki rakamı (Perakende, Toptan…).

    Kontördeki `PaketFiyati`nin aynısı, aynı düzende girilir (Fatura → Fiyat
    Grupları → grup). Bayi kontörde hangi gruptaysa faturada da o grubun rakamını
    öder (`Cuzdan.kontor_grubu`, boşsa varsayılan grup). Tek rakam, anlamı
    kurumun türüne göre: sorgulu kurumda fatura başına hizmet bedeli,
    sorgusuz kalemde net bayi fiyatı. **Satır yoksa kurum o gruba satılmaz.**
    """

    kurum = models.ForeignKey(Kurum, verbose_name="Kurum", related_name="grup_fiyatlari", on_delete=models.CASCADE)
    grup = models.ForeignKey(
        "kontor.FiyatGrubu", verbose_name="Fiyat Grubu", related_name="fatura_fiyatlari", on_delete=models.CASCADE
    )
    tutar = models.DecimalField("Tutar", max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = "Fatura Grup Fiyatı"
        verbose_name_plural = "Fatura Grup Fiyatları"
        constraints = [models.UniqueConstraint(fields=["kurum", "grup"], name="fatura_grup_fiyati_tekil")]

    def __str__(self):
        return f"{self.kurum} · {self.grup}: {self.tutar}"


# -- Robot ----------------------------------------------------------------


def anahtar_ozeti(anahtar):
    return hashlib.sha256((anahtar or "").encode()).hexdigest()


class Robot(ZamanDamgali):
    """Sorguyu yapan bilgisayar (laptop ya da Windows sunucu). Her robotun kendi anahtarı vardır.

    Tek robot iki işi birden yapar: fatura sorgusu ve kontörün aboneye özel
    paket sorgusu (`kontor.RobotSorgusu`). İkisi aynı kapıdan verilir.

    Anahtar bir kez gösterilir, yalnızca SHA-256 özeti saklanır (kontördeki
    bayi API şifresinin aynısı). Robot birkaç saniyede bir nabız atar;
    yönetim hangisinin açık olduğunu, oturumunun düşüp düşmediğini görür.
    """

    ad = models.CharField("Ad", max_length=60, unique=True, help_text="ev-laptop, server-1…")
    anahtar_ozeti = models.CharField(max_length=64, blank=True, editable=False)
    aktif = models.BooleanField("Aktif", default=True)
    son_nabiz = models.DateTimeField("Son Nabız", null=True, blank=True, editable=False)
    mesgul = models.BooleanField("Meşgul", default=False, editable=False)
    oturum_canli = models.BooleanField("Oturum Canlı", default=True, editable=False)
    # Robot kontörün paket sorgusunu da yapıyor mu? Robot iş isterken
    # söyler (`isler=fatura,paket`); eski sürüm söylemez, ona paket işi
    # verilmez ve paket sorgusu için çevrimiçi sayılmaz.
    paket_sorgusu = models.BooleanField("Paket Sorgusu", default=False, editable=False)
    # Robotun çalışma saatleri (makinesindeki ayar.json'dan, nabızla gelir).
    # Robot bu saatlerin dışında hiç istek atmaz; bayiye "sistem bağlı değil"
    # yerine "08:00–23:00 arasında" denebilsin diye burada tutulur.
    mesai_baslangic = models.TimeField("Mesai Başlangıcı", null=True, blank=True, editable=False)
    mesai_bitis = models.TimeField("Mesai Bitişi", null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "Sorgu Robotu"
        verbose_name_plural = "Sorgu Robotları"
        ordering = ["ad"]

    def __str__(self):
        return self.ad

    def yeni_anahtar(self):
        """Yeni anahtar üretir, özetini yazar ve düz hâlini **bir kez** döndürür."""
        anahtar = secrets.token_urlsafe(24)
        self.anahtar_ozeti = anahtar_ozeti(anahtar)
        self.save(update_fields=["anahtar_ozeti", "guncelleme_tarihi"])
        return anahtar

    def anahtar_dogru_mu(self, anahtar):
        if not self.anahtar_ozeti or not anahtar:
            return False
        return hmac.compare_digest(self.anahtar_ozeti, anahtar_ozeti(anahtar))

    def mesai_icinde(self, saat):
        """Gece yarısını aşan aralık da olur. Saat bilinmiyorsa her zaman içinde."""
        bas, bit = self.mesai_baslangic, self.mesai_bitis
        if bas is None or bit is None:
            return True
        return bas <= saat < bit if bas <= bit else (saat >= bas or saat < bit)

    @property
    def mesai_metni(self):
        if self.mesai_baslangic is None or self.mesai_bitis is None:
            return ""
        return f"{self.mesai_baslangic:%H:%M}–{self.mesai_bitis:%H:%M}"

    @property
    def cevrimici(self):
        return bool(
            self.aktif
            and self.son_nabiz
            and timezone.now() - self.son_nabiz < CEVRIMICI_SURESI
        )


# -- Sorgu ----------------------------------------------------------------


class SorguDurumu(models.TextChoices):
    BEKLIYOR = "bekliyor", "Sırada"
    SORGULANIYOR = "sorgulaniyor", "Sorgulanıyor"
    TAMAM = "tamam", "Tamamlandı"
    HATA = "hata", "Sorgulanamadı"


ACIK_SORGU = (SorguDurumu.BEKLIYOR, SorguDurumu.SORGULANIYOR)


class Sorgu(ZamanDamgali):
    """Bayinin bir numara için açtığı fatura sorgusu; robotun kuyruğu.

    Sonuç (`sonuc`) robotun ayrıştırdığı veridir: abone adı ve faturalar.
    Ödeme bu kayıttan yapılır ve tutarlar **buradan** okunur — bayinin
    gönderdiği formdaki rakam değil. Böylece kimse tutarı elle değiştirip
    eksik ödeyemez.
    """

    referans_no = models.CharField(
        "Referans No", max_length=12, unique=True, default=referans_no_uret, editable=False
    )
    bayi = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Bayi", related_name="fatura_sorgulari", on_delete=models.PROTECT
    )
    kurum = models.ForeignKey(Kurum, verbose_name="Kurum", related_name="sorgular", on_delete=models.PROTECT)
    numara = models.CharField("Numara", max_length=40)
    durum = models.CharField("Durum", max_length=20, choices=SorguDurumu.choices, default=SorguDurumu.BEKLIYOR)
    robot = models.ForeignKey(
        Robot, verbose_name="Robot", related_name="sorgular", null=True, blank=True, on_delete=models.SET_NULL
    )
    alinma_tarihi = models.DateTimeField("Robot Aldı", null=True, blank=True)
    sonuc_tarihi = models.DateTimeField("Sonuç", null=True, blank=True)
    sonuc = models.JSONField("Sonuç", default=dict, blank=True)
    mesaj = models.CharField("Mesaj", max_length=255, blank=True)

    class Meta:
        verbose_name = "Fatura Sorgusu"
        verbose_name_plural = "Fatura Sorguları"
        ordering = ["-olusturma_tarihi"]
        indexes = [
            models.Index(fields=["durum", "olusturma_tarihi"]),
            models.Index(fields=["bayi", "-olusturma_tarihi"]),
        ]

    def __str__(self):
        return f"{self.referans_no} · {self.kurum} · {self.numara}"

    def get_absolute_url(self):
        return reverse("fatura:sorgu", args=[self.referans_no])

    @property
    def acik(self):
        return self.durum in ACIK_SORGU

    @property
    def faturalar(self):
        return list((self.sonuc or {}).get("faturalar") or [])

    @property
    def abone_adi(self):
        return (self.sonuc or {}).get("abone_adi") or ""

    @property
    def borc_yok(self):
        return self.durum == SorguDurumu.TAMAM and not self.faturalar


# -- Ödeme ----------------------------------------------------------------


class OdemeDurumu(models.TextChoices):
    BEKLIYOR = "bekliyor", "Ödeniyor"
    ODENDI = "odendi", "Ödendi"
    IPTAL = "iptal", "İptal edildi"


class Odeme(ZamanDamgali):
    """Bayinin ödediği fatura(lar). Tutar bakiyeden düşmüştür.

    Ödemeyi sağlayıcıda yönetim elle yapar ve "Ödendi" der; yapamazsa
    "İptal" ve tutar ters kayıtla döner (`services.iptal_et`). Faturalar
    ödeme anında kopyalanır: sorgu silinse ya da sağlayıcı tutarı değiştirse
    de bayinin neyi ödediği kayıtta kalır.
    """

    siparis = models.OneToOneField(
        "magaza.Siparis", verbose_name="Sipariş", related_name="fatura", on_delete=models.PROTECT
    )
    bayi = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Bayi", related_name="fatura_odemeleri", on_delete=models.PROTECT
    )
    kurum = models.ForeignKey(
        Kurum, verbose_name="Kurum", related_name="odemeler", null=True, blank=True, on_delete=models.SET_NULL
    )
    kurum_adi = models.CharField("Kurum", max_length=120)
    sorgu = models.ForeignKey(
        Sorgu, verbose_name="Sorgu", related_name="odemeler", null=True, blank=True, on_delete=models.SET_NULL
    )
    numara = models.CharField("Numara", max_length=40)
    abone_adi = models.CharField("Abone Adı", max_length=120, blank=True)
    faturalar = models.JSONField(
        "Faturalar", default=list, blank=True,
        help_text="Ödenen faturalar: fatura no, son ödeme, sağlayıcı tutarı, bayinin ödediği.",
    )
    saglayici_tutari = models.DecimalField(
        "Sağlayıcıya Ödenecek", max_digits=12, decimal_places=2, null=True, blank=True,
        help_text=(
            "Sorgulu kurumda faturaların bedeli (sağlayıcının kendi işlem bedeli hariç); "
            "sorgusuz kalemde alışımız."
        ),
    )
    hizmet_bedeli = models.DecimalField("Hizmet Bedeli", max_digits=12, decimal_places=2, default=SIFIR)
    tavsiye_fiyati = models.DecimalField(
        "Müşteri Fiyatı", max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Bayinin o gün gördüğü tavsiye; oran sonra değişse de kayıtta kalır.",
    )
    durum = models.CharField("Durum", max_length=20, choices=OdemeDurumu.choices, default=OdemeDurumu.BEKLIYOR)
    sonuc_notu = models.CharField(
        "Yönetim Notu", max_length=255, blank=True,
        help_text="Bayi görür: iptal sebebi, dekont no…",
    )
    karar_veren = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Karar Veren", related_name="+",
        null=True, blank=True, on_delete=models.SET_NULL,
    )
    karar_tarihi = models.DateTimeField("Karar", null=True, blank=True)

    class Meta:
        verbose_name = "Fatura Ödemesi"
        verbose_name_plural = "Fatura Ödemeleri"
        ordering = ["-olusturma_tarihi"]
        indexes = [
            models.Index(fields=["durum", "-olusturma_tarihi"]),
            models.Index(fields=["bayi", "-olusturma_tarihi"]),
        ]

    def __str__(self):
        return f"{self.siparis.referans_no} · {self.kurum_adi} · {self.numara}"

    def get_absolute_url(self):
        return reverse("fatura:odeme", args=[self.siparis.referans_no])

    @property
    def referans_no(self):
        return self.siparis.referans_no

    @property
    def tutar(self):
        return self.siparis.tutar

    @property
    def bekliyor(self):
        return self.durum == OdemeDurumu.BEKLIYOR

    @property
    def fatura_nolari(self):
        return [f.get("fatura_no") for f in self.faturalar if f.get("fatura_no")]
