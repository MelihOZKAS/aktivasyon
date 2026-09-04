"""Katalog davranışı: operatör görünürlüğü ve dosya temizliği."""

import io
import os
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from apps.katalog.models import BasvuruKategorisi, Kampanya, Operator, Tarife

GECICI_MEDYA = tempfile.mkdtemp(prefix="katalog-test-")


def gorsel(ad="tarife.png"):
    tampon = io.BytesIO()
    Image.new("RGB", (40, 30), "white").save(tampon, format="PNG")
    return SimpleUploadedFile(ad, tampon.getvalue(), content_type="image/png")


class OperatorGorunurlugu(TestCase):
    """Kategoride tarifesi olan operatör formda görünmeli."""

    def setUp(self):
        self.kategori = BasvuruKategorisi.objects.create(ad="MNT")
        self.bagli = Operator.objects.create(ad="Turkcell")
        self.kategori.operatorler.add(self.bagli)
        self.tarifeli = Operator.objects.create(ad="Yeni Telekom")

    def test_kategoriye_bagli_operator_gorunur(self):
        self.assertIn(self.bagli, self.kategori.gecerli_operatorler())

    def test_tarifesi_olan_operator_bagli_olmasa_da_gorunur(self):
        """Tarife tanımlayıp operatörü listeye eklemeyi unutmak tuzaktı."""
        self.assertNotIn(self.tarifeli, self.kategori.gecerli_operatorler())

        Tarife.objects.create(
            kategori=self.kategori, operator=self.tarifeli, ad="Taşıma 15 GB"
        )
        self.assertIn(self.tarifeli, self.kategori.gecerli_operatorler())

    def test_pasif_tarife_operatoru_getirmez(self):
        Tarife.objects.create(
            kategori=self.kategori, operator=self.tarifeli, ad="Kapalı", aktif=False
        )
        self.assertNotIn(self.tarifeli, self.kategori.gecerli_operatorler())

    def test_baska_kategorinin_tarifesi_sizmaz(self):
        digeri = BasvuruKategorisi.objects.create(ad="ADSL")
        Tarife.objects.create(
            kategori=digeri, operator=self.tarifeli, ad="Fiber 50"
        )
        self.assertNotIn(self.tarifeli, self.kategori.gecerli_operatorler())

    def test_hicbiri_yoksa_tum_aktif_operatorler(self):
        bos = BasvuruKategorisi.objects.create(ad="Boş Kategori")
        self.assertEqual(bos.gecerli_operatorler().count(), Operator.objects.count())

    def test_operator_listede_iki_kez_cikmaz(self):
        """Hem bağlı hem tarifesi olan operatör tekrar etmemeli."""
        Tarife.objects.create(
            kategori=self.kategori, operator=self.bagli, ad="Platinum"
        )
        adlar = [o.ad for o in self.kategori.gecerli_operatorler()]
        self.assertEqual(len(adlar), len(set(adlar)))


@override_settings(MEDIA_ROOT=GECICI_MEDYA)
class DosyaTemizligi(TestCase):
    """Kayıt silinince ya da görsel değişince disk temizlensin."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(GECICI_MEDYA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.kategori = BasvuruKategorisi.objects.create(ad="MNT")
        self.operator = Operator.objects.create(ad="Turkcell")

    def _tarife(self):
        with self.captureOnCommitCallbacks(execute=True):
            t = Tarife.objects.create(
                kategori=self.kategori, operator=self.operator,
                ad="Platinum", gorsel=gorsel(),
            )
        return t, t.gorsel.path

    def test_tarife_silinince_gorsel_de_silinir(self):
        tarife, yol = self._tarife()
        self.assertTrue(os.path.exists(yol))

        with self.captureOnCommitCallbacks(execute=True):
            tarife.delete()

        self.assertFalse(os.path.exists(yol))

    def test_gorsel_degisince_eskisi_silinir(self):
        tarife, eski_yol = self._tarife()

        with self.captureOnCommitCallbacks(execute=True):
            tarife.gorsel = gorsel("yeni.png")
            tarife.save()

        self.assertFalse(os.path.exists(eski_yol))
        self.assertTrue(os.path.exists(tarife.gorsel.path))

    def test_gorsel_bosaltilinca_silinir(self):
        tarife, yol = self._tarife()

        with self.captureOnCommitCallbacks(execute=True):
            tarife.gorsel = None
            tarife.save()

        self.assertFalse(os.path.exists(yol))

    def test_kampanya_gorseli_de_temizlenir(self):
        tarife, _ = self._tarife()
        with self.captureOnCommitCallbacks(execute=True):
            kampanya = Kampanya.objects.create(
                tarife=tarife, ad="İlk 3 ay", gorsel=gorsel("kampanya.png")
            )
        yol = kampanya.gorsel.path

        with self.captureOnCommitCallbacks(execute=True):
            kampanya.delete()

        self.assertFalse(os.path.exists(yol))

    def test_islem_geri_alinirsa_dosya_kalir(self):
        from django.db import transaction

        tarife, yol = self._tarife()
        try:
            with transaction.atomic():
                tarife.delete()
                raise RuntimeError("iptal")
        except RuntimeError:
            pass

        self.assertTrue(os.path.exists(yol))
