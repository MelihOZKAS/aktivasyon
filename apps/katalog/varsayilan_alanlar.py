"""Yeni bir kategori açıldığında forma konan alanlar.

Panelden kategori açmak formu boş bırakıyordu: `KategoriAlani` kaydı
olmadan bayi hiçbir şey yazamıyor, yönetici de yirmi satırı elle
giriyordu. Artık **sistemde bilinen bütün alanlar açık gelir**; bu
kategoride sorulmayacak olanı yönetici "Aktif" kutusundan kapatır.
Kapatmak eklemekten kolaydır ve kural tek cümlede durur — istisna yok,
müşteri tipine göre dallanma yok.

Buradaki liste yalnızca **başlangıç** değeridir; kural değişmedi, formu
yine `KategoriAlani` kayıtları çizer. Kategori açıldıktan sonra alanlar
kategorinin kendi verisidir ve bu dosya onlara bir daha dokunmaz.
Yeni bir alan tipi yaygınlaşırsa listeye buradan eklenir.

Satır biçimi: (kod, etiket, tip, zorunlu, grup, seçenekler, çekirdek alan)
"""

from apps.katalog.models import AlanTipi

# Müşteri bilgileri. Çekirdek alanı dolu olanlar başvurunun kendi kolonuna
# yazılır ve aranabilir olur.
ORTAK_ALANLAR = [
    ("kimlik_tipi", "Kimlik Tipi", AlanTipi.SECIM, True, "Müşteri", "", "kimlik_tipi"),
    ("kimlik_no", "TC / Pasaport No", AlanTipi.METIN, True, "Müşteri", "", "kimlik_no"),
    ("isim", "İsim", AlanTipi.METIN, True, "Müşteri", "", "isim"),
    ("soyisim", "Soy İsim", AlanTipi.METIN, True, "Müşteri", "", "soyisim"),
    ("dogum_tarihi", "Doğum Tarihi", AlanTipi.TARIH, False, "Müşteri", "", ""),
    ("irtibat", "İletişim No", AlanTipi.TELEFON, True, "Müşteri", "", "irtibat"),
    ("sehir", "Şehir", AlanTipi.METIN, False, "Adres", "", ""),
    ("ilce", "İlçe", AlanTipi.METIN, False, "Adres", "", ""),
    ("adres", "Adres", AlanTipi.UZUN_METIN, False, "Adres", "", "adres"),
]

TASINACAK_NUMARA = (
    "numara", "Taşınacak No", AlanTipi.TELEFON, True, "Müşteri", "", "numara",
)

# İşlem bilgileri.
ISLEM_ALANLARI = [
    ("gececegi_operator", "Geçeceği Operatör", AlanTipi.METIN, False, "Başvuru detayları", "", ""),
    ("sim_imei", "SIM / IMEI", AlanTipi.SIM_KART, False, "Başvuru detayları", "", ""),
    ("aks", "AKS Kodu", AlanTipi.METIN, False, "Başvuru detayları", "", ""),
    (
        "sabit_hat", "Sabit Hat Durumu", AlanTipi.SECIM, False, "Başvuru detayları",
        "Sabit hattı var\nSabit hattı yok\nYeni sabit hat istiyor", "",
    ),
    (
        "modem_istegi", "Modem İsteği", AlanTipi.SECIM, False, "Başvuru detayları",
        "Modem istiyor\nModem istemiyor\nMevcut modemi kullanacak", "",
    ),
]

# Kimlik görüntüleri. Kimlik de pasaport da açık gelir; kategoride hangisi
# sorulacaksa diğeri kapatılır.
BELGE_ALANLARI = [
    ("kimlik_on", "Kimlik Ön Yüz", AlanTipi.RESIM, True, "Belgeler", "", ""),
    ("kimlik_arka", "Kimlik Arka Yüz", AlanTipi.RESIM, True, "Belgeler", "", ""),
    ("pasaport_on", "Pasaport Ön Sayfa", AlanTipi.RESIM, False, "Belgeler", "", ""),
    ("pasaport_arka", "Pasaport İkinci Sayfa", AlanTipi.RESIM, False, "Belgeler", "", ""),
    ("ikametgah", "İkametgah", AlanTipi.DOSYA, False, "Belgeler", "", ""),
]

def _istege_bagli(alan):
    """Alanı zorunluluktan çıkarır.

    Her kategoriye açılan bir alan zorunlu gelmemeli: yönetici kapatmayı
    unutursa bayi olmayan bir bilgiyi doldurmak zorunda kalır. Kimlik, isim
    ve iletişim gibi gerçekten her işlemde sorulanlar zorunlu kalır.
    """
    kod, etiket, tip, _zorunlu, grup, secenekler, cekirdek = alan
    return (kod, etiket, tip, False, grup, secenekler, cekirdek)


# Yeni kategoriye açılan alanların tamamı, formdaki sırasıyla.
TUM_ALANLAR = [
    *ORTAK_ALANLAR[:6],
    _istege_bagli(TASINACAK_NUMARA),
    *ORTAK_ALANLAR[6:],
    *ISLEM_ALANLARI,
    *BELGE_ALANLARI,
]


def varsayilan_alanlari_ac(kategori):
    """Kategoriye bütün alanları açar; var olan alana dokunmaz.

    Aynı kodlu alan zaten varsa atlanır: komut tekrar çalıştırılabilir,
    yöneticinin kendi eklediği satır ezilmez ve kapattığı alan geri açılmaz.
    """
    from apps.katalog.models import KategoriAlani

    acilan = 0
    for sira, (
        kod, etiket, tip, zorunlu, grup, secenekler, cekirdek
    ) in enumerate(TUM_ALANLAR, start=1):
        _, olusturuldu = KategoriAlani.objects.get_or_create(
            kategori=kategori,
            kod=kod,
            defaults={
                "etiket": etiket,
                "tip": tip,
                "zorunlu": zorunlu,
                "grup": grup,
                "secenekler": secenekler,
                "cekirdek_alan": cekirdek,
                "sira": sira * 10,
            },
        )
        acilan += int(olusturuldu)
    return acilan
