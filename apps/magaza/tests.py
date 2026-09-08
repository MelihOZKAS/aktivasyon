"""Mağaza: bakiyeyle ürün alma ve iptalde iade."""

from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from apps.finans.models import Cuzdan, CuzdanHareketi, HareketTipi
from apps.finans.services import SiparisVerilemez, siparis_durumunu_uygula
from apps.magaza.models import Siparis, SiparisDurumu, Urun
from apps.magaza.services import siparis_olustur


class BakiyeyleSatinAlma(TestCase):
    """Ürün bakiyeden alınır, borca yazılmaz.

    Başvuruda borcun üst sınırı yoktur çünkü borç işlenmiş bir işlemin
    sonucudur; burada ise parası olmayana mal verilmiş olurdu.
    """

    def setUp(self):
        self.bayi = User.objects.create_user("5321112233", password="parola12345")
        self.cuzdan = Cuzdan.objects.create(bayi=self.bayi, bakiye=Decimal("1000.00"))
        self.urun = Urun.objects.create(ad="Tabela", fiyat=Decimal("250.00"))
        self.client.force_login(self.bayi)

    def test_siparis_tutari_bakiyeden_duser(self):
        siparis = siparis_olustur(self.bayi, self.urun, 2)

        self.cuzdan.refresh_from_db()
        self.assertEqual(self.cuzdan.bakiye, Decimal("500.00"))
        self.assertEqual(siparis.tutar, Decimal("500.00"))
        self.assertTrue(siparis.para_islendi)

    def test_bakiye_yetmezse_siparis_hic_acilmaz(self):
        self.cuzdan.bakiye = Decimal("100.00")
        self.cuzdan.save()

        with self.assertRaises(SiparisVerilemez):
            siparis_olustur(self.bayi, self.urun, 1)

        self.assertEqual(Siparis.objects.count(), 0)
        self.cuzdan.refresh_from_db()
        self.assertEqual(self.cuzdan.bakiye, Decimal("100.00"))

    def test_borca_yazilmaz(self):
        """Bakiye yetmediğinde borç hanesi de kıpırdamamalı."""
        self.cuzdan.bakiye = Decimal("0.00")
        self.cuzdan.save()

        with self.assertRaises(SiparisVerilemez):
            siparis_olustur(self.bayi, self.urun, 1)

        self.cuzdan.refresh_from_db()
        self.assertEqual(self.cuzdan.borc, Decimal("0.00"))

    def test_islemi_kapali_bayi_siparis_veremez(self):
        self.cuzdan.islem_yapabilir = False
        self.cuzdan.save()

        with self.assertRaises(SiparisVerilemez):
            siparis_olustur(self.bayi, self.urun, 1)

    def test_pasif_urun_siparis_edilemez(self):
        self.urun.aktif = False
        self.urun.save()

        with self.assertRaises(SiparisVerilemez):
            siparis_olustur(self.bayi, self.urun, 1)

    def test_ayni_anahtar_ikinci_kez_para_dusurmez(self):
        """Sayfa yenilenince aynı sipariş ikinci kez açılmaz."""
        ilk = siparis_olustur(self.bayi, self.urun, 1, anahtar="abc")
        ikinci = siparis_olustur(self.bayi, self.urun, 1, anahtar="abc")

        self.assertEqual(ilk.pk, ikinci.pk)
        self.assertEqual(Siparis.objects.count(), 1)
        self.cuzdan.refresh_from_db()
        self.assertEqual(self.cuzdan.bakiye, Decimal("750.00"))

    def test_fiyat_siparis_aninda_kopyalanir(self):
        """Ürünün fiyatı sonra değişse de ödenen tutar kayıtta doğru kalır."""
        siparis = siparis_olustur(self.bayi, self.urun, 1)
        self.urun.fiyat = Decimal("999.00")
        self.urun.save()

        siparis.refresh_from_db()
        self.assertEqual(siparis.birim_fiyat, Decimal("250.00"))
        self.assertEqual(siparis.urun_adi, "Tabela")


