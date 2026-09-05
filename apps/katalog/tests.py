"""Katalog davranışı: operatör görünürlüğü ve dosya temizliği."""

import io
import os
import shutil
import tempfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from apps.katalog.models import BasvuruKategorisi, Operator, Tarife

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

        _tarife = Tarife.objects.create(
            operator=self.tarifeli, ad="Taşıma 15 GB"
        )
        _tarife.kategoriler.add(self.kategori)
        self.assertIn(self.tarifeli, self.kategori.gecerli_operatorler())

    def test_pasif_tarife_operatoru_getirmez(self):
        _tarife = Tarife.objects.create(
            operator=self.tarifeli, ad="Kapalı", aktif=False
        )
        _tarife.kategoriler.add(self.kategori)
        self.assertNotIn(self.tarifeli, self.kategori.gecerli_operatorler())

    def test_baska_kategorinin_tarifesi_sizmaz(self):
        digeri = BasvuruKategorisi.objects.create(ad="ADSL")
        _tarife = Tarife.objects.create(
            operator=self.tarifeli, ad="Fiber 50"
        )
        _tarife.kategoriler.add(digeri)
        self.assertNotIn(self.tarifeli, self.kategori.gecerli_operatorler())

    def test_hicbiri_yoksa_tum_aktif_operatorler(self):
        bos = BasvuruKategorisi.objects.create(ad="Boş Kategori")
        self.assertEqual(bos.gecerli_operatorler().count(), Operator.objects.count())

    def test_operator_listede_iki_kez_cikmaz(self):
        """Hem bağlı hem tarifesi olan operatör tekrar etmemeli."""
        _tarife = Tarife.objects.create(
            operator=self.bagli, ad="Platinum"
        )
        _tarife.kategoriler.add(self.kategori)
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
                operator=self.operator,
                ad="Platinum", gorsel=gorsel(),
            )
            t.kategoriler.add(self.kategori)
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
        tarife = Tarife.objects.filter(kategoriler=kategori).first()

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
            operator=operator, ad="Platinum", gorsel=gorsel()
        )
        self.tarife.kategoriler.add(kategori)

    def test_tarife_gorseli_uretimde_acilir(self):
        yanit = self.client.get(self.tarife.gorsel.url)

        self.assertEqual(yanit.status_code, 200)
        self.assertIn("public", yanit["Cache-Control"])

    def test_gorsel_indirilmez_goruntulenir(self):
        """Telefon tarayıcıları WebP'yi kendiliğinden indirmeye alabiliyor."""
        yanit = self.client.get(self.tarife.gorsel.url)

        self.assertEqual(yanit["Content-Disposition"], "inline")

    def test_kimlik_klasoru_medya_yolundan_acilmaz(self):
        """Kişisel veri yalnızca izin kontrollü belge görünümünden gelir."""
        yanit = self.client.get("/media/basvuru/2026/09/kimlik.webp")

        self.assertEqual(yanit.status_code, 404)

    def test_ust_klasore_cikilamaz(self):
        """Desen normalleştirmeden önce eşleşir; klasör sonradan denetlenir."""
        yanit = self.client.get("/media/tarife/../basvuru/2026/09/kimlik.webp")

        self.assertEqual(yanit.status_code, 404)


