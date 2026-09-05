"""Kurulum sırasının 5-7. adımlarını örnek verilerle doldurur.

`baslangic_verisi` iskeleti kurar (durumlar, operatörler, kategoriler, form
alanları). Bu komut onun üstüne sistemi *çalışır* hâle getiren veriyi
ekler: tarifeler, kampanyalar, bayi grupları, ücret ve hakediş kuralları,
banka hesabı, duyuru ve SIM stoğu.

Rakamlar örnektir; gerçek anlaşma tutarları yönetim panelinden değiştirilir.
Komut tekrar çalıştırılabilir, var olan kayıtları bozmaz.
"""

from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.basvurular.models import BasvuruDurumu
from apps.bayi.models import Duyuru, SimKart
from apps.finans.models import Banka, BayiGrubu, KuralYonu, UcretKurali
from apps.katalog.models import BasvuruKategorisi, Kampanya, MusteriTipi, Operator, Tarife

GRUPLAR = [
    ("Standart Bayi", "Yeni açılan bayilerin varsayılan kademesi."),
    ("Anlaşmalı Bayi", "Hacim taahhüdü veren bayiler; hakedişleri daha yüksek."),
]

# (kategori, operatör, tarife adı, müşteri tipi, açıklama, kampanya adları)
TARIFELER = [
    (
        "MNT / Numara Taşıma", "Turkcell", "Platinum 20 GB", MusteriTipi.HEPSI,
        "20 GB internet, 1000 dakika, 1000 SMS. Taahhüt 24 ay.",
        ["İlk 3 Ay Yarı Fiyat"],
    ),
    (
        "MNT / Numara Taşıma", "Vodafone", "Uyumlu 12 GB", MusteriTipi.HEPSI,
        "12 GB internet, 750 dakika. Taahhüt 12 ay.", [],
    ),
    (
        "MNT / Numara Taşıma", "Türk Telekom", "Selfy Taşıma 15 GB", MusteriTipi.HEPSI,
        "15 GB internet, sosyal medya paketi dahil. 18-29 yaş.", [],
    ),
    (
        "Kontörlü Yeni Hat", "Turkcell", "Gençlik Kontörlü 10 GB", MusteriTipi.HEPSI,
        "Taahhütsüz kontörlü hat. 10 GB, 500 dakika.", [],
    ),
    (
        "Kontörlü Yeni Hat", "Vodafone", "Hazır Kart 8 GB", MusteriTipi.HEPSI,
        "Taahhütsüz hazır kart. 8 GB, 300 dakika.", [],
    ),
    (
        "Faturalı Yeni Hat", "Vodafone", "Red 20 GB", MusteriTipi.HEPSI,
        "20 GB internet, sınırsız şebeke içi. Taahhüt 24 ay.", [],
    ),
    (
        "Faturalı Yeni Hat", "Türk Telekom", "Selfy 25 GB", MusteriTipi.HEPSI,
        "25 GB internet, TV+ dahil. Taahhüt 24 ay.", [],
    ),
    (
        "Şebeke İçi Geçiş", "Turkcell", "Şebeke İçi 15 GB", MusteriTipi.HEPSI,
        "Mevcut Turkcell hattının paket yükseltmesi.", [],
    ),
    (
        "ADSL / İnternet", "Türk Telekom", "Fiber 100 Mbps", MusteriTipi.HEPSI,
        "100 Mbps fiber, sınırsız kota. Taahhüt 24 ay.",
        [("Modem Hediyeli", "24 ay taahhütte modem ücretsiz verilir.")],
    ),
    (
        "ADSL / İnternet", "Türk Telekom", "Fiber 50 Mbps", MusteriTipi.HEPSI,
        "50 Mbps fiber, sınırsız kota. Taahhüt 12 ay.", [],
    ),
    (
        "Pasaportlu Numara Taşıma", "Vodafone", "Pasaportlu Taşıma 10 GB",
        MusteriTipi.YABANCI, "Yabancı uyruklu müşteriler için taşıma paketi.", [],
    ),
    (
        "Pasaportlu Yeni Hat", "Turkcell", "Pasaportlu Kontörlü 10 GB",
        MusteriTipi.YABANCI, "Pasaportla açılan taahhütsüz hat.", [],
    ),
]