class SiparisIptali(TestCase):
    """Para, siparişin iptal edilmemiş olmasına bağlıdır."""

    def setUp(self):
        self.bayi = User.objects.create_user("5321112233", password="parola12345")
        self.cuzdan = Cuzdan.objects.create(bayi=self.bayi, bakiye=Decimal("1000.00"))
        self.urun = Urun.objects.create(ad="Tabela", fiyat=Decimal("250.00"))
        self.siparis = siparis_olustur(self.bayi, self.urun, 1)

    def _durumu_degistir(self, durum):
        self.siparis.durum = durum
        self.siparis.save(update_fields=["durum"])
        siparis_durumunu_uygula(self.siparis)
        self.siparis.refresh_from_db()
        self.cuzdan.refresh_from_db()

    def test_iptal_parayi_geri_verir(self):
        self._durumu_degistir(SiparisDurumu.IPTAL)

        self.assertEqual(self.cuzdan.bakiye, Decimal("1000.00"))
        self.assertFalse(self.siparis.para_islendi)

    def test_iptalde_defter_satiri_silinmez_ters_kayit_yazilir(self):
        self._durumu_degistir(SiparisDurumu.IPTAL)

        self.assertEqual(self.siparis.cuzdan_hareketleri.count(), 2)
        self.assertTrue(
            self.siparis.cuzdan_hareketleri.filter(tip=HareketTipi.IPTAL).exists()
        )

    def test_teslim_paraya_dokunmaz(self):
        self._durumu_degistir(SiparisDurumu.TESLIM)

        self.assertEqual(self.cuzdan.bakiye, Decimal("750.00"))
        self.assertTrue(self.siparis.para_islendi)

    def test_iptalden_cikinca_yeniden_kesilir(self):
        """Yanlış iptalin düzeltmesi de sadece durumu değiştirmektir."""
        self._durumu_degistir(SiparisDurumu.IPTAL)
        self._durumu_degistir(SiparisDurumu.VERILDI)

        self.assertEqual(self.cuzdan.bakiye, Decimal("750.00"))
        self.assertTrue(self.siparis.para_islendi)

    def test_ikinci_kesinti_sessizce_yutulmaz(self):
        """Anahtar sürüm taşımasa ikinci hareket IntegrityError'a takılırdı."""
        self._durumu_degistir(SiparisDurumu.IPTAL)
        self._durumu_degistir(SiparisDurumu.VERILDI)

        self.assertEqual(
            CuzdanHareketi.objects.filter(
                siparis=self.siparis, tip=HareketTipi.SIPARIS
            ).count(),
            2,
        )

    def test_iki_kez_iptal_parayi_iki_kez_iade_etmez(self):
        self._durumu_degistir(SiparisDurumu.IPTAL)
        siparis_durumunu_uygula(self.siparis)
        self.cuzdan.refresh_from_db()

        self.assertEqual(self.cuzdan.bakiye, Decimal("1000.00"))


class MagazaEkranlari(TestCase):
    def setUp(self):
        self.bayi = User.objects.create_user("5321112233", password="parola12345")
        Cuzdan.objects.create(bayi=self.bayi, bakiye=Decimal("1000.00"))
        self.urun = Urun.objects.create(ad="Tabela", fiyat=Decimal("250.00"))
        self.pasif = Urun.objects.create(
            ad="Eski Afiş", fiyat=Decimal("50.00"), aktif=False
        )
        self.client.force_login(self.bayi)

    def test_magazada_yalnizca_aktif_urunler_listelenir(self):
        yanit = self.client.get("/magaza/")

        self.assertContains(yanit, "Tabela")
        self.assertNotContains(yanit, "Eski Afiş")

    def test_pasif_urun_sayfasi_404(self):
        self.assertEqual(self.client.get("/magaza/eski-afis/").status_code, 404)

    def test_satin_alma_siparis_acar(self):
        yanit = self.client.post(
            f"/magaza/{self.urun.slug}/satin-al/", {"adet": "2", "islem_anahtari": "k1"}
        )

        self.assertEqual(yanit.status_code, 302)
        siparis = Siparis.objects.get()
        self.assertEqual(siparis.adet, 2)
        self.assertEqual(siparis.tutar, Decimal("500.00"))

    def test_bakiye_yetmezse_sebebi_yazilir(self):
        yanit = self.client.post(
            f"/magaza/{self.urun.slug}/satin-al/",
            {"adet": "100", "islem_anahtari": "k2"},
            follow=True,
        )

        self.assertEqual(Siparis.objects.count(), 0)
        self.assertContains(yanit, "borca yazılmaz")

    def test_get_ile_satin_alinamaz(self):
        yanit = self.client.get(f"/magaza/{self.urun.slug}/satin-al/")

        self.assertEqual(yanit.status_code, 302)
        self.assertEqual(Siparis.objects.count(), 0)

    def test_bayi_baskasinin_siparisini_gormez(self):
        digeri = User.objects.create_user("5339998877", password="parola12345")
        Cuzdan.objects.create(bayi=digeri, bakiye=Decimal("1000.00"))
        siparis_olustur(digeri, self.urun, 1)

        yanit = self.client.get("/magaza/siparislerim/")

        self.assertContains(yanit, "Henüz sipariş vermedin")

    def test_tedarikci_magazayi_goremez(self):
        from apps.bayi.models import BayiProfili

        BayiProfili.objects.create(
            kullanici=self.bayi, unvan="Tedarik A.Ş.", bayi_mi=False, tedarikci_mi=True
        )

        yanit = self.client.get("/magaza/")

        self.assertEqual(yanit.status_code, 302)

    def test_siparis_telegrama_bildirilir(self):
        from unittest.mock import patch

        with patch("apps.magaza.views.siparis_bildir") as haber:
            self.client.post(
                f"/magaza/{self.urun.slug}/satin-al/",
                {"adet": "1", "islem_anahtari": "k3"},
            )

        haber.assert_called_once()


