"""Para motoru testleri.

Eski sistemde bakiye mantığı `Bayi_Listesi.save()` içindeydi; aynı kaydı
iki kez kaydetmek parayı iki kez işliyordu. Buradaki testler yeni yapının
bu hatayı yapısal olarak engellediğini doğrular.
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from apps.basvurular.models import Basvuru, BasvuruDurumu
from apps.bayi.models import BayiProfili
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
            operator=self.operator, ad="Süper 20GB"
        )
        self.tarife.kategoriler.add(self.kategori)

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

    def test_yanlis_onay_geri_alinca_para_doner(self):
        """Yanlış başvuru onaylandığında iptal etmek şart değil.

        Durum tetikleyici olmaktan çıktığı an para geri döner; İşlemde'ye
        çekmek de yeter. Yalnızca olumsuz duruma bakıldığı sürece geri alınan
        başvurunun parası bayide kalıyordu.
        """
        islemde = BasvuruDurumu.objects.create(ad="İşlemde", slug="islemde", sira=20)
        self._kural(KuralYonu.TAHSILAT, "25.00", kategori=self.kategori)
        self._kural(KuralYonu.HAKEDIS, "150.00", kategori=self.kategori)

        basvuru = self._basvuru_olustur()
        basvuru.durum = self.aktif
        basvuru.save()

        basvuru.durum = islemde
        basvuru.save()

        self.cuzdan.refresh_from_db()
        basvuru.refresh_from_db()
        self.assertEqual(self.cuzdan.bakiye, TL("1000.00"))
        self.assertFalse(basvuru.para_islendi)
        self.assertEqual(basvuru.hakedis, TL("0.00"))
        # "Sonuçlandı" damgası da kalkar: başvuru yeniden kuyrukta.
        self.assertIsNone(basvuru.sonuclanma_tarihi)

    def test_geri_alinan_basvuru_yeniden_onaylanabilir(self):
        """Düzeltilip yeniden onaylanan başvuruda para gerçekten hareket eder.

        Tekillik anahtarı sürüm içermeseydi ikinci onay defterde sessizce
        yutulur, başvuru "150 hakediş ödendi" derken cüzdanda karşılığı
        olmazdı. Sessiz para tutarsızlığının regresyon testi.
        """
        self._kural(KuralYonu.HAKEDIS, "150.00", kategori=self.kategori)

        basvuru = self._basvuru_olustur()
        for durum in (self.aktif, self.iptal, self.aktif):
            basvuru.durum = durum
            basvuru.save()

        self.cuzdan.refresh_from_db()
        basvuru.refresh_from_db()
        self.assertEqual(self.cuzdan.bakiye, TL("1150.00"))
        self.assertEqual(basvuru.hakedis, TL("150.00"))
        self.assertTrue(basvuru.para_islendi)
        self.assertEqual(
            CuzdanHareketi.objects.filter(tip=HareketTipi.HAKEDIS).count(), 2
        )

    def test_hakedis_once_borcu_kapatir(self):
        """100 borcu olan bayiye 250 hakediş: borç kapanır, 150 bakiyeye geçer."""
        self.cuzdan.bakiye = TL("0.00")
        self.cuzdan.borc = TL("100.00")
        self.cuzdan.save()
        self._kural(KuralYonu.HAKEDIS, "250.00", kategori=self.kategori)

        basvuru = self._basvuru_olustur()
        basvuru.durum = self.aktif
        basvuru.save()

        self.cuzdan.refresh_from_db()
        basvuru.refresh_from_db()
        self.assertEqual(self.cuzdan.borc, TL("0.00"))
        self.assertEqual(self.cuzdan.bakiye, TL("150.00"))
        # Bayinin hakedişi yine 250; borç mahsubu cüzdan tarafındadır.
        self.assertEqual(basvuru.hakedis, TL("250.00"))

    def test_hakedis_borcu_kapatmaya_yetmezse_tamami_borctan_duser(self):
        self.cuzdan.bakiye = TL("0.00")
        self.cuzdan.borc = TL("500.00")
        self.cuzdan.save()
        self._kural(KuralYonu.HAKEDIS, "150.00", kategori=self.kategori)

        basvuru = self._basvuru_olustur()
        basvuru.durum = self.aktif
        basvuru.save()

        self.cuzdan.refresh_from_db()
        self.assertEqual(self.cuzdan.borc, TL("350.00"))
        self.assertEqual(self.cuzdan.bakiye, TL("0.00"))

    def test_borctan_dusulen_hakedis_iptalde_borca_geri_yazilir(self):
        self.cuzdan.bakiye = TL("0.00")
        self.cuzdan.borc = TL("100.00")
        self.cuzdan.save()
        self._kural(KuralYonu.HAKEDIS, "250.00", kategori=self.kategori)

        basvuru = self._basvuru_olustur()
        basvuru.durum = self.aktif
        basvuru.save()
        basvuru.durum = self.iptal
        basvuru.save()

        self.cuzdan.refresh_from_db()
        self.assertEqual(self.cuzdan.borc, TL("100.00"))
        self.assertEqual(self.cuzdan.bakiye, TL("0.00"))

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
            ad="Tedarikçi X fiyatı", yon=KuralYonu.ANA_HAKEDIS,
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
        self.assertEqual(basvuru.ana_hakedis, TL("140.00"))
        self.assertEqual(basvuru.kar, TL("45.00"))

    def test_tedarikci_sonradan_atanabilir(self):
        """İşlem aktifleştikten sonra da satılabilir."""
        self._kurallari_kur()
        basvuru = self._basvuru()
        basvuru.durum = self.aktif
        basvuru.save()

        basvuru.refresh_from_db()
        self.assertEqual(basvuru.ana_hakedis, TL("0.00"))
        self.assertEqual(basvuru.kar, TL("-95.00"))

        basvuru.tedarikci = self.tedarikci
        basvuru.save()

        basvuru.refresh_from_db()
        self.tedarikci_cuzdan.refresh_from_db()
        self.assertEqual(basvuru.ana_hakedis, TL("140.00"))
        self.assertEqual(basvuru.kar, TL("45.00"))
        self.assertEqual(self.tedarikci_cuzdan.bakiye, TL("4860.00"))

    def test_tedarikci_fiyati_tedarikciye_gore_degisir(self):
        digeri = User.objects.create_user("tedarikci2", password="parola123")
        Cuzdan.objects.create(bayi=digeri, bakiye=TL("5000.00"))
        self._kurallari_kur()
        UcretKurali.objects.create(
            ad="Tedarikçi Y fiyatı", yon=KuralYonu.ANA_HAKEDIS,
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
        self.assertEqual(b1.ana_hakedis, TL("140.00"))
        self.assertEqual(b2.ana_hakedis, TL("120.00"))

    def test_tedarikcisiz_basvuruda_tedarikciye_ozel_kural_uygulanmaz(self):
        self._kurallari_kur()
        basvuru = self._basvuru()
        basvuru.durum = self.aktif
        basvuru.save()

        basvuru.refresh_from_db()
        self.assertEqual(basvuru.ana_hakedis, TL("0.00"))
        self.assertFalse(basvuru.ana_hakedis_islendi)

    def test_operatorden_gelen_ana_hakedis_kaydedilir(self):
        """Tedarikçi yoksa tutar operatörden gelir; cüzdan hareketi olmaz
        ama kâr hesabına girer."""
        UcretKurali.objects.create(
            ad="Bayi hakedişi", yon=KuralYonu.HAKEDIS, tutar=TL("95.00"),
            kategori=self.kategori, tetikleyici_durum=self.aktif,
        )
        UcretKurali.objects.create(
            ad="Turkcell ana hakediş", yon=KuralYonu.ANA_HAKEDIS,
            tutar=TL("160.00"), kategori=self.kategori, operator=self.operator,
            tetikleyici_durum=self.aktif,
        )

        basvuru = self._basvuru()
        basvuru.durum = self.aktif
        basvuru.save()

        basvuru.refresh_from_db()
        self.assertEqual(basvuru.ana_hakedis, TL("160.00"))
        self.assertEqual(basvuru.kar, TL("65.00"))
        self.assertEqual(basvuru.ana_hakedis_kaynagi, self.operator.ad)
        # Operatörün cüzdanı yok: hareket yazılmamalı.
        self.assertFalse(
            CuzdanHareketi.objects.filter(
                basvuru=basvuru, tip=HareketTipi.TEDARIKCI_BEDELI
            ).exists()
        )

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

        from apps.finans.services import ana_hakedisi_isle
        ana_hakedisi_isle(basvuru)

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


class KenarDurumTestleri(TestCase):
    """Para motorunun kırılgan olabileceği noktalar."""

    def setUp(self):
        self.beklemede = BasvuruDurumu.objects.create(
            ad="Beklemede", slug="beklemede", baslangic_durumu=True
        )
        self.aktif = BasvuruDurumu.objects.create(
            ad="Aktif", slug="aktif", hakedis_tetikler=True
        )
        self.operator = Operator.objects.create(ad="Turkcell")
        self.kategori = BasvuruKategorisi.objects.create(ad="MNT")

    def _basvuru(self, bayi, tedarikci=None):
        return Basvuru.objects.create(
            bayi=bayi, kategori=self.kategori, operator=self.operator,
            tedarikci=tedarikci, isim="Ayşe", soyisim="Demir",
            kimlik_no="1", irtibat="5551112233", durum=self.beklemede,
        )

    def test_cuzdani_olmayan_bayide_cokmez(self):
        """Elle açılmış bir kullanıcının cüzdanı olmayabilir."""
        cuzdansiz = User.objects.create_user("cuzdansiz", password="parola123")
        self.assertFalse(Cuzdan.objects.filter(bayi=cuzdansiz).exists())

        UcretKurali.objects.create(
            ad="Hakediş", yon=KuralYonu.HAKEDIS, tutar=TL("95.00"),
            kategori=self.kategori, tetikleyici_durum=self.aktif,
        )
        basvuru = self._basvuru(cuzdansiz)
        basvuru.durum = self.aktif
        basvuru.save()

        cuzdan = Cuzdan.objects.get(bayi=cuzdansiz)
        self.assertEqual(cuzdan.bakiye, TL("95.00"))

    def test_ayni_kapsamdaki_kuralda_kazanan_belirli(self):
        """İki kural aynı kapsamda ve önceliktebayse sonuç rastgele olmamalı."""
        eski = UcretKurali.objects.create(
            ad="Eski", yon=KuralYonu.HAKEDIS, tutar=TL("95.00"),
            kategori=self.kategori, tetikleyici_durum=self.aktif,
        )
        yeni = UcretKurali.objects.create(
            ad="Yeni", yon=KuralYonu.HAKEDIS, tutar=TL("120.00"),
            kategori=self.kategori, tetikleyici_durum=self.aktif,
        )
        self.assertGreater(yeni.pk, eski.pk)

        bayi = User.objects.create_user("bayi", password="parola123")
        Cuzdan.objects.create(bayi=bayi)
        basvuru = self._basvuru(bayi)
        basvuru.durum = self.aktif
        basvuru.save()

        # Son eklenen kazanır: sonuç öngörülebilir olmalı.
        basvuru.refresh_from_db()
        self.assertEqual(basvuru.hakedis, TL("120.00"))

    def test_ayni_kullanici_hem_bayi_hem_tedarikci(self):
        """Tek cüzdanda iki hareket: hakediş girer, tedarikçi bedeli çıkar."""
        ikili = User.objects.create_user("ikili", password="parola123")
        cuzdan = Cuzdan.objects.create(bayi=ikili, bakiye=TL("1000.00"))

        UcretKurali.objects.create(
            ad="Hakediş", yon=KuralYonu.HAKEDIS, tutar=TL("100.00"),
            kategori=self.kategori, tetikleyici_durum=self.aktif,
        )
        UcretKurali.objects.create(
            ad="Tedarikçi bedeli", yon=KuralYonu.ANA_HAKEDIS, tutar=TL("130.00"),
            kategori=self.kategori, tedarikci=ikili, tetikleyici_durum=self.aktif,
        )

        basvuru = self._basvuru(ikili, tedarikci=ikili)
        basvuru.durum = self.aktif
        basvuru.save()

        cuzdan.refresh_from_db()
        basvuru.refresh_from_db()
        self.assertEqual(cuzdan.bakiye, TL("970.00"))
        self.assertEqual(basvuru.kar, TL("30.00"))


class TarifeParaEkraniTestleri(TestCase):
    """Bayiye verilen ve operatörden alınan tutar tarifenin sayfasında durur.

    Kural motoru genel kalsın; ama günlük iş "bu tarifede bayiye ne veriyorum,
    ben ne alıyorum" sorusu. İki rakamı ayrı bir ekranda kapsam alanı
    doldurarak aramak gereksizdi.
    """

    def setUp(self):
        self.aktif = BasvuruDurumu.objects.create(
            ad="Aktif", slug="aktif", hakedis_tetikler=True, sira=50
        )
        self.operator = Operator.objects.create(ad="Turkcell")
        self.kategori = BasvuruKategorisi.objects.create(ad="Faturalı Yeni Hat")
        self.tarife = Tarife.objects.create(
            operator=self.operator, ad="Red 20 GB"
        )
        self.tarife.kategoriler.add(self.kategori)

    def test_ad_bos_birakilirsa_kapsamdan_uretilir(self):
        """Tarife sayfasından iki rakam giren yönetici bir de ad uydurmasın."""
        kural = UcretKurali.objects.create(
            yon=KuralYonu.HAKEDIS, tutar=TL("100.00"),
            tarife=self.tarife, tetikleyici_durum=self.aktif,
        )

        # Tarifenin kendi adı kategori ve operatörü de içeriyor; kural
        # listesinde hangi tarifeye ait olduğu tek bakışta okunuyor.
        self.assertEqual(kural.ad, f"{self.tarife} · bayiye ödenen")
        self.assertIn("Red 20 GB", kural.ad)

    def test_verilen_ad_korunur(self):
        kural = UcretKurali.objects.create(
            ad="Özel anlaşma", yon=KuralYonu.HAKEDIS, tutar=TL("100.00"),
            tarife=self.tarife, tetikleyici_durum=self.aktif,
        )

        self.assertEqual(kural.ad, "Özel anlaşma")

    def test_tarife_sayfasi_kari_hesaplar(self):
        UcretKurali.objects.create(
            yon=KuralYonu.HAKEDIS, tutar=TL("100.00"),
            tarife=self.tarife, tetikleyici_durum=self.aktif,
        )
        UcretKurali.objects.create(
            yon=KuralYonu.ANA_HAKEDIS, tutar=TL("150.00"),
            tarife=self.tarife, tetikleyici_durum=self.aktif,
        )
        yonetici = User.objects.create_superuser("yon", "y@x.com", "parola12345")
        self.client.force_login(yonetici)

        yanit = self.client.get(f"/yonetim/katalog/tarife/{self.tarife.pk}/change/")

        self.assertContains(yanit, "Bu tarifenin parası")  # satır içi tablo
        self.assertContains(yanit, "50.00 ₺")  # 150 alış − 100 bayiye = 50 kâr

    def test_tedarikci_alisi_panelden_girilebilir(self):
        """Motor tedarikçi kapsamını destekliyordu ama formda alan yoktu."""
        from apps.finans.admin import TarifeParaKuraliInline

        self.assertIn("tedarikci", TarifeParaKuraliInline.fields)

        yonetici = User.objects.create_superuser("yon3", "y3@x.com", "parola12345")
        self.client.force_login(yonetici)
        yanit = self.client.get("/yonetim/finans/ucretkurali/add/")

        self.assertContains(yanit, "tedarikci")

    def test_ozet_alis_kaynagini_ayirir(self):
        """Operatörden ve tedarikçiden alış ayrı satır; kâr ikisi için ayrı."""
        tedarikci = User.objects.create_user("tedarikci1", password="parola12345")
        BayiProfili.objects.create(
            kullanici=tedarikci, unvan="Ege Tedarik", tedarikci_mi=True
        )
        UcretKurali.objects.create(
            yon=KuralYonu.HAKEDIS, tutar=TL("100.00"),
            tarife=self.tarife, tetikleyici_durum=self.aktif,
        )
        UcretKurali.objects.create(
            yon=KuralYonu.ANA_HAKEDIS, tutar=TL("150.00"),
            tarife=self.tarife, tetikleyici_durum=self.aktif,
        )
        UcretKurali.objects.create(
            yon=KuralYonu.ANA_HAKEDIS, tutar=TL("140.00"), tedarikci=tedarikci,
            tarife=self.tarife, tetikleyici_durum=self.aktif,
        )
        yonetici = User.objects.create_superuser("yon4", "y4@x.com", "parola12345")
        self.client.force_login(yonetici)

        yanit = self.client.get(f"/yonetim/katalog/tarife/{self.tarife.pk}/change/")

        self.assertContains(yanit, "Turkcell")      # operatörden alış satırı
        self.assertContains(yanit, "Ege Tedarik")   # tedarikçiden alış satırı
        self.assertContains(yanit, "50.00 ₺")       # 150 − 100
        self.assertContains(yanit, "40.00 ₺")       # 140 − 100

    def test_kural_yokken_ne_yapilacagi_yazar(self):
        yonetici = User.objects.create_superuser("yon2", "y2@x.com", "parola12345")
        self.client.force_login(yonetici)

        yanit = self.client.get(f"/yonetim/katalog/tarife/{self.tarife.pk}/change/")

        self.assertContains(yanit, "Henüz fiyat girilmedi")


class CuzdanIslemEkrani(TestCase):
    """Yönetici cüzdana elle üç türlü işlem yapabilir.

    Üçü de para ekler; farkları paranın hangi haneye yazıldığı. Hepsinde
    kimin yaptığı defterde durur.
    """

    def setUp(self):
        from django.contrib.auth.models import User

        self.bayi = User.objects.create_user("5551112233", password="parola12345")
        self.cuzdan = Cuzdan.objects.create(bayi=self.bayi)
        self.yonetici = User.objects.create_superuser("yonetici", password="Panel-2026x")
        self.client.force_login(self.yonetici)

    def _adres(self):
        from django.urls import reverse

        return reverse("admin:finans_cuzdan_bakiye_yukle", args=[self.cuzdan.pk])

    def _uygula(self, tip, tutar, anahtar="t1"):
        return self.client.post(
            self._adres(),
            {"tip": tip, "tutar": tutar, "banka": "", "aciklama": "",
             "islem_anahtari": anahtar},
            follow=True,
        )

    def test_kredi_hem_borc_hem_bakiye_ekler(self):
        from apps.finans.models import CuzdanIslemi

        self._uygula(CuzdanIslemi.KREDI, "5000.00")
        self.cuzdan.refresh_from_db()

        self.assertEqual(self.cuzdan.bakiye, TL("5000.00"))
        self.assertEqual(self.cuzdan.borc, TL("5000.00"))

    def test_sadece_borc_arttirilir(self):
        from apps.finans.models import CuzdanIslemi

        self._uygula(CuzdanIslemi.BORC, "1200.00")
        self.cuzdan.refresh_from_db()

        self.assertEqual(self.cuzdan.borc, TL("1200.00"))
        self.assertEqual(self.cuzdan.bakiye, TL("0.00"))

    def test_tahsilat_once_borcu_kapatir_kalani_bakiyeye_yazar(self):
        """600 borcu olana 1000 girilince borç sıfırlanır, bakiyeye 400 yazılır."""
        from apps.finans.models import CuzdanIslemi

        self.cuzdan.borc = TL("600.00")
        self.cuzdan.save(update_fields=["borc"])

        self._uygula(CuzdanIslemi.TAHSILAT, "1000.00")
        self.cuzdan.refresh_from_db()

        self.assertEqual(self.cuzdan.borc, TL("0.00"))
        self.assertEqual(self.cuzdan.bakiye, TL("400.00"))

    def test_borctan_az_tahsilat_yalnizca_borcu_dusurur(self):
        """5000 borcu olana 3000 girilince borç 2000'e iner, bakiye değişmez."""
        from apps.finans.models import CuzdanIslemi

        self.cuzdan.borc = TL("5000.00")
        self.cuzdan.save(update_fields=["borc"])

        self._uygula(CuzdanIslemi.TAHSILAT, "3000.00")
        self.cuzdan.refresh_from_db()

        self.assertEqual(self.cuzdan.borc, TL("2000.00"))
        self.assertEqual(self.cuzdan.bakiye, TL("0.00"))

    def test_islemi_kimin_yaptigi_defterde_durur(self):
        from apps.finans.models import CuzdanIslemi

        self._uygula(CuzdanIslemi.KREDI, "1000.00")

        yapanlar = set(
            CuzdanHareketi.objects.filter(cuzdan=self.cuzdan)
            .values_list("olusturan__username", flat=True)
        )
        self.assertEqual(yapanlar, {"yonetici"})

    def test_sayfa_yenilemek_islemi_ikinci_kez_yazmaz(self):
        """Anahtar formda taşınır; aynı gönderim iki kez işlenmez."""
        from apps.finans.models import CuzdanIslemi

        self._uygula(CuzdanIslemi.BORC, "500.00", anahtar="ayni")
        self._uygula(CuzdanIslemi.BORC, "500.00", anahtar="ayni")
        self.cuzdan.refresh_from_db()

        self.assertEqual(self.cuzdan.borc, TL("500.00"))

    def test_tutar_alani_gorunur_bir_girdi_olarak_cizilir(self):
        """Alan hep vardı ama sınıfsız çizildiği için görünmüyordu.

        unfold'un CSS'inde sınıfsız girdinin kenarlığı ve zemini yok; beyaz
        üstünde beyaz kalıyor ve yönetici tutarı nereye yazacağını bulamıyordu.
        """
        import re

        icerik = self.client.get(self._adres()).content.decode()
        girdi = re.search(r'<input[^>]*name="tutar"[^>]*>', icerik).group(0)

        self.assertIn("border-base-200", girdi)
        self.assertIn("rounded-default", girdi)

    def test_ucu_de_ayni_tutar_alanini_kullanir(self):
        """Tutar tek alandır; üç işlem de onu okur."""
        icerik = self.client.get(self._adres()).content.decode()

        self.assertEqual(icerik.count('name="tip"'), 3)
        self.assertEqual(icerik.count('name="tutar"'), 1)

    def test_kredide_banka_kaydedilmez(self):
        """Kredide kasaya para girmiyor; yazılan hesap yanıltıcı olurdu."""
        from apps.finans.models import Banka, CuzdanIslemi

        banka = Banka.objects.create(
            banka_adi="Ziraat", hesap_sahibi="Firma", iban="TR000000000000000000000001"
        )
        self.client.post(
            self._adres(),
            {"tip": CuzdanIslemi.KREDI, "tutar": "1000.00", "banka": banka.pk,
             "aciklama": "", "islem_anahtari": "k1"},
            follow=True,
        )

        banka.refresh_from_db()
        self.assertEqual(banka.bakiye, TL("0.00"))
        self.assertFalse(
            CuzdanHareketi.objects.filter(cuzdan=self.cuzdan, banka__isnull=False).exists()
        )

    def test_tahsilatta_banka_bakiyesi_artar(self):
        from apps.finans.models import Banka, CuzdanIslemi

        banka = Banka.objects.create(
            banka_adi="Ziraat", hesap_sahibi="Firma", iban="TR000000000000000000000002"
        )
        self.client.post(
            self._adres(),
            {"tip": CuzdanIslemi.TAHSILAT, "tutar": "1000.00", "banka": banka.pk,
             "aciklama": "", "islem_anahtari": "t9"},
            follow=True,
        )

        banka.refresh_from_db()
        self.assertEqual(banka.bakiye, TL("1000.00"))

    def test_kullanici_listesinden_cuzdan_islemine_gidilir(self):
        from django.urls import reverse

        yanit = self.client.get(
            reverse("admin:auth_user_cuzdan_islemi", args=[self.bayi.pk])
        )

        self.assertEqual(yanit.status_code, 302)
        self.assertIn(self._adres(), yanit["Location"])

    def test_cuzdani_olmayan_kullanicida_da_acilir(self):
        from django.contrib.auth.models import User

        from django.urls import reverse

        cuzdansiz = User.objects.create_user("5559998877", password="parola12345")

        yanit = self.client.get(
            reverse("admin:auth_user_cuzdan_islemi", args=[cuzdansiz.pk])
        )

        self.assertEqual(yanit.status_code, 302)
        self.assertTrue(Cuzdan.objects.filter(bayi=cuzdansiz).exists())