class YeniKategoriVarsayilanAlanlari(TestCase):
    """Panelden açılan kategori boş formla gelmez.

    Alanlar açık gelir; sorulmayacak olanı yönetici "Aktif" kutusundan
    kapatır. Kapatmak, on beş satırı elle girmekten kolaydır.
    """

    ADRES = "/yonetim/katalog/basvurukategorisi/add/"

    def setUp(self):
        from django.contrib.auth.models import User

        self.yonetici = User.objects.create_superuser("yonetici", password="Panel-2026x")
        self.client.force_login(self.yonetici)

    def _kategori_ekle(self, ad, musteri_tipi="hepsi"):
        from apps.katalog.models import BasvuruKategorisi

        cevap = self.client.post(
            self.ADRES,
            {
                "ad": ad,
                "slug": "",
                "aciklama": "",
                "ikon": "sim_card",
                "musteri_tipi": musteri_tipi,
                "sira": "10",
                "alanlar-TOTAL_FORMS": "0",
                "alanlar-INITIAL_FORMS": "0",
                "Tarife_kategoriler-TOTAL_FORMS": "0",
                "Tarife_kategoriler-INITIAL_FORMS": "0",
            },
            follow=True,
        )
        self.assertEqual(cevap.status_code, 200)
        return BasvuruKategorisi.objects.get(ad=ad)

    def test_yeni_kategoride_butun_alanlar_acik_gelir(self):
        """Listedeki her alan gelir ve hepsi aktiftir; istisna yok."""
        from apps.katalog.varsayilan_alanlar import TUM_ALANLAR

        kategori = self._kategori_ekle("Yeni İşlem")
        kodlar = set(kategori.alanlar.values_list("kod", flat=True))

        self.assertEqual(kodlar, {alan[0] for alan in TUM_ALANLAR})
        self.assertTrue(all(kategori.alanlar.values_list("aktif", flat=True)))

    def test_kimlik_de_pasaport_da_acik_gelir(self):
        """Müşteri tipine göre dallanma yok: gereksizi yönetici kapatır."""
        kategori = self._kategori_ekle("Pasaportlu İşlem", musteri_tipi="yabanci")
        kodlar = set(kategori.alanlar.values_list("kod", flat=True))

        self.assertIn("pasaport_on", kodlar)
        self.assertIn("kimlik_on", kodlar)

    def test_her_kategoriye_acilan_niste_alan_zorunlu_degil(self):
        """Kapatmayı unutan yönetici bayiyi olmayan bilgiye mahkûm etmesin."""
        kategori = self._kategori_ekle("Yeni İşlem")

        self.assertFalse(kategori.alanlar.get(kod="numara").zorunlu)
        self.assertFalse(kategori.alanlar.get(kod="gececegi_operator").zorunlu)
        # Her işlemde sorulanlar zorunlu kalır.
        self.assertTrue(kategori.alanlar.get(kod="isim").zorunlu)
        self.assertTrue(kategori.alanlar.get(kod="kimlik_no").zorunlu)

    def test_var_olan_kategori_kaydedilince_alan_cogalmaz(self):
        kategori = self._kategori_ekle("Yeni İşlem")
        adet = kategori.alanlar.count()

        self.client.post(
            f"/yonetim/katalog/basvurukategorisi/{kategori.pk}/change/",
            {
                "ad": "Yeni İşlem",
                "slug": kategori.slug,
                "aciklama": "",
                "ikon": "sim_card",
                "musteri_tipi": "hepsi",
                "sira": "10",
                "aktif": "on",
                "alanlar-TOTAL_FORMS": "0",
                "alanlar-INITIAL_FORMS": "0",
                "Tarife_kategoriler-TOTAL_FORMS": "0",
                "Tarife_kategoriler-INITIAL_FORMS": "0",
            },
            follow=True,
        )

        self.assertEqual(kategori.alanlar.count(), adet)

    def test_kapatilan_alan_geri_acilmaz(self):
        """Yönetici bir alanı kapattıysa sonraki kayıtta geri gelmemeli."""
        kategori = self._kategori_ekle("Yeni İşlem")
        alan = kategori.alanlar.get(kod="sim_imei")
        alan.aktif = False
        alan.save(update_fields=["aktif"])

        from apps.katalog.varsayilan_alanlar import varsayilan_alanlari_ac

        varsayilan_alanlari_ac(kategori)
        alan.refresh_from_db()

        self.assertFalse(alan.aktif)


