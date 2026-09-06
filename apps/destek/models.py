"""Bayi ile yönetim arasındaki destek talepleri.

Bayi "şu başvuruda ne oldu", "bakiyem yüklenmedi" diye telefonla arıyordu;
konuşma hiçbir yerde kalmıyor, kimin ne dediği unutuluyordu. Talep bir
konu ve mesajlardan oluşur — yazışma kayda geçer, iki taraf da geçmişi
görür.

Durum bilinçli olarak **iki tanedir**: açık ve kapalı. "Kimin sırası"
sorusunun cevabı ayrı bir alanda tutulmaz, son mesajın kimden geldiğine
bakılarak okunur (`bekleyen_taraf`). Üçüncü bir durum eklemek iki kaydı
senkron tutmak demekti; senkron kalmayan gün de yanlış tarafı bekletirdi.
"""

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils.crypto import get_random_string

from apps.katalog.models import ZamanDamgali


class TalepDurumu(models.TextChoices):
    ACIK = "acik", "Açık"
    KAPALI = "kapali", "Kapalı"


def referans_no_uret():
    """İnsan okunabilir, tahmin edilemez talep numarası.

    Başvurudaki kuralın aynısı: adresler sayaçla değil referansla kurulur,
    kimse id artırarak başkasının talebini denemesin.
    """
    return get_random_string(8, allowed_chars="ABCDEFGHJKLMNPQRSTUVWXYZ23456789")


class DestekTalebi(ZamanDamgali):
    bayi = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Açan",
        related_name="destek_talepleri",
        on_delete=models.CASCADE,
    )
    referans_no = models.CharField(
        "Talep No",
        max_length=10,
        unique=True,
        default=referans_no_uret,
        editable=False,
    )
    konu = models.CharField("Konu", max_length=150)
    durum = models.CharField(
        "Durum", max_length=20, choices=TalepDurumu.choices, default=TalepDurumu.ACIK
    )
    basvuru = models.ForeignKey(
        "basvurular.Basvuru",
        verbose_name="İlgili Başvuru",
        related_name="destek_talepleri",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="Talep bir başvuruyla ilgiliyse bağlanır; zorunlu değildir.",
    )
    son_mesaj_tarihi = models.DateTimeField(
        "Son Mesaj", null=True, blank=True, editable=False
    )
    # Sıralama ve rozet bu alandan okunur: son mesajı bayi yazdıysa sıra
    # yönetimdedir. Her mesajda güncellenir; sorgu başına mesaj tablosuna
    # gitmemek için kayıtta durur.
    yanit_bekliyor = models.BooleanField(
        "Yanıt Bekliyor", default=True, editable=False
    )

    class Meta:
        verbose_name = "Destek Talebi"
        verbose_name_plural = "Destek Talepleri"
        ordering = ["-son_mesaj_tarihi", "-olusturma_tarihi"]
        indexes = [
            models.Index(fields=["bayi", "-son_mesaj_tarihi"]),
            models.Index(fields=["durum", "-son_mesaj_tarihi"]),
        ]

    def __str__(self):
        return f"{self.referans_no} · {self.konu}"

    def get_absolute_url(self):
        return reverse("destek:detay", args=[self.referans_no])

    @property
    def acik_mi(self):
        return self.durum == TalepDurumu.ACIK

    @property
    def bekleyen_taraf(self):
        """Sıra kimde? Kapalı talepte kimse beklemiyor."""
        if not self.acik_mi:
            return ""
        return "Yönetim" if self.yanit_bekliyor else "Bayi"


class DestekMesaji(models.Model):
    """Talebe yazılan tek bir mesaj. Yazışma silinmez, düzenlenmez."""

    talep = models.ForeignKey(
        DestekTalebi,
        verbose_name="Talep",
        related_name="mesajlar",
        on_delete=models.CASCADE,
    )
    gonderen = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Gönderen",
        related_name="destek_mesajlari",
        null=True,
        on_delete=models.SET_NULL,
    )
    # Gönderenin o anki rolü kayda geçer: kullanıcı sonradan personel olsa
    # da eski mesajı bayi mesajı olarak kalmalı.
    personelden = models.BooleanField("Yönetimden", default=False)
    icerik = models.TextField("Mesaj")
    tarih = models.DateTimeField("Tarih", auto_now_add=True)

    class Meta:
        verbose_name = "Destek Mesajı"
        verbose_name_plural = "Destek Mesajları"
        ordering = ["tarih"]

    def __str__(self):
        return f"{self.talep.referans_no} · {self.icerik[:40]}"
