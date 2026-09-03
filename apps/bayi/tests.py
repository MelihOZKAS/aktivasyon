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