class PaneldeAdiDegisenKayit(TestCase):
    """Kurulum her container açılışında çalışır; panel düzenlemesi onu kırmamalı.

    Yönetici kategorinin adını değiştirdiğinde slug eskisi gibi kalıyordu.
    `get_or_create(ad=...)` kaydı bulamayıp yeniden açmaya çalışıyor, tekil
    slug kısıtına çarpıyor ve container açılışta ölüyordu — sunucu tek bir
    yeniden adlandırmayla ayağa kalkmaz olmuştu.
    """

    def setUp(self):
        from django.core.management import call_command

        call_command("baslangic_verisi", stdout=self._cikti())

    @staticmethod
    def _cikti():
        import io

        return io.StringIO()

    def test_kategori_adi_degistirilse_de_kurulum_tekrar_calisir(self):
        from django.core.management import call_command

        from apps.katalog.models import BasvuruKategorisi

        kategori = BasvuruKategorisi.objects.get(slug="mnt-numara-tasima")
        kategori.ad = "Numara Taşıma (MNT)"
        kategori.save(update_fields=["ad"])
        adet = BasvuruKategorisi.objects.count()

        call_command("baslangic_verisi", stdout=self._cikti())

        kategori.refresh_from_db()
        self.assertEqual(BasvuruKategorisi.objects.count(), adet)
        # Panelde verilen ad kurulumla geri alınmaz.
        self.assertEqual(kategori.ad, "Numara Taşıma (MNT)")

    def test_operator_adi_degistirilse_de_kurulum_tekrar_calisir(self):
        from django.core.management import call_command

        from apps.katalog.models import Operator

        operator = Operator.objects.get(slug="turkcell")
        operator.ad = "Turkcell A.Ş."
        operator.save(update_fields=["ad"])
        adet = Operator.objects.count()

        call_command("baslangic_verisi", stdout=self._cikti())

        self.assertEqual(Operator.objects.count(), adet)

    def test_slug_degistirilse_de_kurulum_tekrar_calisir(self):
        """Kısa adı değişen kayıt adından bulunur."""
        from django.core.management import call_command

        from apps.katalog.models import BasvuruKategorisi

        kategori = BasvuruKategorisi.objects.get(slug="mnt-numara-tasima")
        kategori.slug = "numara-tasima"
        kategori.save(update_fields=["slug"])
        adet = BasvuruKategorisi.objects.count()

        call_command("baslangic_verisi", stdout=self._cikti())

        self.assertEqual(BasvuruKategorisi.objects.count(), adet)


class TarifeBirdenCokKategoride(TestCase):
    """Aynı tarife birden çok kategoride geçerli olabilir.

    Operatör aynı paketi hem numara taşımada hem yeni hatta veriyordu;
    tarifenin tek kategorisi olduğu için aynı tarife iki kez açılıyor,
    fiyatı da iki yerde güncelleniyordu.
    """

    def setUp(self):
        from apps.katalog.models import BasvuruKategorisi, Operator, Tarife

        self.operator = Operator.objects.create(ad="Turkcell")
        self.tasima = BasvuruKategorisi.objects.create(ad="Numara Taşıma")
        self.yeni_hat = BasvuruKategorisi.objects.create(ad="Faturalı Yeni Hat")
        self.sebeke = BasvuruKategorisi.objects.create(ad="Şebeke İçi Geçiş")
        self.tarife = Tarife.objects.create(operator=self.operator, ad="Platinum 30 GB")
        self.tarife.kategoriler.add(self.tasima, self.yeni_hat)

    def test_secilen_her_kategoride_gorunur(self):
        from apps.katalog.models import Tarife

        for kategori in (self.tasima, self.yeni_hat):
            self.assertIn(
                self.tarife, Tarife.objects.filter(kategoriler=kategori)
            )

    def test_secilmeyen_kategoride_gorunmez(self):
        from apps.katalog.models import Tarife

        self.assertNotIn(
            self.tarife, Tarife.objects.filter(kategoriler=self.sebeke)
        )

    def test_basvuru_formunda_iki_kategoride_de_secilebilir(self):
        from apps.basvurular.forms import BasvuruFormu

        for kategori in (self.tasima, self.yeni_hat):
            form = BasvuruFormu(kategori=kategori)
            self.assertIn(self.tarife, form.fields["tarife"].queryset)

    def test_kategorisi_olan_operator_forma_girer(self):
        """Tarifesi olan operatör her iki kategoride de seçilebilir olmalı."""
        for kategori in (self.tasima, self.yeni_hat):
            self.assertIn(self.operator, kategori.gecerli_operatorler())

    def test_basvuruda_kategoriye_ait_olmayan_tarife_reddedilir(self):
        from django.contrib.auth.models import User
        from django.core.exceptions import ValidationError

        from apps.basvurular.models import Basvuru, BasvuruDurumu

        durum = BasvuruDurumu.objects.create(
            ad="Beklemede", slug="beklemede", baslangic_durumu=True
        )
        bayi = User.objects.create_user("bayi", password="parola12345")
        basvuru = Basvuru(
            bayi=bayi, kategori=self.sebeke, operator=self.operator,
            tarife=self.tarife, isim="Ayşe", soyisim="Demir", kimlik_no="1",
            irtibat="5551112233", durum=durum,
        )

        with self.assertRaises(ValidationError):
            basvuru.full_clean(exclude=["referans_no"])

    def test_kategori_adlari_tek_satirda_yazilir(self):
        self.assertIn("Numara Taşıma", self.tarife.kategori_adlari)
        self.assertIn("Faturalı Yeni Hat", self.tarife.kategori_adlari)


