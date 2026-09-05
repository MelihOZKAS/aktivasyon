"""Sistemi kullanılabilir hale getiren başlangıç verisini yükler.

Eski sistemdeki 7 ayrı başvuru modeli burada 7 satır veriye dönüşür.
Komut tekrar çalıştırılabilir; var olan kayıtları bozmaz.
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from apps.basvurular.models import BasvuruDurumu
from apps.katalog.models import AlanTipi, BasvuruKategorisi, KategoriAlani, MusteriTipi, Operator
from apps.katalog.utils import turkce_slug
from apps.katalog.varsayilan_alanlar import ORTAK_ALANLAR, TASINACAK_NUMARA


def _getir_ya_da_ac(model, ad, defaults):
    """Kaydı adından **ya da** slug'ından bulur; yoksa açar.

    `get_or_create(ad=...)` yetmiyordu: yönetici panelden kategorinin adını
    değiştirdiğinde slug eskisi gibi kalıyor, komut kaydı bulamayıp yeniden
    açmaya çalışıyor ve tekil slug kısıtına çarpıyordu. Kurulum her container
    açılışında çalıştığı için sonuç, tek bir yeniden adlandırmayla ayağa
    kalkmayan bir sunucuydu.

    Adı da slug'ı da tekil olduğu için ikisine birden bakılır. Bulunan kayda
    dokunulmaz: panelde yapılan düzenleme kurulumla geri alınmaz.
    """
    slug = turkce_slug(ad)
    mevcut = model.objects.filter(Q(slug=slug) | Q(ad=ad)).first()
    if mevcut is not None:
        return mevcut, False
    return model.objects.create(ad=ad, slug=slug, **defaults), True

DURUMLAR = [
    # (ad, slug, renk, ikon, baslangic, hakedis, olumsuz, bayi_duzenler,
    #  sira, sinyal, bildirim, belge_sil)
    ("Beklemede", "beklemede", "#64748b", "schedule", True, False, False, False, 10, 1, False, False),
    ("İşlemde", "islemde", "#3b82f6", "sync", False, False, False, False, 20, 3, False, False),
    ("Eksik Evrak", "eksik-evrak", "#f59e0b", "warning", False, False, False, True, 30, 2, True, False),
    ("Mutabakat Bekliyor", "mutabakat", "#0891b2", "handshake", False, False, False, False, 40, 4, False, False),
    ("Aktif", "aktif", "#16a34a", "check_circle", False, True, False, False, 50, 5, True, True),
    ("Hatalı", "hatali", "#dc2626", "cancel", False, False, True, False, 60, 1, True, False),
    ("İptal", "iptal", "#78716c", "block", False, False, True, False, 70, 1, True, True),
]

OPERATORLER = [
    ("Turkcell", "#ffc900"),
    ("Vodafone", "#e60000"),
    ("Türk Telekom", "#00a0e3"),
]

# Ortak müşteri alanları panelden açılan kategorilerde de kullanılıyor;
# liste tek yerde durur (apps/katalog/varsayilan_alanlar.py).

# (ad, ikon, musteri_tipi, tarife_zorunlu, sim_karsiligi, sira,
#  kategoriye özel ek alanlar)
KATEGORILER = [
    (
        "MNT / Numara Taşıma",
        "swap_horiz",
        MusteriTipi.HEPSI,
        True,
        True,
        10,
        [
            ("gececegi_operator", "Geçeceği Operatör", AlanTipi.METIN, True, "", ""),
            ("sim_imei", "SIM / IMEI", AlanTipi.SIM_KART, False, "", ""),
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
        True,
        20,
        [
            ("sim_imei", "SIM / IMEI", AlanTipi.SIM_KART, True, "", ""),
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
        True,
        30,
        [
            ("sim_imei", "SIM / IMEI", AlanTipi.SIM_KART, False, "", ""),
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
        False,
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
        False,
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
        True,
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
        True,
        70,
        [
            ("sim_imei", "SIM / IMEI", AlanTipi.SIM_KART, False, "", ""),
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
        for (
            ad, slug, renk, ikon, baslangic, hakedis, olumsuz, duzenle, sira,
            sinyal, bildirim, belge_sil,
        ) in DURUMLAR:
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
                    "bildirim_gonder": bildirim,
                    "belgeleri_sil": belge_sil,
                },
            )
            if olusturuldu:
                self.stdout.write(f"  durum: {ad}")

        operatorler = []
        for sira, (ad, renk) in enumerate(OPERATORLER, start=1):
            operator, olusturuldu = _getir_ya_da_ac(
                Operator, ad, {"renk": renk, "sira": sira * 10}
            )
            operatorler.append(operator)
            if olusturuldu:
                self.stdout.write(f"  operatör: {ad}")

        for (
            ad, ikon, musteri_tipi, tarife_zorunlu, sim_karsiligi, sira, alanlar
        ) in KATEGORILER:
            kategori, olusturuldu = _getir_ya_da_ac(
                BasvuruKategorisi,
                ad,
                {
                    "ikon": ikon,
                    "musteri_tipi": musteri_tipi,
                    "tarife_zorunlu": tarife_zorunlu,
                    "sim_karsiligi_gerekir": sim_karsiligi,
                    "sira": sira,
                },
            )
            if olusturuldu:
                kategori.operatorler.set(operatorler)
                self.stdout.write(f"  kategori: {ad}")

            # Numara taşıma / şebeke içi işlemlerde taşınacak numara sorulur.
            ortak = list(ORTAK_ALANLAR)
            if "Taşıma" in ad or "Şebeke" in ad:
                ortak.insert(5, TASINACAK_NUMARA)

            tum_alanlar = [
                (kod, etiket, tip, zorunlu, grup, secenekler, cekirdek)
                for kod, etiket, tip, zorunlu, grup, secenekler, cekirdek in ortak
            ] + [
                (kod, etiket, tip, zorunlu, grup or "Başvuru detayları", secenekler, "")
                for kod, etiket, tip, zorunlu, grup, secenekler in alanlar
            ]

            for alan_sira, (
                kod, etiket, tip, zorunlu, grup, secenekler, cekirdek
            ) in enumerate(tum_alanlar, start=1):
                KategoriAlani.objects.get_or_create(
                    kategori=kategori,
                    kod=kod,
                    defaults={
                        "etiket": etiket,
                        "tip": tip,
                        "zorunlu": zorunlu,
                        "grup": grup,
                        "secenekler": secenekler,
                        "cekirdek_alan": cekirdek,
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
