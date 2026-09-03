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
from apps.finans.services import YetersizBakiye, basvuru_parasini_isle
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

    def test_bakiye_yetmezse_borc_limitinden_karsilanir(self):
        self.cuzdan.bakiye = TL("10.00")
        self.cuzdan.borc_izni = True
        self.cuzdan.borc_limiti = TL("500.00")
        self.cuzdan.save()

        self._kural(KuralYonu.TAHSILAT, "100.00", kategori=self.kategori)

        basvuru = self._basvuru_olustur()
        basvuru.durum = self.aktif
        basvuru.save()

        self.cuzdan.refresh_from_db()
        # 10 TL bakiyeden, kalan 90 TL borca
        self.assertEqual(self.cuzdan.bakiye, TL("0.00"))
        self.assertEqual(self.cuzdan.borc, TL("90.00"))

    def test_borc_limiti_asilirsa_hata_verir(self):
        self.cuzdan.bakiye = TL("10.00")
        self.cuzdan.borc_izni = True
        self.cuzdan.borc_limiti = TL("50.00")
        self.cuzdan.save()

        self._kural(KuralYonu.TAHSILAT, "500.00", kategori=self.kategori)

        basvuru = self._basvuru_olustur()
        basvuru.durum = self.aktif

        with self.assertRaises(YetersizBakiye):
            basvuru.save()

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

    def test_borc_izni_kapaliyken_limit_yok_sayilir(self):
        """Tutar girilmiş olsa bile izin kapalıysa bayi borçlanamaz."""
        self.cuzdan.bakiye = TL("0.00")
        self.cuzdan.borc_izni = False
        self.cuzdan.borc_limiti = TL("5000.00")
        self.cuzdan.save()

        self.assertEqual(self.cuzdan.gecerli_borc_limiti, TL("0.00"))
        self.assertFalse(self.cuzdan.karsilar_mi(TL("1.00")))

    def test_borc_izni_acikken_limit_girilen_tutar_kadardir(self):
        self.cuzdan.bakiye = TL("0.00")
        self.cuzdan.borc_izni = True
        self.cuzdan.borc_limiti = TL("2000.00")
        self.cuzdan.save()

        self.assertEqual(self.cuzdan.gecerli_borc_limiti, TL("2000.00"))
        self.assertTrue(self.cuzdan.karsilar_mi(TL("2000.00")))
        self.assertFalse(self.cuzdan.karsilar_mi(TL("2000.01")))

    def test_yeni_cuzdan_varsayilan_olarak_borclanamaz(self):
        yeni_bayi = User.objects.create_user("bayi3", password="parola123")
        cuzdan = Cuzdan.objects.create(bayi=yeni_bayi)

        self.assertFalse(cuzdan.borc_izni)
        self.assertEqual(cuzdan.gecerli_borc_limiti, TL("0.00"))
        self.assertFalse(cuzdan.karsilar_mi(TL("1.00")))

    def test_yetersiz_bakiye_mesaji_limiti_sizdirmaz(self):
        """Bayiye gösterilen mesaj borç limitini ele vermemeli."""
        self.cuzdan.bakiye = TL("0.00")
        self.cuzdan.borc_izni = True
        self.cuzdan.borc_limiti = TL("50.00")
        self.cuzdan.save()

        self._kural(KuralYonu.TAHSILAT, "500.00", kategori=self.kategori)
        basvuru = self._basvuru_olustur()
        basvuru.durum = self.aktif

        with self.assertRaises(YetersizBakiye) as yakalanan:
            basvuru.save()

        mesaj = str(yakalanan.exception)
        self.assertNotIn("50", mesaj)
        self.assertNotIn("Kullanılabilir", mesaj)
        self.assertIn("Bakiye bu işlem için yeterli değil", mesaj)
        # Ayrıntı yalnızca kayıt/yönetim tarafı için ayrı alanda durur.
        self.assertIn("Kullanılabilir", yakalanan.exception.detay)

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
