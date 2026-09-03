"""Para motoru testleri.

Eski sistemde bakiye mantığı `Bayi_Listesi.save()` içindeydi; aynı kaydı
iki kez kaydetmek parayı iki kez işliyordu. Buradaki testler yeni yapının
bu hatayı yapısal olarak engellediğini doğrular.
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from apps.basvurular.models import Basvuru, BasvuruDurumu
from apps.finans.models import Cuzdan, CuzdanHareketi, HareketTipi, KuralYonu, UcretKurali
from apps.finans.services import basvuru_parasini_isle
from apps.katalog.models import BasvuruKategorisi, Operator, Tarife

TL = Decimal


class ParaMotoruTestleri(TestCase):
    def setUp(self):
        self.beklemede = BasvuruDurumu.objects.create(
            ad="Beklemede", slug="beklemede", baslangic_durumu=True, sira=10
        )
        self.aktif = BasvuruDurumu.objects.create(
            ad="Aktif", slug="aktif", hakedis_tetikler=True, sira=50
        )
        self.iptal = BasvuruDurumu.objects.create(
            ad="İptal", slug="iptal", olumsuz_sonuc=True, sira=70
        )

        self.bayi = User.objects.create_user("bayi1", password="parola123")
        self.cuzdan = Cuzdan.objects.create(bayi=self.bayi, bakiye=TL("1000.00"))

        self.operator = Operator.objects.create(ad="Turkcell")
        self.kategori = BasvuruKategorisi.objects.create(ad="Faturalı Yeni Hat")
        self.tarife = Tarife.objects.create(
            kategori=self.kategori, operator=self.operator, ad="Süper 20GB"
        )

    def _basvuru_olustur(self, durum=None):
        return Basvuru.objects.create(
            bayi=self.bayi,
            kategori=self.kategori,
            operator=self.operator,
            tarife=self.tarife,
            kimlik_no="12345678901",
            isim="Ahmet",
            soyisim="Yılmaz",
            irtibat="5551234567",
            durum=durum or self.beklemede,
        )

    def _kural(self, yon, tutar, **kapsam):
        return UcretKurali.objects.create(
            ad=f"{yon} kuralı",
            yon=yon,
            tutar=TL(tutar),
            tetikleyici_durum=self.aktif,
            **kapsam,
        )

    def test_aktif_olunca_hakedis_yatar_ve_ucret_kesilir(self):
        self._kural(KuralYonu.TAHSILAT, "25.00", kategori=self.kategori)
        self._kural(KuralYonu.HAKEDIS, "150.00", kategori=self.kategori)

        basvuru = self._basvuru_olustur()
        basvuru.durum = self.aktif
        basvuru.save()

        self.cuzdan.refresh_from_db()
        basvuru.refresh_from_db()

        # 1000 - 25 + 150 = 1125
        self.assertEqual(self.cuzdan.bakiye, TL("1125.00"))
        self.assertEqual(basvuru.tahsil_edilen, TL("25.00"))
        self.assertEqual(basvuru.hakedis, TL("150.00"))
        self.assertTrue(basvuru.para_islendi)

    def test_beklemede_iken_para_islemez(self):
        self._kural(KuralYonu.HAKEDIS, "150.00", kategori=self.kategori)
        self._basvuru_olustur()

        self.cuzdan.refresh_from_db()
        self.assertEqual(self.cuzdan.bakiye, TL("1000.00"))
        self.assertEqual(CuzdanHareketi.objects.count(), 0)

    def test_tekrar_kaydetmek_parayi_iki_kez_islemez(self):
        """Eski sistemdeki çift-işleme hatasının regresyon testi."""
        self._kural(KuralYonu.HAKEDIS, "150.00", kategori=self.kategori)

        basvuru = self._basvuru_olustur()
        basvuru.durum = self.aktif
        basvuru.save()
        basvuru.save()
        basvuru.save()

        # Servisi doğrudan da tekrar çağır
        basvuru_parasini_isle(basvuru)

        self.cuzdan.refresh_from_db()
        self.assertEqual(self.cuzdan.bakiye, TL("1150.00"))
        self.assertEqual(
            CuzdanHareketi.objects.filter(tip=HareketTipi.HAKEDIS).count(), 1
        )

    def test_en_spesifik_kural_kazanir(self):
        self._kural(KuralYonu.HAKEDIS, "100.00", kategori=self.kategori)
        self._kural(KuralYonu.HAKEDIS, "175.00", tarife=self.tarife, kategori=self.kategori)

        basvuru = self._basvuru_olustur()
        basvuru.durum = self.aktif
        basvuru.save()

        basvuru.refresh_from_db()
        self.assertEqual(basvuru.hakedis, TL("175.00"))

    def test_bayiye_ozel_kural_her_seyi_ezer(self):
        self._kural(KuralYonu.HAKEDIS, "100.00", kategori=self.kategori)
        self._kural(KuralYonu.HAKEDIS, "175.00", tarife=self.tarife)
        self._kural(KuralYonu.HAKEDIS, "300.00", bayi=self.bayi)

        basvuru = self._basvuru_olustur()
        basvuru.durum = self.aktif
        basvuru.save()

        basvuru.refresh_from_db()
        self.assertEqual(basvuru.hakedis, TL("300.00"))

    def test_bakiye_yetmezse_kalan_borca_yazilir(self):
        self.cuzdan.bakiye = TL("10.00")
        self.cuzdan.save()

        self._kural(KuralYonu.TAHSILAT, "100.00", kategori=self.kategori)

        basvuru = self._basvuru_olustur()
        basvuru.durum = self.aktif
        basvuru.save()

        self.cuzdan.refresh_from_db()
        # 10 TL bakiyeden, kalan 90 TL borca
        self.assertEqual(self.cuzdan.bakiye, TL("0.00"))
        self.assertEqual(self.cuzdan.borc, TL("90.00"))

    def test_bakiyesi_sifir_olan_bayide_tumu_borca_yazilir(self):
        """Borç için üst sınır yok; işlem her hâlükârda tamamlanır."""
        self.cuzdan.bakiye = TL("0.00")
        self.cuzdan.save()

        self._kural(KuralYonu.TAHSILAT, "500.00", kategori=self.kategori)

        basvuru = self._basvuru_olustur()
        basvuru.durum = self.aktif
        basvuru.save()

        self.cuzdan.refresh_from_db()
        self.assertEqual(self.cuzdan.bakiye, TL("0.00"))
        self.assertEqual(self.cuzdan.borc, TL("500.00"))

    def test_iptal_edilince_para_geri_alinir(self):
        self._kural(KuralYonu.TAHSILAT, "25.00", kategori=self.kategori)
        self._kural(KuralYonu.HAKEDIS, "150.00", kategori=self.kategori)

        basvuru = self._basvuru_olustur()
        basvuru.durum = self.aktif
        basvuru.save()

        self.cuzdan.refresh_from_db()
        self.assertEqual(self.cuzdan.bakiye, TL("1125.00"))

        basvuru.durum = self.iptal
        basvuru.save()

        self.cuzdan.refresh_from_db()
        basvuru.refresh_from_db()
        self.assertEqual(self.cuzdan.bakiye, TL("1000.00"))
        self.assertFalse(basvuru.para_islendi)
        self.assertEqual(basvuru.hakedis, TL("0.00"))


    def test_durum_gecmisi_kaydedilir(self):
        basvuru = self._basvuru_olustur()
        basvuru.durum = self.aktif
        basvuru.save()

        gecmis = basvuru.durum_gecmisi.order_by("id")
        self.assertEqual(gecmis.count(), 2)
        self.assertEqual(gecmis[0].yeni_durum, self.beklemede)
        self.assertEqual(gecmis[1].yeni_durum, self.aktif)


class BakiyeYuklemeTestleri(TestCase):
    def setUp(self):
        self.bayi = User.objects.create_user("bayi2", password="parola123")
        self.cuzdan = Cuzdan.objects.create(bayi=self.bayi)

    def test_borc_varsa_once_borctan_duser(self):
        from apps.finans.services import bakiye_yukle
        from apps.finans.models import Banka

        self.cuzdan.borc = TL("300.00")
        self.cuzdan.save()

        bakiye_yukle(self.cuzdan, TL("500.00"), anahtar="test-1")

        self.cuzdan.refresh_from_db()
        self.assertEqual(self.cuzdan.borc, TL("0.00"))
        self.assertEqual(self.cuzdan.bakiye, TL("200.00"))

    def test_borctan_az_yukleme_bakiyeye_gecmez(self):
        from apps.finans.services import bakiye_yukle

        self.cuzdan.borc = TL("300.00")
        self.cuzdan.save()

        bakiye_yukle(self.cuzdan, TL("100.00"), anahtar="test-2")

        self.cuzdan.refresh_from_db()
        self.assertEqual(self.cuzdan.borc, TL("200.00"))
        self.assertEqual(self.cuzdan.bakiye, TL("0.00"))

    def test_ayni_anahtarla_iki_kez_yukleme_tek_kez_islenir(self):
        from apps.finans.services import bakiye_yukle

        bakiye_yukle(self.cuzdan, TL("250.00"), anahtar="test-3")
        bakiye_yukle(self.cuzdan, TL("250.00"), anahtar="test-3")

        self.cuzdan.refresh_from_db()
        self.assertEqual(self.cuzdan.bakiye, TL("250.00"))

    def test_banka_bakiyesi_de_artar(self):
        from apps.finans.models import Banka
        from apps.finans.services import bakiye_yukle

        banka = Banka.objects.create(
            banka_adi="Ziraat", hesap_sahibi="Aktivasyon Ltd.", iban="TR000000000000000000000000"
        )
        bakiye_yukle(self.cuzdan, TL("1000.00"), banka=banka, anahtar="test-4")

        banka.refresh_from_db()
        self.cuzdan.refresh_from_db()
        self.assertEqual(banka.bakiye, TL("1000.00"))
        self.assertEqual(self.cuzdan.bakiye, TL("1000.00"))

    def test_sifir_veya_negatif_yukleme_reddedilir(self):
        from apps.finans.services import bakiye_yukle

        with self.assertRaises(ValueError):
            bakiye_yukle(self.cuzdan, TL("0.00"))


class TedarikciTestleri(TestCase):
    """İşlemi tedarikçiye satıyoruz; aradaki fark kârımız."""

    def setUp(self):
        from apps.bayi.models import BayiProfili

        self.beklemede = BasvuruDurumu.objects.create(
            ad="Beklemede", slug="beklemede", baslangic_durumu=True
        )
        self.aktif = BasvuruDurumu.objects.create(
            ad="Aktif", slug="aktif", hakedis_tetikler=True
        )
        self.iptal = BasvuruDurumu.objects.create(
            ad="İptal", slug="iptal", olumsuz_sonuc=True
        )

        self.bayi = User.objects.create_user("bayi", password="parola123")
        self.cuzdan = Cuzdan.objects.create(bayi=self.bayi, bakiye=TL("1000.00"))
        BayiProfili.objects.create(kullanici=self.bayi, unvan="Bayi A", bayi_mi=True)

        self.tedarikci = User.objects.create_user("tedarikci", password="parola123")
        self.tedarikci_cuzdan = Cuzdan.objects.create(
            bayi=self.tedarikci, bakiye=TL("5000.00")
        )
        BayiProfili.objects.create(
            kullanici=self.tedarikci, unvan="Tedarikçi X",
            bayi_mi=False, tedarikci_mi=True,
        )

        self.operator = Operator.objects.create(ad="Turkcell")
        self.kategori = BasvuruKategorisi.objects.create(ad="MNT")

    def _basvuru(self, tedarikci=None):
        return Basvuru.objects.create(
            bayi=self.bayi, kategori=self.kategori, operator=self.operator,
            tedarikci=tedarikci, isim="Ayşe", soyisim="Demir",
            kimlik_no="1", irtibat="5551112233", durum=self.beklemede,
        )

    def _kurallari_kur(self):
        UcretKurali.objects.create(
            ad="Bayi hakedişi", yon=KuralYonu.HAKEDIS, tutar=TL("95.00"),
            kategori=self.kategori, tetikleyici_durum=self.aktif,
        )
        UcretKurali.objects.create(
            ad="Tedarikçi X fiyatı", yon=KuralYonu.TEDARIKCI_GELIRI,
            tutar=TL("140.00"), kategori=self.kategori,
            tedarikci=self.tedarikci, tetikleyici_durum=self.aktif,
        )

    def test_aktif_olunca_tedarikciden_tahsil_edilir(self):
        self._kurallari_kur()
        basvuru = self._basvuru(tedarikci=self.tedarikci)
        basvuru.durum = self.aktif
        basvuru.save()

        basvuru.refresh_from_db()
        self.cuzdan.refresh_from_db()
        self.tedarikci_cuzdan.refresh_from_db()

        self.assertEqual(self.cuzdan.bakiye, TL("1095.00"))
        self.assertEqual(self.tedarikci_cuzdan.bakiye, TL("4860.00"))
        self.assertEqual(basvuru.tedarikci_geliri, TL("140.00"))
        self.assertEqual(basvuru.kar, TL("45.00"))

    def test_tedarikci_sonradan_atanabilir(self):
        """İşlem aktifleştikten sonra da satılabilir."""
        self._kurallari_kur()
        basvuru = self._basvuru()
        basvuru.durum = self.aktif
        basvuru.save()

        basvuru.refresh_from_db()
        self.assertEqual(basvuru.tedarikci_geliri, TL("0.00"))
        self.assertEqual(basvuru.kar, TL("-95.00"))

        basvuru.tedarikci = self.tedarikci
        basvuru.save()

        basvuru.refresh_from_db()
        self.tedarikci_cuzdan.refresh_from_db()
        self.assertEqual(basvuru.tedarikci_geliri, TL("140.00"))
        self.assertEqual(basvuru.kar, TL("45.00"))
        self.assertEqual(self.tedarikci_cuzdan.bakiye, TL("4860.00"))

    def test_tedarikci_fiyati_tedarikciye_gore_degisir(self):
        digeri = User.objects.create_user("tedarikci2", password="parola123")
        Cuzdan.objects.create(bayi=digeri, bakiye=TL("5000.00"))
        self._kurallari_kur()
        UcretKurali.objects.create(
            ad="Tedarikçi Y fiyatı", yon=KuralYonu.TEDARIKCI_GELIRI,
            tutar=TL("120.00"), kategori=self.kategori,
            tedarikci=digeri, tetikleyici_durum=self.aktif,
        )

        b1 = self._basvuru(tedarikci=self.tedarikci)
        b1.durum = self.aktif
        b1.save()
        b2 = self._basvuru(tedarikci=digeri)
        b2.durum = self.aktif
        b2.save()

        b1.refresh_from_db()
        b2.refresh_from_db()
        self.assertEqual(b1.tedarikci_geliri, TL("140.00"))
        self.assertEqual(b2.tedarikci_geliri, TL("120.00"))

    def test_tedarikcisiz_basvuruda_tedarikci_kurali_uygulanmaz(self):
        self._kurallari_kur()
        basvuru = self._basvuru()
        basvuru.durum = self.aktif
        basvuru.save()

        basvuru.refresh_from_db()
        self.assertEqual(basvuru.tedarikci_geliri, TL("0.00"))
        self.assertFalse(basvuru.tedarikci_islendi)

    def test_iptalde_tedarikciye_de_iade_edilir(self):
        self._kurallari_kur()
        basvuru = self._basvuru(tedarikci=self.tedarikci)
        basvuru.durum = self.aktif
        basvuru.save()

        basvuru.durum = self.iptal
        basvuru.save()

        basvuru.refresh_from_db()
        self.cuzdan.refresh_from_db()
        self.tedarikci_cuzdan.refresh_from_db()
        self.assertEqual(self.cuzdan.bakiye, TL("1000.00"))
        self.assertEqual(self.tedarikci_cuzdan.bakiye, TL("5000.00"))
        self.assertEqual(basvuru.kar, TL("0.00"))

    def test_tedarikci_bedeli_iki_kez_islenmez(self):
        self._kurallari_kur()
        basvuru = self._basvuru(tedarikci=self.tedarikci)
        basvuru.durum = self.aktif
        basvuru.save()
        basvuru.save()

        from apps.finans.services import tedarikci_bedelini_isle
        tedarikci_bedelini_isle(basvuru)

        self.tedarikci_cuzdan.refresh_from_db()
        self.assertEqual(self.tedarikci_cuzdan.bakiye, TL("4860.00"))

    def test_bir_kullanici_hem_bayi_hem_tedarikci_olabilir(self):
        from apps.bayi.models import BayiProfili

        profil = BayiProfili.objects.get(kullanici=self.bayi)
        profil.tedarikci_mi = True
        profil.save()

        self.assertTrue(profil.bayi_mi)
        self.assertTrue(profil.tedarikci_mi)
        self.assertEqual(profil.rol_adi, "Bayi ve Tedarikçi")