class AyniAdliTarifelerGecisiBozmaz(TestCase):
    """Aynı ad + operatör iki ayrı kategoride durabilir.

    Kategori çoğullaşırken (operatör, ad) tekillik kısıtı konmuştu; üretimde
    "İlk Turkcellim" iki kategoride ayrı ayrı tanımlı olduğu için migration
    kısıtı kuramayıp container'ı açılışta öldürdü. Kısıt kaldırıldı:
    tarifeleri birleştirmek para kuralları arasında seçim yapmak demek,
    bu karar yöneticinindir.
    """

    def test_ayni_ad_ve_operator_iki_kez_tanimlanabilir(self):
        from apps.katalog.models import BasvuruKategorisi, Operator, Tarife

        operator = Operator.objects.create(ad="Turkcell")
        tasima = BasvuruKategorisi.objects.create(ad="Numara Taşıma")
        yeni_hat = BasvuruKategorisi.objects.create(ad="Yeni Hat")

        birinci = Tarife.objects.create(operator=operator, ad="İlk Turkcellim")
        birinci.kategoriler.add(tasima)
        ikinci = Tarife.objects.create(operator=operator, ad="İlk Turkcellim")
        ikinci.kategoriler.add(yeni_hat)

        self.assertEqual(
            Tarife.objects.filter(operator=operator, ad="İlk Turkcellim").count(), 2
        )

    def test_yonetici_ikisini_tek_tarifede_toplayabilir(self):
        """Birleştirme yolu açık: kategorileri işaretle, diğerini kapat."""
        from apps.katalog.models import BasvuruKategorisi, Operator, Tarife

        operator = Operator.objects.create(ad="Turkcell")
        tasima = BasvuruKategorisi.objects.create(ad="Numara Taşıma")
        yeni_hat = BasvuruKategorisi.objects.create(ad="Yeni Hat")

        kalan = Tarife.objects.create(operator=operator, ad="İlk Turkcellim")
        kalan.kategoriler.add(tasima)
        kapanan = Tarife.objects.create(operator=operator, ad="İlk Turkcellim")
        kapanan.kategoriler.add(yeni_hat)

        kalan.kategoriler.add(yeni_hat)
        kapanan.aktif = False
        kapanan.save(update_fields=["aktif"])

        for kategori in (tasima, yeni_hat):
            secilebilir = Tarife.objects.filter(kategoriler=kategori, aktif=True)
            self.assertEqual(list(secilebilir), [kalan])


