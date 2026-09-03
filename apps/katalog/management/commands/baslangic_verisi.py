"""Sistemi kullanılabilir hale getiren başlangıç verisini yükler.

Eski sistemdeki 7 ayrı başvuru modeli burada 7 satır veriye dönüşür.
Komut tekrar çalıştırılabilir; var olan kayıtları bozmaz.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.basvurular.models import BasvuruDurumu
from apps.katalog.models import AlanTipi, BasvuruKategorisi, KategoriAlani, MusteriTipi, Operator

DURUMLAR = [
    # (ad, slug, renk, ikon, baslangic, hakedis, olumsuz, bayi_duzenler, sira, sinyal)
    ("Beklemede", "beklemede", "#64748b", "schedule", True, False, False, False, 10, 1),
    ("İşlemde", "islemde", "#3b82f6", "sync", False, False, False, False, 20, 3),
    ("Eksik Evrak", "eksik-evrak", "#f59e0b", "warning", False, False, False, True, 30, 2),
    ("Mutabakat Bekliyor", "mutabakat", "#8b5cf6", "handshake", False, False, False, False, 40, 4),
    ("Aktif", "aktif", "#16a34a", "check_circle", False, True, False, False, 50, 5),
    ("Hatalı", "hatali", "#dc2626", "cancel", False, False, True, False, 60, 1),
    ("İptal", "iptal", "#78716c", "block", False, False, True, False, 70, 1),
]

OPERATORLER = [
    ("Turkcell", "#ffc900"),
    ("Vodafone", "#e60000"),
    ("Türk Telekom", "#00a0e3"),
]

# (ad, ikon, musteri_tipi, tarife_zorunlu, sira, ek alanlar)
KATEGORILER = [
    (
        "MNT / Numara Taşıma",
        "swap_horiz",
        MusteriTipi.HEPSI,
        True,
        10,
        [
            ("gececegi_operator", "Geçeceği Operatör", AlanTipi.METIN, True, "", ""),
            ("sim_imei", "SIM / IMEI", AlanTipi.METIN, False, "", ""),
            ("aks", "AKS Kodu", AlanTipi.METIN, True, "", ""),
            ("kimlik_on", "Kimlik Ön Yüz", AlanTipi.RESIM, True, "Belgeler", ""),
            ("kimlik_arka", "Kimlik Arka Yüz", AlanTipi.RESIM, True, "Belgeler", ""),
            ("ikametgah", "İkametgah", AlanTipi.DOSYA, False, "Belgeler", ""),
        ],
    ),
    (
        "Kontörlü Yeni Hat",
        "sim_card",
        MusteriTipi.HEPSI,
        True,
        20,
        [
            ("sim_imei", "SIM / IMEI", AlanTipi.METIN, True, "", ""),
            ("aks", "AKS Kodu", AlanTipi.METIN, True, "", ""),
            ("kimlik_on", "Kimlik Ön Yüz", AlanTipi.RESIM, True, "Belgeler", ""),
            ("kimlik_arka", "Kimlik Arka Yüz", AlanTipi.RESIM, True, "Belgeler", ""),
        ],
    ),
    (
        "Faturalı Yeni Hat",
        "receipt_long",
        MusteriTipi.HEPSI,
        True,
        30,
        [
            ("sim_imei", "SIM / IMEI", AlanTipi.METIN, False, "", ""),
            ("aks", "AKS Kodu", AlanTipi.METIN, True, "", ""),
            ("kimlik_on", "Kimlik Ön Yüz", AlanTipi.RESIM, True, "Belgeler", ""),
            ("kimlik_arka", "Kimlik Arka Yüz", AlanTipi.RESIM, True, "Belgeler", ""),
            ("ikametgah", "İkametgah", AlanTipi.DOSYA, True, "Belgeler", ""),
        ],
    ),
    (
        "Şebeke İçi Geçiş",
        "cell_tower",
        MusteriTipi.HEPSI,
        True,
        40,
        [
            ("aks", "AKS Kodu", AlanTipi.METIN, True, "", ""),
            ("kimlik_on", "Kimlik Ön Yüz", AlanTipi.RESIM, True, "Belgeler", ""),
            ("kimlik_arka", "Kimlik Arka Yüz", AlanTipi.RESIM, True, "Belgeler", ""),
            ("ikametgah", "İkametgah", AlanTipi.DOSYA, False, "Belgeler", ""),
        ],
    ),
    (
        "ADSL / İnternet",
        "router",
        MusteriTipi.HEPSI,
        True,
        50,
        [
            ("sabit_hat", "Sabit Hat Durumu", AlanTipi.SECIM, True, "", "Sabit hattı var\nSabit hattı yok\nYeni sabit hat istiyor"),
            ("modem_istegi", "Modem İsteği", AlanTipi.SECIM, True, "", "Modem istiyor\nModem istemiyor\nMevcut modemi kullanacak"),
            ("aks", "AKS Kodu", AlanTipi.METIN, False, "", ""),
            ("kimlik_on", "Kimlik Ön Yüz", AlanTipi.RESIM, True, "Belgeler", ""),
            ("kimlik_arka", "Kimlik Arka Yüz", AlanTipi.RESIM, True, "Belgeler", ""),
            ("ikametgah", "İkametgah", AlanTipi.DOSYA, True, "Belgeler", ""),
        ],
    ),
    (
        "Pasaportlu Numara Taşıma",
        "flight_takeoff",
        MusteriTipi.YABANCI,
        False,
        60,
        [
            ("gececegi_operator", "Geçeceği Operatör", AlanTipi.METIN, True, "", ""),
            ("pasaport_on", "Pasaport Ön Sayfa", AlanTipi.RESIM, True, "Belgeler", ""),
            ("pasaport_arka", "Pasaport İkinci Sayfa", AlanTipi.RESIM, True, "Belgeler", ""),
            ("ikametgah", "İkametgah", AlanTipi.DOSYA, False, "Belgeler", ""),
        ],
    ),
    (
        "Pasaportlu Yeni Hat",
        "badge",
        MusteriTipi.YABANCI,
        False,
        70,
        [
            ("sim_imei", "SIM / IMEI", AlanTipi.METIN, False, "", ""),
            ("pasaport_on", "Pasaport Ön Sayfa", AlanTipi.RESIM, True, "Belgeler", ""),
            ("pasaport_arka", "Pasaport İkinci Sayfa", AlanTipi.RESIM, True, "Belgeler", ""),
            ("ikametgah", "İkametgah", AlanTipi.DOSYA, False, "Belgeler", ""),
        ],
    ),
]


class Command(BaseCommand):
    help = "Başvuru durumlarını, operatörleri ve başlangıç kategorilerini oluşturur."

    @transaction.atomic
    def handle(self, *args, **options):
        for ad, slug, renk, ikon, baslangic, hakedis, olumsuz, duzenle, sira, sinyal in DURUMLAR:
            _, olusturuldu = BasvuruDurumu.objects.get_or_create(
                slug=slug,
                defaults={
                    "ad": ad,
                    "renk": renk,
                    "ikon": ikon,
                    "baslangic_durumu": baslangic,
                    "hakedis_tetikler": hakedis,
                    "olumsuz_sonuc": olumsuz,
                    "bayi_duzenleyebilir": duzenle,
                    "sira": sira,
                    "sinyal_seviyesi": sinyal,
                },
            )
            if olusturuldu:
                self.stdout.write(f"  durum: {ad}")

        operatorler = []
        for sira, (ad, renk) in enumerate(OPERATORLER, start=1):
            operator, olusturuldu = Operator.objects.get_or_create(
                ad=ad, defaults={"renk": renk, "sira": sira * 10}
            )
            operatorler.append(operator)
            if olusturuldu:
                self.stdout.write(f"  operatör: {ad}")

        for ad, ikon, musteri_tipi, tarife_zorunlu, sira, alanlar in KATEGORILER:
            kategori, olusturuldu = BasvuruKategorisi.objects.get_or_create(
                ad=ad,
                defaults={
                    "ikon": ikon,
                    "musteri_tipi": musteri_tipi,
                    "tarife_zorunlu": tarife_zorunlu,
                    "sira": sira,
                },
            )
            if olusturuldu:
                kategori.operatorler.set(operatorler)
                self.stdout.write(f"  kategori: {ad}")

            for alan_sira, (kod, etiket, tip, zorunlu, grup, secenekler) in enumerate(
                alanlar, start=1
            ):
                KategoriAlani.objects.get_or_create(
                    kategori=kategori,
                    kod=kod,
                    defaults={
                        "etiket": etiket,
                        "tip": tip,
                        "zorunlu": zorunlu,
                        "grup": grup,
                        "secenekler": secenekler,
                        "sira": alan_sira * 10,
                    },
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nHazır: {BasvuruDurumu.objects.count()} durum, "
                f"{Operator.objects.count()} operatör, "
                f"{BasvuruKategorisi.objects.count()} kategori, "
                f"{KategoriAlani.objects.count()} form alanı."
            )
        )
