"""Katalog davranışı: operatör görünürlüğü ve dosya temizliği."""

import io
import os
import shutil
import tempfile
from pathlib import Path

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

    def test_verilen_parolayla_yonetici_acilir(self):
        from django.contrib.auth.models import User

        self._kur("--yonetici", "fadil", "--parola", "Cok-Uzun-Bir-Parola-42.")

        kullanici = User.objects.get(username="fadil")
        self.assertTrue(kullanici.is_superuser)
        self.assertTrue(kullanici.check_password("Cok-Uzun-Bir-Parola-42."))

    def test_var_olan_yoneticinin_parolasi_degismez(self):
        """Yeniden kurulum, elle değiştirilmiş bir parolayı sessizce ezmemeli."""
        from django.contrib.auth.models import User

        kullanici = User.objects.create_user("melih", password="eski-parola")
        self._kur("--yonetici", "melih", "--parola", "yeni-parola")

        kullanici.refresh_from_db()
        self.assertTrue(kullanici.is_superuser)
        self.assertTrue(kullanici.check_password("eski-parola"))

    def test_parolayi_yenile_var_olan_hesabi_gunceller(self):
        from django.contrib.auth.models import User

        kullanici = User.objects.create_user("melih", password="eski-parola")
        self._kur("--yonetici", "melih", "--parola", "yeni-parola", "--parolayi-yenile")

        kullanici.refresh_from_db()
        self.assertTrue(kullanici.check_password("yeni-parola"))

    def test_parola_tek_basina_reddedilir(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            self._kur("--parola", "bir-parola")

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

    def test_bozuk_migration_gecmisi_ne_yapilacagini_soyler(self):
        """Eski veritabanında migrate patlıyordu; traceback yerine yol gösterilmeli."""
        from unittest.mock import patch

        from django.core.management.base import CommandError
        from django.db.migrations.exceptions import InconsistentMigrationHistory

        hata = InconsistentMigrationHistory(
            "Migration basvurular.0001_initial is applied before its dependency "
            "katalog.0001_initial on database 'default'."
        )
        yol = "apps.katalog.management.commands.kurulum.call_command"
        with patch(yol, side_effect=hata):
            with self.assertRaises(CommandError) as kutu:
                self._kur()

        mesaj = str(kutu.exception)
        self.assertIn("--sifirla", mesaj)
        self.assertIn("docker compose run", mesaj)

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


@override_settings(MEDIA_ROOT=GECICI_MEDYA)
class SahipsizBelgeTemizligi(TestCase):
    """Veritabanı sıfırlanınca kimlik görüntüleri diskte kalmamalı."""

    def setUp(self):
        self.kok = Path(GECICI_MEDYA)
        shutil.rmtree(self.kok / "basvuru", ignore_errors=True)
        shutil.rmtree(self.kok / "evrak", ignore_errors=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(GECICI_MEDYA, ignore_errors=True)
        super().tearDownClass()

    def _dosya(self, göreli):
        yol = self.kok / göreli
        yol.parent.mkdir(parents=True, exist_ok=True)
        yol.write_bytes(b"kimlik")
        return yol

    def _calistir(self, *argumanlar):
        from django.core.management import call_command

        cikti = io.StringIO()
        call_command("sahipsiz_belgeler", *argumanlar, stdout=cikti, stderr=cikti)
        return cikti.getvalue()

    def test_eski_sistemin_evrak_klasoru_de_taranir(self):
        """Eski yapı `evrak/` kullanıyordu; yeni yapıda oraya yazan model yok."""
        eski = self._dosya("evrak/2023/kimlik_on.jpg")
        yeni = self._dosya("basvuru/2026/09/kimlik_arka.webp")

        self._calistir("--sil")

        self.assertFalse(eski.exists())
        self.assertFalse(yeni.exists())

    def test_kayitli_belge_silinmez(self):
        from apps.basvurular.models import Basvuru, BasvuruBelgesi, BasvuruDurumu
        from django.contrib.auth.models import User

        kategori = BasvuruKategorisi.objects.create(ad="MNT")
        durum = BasvuruDurumu.objects.create(ad="Beklemede", slug="beklemede")
        bayi = User.objects.create_user("bayi", password="parola123")
        basvuru = Basvuru.objects.create(
            bayi=bayi, kategori=kategori, durum=durum, isim="Ali"
        )
        goreli = "basvuru/2026/09/duran.webp"
        yol = self._dosya(goreli)
        BasvuruBelgesi.objects.create(basvuru=basvuru, alan_kodu="kimlik_on", dosya=goreli)

        self._calistir("--sil")

        self.assertTrue(yol.exists())

    def test_sil_verilmezse_yalnizca_raporlar(self):
        yol = self._dosya("evrak/eski.jpg")

        cikti = self._calistir()

        self.assertTrue(yol.exists())
        self.assertIn("Silmek için --sil", cikti)

    def test_tarife_gorseline_dokunulmaz(self):
        """Görsel klasörleri kendi modellerine bağlı; tarama dışında kalmalı."""
        yol = self._dosya("tarife/2026/09/kapak.webp")

        self._calistir("--sil")

        self.assertTrue(yol.exists())


class StatikDosyalar(TestCase):
    """`collectstatic` üretim deposuyla hatasız çalışmalı.

    Tailwind'in kaynak dosyası bir süre `static/` altındaydı ve
    `collectstatic` onu da toplayıp `@import "tailwindcss"` satırında
    çöküyordu. Container açılışta buna çarpıp ölüyordu; hata ancak
    sunucuda görülüyordu.
    """

    def test_uretim_deposuyla_toplanabiliyor(self):
        import tempfile

        from django.conf import settings
        from django.core.management import call_command

        with tempfile.TemporaryDirectory(prefix="statik-test-") as hedef:
            with override_settings(
                STATIC_ROOT=hedef,
                STORAGES={
                    **settings.STORAGES,
                    "staticfiles": {
                        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
                    },
                },
            ):
                call_command(
                    "collectstatic", "--noinput", "--clear",
                    verbosity=0, stdout=io.StringIO(), stderr=io.StringIO(),
                )

            self.assertTrue((Path(hedef) / "staticfiles.json").exists())

    def test_tailwind_kaynagi_static_altinda_degil(self):
        """Kaynak dosya derleme girdisidir; yayınlanan klasöre konmaz."""
        from django.conf import settings

        for klasor in settings.STATICFILES_DIRS:
            for yol in Path(klasor).rglob("*.css"):
                icerik = yol.read_text(errors="ignore")
                self.assertNotIn(
                    '@import "tailwindcss"',
                    icerik,
                    f"{yol} derlenmemiş kaynak; static/ dışına taşınmalı",
                )


class YonetimPaneliTurkcesi(TestCase):
    """django-unfold Türkçe çeviriyle gelmiyor; eksikler bizim katalogda.

    Derlenmiş `.mo` dosyası bir süre `.gitignore`'daydı: yerelde her şey
    Türkçeydi ama sunucuda İngilizce görünüyordu, çünkü Django `.po`
    değil `.mo` okur ve sunucuda `compilemessages` çalışmıyor.
    """

    def test_derlenmis_katalog_yerinde(self):
        from django.conf import settings

        for yol in settings.LOCALE_PATHS:
            mo = Path(yol) / "tr" / "LC_MESSAGES" / "django.mo"
            self.assertTrue(mo.exists(), f"{mo} yok — compilemessages çalıştırın")

    def test_unfold_metinleri_turkce(self):
        from django.utils import translation

        with translation.override("tr"):
            for metin in (
                "Type to search",
                "No results found",
                "Reset filters",
                "This page yielded into no results. "
                "Create a new item or reset your filters.",
                "Log out",
                "Change password",
            ):
                self.assertNotEqual(
                    translation.gettext(metin), metin, f"çevrilmemiş: {metin}"
                )


@override_settings(MEDIA_ROOT=GECICI_MEDYA, DEBUG=False)
class AcikGorselSunumu(TestCase):
    """Bayiye gösterilen görsel üretimde de açılmalı.

    Görsel admin'den yüklenir. Django'nun `static()` yardımcısı yalnızca DEBUG
    açıkken URL üretir, WhiteNoise ise açılışta taradığı `STATIC_ROOT`'u sunar;
    sonradan yüklenen dosya ikisine de girmediği için görsel yerelde görünüp
    üretimde 404 veriyordu.
    """

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(GECICI_MEDYA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        kategori = BasvuruKategorisi.objects.create(ad="MNT")
        operator = Operator.objects.create(ad="Turkcell")
        self.tarife = Tarife.objects.create(
            kategori=kategori, operator=operator, ad="Platinum", gorsel=gorsel()
        )

    def test_tarife_gorseli_uretimde_acilir(self):
        yanit = self.client.get(self.tarife.gorsel.url)

        self.assertEqual(yanit.status_code, 200)
        self.assertIn("public", yanit["Cache-Control"])

    def test_kampanya_gorseli_de_acilir(self):
        kampanya = Kampanya.objects.create(
            tarife=self.tarife, ad="Yaz", gorsel=gorsel("kampanya.png")
        )

        self.assertEqual(self.client.get(kampanya.gorsel.url).status_code, 200)

    def test_kimlik_klasoru_medya_yolundan_acilmaz(self):
        """Kişisel veri yalnızca izin kontrollü belge görünümünden gelir."""
        yanit = self.client.get("/media/basvuru/2026/09/kimlik.webp")

        self.assertEqual(yanit.status_code, 404)

    def test_ust_klasore_cikilamaz(self):
        """Desen normalleştirmeden önce eşleşir; klasör sonradan denetlenir."""
        yanit = self.client.get("/media/tarife/../basvuru/2026/09/kimlik.webp")

        self.assertEqual(yanit.status_code, 404)
