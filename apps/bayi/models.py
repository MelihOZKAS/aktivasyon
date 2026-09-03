"""Bayi tarafı: profil bilgileri, SIM kart stoğu ve duyurular."""

from django.conf import settings
from django.db import models

from apps.katalog.models import Operator, ZamanDamgali


class BayiProfili(ZamanDamgali):
    """Kullanıcıya bağlı bayi bilgileri. Cüzdan ayrı modelde tutulur."""

    kullanici = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name="Kullanıcı",
        related_name="bayi_profili",
        on_delete=models.CASCADE,
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


class SimKartDurumu(models.TextChoices):
    STOKTA = "stokta", "Stokta"
    KULLANILDI = "kullanildi", "Kullanıldı"
    ARIZALI = "arizali", "Arızalı"
    IADE = "iade", "İade"


class SimKart(ZamanDamgali):
    """Bayilere zimmetlenen SIM kart / IMEI stoğu."""

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
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    imei = models.CharField("SIM / IMEI", max_length=40, unique=True)
    durum = models.CharField(
        "Durum", max_length=20, choices=SimKartDurumu.choices, default=SimKartDurumu.STOKTA
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
