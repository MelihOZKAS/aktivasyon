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


class KurulumKomutu(TestCase):
    """`manage.py kurulum` sistemi tek başına ayağa kaldırabilmeli.

    Sıfırdan kurulan bir veritabanında elle hiçbir kayıt açmadan başvuru
    girilip parası işlenebilmeli; kurulum sırasının bütün adımları veriyle
    dolmalı.
    """

    @staticmethod
    def _kur(*argumanlar):
        from django.core.management import call_command

        call_command("kurulum", *argumanlar, stdout=io.StringIO(), stderr=io.StringIO())

    def test_ornek_kurulum_her_adimi_doldurur(self):
        from django.contrib.auth.models import User

        from apps.basvurular.models import BasvuruDurumu
        from apps.bayi.models import SimKart
        from apps.finans.models import BayiGrubu, KuralYonu, UcretKurali
        from apps.katalog.models import KategoriAlani

        self._kur("--ornek", "--zorla")

        # 1-4: durumlar, operatörler, kategoriler, form alanları
        self.assertTrue(BasvuruDurumu.objects.filter(baslangic_durumu=True).exists())
        self.assertTrue(BasvuruDurumu.objects.filter(hakedis_tetikler=True).exists())
        self.assertTrue(Operator.objects.exists())
        self.assertTrue(BasvuruKategorisi.objects.exists())
        self.assertTrue(KategoriAlani.objects.filter(cekirdek_alan="isim").exists())

        # 5-7: tarifeler, gruplar, üç yönde de kural
        self.assertTrue(Tarife.objects.exists())
        self.assertTrue(BayiGrubu.objects.exists())
        for yon in (KuralYonu.TAHSILAT, KuralYonu.HAKEDIS, KuralYonu.ANA_HAKEDIS):
            self.assertTrue(
                UcretKurali.objects.filter(yon=yon).exists(), f"{yon} kuralı yok"
            )

        # 8: kullanıcılar, cüzdanları ve SIM stoğu
        self.assertTrue(User.objects.filter(is_superuser=True).exists())
        bayi = User.objects.get(username="bayi.kaya")
        self.assertTrue(bayi.cuzdan.bakiye > 0)
        self.assertTrue(SimKart.objects.bayinin_stogu(bayi).exists())

    def test_kurulan_sistem_parayi_kendi_isler(self):
        """Kurulumdan sonra elle kural yazmadan hakediş ve kâr oluşmalı."""
        from decimal import Decimal

        from django.contrib.auth.models import User

        from apps.basvurular.models import Basvuru, BasvuruDurumu

        self._kur("--ornek", "--zorla")

        bayi = User.objects.get(username="bayi.kaya")
        onceki_bakiye = bayi.cuzdan.bakiye
        kategori = BasvuruKategorisi.objects.get(ad="Kontörlü Yeni Hat")
        tarife = Tarife.objects.filter(kategori=kategori).first()

        basvuru = Basvuru.objects.create(
            bayi=bayi,
            kategori=kategori,
            operator=tarife.operator,
            tarife=tarife,
            kimlik_no="12345678901",
            isim="Ayşe",
            soyisim="Demir",
            irtibat="5551234567",
            durum=BasvuruDurumu.objects.get(baslangic_durumu=True),
        )
        basvuru.durum = BasvuruDurumu.objects.get(hakedis_tetikler=True)
        basvuru.save()

        basvuru.refresh_from_db()
        bayi.cuzdan.refresh_from_db()

        self.assertEqual(basvuru.tahsil_edilen, Decimal("25.00"))
        self.assertEqual(basvuru.hakedis, Decimal("60.00"))
        self.assertEqual(basvuru.ana_hakedis, Decimal("140.00"))
        # Kâr = ana hakediş + tahsilat − hakediş
        self.assertEqual(basvuru.kar, Decimal("105.00"))
        self.assertEqual(bayi.cuzdan.bakiye, onceki_bakiye - 25 + 60)

    def test_ikinci_calistirma_kayitlari_cogaltmaz(self):
        from apps.finans.models import UcretKurali

        self._kur("--ornek", "--zorla")
        sayilar = (
            Operator.objects.count(),
            BasvuruKategorisi.objects.count(),
            Tarife.objects.count(),
            UcretKurali.objects.count(),
        )

        self._kur("--ornek", "--zorla")

        self.assertEqual(
            sayilar,
            (
                Operator.objects.count(),
                BasvuruKategorisi.objects.count(),
                Tarife.objects.count(),
                UcretKurali.objects.count(),
            ),
        )

    def test_yonetici_hesabi_acilir(self):
        from django.contrib.auth.models import User

        self._kur("--yonetici", "kurulum.admin")

        kullanici = User.objects.get(username="kurulum.admin")
        self.assertTrue(kullanici.is_superuser)
        self.assertTrue(kullanici.is_staff)

    def test_var_olan_yoneticinin_parolasi_degismez(self):
        from django.contrib.auth.models import User

        kullanici = User.objects.create_user("melih", password="eski-parola")
        self._kur("--yonetici", "melih")

        kullanici.refresh_from_db()
        self.assertTrue(kullanici.is_superuser)
        self.assertTrue(kullanici.check_password("eski-parola"))

    def test_yanlis_ad_yazilirsa_hicbir_sey_silinmez(self):
        """--sifirla onayı veritabanı adının yazılmasını ister."""
        from unittest.mock import patch

        from django.core.management.base import CommandError

        self._kur()
        onceki = BasvuruKategorisi.objects.count()

        with patch("builtins.input", return_value="yanlis-ad"):
            with self.assertRaises(CommandError):
                self._kur("--sifirla")

        self.assertEqual(BasvuruKategorisi.objects.count(), onceki)

    def test_ornek_veri_uretimde_kazara_calismaz(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError

        with override_settings(DEBUG=False):
            for komut in ("ornek_veri", "ornek_kullanicilar"):
                with self.assertRaises(CommandError, msg=komut):
                    call_command(komut, stdout=io.StringIO())

    def test_durum_renklerinde_mor_yok(self):
        """Tasarım kuralı: mor/violet renk kullanılmaz."""
        import colorsys

        from apps.basvurular.models import BasvuruDurumu

        self._kur()
        for durum in BasvuruDurumu.objects.all():
            kod = durum.renk.lstrip("#")
            r, g, b = (int(kod[i:i + 2], 16) / 255 for i in (0, 2, 4))
            ton, _, doygunluk = colorsys.rgb_to_hsv(r, g, b)
            mor = 0.72 <= ton <= 0.85 and doygunluk > 0.25
            self.assertFalse(mor, f"{durum.ad} moru andırıyor: {durum.renk}")