class BaslangicDurumuIkiyeKatlanmaz(TestCase):
    """Yönetici başlangıç durumunu adlandırdıysa tohum ikincisini açmaz.

    Başlangıç durumunun adı "Giriş" yapılıp giriş bedeli ona bağlanmıştı.
    Açılışta çalışan başlangıç verisi "beklemede" slug'ını bulamayıp yeni bir
    "Beklemede" açıyor ve onu da başlangıç işaretliyordu; yeni başvurular ona
    düşüyor, giriş bedeli hiç kesilmiyordu.
    """

    def setUp(self):
        import io

        from django.core.management import call_command

        call_command("baslangic_verisi", stdout=io.StringIO())
        self.cikti = io.StringIO()

    def _tekrar_calistir(self):
        import io

        from django.core.management import call_command

        call_command("baslangic_verisi", stdout=io.StringIO())

    def test_adi_degisen_baslangic_durumu_ikinci_kez_acilmaz(self):
        from apps.basvurular.models import BasvuruDurumu

        durum = BasvuruDurumu.objects.get(baslangic_durumu=True)
        durum.ad = "Giriş"
        durum.slug = "giris"
        durum.save(update_fields=["ad", "slug"])

        self._tekrar_calistir()

        self.assertEqual(BasvuruDurumu.objects.filter(baslangic_durumu=True).count(), 1)
        self.assertEqual(
            BasvuruDurumu.objects.get(baslangic_durumu=True).slug, "giris"
        )

    def test_yeni_basvuru_yoneticinin_sectigi_durumda_acilir(self):
        from apps.basvurular.models import BasvuruDurumu

        durum = BasvuruDurumu.objects.get(baslangic_durumu=True)
        durum.ad = "Giriş"
        durum.slug = "giris"
        durum.save(update_fields=["ad", "slug"])

        self._tekrar_calistir()

        secilen = BasvuruDurumu.objects.filter(
            baslangic_durumu=True, aktif=True
        ).first()
        self.assertEqual(secilen.slug, "giris")


class KategoriAlaniHatalari(TestCase):
    """Hata mesajı ne yapılacağını söylemeli.

    Yönetici ikinci bir kimlik görseli eklemek isterken Çekirdek Alan'ı da
    dolduruyor ve ham veritabanı kısıtı mesajıyla karşılaşıyordu:
    "kategori_cekirdek_alan_benzersiz kısıtlaması ihlal edildi". Ne olduğu
    da ne yapılacağı da anlaşılmıyordu.
    """

    def setUp(self):
        from django.core.exceptions import ValidationError  # noqa: F401
        from apps.katalog.models import (
            AlanTipi, BasvuruKategorisi, CekirdekAlan, KategoriAlani,
        )

        self.kategori = BasvuruKategorisi.objects.create(ad="Faturalı Yeni Hat")
        self.mevcut = KategoriAlani.objects.create(
            kategori=self.kategori, kod="kimlik_tipi", etiket="Kimlik Tipi",
            tip=AlanTipi.SECIM, cekirdek_alan=CekirdekAlan.KIMLIK_TIPI, sira=1,
        )

    def _alan(self, **degisiklikler):
        from apps.katalog.models import AlanTipi, KategoriAlani

        alanlar = {
            "kategori": self.kategori,
            "kod": "kimlik_on_cocuk",
            "etiket": "Kimlik Çocuk Ön",
            "tip": AlanTipi.RESIM,
            "sira": 2,
        }
        alanlar.update(degisiklikler)
        return KategoriAlani(**alanlar)

    def test_ikinci_kimlik_gorseli_eklenebilir(self):
        """Çekirdek alan boşsa aynı kategoriye ikinci görsel girer."""
        alan = self._alan()
        alan.full_clean()
        alan.save()

        self.assertEqual(self.kategori.alanlar.count(), 2)

    def test_ayni_cekirdek_alan_ikinci_kez_kullanilamaz(self):
        from django.core.exceptions import ValidationError

        from apps.katalog.models import AlanTipi, CekirdekAlan

        alan = self._alan(tip=AlanTipi.METIN, cekirdek_alan=CekirdekAlan.KIMLIK_TIPI)

        with self.assertRaises(ValidationError) as hata:
            alan.full_clean()

        mesaj = " ".join(hata.exception.message_dict["cekirdek_alan"])
        # Çakışan alanı adıyla söyler ve ne yapılacağını yazar.
        self.assertIn("Kimlik Tipi", mesaj)
        self.assertIn("boş bırakın", mesaj)

    def test_gorsel_alan_cekirdek_olamaz_uyarisi_yol_gosterir(self):
        from django.core.exceptions import ValidationError

        from apps.katalog.models import CekirdekAlan

        alan = self._alan(cekirdek_alan=CekirdekAlan.ISIM)

        with self.assertRaises(ValidationError) as hata:
            alan.full_clean()

        mesaj = " ".join(hata.exception.message_dict["cekirdek_alan"])
        self.assertIn("boş bırakın", mesaj)

    def test_ayni_kod_ikinci_kez_kullanilamaz(self):
        from django.core.exceptions import ValidationError

        alan = self._alan(kod="kimlik_tipi")

        with self.assertRaises(ValidationError) as hata:
            alan.full_clean()

        self.assertIn("kod", hata.exception.message_dict)

    def test_alanlarin_hepsinde_yardim_metni_var(self):
        """Yönetici her başlığın nerede ne yaptığını okuyabilmeli."""
        from apps.katalog.models import KategoriAlani

        yardimsiz = [
            alan.name
            for alan in KategoriAlani._meta.get_fields()
            if getattr(alan, "editable", False)
            and not getattr(alan, "auto_created", False)
            and alan.name not in {"id", "kategori", "olusturma_tarihi", "guncelleme_tarihi"}
            and not alan.help_text
        ]

        self.assertEqual(yardimsiz, [])