# Kategori bazlı üç yön: bayiye hakediş, bayiden tahsilat, bize gelen ana
# hakediş. Aradaki fark kârdır ve başvuru satırında görünür.
# (kategori, ad, yön, tutar)
KURALLAR = [
    ("MNT / Numara Taşıma", "MNT hakedişi", KuralYonu.HAKEDIS, "95.00"),
    ("MNT / Numara Taşıma", "MNT ana hakedişi", KuralYonu.ANA_HAKEDIS, "160.00"),

    ("Kontörlü Yeni Hat", "Kontörlü hat ücreti", KuralYonu.TAHSILAT, "25.00"),
    ("Kontörlü Yeni Hat", "Kontörlü hat hakedişi", KuralYonu.HAKEDIS, "60.00"),
    ("Kontörlü Yeni Hat", "Kontörlü hat ana hakedişi", KuralYonu.ANA_HAKEDIS, "140.00"),

    ("Faturalı Yeni Hat", "Faturalı hat hakedişi", KuralYonu.HAKEDIS, "150.00"),
    ("Faturalı Yeni Hat", "Faturalı hat ana hakedişi", KuralYonu.ANA_HAKEDIS, "260.00"),

    ("Şebeke İçi Geçiş", "Şebeke içi geçiş hakedişi", KuralYonu.HAKEDIS, "45.00"),
    ("Şebeke İçi Geçiş", "Şebeke içi geçiş ana hakedişi", KuralYonu.ANA_HAKEDIS, "90.00"),

    ("ADSL / İnternet", "ADSL hakedişi", KuralYonu.HAKEDIS, "200.00"),
    ("ADSL / İnternet", "ADSL ana hakedişi", KuralYonu.ANA_HAKEDIS, "350.00"),

    ("Pasaportlu Numara Taşıma", "Pasaportlu taşıma hakedişi", KuralYonu.HAKEDIS, "110.00"),
    ("Pasaportlu Numara Taşıma", "Pasaportlu taşıma ana hakedişi", KuralYonu.ANA_HAKEDIS, "190.00"),

    ("Pasaportlu Yeni Hat", "Pasaportlu hat hakedişi", KuralYonu.HAKEDIS, "120.00"),
    ("Pasaportlu Yeni Hat", "Pasaportlu hat ana hakedişi", KuralYonu.ANA_HAKEDIS, "210.00"),
]

# Daha dar kapsamlı kural, genel kuralı ezer. İki örnek: bir bayi kademesi
# ve bir tedarikçi anlaşması.
# (kategori, grup adı, ad, yön, tutar)
GRUP_KURALLARI = [
    ("MNT / Numara Taşıma", "Anlaşmalı Bayi", "Anlaşmalı bayi · MNT hakedişi",
     KuralYonu.HAKEDIS, "110.00"),
    ("Faturalı Yeni Hat", "Anlaşmalı Bayi", "Anlaşmalı bayi · faturalı hat hakedişi",
     KuralYonu.HAKEDIS, "170.00"),
]

# (kategori, tedarikçi kullanıcı adı, ad, tutar) — tedarikçi kendi payını
# aldığı için bize ödediği ana hakediş operatörünkinden düşüktür.
TEDARIKCI_KURALLARI = [
    ("MNT / Numara Taşıma", "tedarikci.ege", "Ege Tedarik · MNT ana hakedişi", "145.00"),
    ("Faturalı Yeni Hat", "tedarikci.ege", "Ege Tedarik · faturalı hat ana hakedişi", "235.00"),
]

BANKALAR = [
    ("Ziraat Bankası", "Aktivasyon Telekom Ltd. Şti.", "TR000000000000000000000001"),
]

DUYURULAR = [
    (
        "Hoş geldiniz",
        "Panel yeni sürümüne geçti. Başvurularınızı buradan girip durumunu "
        "anlık takip edebilirsiniz. Sorularınız için ofisi arayın.",
        False,
    ),
    (
        "Evrak kuralı",
        "Kimlik görselleri okunaklı ve dört köşesi görünecek şekilde "
        "yüklenmelidir. Okunmayan evrak “Eksik Evrak” durumuna alınır.",
        True,
    ),
]

# Bayiye zimmetlenecek örnek stok. Gerçekte kartlar tek tek girilir.
SIM_STOGU = [
    ("8990011234567890001", "Turkcell", "bayi.kaya"),
    ("8990011234567890002", "Turkcell", "bayi.kaya"),
    ("8990011234567890003", "Turkcell", "bayi.kaya"),
    ("8990011234567890004", "Vodafone", "bayi.kaya"),
    ("8990011234567890005", "Vodafone", "bayi.kaya"),
    ("8990011234567890006", "Vodafone", None),
    ("8990011234567890007", "Türk Telekom", None),
    ("8990011234567890008", "Türk Telekom", None),
]


