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
        self.cuzdan = Cuzdan.objects.create(
            bayi=self.bayi,
            bakiye=TL("8660.00"),
            borc_izni=True,
            borc_limiti=TL("2500.00"),
        )
        self.client.force_login(self.bayi)

    def _sayfalar(self):
        return {ad: self.client.get(reverse(ad)).content.decode() for ad in BAYI_SAYFALARI}

    def test_borc_limiti_hicbir_sayfada_gorunmez(self):
        for ad, icerik in self._sayfalar().items():
            self.assertNotIn("Borç limiti", icerik, ad)
            self.assertNotIn("2.500", icerik, ad)
            self.assertNotIn("2500", icerik, ad)

    def test_kullanilabilir_tutar_gosterilmez(self):
        """Bakiyeden farkı limiti ele verdiği için bu değer de gizlidir."""
        for ad, icerik in self._sayfalar().items():
            self.assertNotIn("Kullanılabilir", icerik, ad)
            self.assertNotIn("11.160", icerik, ad)

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

    def test_borc_izni_kapali_bayide_de_limit_sizmaz(self):
        self.cuzdan.borc_izni = False
        self.cuzdan.save()

        for ad, icerik in self._sayfalar().items():
            self.assertNotIn("Borç limiti", icerik, ad)
            self.assertNotIn("Borç", icerik, ad)


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
            {"bayi": self.bayi.pk, "bakiye": "999999", "borc": "0",
             "borc_izni": "on", "borc_limiti": "999999"},
            follow=True,
        )
        cuzdan.refresh_from_db()
        self.assertEqual(cuzdan.bakiye, TL("0.00"))
        self.assertFalse(cuzdan.borc_izni)

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