class TarifeGorunurlukSutunlari(TestCase):
    """İki görünürlük anahtarı listede karışmamalı.

    Yan yana iki tik kutusuyken hangisinin ne olduğu ancak sütun başlığı
    okunarak anlaşılıyordu. İkisi de kendi cümlesini yazar.
    """

    def setUp(self):
        from django.contrib.auth.models import User

        from apps.katalog.models import BasvuruKategorisi, Operator, Tarife

        operator = Operator.objects.create(ad="Turkcell")
        kategori = BasvuruKategorisi.objects.create(ad="Kontörlü Yeni Hat")
        self.tarife = Tarife.objects.create(operator=operator, ad="Platinum")
        self.tarife.kategoriler.add(kategori)

        self.yonetici = User.objects.create_superuser("yonetici", password="Panel-2026x")
        self.client.force_login(self.yonetici)

    def _liste(self):
        from django.urls import reverse

        return self.client.get(
            reverse("admin:katalog_tarife_changelist")
        ).content.decode()

    def test_iki_anahtar_da_kendi_cumlesini_yazar(self):
        icerik = self._liste()

        self.assertIn("Katalogda görünür", icerik)
        self.assertIn("Aktif", icerik)

    def test_katalogda_gizli_tarife_ayri_yazar(self):
        self.tarife.bayiye_gorunur = False
        self.tarife.save(update_fields=["bayiye_gorunur"])

        icerik = self._liste()

        self.assertIn("Katalogda gizli", icerik)

    def test_pasif_tarife_ayri_yazar(self):
        self.tarife.aktif = False
        self.tarife.save(update_fields=["aktif"])

        icerik = self._liste()

        self.assertIn("Pasif", icerik)

    def test_toplu_islemle_katalogdan_gizlenir(self):
        from django.urls import reverse

        self.client.post(
            reverse("admin:katalog_tarife_changelist"),
            {"action": "bayiden_gizle", "_selected_action": [self.tarife.pk]},
            follow=True,
        )

        self.tarife.refresh_from_db()
        self.assertFalse(self.tarife.bayiye_gorunur)
        # Katalogdan gizlemek tarifeyi pasifleştirmez.
        self.assertTrue(self.tarife.aktif)

    def test_toplu_islemle_pasiflestirilir(self):
        from django.urls import reverse

        self.client.post(
            reverse("admin:katalog_tarife_changelist"),
            {"action": "pasiflestir", "_selected_action": [self.tarife.pk]},
            follow=True,
        )

        self.tarife.refresh_from_db()
        self.assertFalse(self.tarife.aktif)
        self.assertTrue(self.tarife.bayiye_gorunur)