class Command(BaseCommand):
    help = (
        "Örnek tarife, kampanya, ücret kuralı, banka, duyuru ve SIM stoğu "
        "oluşturur. Önce baslangic_verisi çalıştırılmış olmalıdır."
    )

    def add_arguments(self, ayristirici):
        ayristirici.add_argument(
            "--zorla",
            action="store_true",
            help="DEBUG kapalıyken de çalıştır. Üretimde gerçek tutarları elle girin.",
        )

    @transaction.atomic
    def handle(self, *args, **secenekler):
        from django.conf import settings

        if not settings.DEBUG and not secenekler["zorla"]:
            raise CommandError(
                "Bu komut örnek fiyatlarla kural yazar ve yalnızca geliştirme "
                "içindir. Üretimde çalıştırmak için --zorla gerekir."
            )

        if not BasvuruKategorisi.objects.exists():
            raise CommandError(
                "Kategori bulunamadı. Önce: manage.py baslangic_verisi"
            )

        aktif_durum = BasvuruDurumu.objects.filter(hakedis_tetikler=True).first()
        if aktif_durum is None:
            raise CommandError(
                "Hakediş tetikleyen bir durum yok. Önce: manage.py baslangic_verisi"
            )

        gruplar = self._gruplar()
        tarifeler = self._tarifeler()
        self._kurallar(aktif_durum, gruplar, tarifeler)
        self._banka()
        self._duyurular()
        self._sim_stogu()

        self.stdout.write(
            self.style.SUCCESS(
                f"\nHazır: {Tarife.objects.count()} tarife, "
                f"{Kampanya.objects.count()} kampanya, "
                f"{UcretKurali.objects.count()} ücret kuralı, "
                f"{SimKart.objects.count()} SIM kart.\n"
                f"Kurallar “{aktif_durum.ad}” durumunda işler.\n"
            )
        )

    def _gruplar(self):
        self.stdout.write(self.style.MIGRATE_HEADING("\nBayi grupları"))
        gruplar = {}
        for ad, aciklama in GRUPLAR:
            grup, yeni = BayiGrubu.objects.get_or_create(
                ad=ad, defaults={"aciklama": aciklama}
            )
            gruplar[ad] = grup
            self.stdout.write(f"  {ad:18} {'oluşturuldu' if yeni else 'zaten var'}")
        return gruplar

    def _tarifeler(self):
        self.stdout.write(self.style.MIGRATE_HEADING("\nTarifeler ve kampanyalar"))
        tarifeler = {}
        for sira, (
            kategori_adi, operator_adi, tarife_adi, musteri_tipi, aciklama, kampanyalar
        ) in enumerate(TARIFELER, start=1):
            kategori = BasvuruKategorisi.objects.filter(ad=kategori_adi).first()
            operator = Operator.objects.filter(ad=operator_adi).first()
            if kategori is None or operator is None:
                self.stdout.write(
                    self.style.WARNING(f"  atlandı: {kategori_adi} · {operator_adi}")
                )
                continue

            tarife, yeni = Tarife.objects.get_or_create(
                operator=operator,
                ad=tarife_adi,
                defaults={
                    "musteri_tipi": musteri_tipi,
                    "aciklama": aciklama,
                    "sira": sira * 10,
                },
            )
            # Aynı tarife birden çok kategoride geçerli olabilir; bağlantı
            # eklenir, var olanlar sökülmez.
            tarife.kategoriler.add(kategori)
            tarifeler[(kategori_adi, tarife_adi)] = tarife
            # Tarifesi olan operatör kategorinin listesine de girsin; aksi
            # hâlde tarife tanımlı ama formda operatör seçilemez oluyor.
            kategori.operatorler.add(operator)
            self.stdout.write(
                f"  {kategori_adi:26} {operator_adi:14} {tarife_adi:26} "
                f"{'oluşturuldu' if yeni else 'zaten var'}"
            )

            for kampanya_sira, kampanya_adi in enumerate(kampanyalar, start=1):
                Kampanya.objects.get_or_create(
                    tarife=tarife,
                    ad=kampanya_adi,
                    defaults={"sira": kampanya_sira * 10},
                )
        return tarifeler

    def _kurallar(self, aktif_durum, gruplar, tarifeler):
        from django.contrib.auth.models import User

        self.stdout.write(self.style.MIGRATE_HEADING("\nÜcret ve hakediş kuralları"))

        for kategori_adi, ad, yon, tutar in KURALLAR:
            kategori = BasvuruKategorisi.objects.filter(ad=kategori_adi).first()
            if kategori is None:
                continue
            _, yeni = UcretKurali.objects.get_or_create(
                ad=ad,
                defaults={
                    "yon": yon,
                    "tutar": Decimal(tutar),
                    "kategori": kategori,
                    "tetikleyici_durum": aktif_durum,
                },
            )
            self._kural_satiri(ad, yon, tutar, yeni)

        for kategori_adi, grup_adi, ad, yon, tutar in GRUP_KURALLARI:
            kategori = BasvuruKategorisi.objects.filter(ad=kategori_adi).first()
            grup = gruplar.get(grup_adi)
            if kategori is None or grup is None:
                continue
            _, yeni = UcretKurali.objects.get_or_create(
                ad=ad,
                defaults={
                    "yon": yon,
                    "tutar": Decimal(tutar),
                    "kategori": kategori,
                    "bayi_grubu": grup,
                    "tetikleyici_durum": aktif_durum,
                },
            )
            self._kural_satiri(ad, yon, tutar, yeni)

        for kategori_adi, kullanici_adi, ad, tutar in TEDARIKCI_KURALLARI:
            kategori = BasvuruKategorisi.objects.filter(ad=kategori_adi).first()
            tedarikci = User.objects.filter(username=kullanici_adi).first()
            if kategori is None or tedarikci is None:
                continue
            _, yeni = UcretKurali.objects.get_or_create(
                ad=ad,
                defaults={
                    "yon": KuralYonu.ANA_HAKEDIS,
                    "tutar": Decimal(tutar),
                    "kategori": kategori,
                    "tedarikci": tedarikci,
                    "tetikleyici_durum": aktif_durum,
                },
            )
            self._kural_satiri(ad, KuralYonu.ANA_HAKEDIS, tutar, yeni)

    def _kural_satiri(self, ad, yon, tutar, yeni):
        etiket = dict(KuralYonu.choices)[yon].split(" (")[0]
        self.stdout.write(
            f"  {ad:44} {etiket:14} {tutar:>8} ₺  "
            f"{'oluşturuldu' if yeni else 'zaten var'}"
        )

    def _banka(self):
        self.stdout.write(self.style.MIGRATE_HEADING("\nBanka hesapları"))
        for banka_adi, hesap_sahibi, iban in BANKALAR:
            _, yeni = Banka.objects.get_or_create(
                iban=iban,
                defaults={
                    "banka_adi": banka_adi,
                    "hesap_sahibi": hesap_sahibi,
                    "aciklama": "Bakiye yüklerken açıklamaya bayi kodunuzu yazın.",
                },
            )
            self.stdout.write(
                f"  {banka_adi:18} {iban}  {'oluşturuldu' if yeni else 'zaten var'}"
            )

    def _duyurular(self):
        self.stdout.write(self.style.MIGRATE_HEADING("\nDuyurular"))
        for baslik, icerik, onemli in DUYURULAR:
            _, yeni = Duyuru.objects.get_or_create(
                baslik=baslik, defaults={"icerik": icerik, "onemli": onemli}
            )
            self.stdout.write(f"  {baslik:18} {'oluşturuldu' if yeni else 'zaten var'}")

    def _sim_stogu(self):
        from django.contrib.auth.models import User

        self.stdout.write(self.style.MIGRATE_HEADING("\nSIM stoğu"))
        zimmetli = bekleyen = 0
        for imei, operator_adi, kullanici_adi in SIM_STOGU:
            operator = Operator.objects.filter(ad=operator_adi).first()
            bayi = (
                User.objects.filter(username=kullanici_adi).first()
                if kullanici_adi
                else None
            )
            # Durumu SimKart.save() zimmete göre kendisi belirler.
            _, yeni = SimKart.objects.get_or_create(
                imei=imei, defaults={"operator": operator, "bayi": bayi}
            )
            if bayi:
                zimmetli += 1
            else:
                bekleyen += 1
            if not yeni:
                continue
        self.stdout.write(
            f"  {zimmetli} kart bayiye zimmetli, {bekleyen} kart beklemede"
        )
