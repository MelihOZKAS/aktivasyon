"""Bayi panelinin gizlilik kuralları.

Borç limiti bayiye hiçbir ekranda gösterilmez. "Kullanılabilir tutar" da
gösterilmez: bakiyeden farkı limiti ele verir. "Borç" satırı yalnızca
gerçekten borç varsa görünür.
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.finans.models import Cuzdan

TL = Decimal

BAYI_SAYFALARI = ["bayi:panel", "bayi:cuzdan"]


class BorcGizliligiTestleri(TestCase):
    def setUp(self):
        self.bayi = User.objects.create_user("bayi", password="parola12345")
        self.cuzdan = Cuzdan.objects.create(bayi=self.bayi, bakiye=TL("8660.00"))
        self.client.force_login(self.bayi)

    def _sayfalar(self):
        return {ad: self.client.get(reverse(ad)).content.decode() for ad in BAYI_SAYFALARI}

    def test_borc_limiti_kavrami_kalmadi(self):
        for ad, icerik in self._sayfalar().items():
            self.assertNotIn("Borç limiti", icerik, ad)
            self.assertNotIn("Kullanılabilir", icerik, ad)

    def test_borc_yokken_borc_yazisi_gorunmez(self):
        for ad, icerik in self._sayfalar().items():
            self.assertNotIn("Borç", icerik, ad)

    def test_borc_varken_borc_gorunur(self):
        self.cuzdan.borc = TL("340.00")
        self.cuzdan.save()

        for ad, icerik in self._sayfalar().items():
            self.assertIn("Borç", icerik, ad)
            self.assertIn("340,00", icerik, ad)

    def test_bakiye_gosterilir(self):
        for ad, icerik in self._sayfalar().items():
            self.assertIn("8.660,00", icerik, ad)



class GirisVeYetkiTestleri(TestCase):
    """Tek giriş kapısı ve yönetim yetkisi.

    Bayi ve yönetici aynı ekrandan girer; yönetim işlemlerini yalnızca
    yetkili kullanıcı yapabilir.
    """

    def setUp(self):
        self.bayi = User.objects.create_user("bayi", password="parola12345")
        Cuzdan.objects.create(bayi=self.bayi)
        self.yonetici = User.objects.create_superuser(
            "yonetici", "yonetici@ornek.com", "parola12345"
        )

    def test_bayi_girisi_panele_gider(self):
        yanit = self.client.post(
            reverse("bayi:giris"), {"username": "bayi", "password": "parola12345"}
        )
        self.assertRedirects(yanit, reverse("bayi:panel"))

    def test_yonetici_girisi_yonetim_paneline_gider(self):
        yanit = self.client.post(
            reverse("bayi:giris"), {"username": "yonetici", "password": "parola12345"}
        )
        self.assertRedirects(yanit, reverse("admin:index"))

    def test_admin_giris_formu_tek_kapiya_yonlendirir(self):
        yanit = self.client.get("/yonetim/login/")
        self.assertEqual(yanit.status_code, 302)
        self.assertIn(reverse("bayi:giris"), yanit["Location"])

    def test_bayi_yonetim_paneline_giremez(self):
        self.client.force_login(self.bayi)
        yanit = self.client.get("/yonetim/", follow=True)
        self.assertRedirects(yanit, reverse("bayi:panel"))
        self.assertContains(yanit, "erişim yetkin yok")

    def test_bayi_yonetim_sayfalarinda_dongude_kalmaz(self):
        """Yetkisiz bayi giriş ekranı ile yönetim arasında sonsuz döngüye girmemeli."""
        self.client.force_login(self.bayi)
        yanit = self.client.get("/yonetim/katalog/basvurukategorisi/", follow=True)
        self.assertEqual(yanit.status_code, 200)
        self.assertEqual(yanit.redirect_chain[-1][0], reverse("bayi:panel"))

    def test_bayi_kategori_ekleyemez(self):
        from apps.katalog.models import BasvuruKategorisi

        self.client.force_login(self.bayi)
        yanit = self.client.post(
            "/yonetim/katalog/basvurukategorisi/add/",
            {"ad": "Korsan Kategori", "slug": "korsan", "musteri_tipi": "hepsi", "sira": 0},
            follow=True,
        )
        self.assertFalse(BasvuruKategorisi.objects.filter(ad="Korsan Kategori").exists())
        self.assertEqual(yanit.redirect_chain[-1][0], reverse("bayi:panel"))

    def test_bayi_ucret_kurali_ekleyemez(self):
        from apps.finans.models import UcretKurali

        self.client.force_login(self.bayi)
        self.client.post(
            "/yonetim/finans/ucretkurali/add/",
            {"ad": "Bedava para", "yon": "hakedis", "tutar": "9999", "oncelik": 0},
            follow=True,
        )
        self.assertFalse(UcretKurali.objects.filter(ad="Bedava para").exists())

    def test_bayi_kendi_cuzdanini_duzenleyemez(self):
        self.client.force_login(self.bayi)
        cuzdan = Cuzdan.objects.get(bayi=self.bayi)
        self.client.post(
            f"/yonetim/finans/cuzdan/{cuzdan.pk}/change/",
            {"bayi": self.bayi.pk, "bakiye": "999999", "borc": "0"},
            follow=True,
        )
        cuzdan.refresh_from_db()
        self.assertEqual(cuzdan.bakiye, TL("0.00"))

    def test_disa_yonlendirme_engellenir(self):
        """`next` dışarıdan gelir; başka bir siteye yönlendirilemez."""
        self.client.force_login(self.yonetici)

        for kotucul in [
            "https://kotu-site.example/calinti",
            "//kotu-site.example/calinti",
            "http://kotu-site.example",
            "javascript:alert(1)",
        ]:
            yanit = self.client.get("/yonetim/login/", {"next": kotucul})
            self.assertEqual(yanit["Location"], reverse("admin:index"), kotucul)

    def test_kendi_sunucumuzdaki_hedef_korunur(self):
        self.client.force_login(self.yonetici)
        yanit = self.client.get("/yonetim/login/", {"next": "/yonetim/katalog/tarife/"})
        self.assertEqual(yanit["Location"], "/yonetim/katalog/tarife/")

    def test_yonetici_yonetim_paneline_erisir(self):
        self.client.force_login(self.yonetici)
        for yol in [
            "/yonetim/",
            "/yonetim/katalog/basvurukategorisi/",
            "/yonetim/finans/ucretkurali/",
        ]:
            self.assertEqual(self.client.get(yol).status_code, 200, yol)


class SimKartTestleri(TestCase):
    """Bayi yalnızca kendisine zimmetli SIM kartlarla işlem yapabilir."""

    def setUp(self):
        from apps.bayi.models import SimKart, SimKartDurumu
        from apps.basvurular.models import BasvuruDurumu
        from apps.katalog.models import AlanTipi, BasvuruKategorisi, KategoriAlani, Operator

        BasvuruDurumu.objects.create(ad="Beklemede", slug="beklemede", baslangic_durumu=True)
        self.bayi = User.objects.create_user("bayi", password="parola12345")
        self.digeri = User.objects.create_user("digeri", password="parola12345")
        for k in (self.bayi, self.digeri):
            Cuzdan.objects.create(bayi=k)

        self.operator = Operator.objects.create(ad="Vodafone")
        self.kategori = BasvuruKategorisi.objects.create(
            ad="Kontörlü Yeni Hat", tarife_zorunlu=False
        )
        self.kategori.operatorler.add(self.operator)
        KategoriAlani.objects.create(
            kategori=self.kategori, kod="sim", etiket="SIM Kart",
            tip=AlanTipi.SIM_KART, zorunlu=True, sira=10,
        )

        self.benim = SimKart.objects.create(
            imei="8990011223344551", operator=self.operator,
            bayi=self.bayi, durum=SimKartDurumu.ATANDI,
        )
        self.baskasinin = SimKart.objects.create(
            imei="8990011223344552", operator=self.operator,
            bayi=self.digeri, durum=SimKartDurumu.ATANDI,
        )
        self.sahipsiz = SimKart.objects.create(
            imei="8990011223344553", operator=self.operator,
            durum=SimKartDurumu.BEKLEMEDE,
        )
        self.client.force_login(self.bayi)

    def _url(self):
        return reverse("basvurular:yeni", args=[self.kategori.slug])

    def _gonderi(self, imei):
        return {
            "operator": self.operator.pk, "tarife": "", "kampanya": "",
            "musteri_tipi": "turk", "bayi_aciklamasi": "", "alan__sim": imei,
        }

    def test_kendi_simiyle_basvuru_girebilir(self):
        from apps.basvurular.models import Basvuru
        from apps.bayi.models import SimKartDurumu

        yanit = self.client.post(self._url(), self._gonderi(self.benim.imei))
        self.assertEqual(yanit.status_code, 302)

        basvuru = Basvuru.objects.get()
        self.benim.refresh_from_db()
        self.assertEqual(self.benim.durum, SimKartDurumu.KULLANILDI)
        self.assertEqual(self.benim.basvuru, basvuru)

    def test_baskasinin_simiyle_giremez(self):
        from apps.basvurular.models import Basvuru

        yanit = self.client.post(self._url(), self._gonderi(self.baskasinin.imei))
        self.assertEqual(yanit.status_code, 200)
        self.assertIn("alan__sim", yanit.context["form"].errors)
        self.assertEqual(Basvuru.objects.count(), 0)

    def test_sahipsiz_simle_giremez(self):
        yanit = self.client.post(self._url(), self._gonderi(self.sahipsiz.imei))
        self.assertIn("alan__sim", yanit.context["form"].errors)

    def test_kayitli_olmayan_imei_reddedilir(self):
        yanit = self.client.post(self._url(), self._gonderi("0000000000000000"))
        self.assertIn("alan__sim", yanit.context["form"].errors)

    def test_kullanilmis_sim_tekrar_kullanilamaz(self):
        self.client.post(self._url(), self._gonderi(self.benim.imei))
        yanit = self.client.post(self._url(), self._gonderi(self.benim.imei))
        self.assertIn("alan__sim", yanit.context["form"].errors)

    def test_bayiye_atama_durumu_gunceller(self):
        from apps.bayi.models import SimKartDurumu

        self.sahipsiz.bayi = self.bayi
        self.sahipsiz.save()
        self.assertEqual(self.sahipsiz.durum, SimKartDurumu.ATANDI)

    def test_bayiden_geri_alinca_beklemeye_doner(self):
        from apps.bayi.models import SimKartDurumu

        self.benim.bayi = None
        self.benim.save()
        self.assertEqual(self.benim.durum, SimKartDurumu.BEKLEMEDE)

    def test_yonetici_toplu_zimmetleyebilir(self):
        from apps.bayi.models import SimKart, SimKartDurumu

        yonetici = User.objects.create_superuser("yon", "y@x.com", "parola12345")
        self.client.force_login(yonetici)

        self.client.post(
            "/yonetim/bayi/simkart/",
            {
                "action": "bayiye_ata",
                "_selected_action": [self.sahipsiz.pk],
                "uygula": "1",
                "bayi": self.bayi.pk,
            },
            follow=True,
        )
        self.sahipsiz.refresh_from_db()
        self.assertEqual(self.sahipsiz.bayi, self.bayi)
        self.assertEqual(self.sahipsiz.durum, SimKartDurumu.ATANDI)

    def test_kullanilmis_sim_baska_bayiye_devredilmez(self):
        from apps.bayi.models import SimKartDurumu

        self.client.post(self._url(), self._gonderi(self.benim.imei))

        yonetici = User.objects.create_superuser("yon2", "y2@x.com", "parola12345")
        self.client.force_login(yonetici)
        self.client.post(
            "/yonetim/bayi/simkart/",
            {
                "action": "bayiye_ata",
                "_selected_action": [self.benim.pk],
                "uygula": "1",
                "bayi": self.digeri.pk,
            },
            follow=True,
        )
        self.benim.refresh_from_db()
        self.assertEqual(self.benim.bayi, self.bayi)
        self.assertEqual(self.benim.durum, SimKartDurumu.KULLANILDI)

    def test_basvuru_iptal_olunca_sim_stoga_doner(self):
        """Operatörden iptal gelirse kart çöp olmamalı, yeniden kullanılabilmeli."""
        from apps.basvurular.models import Basvuru, BasvuruDurumu
        from apps.bayi.models import SimKartDurumu

        self.client.post(self._url(), self._gonderi(self.benim.imei))
        self.benim.refresh_from_db()
        self.assertEqual(self.benim.durum, SimKartDurumu.KULLANILDI)

        iptal = BasvuruDurumu.objects.create(
            ad="İptal", slug="iptal", olumsuz_sonuc=True, sira=70
        )
        basvuru = Basvuru.objects.get()
        basvuru.durum = iptal
        basvuru.save()

        self.benim.refresh_from_db()
        self.assertEqual(self.benim.durum, SimKartDurumu.ATANDI)
        self.assertEqual(self.benim.bayi, self.bayi)

    def test_stoga_donen_sim_yeniden_kullanilabilir(self):
        from apps.basvurular.models import Basvuru, BasvuruDurumu

        self.client.post(self._url(), self._gonderi(self.benim.imei))
        iptal = BasvuruDurumu.objects.create(
            ad="İptal", slug="iptal", olumsuz_sonuc=True, sira=70
        )
        ilk = Basvuru.objects.get()
        ilk.durum = iptal
        ilk.save()

        yanit = self.client.post(self._url(), self._gonderi(self.benim.imei))
        self.assertEqual(yanit.status_code, 302)
        self.assertEqual(Basvuru.objects.count(), 2)


class BayiBasvuruFormuTestleri(TestCase):
    """Kamuya açık bayi başvuru formu."""

    def setUp(self):
        from apps.bayi.models import BayiBasvurusu

        self.model = BayiBasvurusu
        self.url = reverse("bayi:bayi-basvurusu")

    def _veri(self, **degisiklik):
        veri = {"isim": "Melih", "soyisim": "Kaya", "irtibat": "5321234567", "website": ""}
        veri.update(degisiklik)
        return veri

    def test_giris_yapmadan_erisilebilir(self):
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_basvuru_kaydedilir(self):
        yanit = self.client.post(self.url, self._veri())
        self.assertEqual(yanit.status_code, 200)
        self.assertContains(yanit, "Başvurunuz alındı")

        basvuru = self.model.objects.get()
        self.assertEqual(basvuru.ad_soyad, "Melih Kaya")
        self.assertEqual(basvuru.irtibat, "5321234567")
        self.assertEqual(basvuru.durum, "yeni")

    def test_basindaki_sifir_temizlenir(self):
        self.client.post(self.url, self._veri(irtibat="0532 123 45 67"))
        self.assertEqual(self.model.objects.get().irtibat, "5321234567")

    def test_gecersiz_telefon_reddedilir(self):
        for kotu in ["123", "02121234567", "abcdefghij"]:
            yanit = self.client.post(self.url, self._veri(irtibat=kotu))
            self.assertContains(yanit, "10 hane girin")
        self.assertEqual(self.model.objects.count(), 0)

    def test_zorunlu_alanlar_bos_birakilamaz(self):
        yanit = self.client.post(self.url, self._veri(isim="", soyisim=""))
        self.assertEqual(self.model.objects.count(), 0)
        self.assertContains(yanit, "Bu alan zorunludur")

    def test_bot_tuzagi_kaydi_engeller(self):
        """Tuzak alan doluysa kayıt açılmaz ama bot bunu anlamaz."""
        yanit = self.client.post(self.url, self._veri(website="http://spam.example"))
        self.assertContains(yanit, "Başvurunuz alındı")
        self.assertEqual(self.model.objects.count(), 0)

    def test_yeni_basvuruda_telegram_bildirimi_gider(self):
        from unittest.mock import patch
        from apps.bildirim import telegram

        with self.settings(
            TELEGRAM_BOT_TOKEN="x:y", TELEGRAM_SOHBET_ID="@g", TELEGRAM_ARKA_PLAN=False
        ):
            with patch.object(telegram, "_gonder") as sahte:
                with self.captureOnCommitCallbacks(execute=True):
                    self.client.post(self.url, self._veri())
        sahte.assert_called_once()
        self.assertIn("Yeni bayi başvurusu", sahte.call_args[0][0])

    def test_bayi_giris_ekraninda_baglanti_var(self):
        yanit = self.client.get(reverse("bayi:giris"))
        self.assertContains(yanit, self.url)


class TarifeSayfasiTestleri(TestCase):
    """Bayinin göreceği tarife kataloğu."""

    def setUp(self):
        from apps.katalog.models import BasvuruKategorisi, Kampanya, Operator, Tarife

        self.bayi = User.objects.create_user("bayi", password="parola12345")
        Cuzdan.objects.create(bayi=self.bayi)
        self.operator = Operator.objects.create(ad="Turkcell", renk="#ffc900")
        self.kategori = BasvuruKategorisi.objects.create(ad="Faturalı Yeni Hat")
        self.tarife = Tarife.objects.create(
            kategori=self.kategori, operator=self.operator,
            ad="Platinum 30 GB", aciklama="Aylık 30 GB, sınırsız konuşma.",
        )
        self.kampanya = Kampanya.objects.create(
            tarife=self.tarife, ad="İlk 3 ay yarı fiyat", aciklama="Yeni müşterilere."
        )
        self.url = reverse("bayi:tarifeler")
        self.client.force_login(self.bayi)

    def test_giris_gerekir(self):
        self.client.logout()
        yanit = self.client.get(self.url)
        self.assertEqual(yanit.status_code, 302)
        self.assertIn("/giris-yap/", yanit["Location"])

    def test_tarife_ve_aciklama_gorunur(self):
        yanit = self.client.get(self.url)
        self.assertContains(yanit, "Platinum 30 GB")
        self.assertContains(yanit, "Aylık 30 GB")
        self.assertContains(yanit, "Turkcell")

    def test_gecerli_kampanya_gorunur(self):
        yanit = self.client.get(self.url)
        self.assertContains(yanit, "İlk 3 ay yarı fiyat")

    def test_suresi_gecmis_kampanya_gorunmez(self):
        import datetime

        self.kampanya.bitis_tarihi = datetime.date(2020, 1, 1)
        self.kampanya.save()
        self.assertNotContains(self.client.get(self.url), "İlk 3 ay yarı fiyat")

    def test_pasif_tarife_gorunmez(self):
        self.tarife.aktif = False
        self.tarife.save()
        self.assertNotContains(self.client.get(self.url), "Platinum 30 GB")

    def test_operator_sekmesiyle_filtrelenir(self):
        """Bayi önce operatörü seçiyor; sekmeler ona göre."""
        from apps.katalog.models import Operator, Tarife

        vodafone = Operator.objects.create(ad="Vodafone", renk="#e60000", sira=20)
        Tarife.objects.create(
            kategori=self.kategori, operator=vodafone, ad="Red 20 GB"
        )

        yanit = self.client.get(self.url, {"operator": vodafone.slug})
        self.assertContains(yanit, "Red 20 GB")
        self.assertNotContains(yanit, "Platinum 30 GB")

    def test_kategori_satirda_rozet_olarak_gorunur(self):
        """Operatör sekmede seçili olduğu için satırda kategori gösterilir."""
        yanit = self.client.get(self.url)
        self.assertContains(yanit, "Faturalı Yeni Hat")

    def test_tarifesiz_operator_sekmede_cikmaz(self):
        from apps.katalog.models import Operator

        Operator.objects.create(ad="Netgsm", sira=99)
        self.assertNotContains(self.client.get(self.url), "Netgsm")