class StokVeAlacakOzeti(TestCase):
    """Tek ekranda "nerede ne var".

    SIM kartlar, beklenen karşılıklar ve tedarikçi borçları ayrı listelerde
    duruyordu; yönetici üçünü ayrı ekranda açıp kafasında topluyordu.
    """

    ADRES = "/yonetim/ozet/"

    def setUp(self):
        from decimal import Decimal

        from django.contrib.auth.models import User

        from apps.basvurular.models import Basvuru, BasvuruDurumu
        from apps.bayi.models import BayiProfili, SimKart, SimKartDurumu
        from apps.finans.models import Cuzdan
        from apps.katalog.models import BasvuruKategorisi, Operator

        self.aktif = BasvuruDurumu.objects.create(
            ad="Aktif", slug="aktif", hakedis_tetikler=True
        )
        self.operator = Operator.objects.create(ad="Turkcell")
        self.kategori = BasvuruKategorisi.objects.create(
            ad="Kontörlü Yeni Hat", sim_karsiligi_gerekir=True
        )

        self.bayi = User.objects.create_user("5435609672", password="parola12345")
        BayiProfili.objects.create(kullanici=self.bayi, unvan="fadil deneme")
        Cuzdan.objects.create(bayi=self.bayi)

        self.tedarikci = User.objects.create_user("5524144444", password="parola12345")
        BayiProfili.objects.create(
            kullanici=self.tedarikci, unvan="Melih Paşa", tedarikci_mi=True
        )
        Cuzdan.objects.create(bayi=self.tedarikci, borc=Decimal("4500.00"))

        SimKart.objects.create(imei="1", operator=self.operator)
        SimKart.objects.create(
            imei="2", operator=self.operator, bayi=self.bayi,
            durum=SimKartDurumu.ATANDI,
        )
        SimKart.objects.create(
            imei="3", operator=self.operator, bayi=self.bayi,
            durum=SimKartDurumu.ATANDI,
        )

        Basvuru.objects.create(
            bayi=self.bayi, kategori=self.kategori, operator=self.operator,
            isim="Ayşe", soyisim="Demir", kimlik_no="1", irtibat="5551112233",
            durum=self.aktif, ana_hakedis=Decimal("400.00"), ana_hakedis_islendi=True,
        )

        self.yonetici = User.objects.create_superuser("yonetici", password="Panel-2026x")
        self.client.force_login(self.yonetici)

    def _sayfa(self):
        return self.client.get(self.ADRES).content.decode()

    def test_sim_stogu_durumlariyla_gorunur(self):
        icerik = self._sayfa()

        self.assertIn("SIM stoğu", icerik)
        self.assertIn("Bayiye Atandı", icerik)

    def test_bayideki_kartlar_unvaniyla_sayilir(self):
        icerik = self._sayfa()

        self.assertIn("fadil deneme", icerik)
        self.assertIn("5435609672", icerik)

    def test_beklenen_sim_kartlar_listelenir(self):
        icerik = self._sayfa()

        self.assertIn("Beklenen SIM kartlar", icerik)
        self.assertIn("Turkcell", icerik)

    def test_tedarikci_borcu_alacak_olarak_gorunur(self):
        icerik = self._sayfa()

        self.assertIn("Tedarikçilerden alacağım", icerik)
        self.assertIn("Melih Paşa", icerik)
        # Şablon Türkçe biçimde yazıyor: 4500,00
        self.assertIn("4500,00", icerik)

    def test_borcu_olmayan_bayi_alacak_listesine_girmez(self):
        """Liste tedarikçilere ait; borçlu bayi buraya karışmaz."""
        from decimal import Decimal

        from apps.finans.models import Cuzdan

        Cuzdan.objects.filter(bayi=self.bayi).update(borc=Decimal("999.00"))

        icerik = self._sayfa()

        self.assertNotIn("999,00", icerik)

    def test_ana_hakedis_kaynagina_gore_ayrilir(self):
        icerik = self._sayfa()

        self.assertIn("İşlenen ana hakediş", icerik)
        self.assertIn("400,00", icerik)

    def test_personel_olmayan_giremez(self):
        self.client.force_login(self.bayi)

        yanit = self.client.get(self.ADRES)

        self.assertEqual(yanit.status_code, 302)