class SiparisYonetimEkrani(TestCase):
    """Karar hangi yoldan verilirse verilsin para tek servisten geçer."""

    def setUp(self):
        self.yonetici = User.objects.create_superuser("yonetici", password="Panel-2026x")
        self.bayi = User.objects.create_user("5321112233", password="parola12345")
        self.cuzdan = Cuzdan.objects.create(bayi=self.bayi, bakiye=Decimal("1000.00"))
        self.urun = Urun.objects.create(ad="Tabela", fiyat=Decimal("250.00"))
        self.siparis = siparis_olustur(self.bayi, self.urun, 1)
        self.client.force_login(self.yonetici)

    def _adres(self, yol):
        return f"/yonetim/magaza/siparis/{self.siparis.pk}/{yol}/"

    def test_iptal_get_yalnizca_onay_ekrani_acar(self):
        """Düz bağlantı para oynatmamalı: yöneticinin açtığı sayfa yeter."""
        yanit = self.client.get(self._adres("iptal-et"))

        self.assertEqual(yanit.status_code, 200)
        self.cuzdan.refresh_from_db()
        self.assertEqual(self.cuzdan.bakiye, Decimal("750.00"))

    def test_iptal_post_parayi_iade_eder(self):
        self.client.post(self._adres("iptal-et"))

        self.siparis.refresh_from_db()
        self.cuzdan.refresh_from_db()
        self.assertEqual(self.siparis.durum, SiparisDurumu.IPTAL)
        self.assertFalse(self.siparis.para_islendi)
        self.assertEqual(self.cuzdan.bakiye, Decimal("1000.00"))

    def test_teslim_paraya_dokunmaz(self):
        self.client.post(self._adres("teslim-edildi"))

        self.siparis.refresh_from_db()
        self.cuzdan.refresh_from_db()
        self.assertEqual(self.siparis.durum, SiparisDurumu.TESLIM)
        self.assertEqual(self.cuzdan.bakiye, Decimal("750.00"))

    def test_formdan_iptal_de_parayi_iade_eder(self):
        """Durum alanı formda düzenlenebilir; servis orada da çağrılmalı.

        Ödeme bildirimindeki tuzağın aynısı: kayıt iptal görünüp para
        bayide kalsaydı, defterle karşılaştıran olmadıkça fark edilmezdi.
        """
        self.client.post(
            f"/yonetim/magaza/siparis/{self.siparis.pk}/change/",
            {
                "urun": self.urun.pk,
                "durum": SiparisDurumu.IPTAL,
                "yonetim_notu": "Stokta yok",
            },
        )

        self.siparis.refresh_from_db()
        self.cuzdan.refresh_from_db()
        self.assertEqual(self.siparis.durum, SiparisDurumu.IPTAL)
        self.assertEqual(self.cuzdan.bakiye, Decimal("1000.00"))

    def test_iptal_edilmis_siparis_ikinci_kez_iade_etmez(self):
        self.client.post(self._adres("iptal-et"))
        self.client.post(self._adres("iptal-et"))

        self.cuzdan.refresh_from_db()
        self.assertEqual(self.cuzdan.bakiye, Decimal("1000.00"))

    def test_bakiye_yetmezse_siparis_iptalde_kalir(self):
        """İptalden çıkarılan sipariş yeniden kesilir; para yoksa geri döner."""
        self.client.post(self._adres("iptal-et"))
        self.cuzdan.refresh_from_db()
        self.cuzdan.bakiye = Decimal("10.00")
        self.cuzdan.save()

        self.client.post(
            f"/yonetim/magaza/siparis/{self.siparis.pk}/change/",
            {"urun": self.urun.pk, "durum": SiparisDurumu.VERILDI, "yonetim_notu": ""},
        )

        self.siparis.refresh_from_db()
        self.cuzdan.refresh_from_db()
        self.assertEqual(self.siparis.durum, SiparisDurumu.IPTAL)
        self.assertEqual(self.cuzdan.bakiye, Decimal("10.00"))

    def test_teslim_get_ile_isaretlenemez(self):
        """Kaydı değiştiren GET, yöneticinin açtığı sayfadan tetiklenebilirdi.

        Gömülü bir <img> bile siparişi teslim edilmiş yapar, bekleyen iş
        rozetten düşer ve kimse fark etmezdi.
        """
        yanit = self.client.get(self._adres("teslim-edildi"))

        self.assertEqual(yanit.status_code, 302)
        self.siparis.refresh_from_db()
        self.assertEqual(self.siparis.durum, SiparisDurumu.VERILDI)

    def test_teslim_dugmesi_baglanti_degil(self):
        """Listedeki düğme changelist formunu POST'lamalı."""
        yanit = self.client.get("/yonetim/magaza/siparis/")

        self.assertContains(yanit, 'formaction="%s"' % self._adres("teslim-edildi"))
        self.assertNotContains(yanit, 'href="%s"' % self._adres("teslim-edildi"))

    def test_rozet_bekleyen_siparisi_sayar(self):
        from apps.rozetler import bekleyen_siparisler

        self.assertEqual(bekleyen_siparisler(None), "1")
        self.client.post(self._adres("teslim-edildi"))
        self.assertEqual(bekleyen_siparisler(None), "")
