"""Dinamik form ve başvuru akışı testleri."""

import io
import shutil
import tempfile
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.basvurular.models import Basvuru, BasvuruBelgesi, BasvuruDurumu
from apps.finans.models import Cuzdan, KuralYonu, UcretKurali
from apps.katalog.models import (
    AlanTipi,
    BasvuruKategorisi,
    KategoriAlani,
    Operator,
    Tarife,
)


def kucuk_png():
    """Testlerde kullanılmak üzere geçerli, 1x1 piksellik PNG."""
    from PIL import Image

    tampon = io.BytesIO()
    Image.new("RGB", (1, 1), "white").save(tampon, format="PNG")
    return SimpleUploadedFile("kimlik.png", tampon.getvalue(), content_type="image/png")


# Testlerdeki yüklemeler projenin media/ klasörünü kirletmesin.
GECICI_MEDYA = tempfile.mkdtemp(prefix="aktivasyon-test-")


@override_settings(MEDIA_ROOT=GECICI_MEDYA)
class DinamikFormTestleri(TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(GECICI_MEDYA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.beklemede = BasvuruDurumu.objects.create(
            ad="Beklemede", slug="beklemede", baslangic_durumu=True, sira=10
        )
        self.aktif = BasvuruDurumu.objects.create(
            ad="Aktif", slug="aktif", hakedis_tetikler=True, sinyal_seviyesi=5, sira=50
        )

        self.bayi = User.objects.create_user("bayi", password="parola12345")
        self.cuzdan = Cuzdan.objects.create(bayi=self.bayi, bakiye=Decimal("500.00"))

        self.operator = Operator.objects.create(ad="Vodafone")
        self.kategori = BasvuruKategorisi.objects.create(ad="Faturalı Yeni Hat")
        self.kategori.operatorler.add(self.operator)
        self.tarife = Tarife.objects.create(
            operator=self.operator, ad="Red 20 GB"
        )
        self.tarife.kategoriler.add(self.kategori)

        for sira, (kod, etiket, cekirdek, zorunlu) in enumerate([
            ("isim", "İsim", "isim", True),
            ("soyisim", "Soy İsim", "soyisim", True),
            ("kimlik_no", "TC No", "kimlik_no", True),
            ("irtibat", "İletişim No", "irtibat", True),
        ], start=1):
            KategoriAlani.objects.create(
                kategori=self.kategori, kod=kod, etiket=etiket,
                cekirdek_alan=cekirdek, tip=AlanTipi.METIN, zorunlu=zorunlu, sira=sira,
            )
        KategoriAlani.objects.create(
            kategori=self.kategori, kod="aks", etiket="AKS Kodu",
            tip=AlanTipi.METIN, zorunlu=True, sira=10,
        )
        KategoriAlani.objects.create(
            kategori=self.kategori, kod="sim_imei", etiket="SIM / IMEI",
            tip=AlanTipi.METIN, zorunlu=False, sira=20,
        )
        KategoriAlani.objects.create(
            kategori=self.kategori, kod="kimlik_on", etiket="Kimlik Ön Yüz",
            tip=AlanTipi.RESIM, zorunlu=True, grup="Belgeler", sira=30,
        )

        self.client.force_login(self.bayi)

    def _url(self):
        return reverse("basvurular:yeni", args=[self.kategori.slug])

    def _gonderi(self, **degisiklikler):
        veri = {
            "operator": self.operator.pk,
            "tarife": self.tarife.pk,
            "kampanya": "",
            "musteri_tipi": "turk",
            "bayi_aciklamasi": "",
            "alan__isim": "Ayşe",
            "alan__soyisim": "Demir",
            "alan__kimlik_no": "12345678901",
            "alan__irtibat": "5551112233",
            "alan__aks": "AKS-1234",
            "alan__sim_imei": "8990011223344",
            "alan__kimlik_on": kucuk_png(),
        }
        veri.update(degisiklikler)
        return veri

    def test_form_kategoriye_gore_alanlari_uretir(self):
        yanit = self.client.get(self._url())
        self.assertEqual(yanit.status_code, 200)
        form = yanit.context["form"]
        self.assertIn("alan__aks", form.fields)
        self.assertIn("alan__sim_imei", form.fields)
        self.assertIn("alan__kimlik_on", form.fields)
        # Çekirdek alanlar da tanımdan geliyor, kodda sabit değil.
        self.assertIn("alan__isim", form.fields)

    def test_basvuru_gonderilir_ve_ek_bilgiler_kaydedilir(self):
        yanit = self.client.post(self._url(), self._gonderi())
        self.assertEqual(yanit.status_code, 302)

        basvuru = Basvuru.objects.get()
        self.assertEqual(basvuru.bayi, self.bayi)
        self.assertEqual(basvuru.durum, self.beklemede)
        self.assertEqual(basvuru.ek_bilgiler["aks"], "AKS-1234")
        self.assertEqual(basvuru.ek_bilgiler["sim_imei"], "8990011223344")
        # Çekirdek alanlar JSON'a değil kendi kolonlarına yazılır.
        self.assertEqual(basvuru.isim, "Ayşe")
        self.assertEqual(basvuru.kimlik_no, "12345678901")
        self.assertNotIn("isim", basvuru.ek_bilgiler)
        self.assertEqual(basvuru.belgeler.count(), 1)
        self.assertEqual(basvuru.belgeler.first().alan_kodu, "kimlik_on")

    def test_zorunlu_dinamik_alan_bos_birakilamaz(self):
        yanit = self.client.post(self._url(), self._gonderi(**{"alan__aks": ""}))
        self.assertEqual(yanit.status_code, 200)
        self.assertIn("alan__aks", yanit.context["form"].errors)
        self.assertEqual(Basvuru.objects.count(), 0)

    def test_kategoriye_ait_olmayan_operator_reddedilir(self):
        baska = Operator.objects.create(ad="Turkcell")
        yanit = self.client.post(self._url(), self._gonderi(operator=baska.pk))
        self.assertEqual(yanit.status_code, 200)
        self.assertIn("operator", yanit.context["form"].errors)

    def test_operatoru_uyusmayan_tarife_reddedilir(self):
        """Operatör kategoride geçerli ama seçilen tarife başka operatöre ait."""
        turkcell = Operator.objects.create(ad="Turkcell")
        self.kategori.operatorler.add(turkcell)

        yanit = self.client.post(self._url(), self._gonderi(operator=turkcell.pk))
        self.assertEqual(yanit.status_code, 200)
        self.assertIn("tarife", yanit.context["form"].errors)
        self.assertEqual(Basvuru.objects.count(), 0)

    def test_dogrulama_deseni_uygulanir(self):
        KategoriAlani.objects.filter(kod="aks").update(dogrulama_deseni=r"^AKS-\d{4}$")
        yanit = self.client.post(self._url(), self._gonderi(**{"alan__aks": "yanlis"}))
        self.assertIn("alan__aks", yanit.context["form"].errors)

    def test_basvuru_girisinde_para_islenmez(self):
        UcretKurali.objects.create(
            ad="Hakediş", yon=KuralYonu.HAKEDIS, tutar=Decimal("150.00"),
            kategori=self.kategori, tetikleyici_durum=self.aktif,
        )
        self.client.post(self._url(), self._gonderi())

        self.cuzdan.refresh_from_db()
        self.assertEqual(self.cuzdan.bakiye, Decimal("500.00"))
        self.assertFalse(Basvuru.objects.get().para_islendi)

    def test_bayi_baskasinin_basvurusunu_goremez(self):
        baskasi = User.objects.create_user("digerbayi", password="parola12345")
        Cuzdan.objects.create(bayi=baskasi)
        basvuru = Basvuru.objects.create(
            bayi=baskasi, kategori=self.kategori, operator=self.operator,
            tarife=self.tarife, kimlik_no="99999999999", isim="Gizli", soyisim="Kayıt",
            irtibat="5559998877", durum=self.beklemede,
        )
        yanit = self.client.get(reverse("basvurular:detay", args=[basvuru.referans_no]))
        self.assertEqual(yanit.status_code, 404)

    def test_liste_arama_ile_filtrelenir(self):
        self.client.post(self._url(), self._gonderi())
        Basvuru.objects.create(
            bayi=self.bayi, kategori=self.kategori, operator=self.operator,
            tarife=self.tarife, kimlik_no="55555555555", isim="Mehmet", soyisim="Kaya",
            irtibat="5321112233", durum=self.beklemede,
        )
        yanit = self.client.get(reverse("basvurular:liste"), {"q": "Ayşe"})
        self.assertEqual(len(yanit.context["sayfa"].object_list), 1)

    def test_htmx_tarife_secenekleri_operatore_gore_gelir(self):
        yanit = self.client.get(
            reverse("basvurular:tarifeler"),
            {"kategori": self.kategori.slug, "operator": self.operator.pk},
        )
        self.assertContains(yanit, "Red 20 GB")

    def test_giris_yapmadan_erisim_engellenir(self):
        self.client.logout()
        for ad in ["basvurular:liste", "basvurular:kategori-sec", "bayi:panel", "bayi:cuzdan"]:
            yanit = self.client.get(reverse(ad))
            self.assertEqual(yanit.status_code, 302, ad)
            self.assertIn("/giris-yap/", yanit["Location"], ad)

    def test_anasayfa_herkese_acik(self):
        self.client.logout()
        yanit = self.client.get(reverse("bayi:anasayfa"))
        self.assertEqual(yanit.status_code, 200)
        self.assertContains(yanit, "Faturalı Yeni Hat")


class UrlYapisiTestleri(TestCase):
    """URL'ler okunur olmalı: kategori slug'ı, başvuru referans numarası."""

    def setUp(self):
        self.durum = BasvuruDurumu.objects.create(
            ad="Beklemede", slug="beklemede", baslangic_durumu=True
        )
        self.bayi = User.objects.create_user("bayi", password="parola12345")
        Cuzdan.objects.create(bayi=self.bayi)
        self.operator = Operator.objects.create(ad="Türk Telekom")
        self.kategori = BasvuruKategorisi.objects.create(ad="Faturalı Yeni Hat")
        self.client.force_login(self.bayi)

    def test_turkce_slug_harf_dusurmez(self):
        """Django slugify'ı 'Faturalı' -> 'fatural' yapıyordu."""
        self.assertEqual(self.kategori.slug, "faturali-yeni-hat")
        self.assertEqual(self.operator.slug, "turk-telekom")

        for ad, beklenen in [
            ("MNT / Numara Taşıma", "mnt-numara-tasima"),
            ("Şebeke İçi Geçiş", "sebeke-ici-gecis"),
            ("Kontörlü Yeni Hat", "kontorlu-yeni-hat"),
        ]:
            self.assertEqual(BasvuruKategorisi.objects.create(ad=ad).slug, beklenen)

    def test_form_urlinde_sorgu_dizesi_yok(self):
        url = reverse("basvurular:yeni", args=[self.kategori.slug])
        self.assertEqual(url, "/basvuru/yeni/faturali-yeni-hat/")
        self.assertNotIn("?", url)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_detay_urli_referans_numarasi_kullanir(self):
        basvuru = Basvuru.objects.create(
            bayi=self.bayi, kategori=self.kategori, operator=self.operator,
            kimlik_no="12345678901", isim="Ayşe", soyisim="Demir",
            irtibat="5551112233", durum=self.durum,
        )
        url = reverse("basvurular:detay", args=[basvuru.referans_no])
        self.assertEqual(url, f"/basvuru/{basvuru.referans_no}/")
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_gecersiz_referans_desene_uymaz(self):
        """Dönüştürücünün deseni dar; sabit yollarla çakışma olmaz."""
        self.assertEqual(self.client.get("/basvuru/kucukharf1/").status_code, 404)
        self.assertEqual(self.client.get("/basvuru/yeni/").status_code, 200)

    def test_bilinmeyen_kategori_slugu_404(self):
        self.assertEqual(self.client.get("/basvuru/yeni/olmayan-kategori/").status_code, 404)


@override_settings(MEDIA_ROOT=GECICI_MEDYA)
class BelgeErisimTestleri(TestCase):
    """Kimlik ve pasaport görüntüleri kişisel veridir.

    Yalnızca başvuruyu giren bayi ve yetkili personel görebilir; doğrudan
    MEDIA_URL üzerinden erişim üretimde hiç açılmaz.
    """

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(GECICI_MEDYA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        from apps.basvurular.models import BasvuruBelgesi
        from apps.finans.models import Cuzdan

        self.durum = BasvuruDurumu.objects.create(
            ad="Beklemede", slug="beklemede", baslangic_durumu=True
        )
        self.sahibi = User.objects.create_user("sahibi", password="parola12345")
        self.digeri = User.objects.create_user("digeri", password="parola12345")
        self.personel = User.objects.create_user(
            "personel", password="parola12345", is_staff=True
        )
        for k in (self.sahibi, self.digeri):
            Cuzdan.objects.create(bayi=k)

        self.operator = Operator.objects.create(ad="Vodafone")
        self.kategori = BasvuruKategorisi.objects.create(ad="Faturalı Yeni Hat")
        self.basvuru = Basvuru.objects.create(
            bayi=self.sahibi, kategori=self.kategori, operator=self.operator,
            kimlik_no="12345678901", isim="Ayşe", soyisim="Demir",
            irtibat="5551112233", durum=self.durum,
        )
        self.belge = BasvuruBelgesi.objects.create(
            basvuru=self.basvuru, alan_kodu="kimlik_on",
            etiket="Kimlik Ön Yüz", dosya=kucuk_png(),
        )
        self.url = self.belge.get_absolute_url()

    def test_sahibi_belgeyi_gorebilir(self):
        self.client.force_login(self.sahibi)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_personel_belgeyi_gorebilir(self):
        self.client.force_login(self.personel)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_baska_bayi_belgeyi_goremez(self):
        self.client.force_login(self.digeri)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_giris_yapmayan_goremez(self):
        yanit = self.client.get(self.url)
        self.assertEqual(yanit.status_code, 302)
        self.assertIn("/giris-yap/", yanit["Location"])

    def test_belge_ozel_olarak_isaretlenir(self):
        """Paylaşımlı önbellekler kişisel veriyi saklamamalı."""
        self.client.force_login(self.sahibi)
        yanit = self.client.get(self.url)
        self.assertIn("private", yanit["Cache-Control"])
        self.assertEqual(yanit["X-Content-Type-Options"], "nosniff")

    def test_uretimde_dogrudan_medya_yolu_acilmaz(self):
        """Kimlik klasörü hiçbir URL desenine düşmez.

        Tarife, kampanya ve operatör görselleri `/media/` altından sunulur
        (`apps.medya`); `basvuru/` bilinçli olarak o listenin dışındadır.
        """
        from django.urls import Resolver404, resolve

        with override_settings(DEBUG=False):
            with self.assertRaises(Resolver404):
                resolve("/media/basvuru/2026/09/kimlik.png")


@override_settings(MEDIA_ROOT=GECICI_MEDYA)
class BelgeYuklemeGuvenligiTestleri(TestCase):
    """Bayi yüklediği belgeyi personel açar; tarayıcıda çalışan dosya yüklenemez."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(GECICI_MEDYA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        from apps.finans.models import Cuzdan

        BasvuruDurumu.objects.create(ad="Beklemede", slug="beklemede", baslangic_durumu=True)
        self.bayi = User.objects.create_user("bayi", password="parola12345")
        Cuzdan.objects.create(bayi=self.bayi)

        self.operator = Operator.objects.create(ad="Vodafone")
        self.kategori = BasvuruKategorisi.objects.create(
            ad="Faturalı Yeni Hat", tarife_zorunlu=False
        )
        self.kategori.operatorler.add(self.operator)
        KategoriAlani.objects.create(
            kategori=self.kategori, kod="ikametgah", etiket="İkametgah",
            tip=AlanTipi.DOSYA, zorunlu=True, sira=10,
        )
        self.client.force_login(self.bayi)

    def _gonderi(self, dosya):
        return {
            "operator": self.operator.pk, "tarife": "", "kampanya": "",
            "musteri_tipi": "turk", "bayi_aciklamasi": "",
            "alan__ikametgah": dosya,
        }

    def _url(self):
        return reverse("basvurular:yeni", args=[self.kategori.slug])

    def test_html_dosyasi_reddedilir(self):
        kotucul = SimpleUploadedFile(
            "evrak.html", b"<script>alert(document.cookie)</script>", content_type="text/html"
        )
        yanit = self.client.post(self._url(), self._gonderi(kotucul))
        self.assertEqual(yanit.status_code, 200)
        self.assertIn("alan__ikametgah", yanit.context["form"].errors)
        self.assertEqual(Basvuru.objects.count(), 0)

    def test_svg_dosyasi_reddedilir(self):
        svg = SimpleUploadedFile(
            "evrak.svg",
            b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
            content_type="image/svg+xml",
        )
        yanit = self.client.post(self._url(), self._gonderi(svg))
        self.assertIn("alan__ikametgah", yanit.context["form"].errors)

    def test_uzantisi_degistirilmis_dosya_reddedilir(self):
        """İçerik HTML ama adı .png: uzantı denetimi tek başına yetmez."""
        sahte = SimpleUploadedFile(
            "evrak.png", b"<script>alert(1)</script>", content_type="image/png"
        )
        yanit = self.client.post(self._url(), self._gonderi(sahte))
        self.assertIn("alan__ikametgah", yanit.context["form"].errors)
        self.assertIn("uyuşmuyor", str(yanit.context["form"].errors))

    def test_gecerli_pdf_kabul_edilir(self):
        pdf = SimpleUploadedFile(
            "ikametgah.pdf", b"%PDF-1.4\n%%EOF\n", content_type="application/pdf"
        )
        yanit = self.client.post(self._url(), self._gonderi(pdf))
        self.assertEqual(yanit.status_code, 302)
        self.assertEqual(Basvuru.objects.count(), 1)

    def test_pdf_gomulu_gosterilmez_indirilir(self):
        pdf = SimpleUploadedFile(
            "ikametgah.pdf", b"%PDF-1.4\n%%EOF\n", content_type="application/pdf"
        )
        self.client.post(self._url(), self._gonderi(pdf))
        belge = Basvuru.objects.get().belgeler.get()

        yanit = self.client.get(belge.get_absolute_url())
        self.assertEqual(yanit.status_code, 200)
        self.assertIn("attachment", yanit["Content-Disposition"])
        self.assertIn("sandbox", yanit["Content-Security-Policy"])

    def test_resim_gomulu_gosterilebilir(self):
        KategoriAlani.objects.create(
            kategori=self.kategori, kod="kimlik_on", etiket="Kimlik Ön",
            tip=AlanTipi.RESIM, zorunlu=False, sira=20,
        )
        veri = self._gonderi(
            SimpleUploadedFile("ikametgah.pdf", b"%PDF-1.4\n%%EOF\n", content_type="application/pdf")
        )
        veri["alan__kimlik_on"] = kucuk_png()
        self.client.post(self._url(), veri)

        belge = Basvuru.objects.get().belgeler.get(alan_kodu="kimlik_on")
        yanit = self.client.get(belge.get_absolute_url())
        self.assertNotIn("attachment", yanit.get("Content-Disposition", ""))
        # Yüklenen PNG kaydedilirken WebP'ye çevrildi.
        self.assertEqual(yanit["Content-Type"], "image/webp")


@override_settings(MEDIA_ROOT=GECICI_MEDYA)
class BelgeSilmeTestleri(TestCase):
    """İşi biten başvurunun kimlik görüntüleri hemen silinir."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(GECICI_MEDYA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        from apps.finans.models import Cuzdan

        self.beklemede = BasvuruDurumu.objects.create(
            ad="Beklemede", slug="beklemede", baslangic_durumu=True
        )
        self.aktif = BasvuruDurumu.objects.create(
            ad="Aktif", slug="aktif", hakedis_tetikler=True, belgeleri_sil=True
        )
        self.iptal = BasvuruDurumu.objects.create(
            ad="İptal", slug="iptal", olumsuz_sonuc=True, belgeleri_sil=True
        )
        self.hatali = BasvuruDurumu.objects.create(
            ad="Hatalı", slug="hatali", olumsuz_sonuc=True, belgeleri_sil=False
        )
        self.eksik = BasvuruDurumu.objects.create(
            ad="Eksik Evrak", slug="eksik", bayi_duzenleyebilir=True
        )

        self.bayi = User.objects.create_user("bayi", password="parola12345")
        Cuzdan.objects.create(bayi=self.bayi)
        self.operator = Operator.objects.create(ad="Vodafone")
        self.kategori = BasvuruKategorisi.objects.create(ad="Faturalı Yeni Hat")

    def _basvuru_ve_belge(self):
        basvuru = Basvuru.objects.create(
            bayi=self.bayi, kategori=self.kategori, operator=self.operator,
            isim="Ayşe", soyisim="Demir", kimlik_no="1",
            irtibat="5551112233", durum=self.beklemede,
        )
        belge = BasvuruBelgesi.objects.create(
            basvuru=basvuru, alan_kodu="kimlik_on",
            etiket="Kimlik Ön", dosya=kucuk_png(),
        )
        return basvuru, belge, belge.dosya.path

    def test_aktif_olunca_belgeler_hemen_silinir(self):
        import os

        basvuru, belge, yol = self._basvuru_ve_belge()
        self.assertTrue(os.path.exists(yol))

        # Dosya silme commit sonrasına ertelenir; testte tetiklenmesi gerekir.
        with self.captureOnCommitCallbacks(execute=True):
            basvuru.durum = self.aktif
            basvuru.save()

        basvuru.refresh_from_db()
        self.assertTrue(basvuru.belgeler_silindi)
        self.assertFalse(BasvuruBelgesi.objects.filter(pk=belge.pk).exists())
        self.assertFalse(os.path.exists(yol))
        # Başvuru kaydı ve para geçmişi durmalı.
        self.assertTrue(Basvuru.objects.filter(pk=basvuru.pk).exists())

    def test_iptal_olunca_da_silinir(self):
        import os

        basvuru, belge, yol = self._basvuru_ve_belge()
        with self.captureOnCommitCallbacks(execute=True):
            basvuru.durum = self.iptal
            basvuru.save()

        basvuru.refresh_from_db()
        self.assertTrue(basvuru.belgeler_silindi)
        self.assertFalse(os.path.exists(yol))

    def test_hatali_durumunda_silinmez(self):
        """Düzeltilip yeniden denenebilecek durumlarda belge durmalı."""
        import os

        basvuru, belge, yol = self._basvuru_ve_belge()
        basvuru.durum = self.hatali
        basvuru.save()

        basvuru.refresh_from_db()
        self.assertFalse(basvuru.belgeler_silindi)
        self.assertTrue(BasvuruBelgesi.objects.filter(pk=belge.pk).exists())
        self.assertTrue(os.path.exists(yol))

    def test_eksik_evrakta_silinmez(self):
        basvuru, belge, _ = self._basvuru_ve_belge()
        basvuru.durum = self.eksik
        basvuru.save()

        self.assertTrue(BasvuruBelgesi.objects.filter(pk=belge.pk).exists())

    def test_ara_durumlarda_silinmez(self):
        basvuru, belge, _ = self._basvuru_ve_belge()
        self.assertTrue(BasvuruBelgesi.objects.filter(pk=belge.pk).exists())

    def test_silme_iki_kez_calismaz(self):
        basvuru, _, _ = self._basvuru_ve_belge()
        with self.captureOnCommitCallbacks(execute=True):
            basvuru.durum = self.aktif
            basvuru.save()
            basvuru.durum = self.iptal
            basvuru.save()

        basvuru.refresh_from_db()
        self.assertTrue(basvuru.belgeler_silindi)

    def test_silinen_belge_detayda_aciklaniyor(self):
        basvuru, _, _ = self._basvuru_ve_belge()
        with self.captureOnCommitCallbacks(execute=True):
            basvuru.durum = self.aktif
            basvuru.save()

        self.client.force_login(self.bayi)
        yanit = self.client.get(
            reverse("basvurular:detay", args=[basvuru.referans_no])
        )
        self.assertContains(yanit, "Bu başvurunun işi tamamlandı")


    def test_geri_alinan_islemde_dosya_silinmez(self):
        """Transaction geri alınırsa dosya da yerinde kalmalı."""
        import os
        from django.db import transaction

        basvuru, belge, yol = self._basvuru_ve_belge()

        try:
            with transaction.atomic():
                basvuru.durum = self.aktif
                basvuru.save()
                raise RuntimeError("iptal")
        except RuntimeError:
            pass

        self.assertTrue(os.path.exists(yol))
        self.assertTrue(BasvuruBelgesi.objects.filter(pk=belge.pk).exists())


class GorselKucultmeTestleri(TestCase):
    """Telefon fotoğrafları küçültülüp WebP'ye çevrilir."""

    def _foto(self, ad="kimlik.jpg", boyut=(3000, 2000), bicim="JPEG"):
        from PIL import Image

        tampon = io.BytesIO()
        gorsel = Image.new("RGB", boyut, (240, 238, 232))
        # Düz renk çok iyi sıkışır; gerçekçi olması için desen ekle.
        for x in range(0, boyut[0], 11):
            for y in range(0, boyut[1], 97):
                gorsel.putpixel((x, y), (x % 255, y % 255, 90))
        gorsel.save(tampon, bicim, quality=95)
        icerik = tampon.getvalue()
        tur = "image/jpeg" if bicim == "JPEG" else f"image/{bicim.lower()}"
        return SimpleUploadedFile(ad, icerik, content_type=tur), len(icerik)

    def test_buyuk_foto_kucultulur_ve_webp_olur(self):
        from apps.basvurular.gorsel import gorseli_kucult
        from PIL import Image

        dosya, asil_boyut = self._foto()
        sonuc = gorseli_kucult(dosya)

        self.assertTrue(sonuc.name.endswith(".webp"))
        self.assertLess(sonuc.size, asil_boyut)

        sonuc.seek(0)
        with Image.open(sonuc) as g:
            self.assertEqual(g.format, "WEBP")
            self.assertLessEqual(max(g.size), 1000)

    def test_pdf_dokunulmadan_gecer(self):
        from apps.basvurular.gorsel import gorseli_kucult

        pdf = SimpleUploadedFile(
            "ikametgah.pdf", b"%PDF-1.4\n%%EOF\n", content_type="application/pdf"
        )
        sonuc = gorseli_kucult(pdf)
        self.assertIs(sonuc, pdf)
        self.assertTrue(sonuc.name.endswith(".pdf"))

    def test_kucuk_gorsel_buyutulmez(self):
        from apps.basvurular.gorsel import gorseli_kucult
        from PIL import Image

        dosya, _ = self._foto(boyut=(400, 300))
        sonuc = gorseli_kucult(dosya)

        sonuc.seek(0)
        with Image.open(sonuc) as g:
            self.assertEqual(g.size, (400, 300))

    def test_bozuk_dosyada_ozgun_dosya_korunur(self):
        """Dönüşüm başarısız olsa da bayinin yüklemesi kaybolmamalı."""
        from apps.basvurular.gorsel import gorseli_kucult

        bozuk = SimpleUploadedFile("kimlik.png", b"bu bir resim degil", content_type="image/png")
        sonuc = gorseli_kucult(bozuk)
        self.assertIs(sonuc, bozuk)

    def test_exif_donme_uygulanip_veri_temizlenir(self):
        """Telefon fotoğrafı yan yatmamalı, konum bilgisi de taşınmamalı."""
        from apps.basvurular.gorsel import gorseli_kucult
        from PIL import Image

        tampon = io.BytesIO()
        gorsel = Image.new("RGB", (600, 300), (200, 100, 100))
        exif = Image.Exif()
        exif[274] = 6  # 90 derece döndür
        gorsel.save(tampon, "JPEG", exif=exif)
        dosya = SimpleUploadedFile(
            "kimlik.jpg", tampon.getvalue(), content_type="image/jpeg"
        )

        sonuc = gorseli_kucult(dosya)
        sonuc.seek(0)
        with Image.open(sonuc) as g:
            # Döndürme uygulandığı için en ve boy yer değiştirmiş olmalı.
            self.assertEqual(g.size, (300, 600))
            self.assertFalse(g.getexif())


class SimAlacakTestleri(TestCase):
    """SIM karşılığı: işlemi tedarikçi üstlendiyse alacak ondan."""

    def setUp(self):
        from apps.bayi.models import BayiProfili
        from apps.finans.models import Cuzdan
        from apps.katalog.models import Operator

        self.beklemede = BasvuruDurumu.objects.create(
            ad="Beklemede", slug="beklemede", baslangic_durumu=True
        )
        self.aktif = BasvuruDurumu.objects.create(
            ad="Aktif", slug="aktif", hakedis_tetikler=True
        )
        self.turkcell = Operator.objects.create(ad="Turkcell")
        self.vodafone = Operator.objects.create(ad="Vodafone")

        self.simli = BasvuruKategorisi.objects.create(
            ad="Kontörlü Yeni Hat", sim_karsiligi_gerekir=True
        )
        self.simsiz = BasvuruKategorisi.objects.create(
            ad="ADSL", sim_karsiligi_gerekir=False
        )

        self.bayi = User.objects.create_user("bayi", password="parola12345")
        Cuzdan.objects.create(bayi=self.bayi)
        self.tedarikci = User.objects.create_user("tedarik", password="parola12345")
        Cuzdan.objects.create(bayi=self.tedarikci, bakiye=Decimal("9000.00"))
        BayiProfili.objects.create(
            kullanici=self.tedarikci, unvan="Ege Tedarik",
            bayi_mi=False, tedarikci_mi=True,
        )

    def _basvuru(self, kategori, operator, tedarikci=None, aktif=True):
        b = Basvuru.objects.create(
            bayi=self.bayi, kategori=kategori, operator=operator,
            tedarikci=tedarikci, isim="Ayşe", soyisim="Demir",
            kimlik_no="1", irtibat="5551112233", durum=self.beklemede,
        )
        if aktif:
            b.durum = self.aktif
            b.save()
        return b

    def test_tedarikcisiz_islem_operatorden_alacak(self):
        b = self._basvuru(self.simli, self.turkcell)
        self.assertEqual(b.sim_karsiligi_kimden, "Turkcell")

    def test_tedarikciye_satilan_islem_tedarikciden_alacak(self):
        b = self._basvuru(self.simli, self.turkcell, tedarikci=self.tedarikci)
        self.assertEqual(b.sim_karsiligi_kimden, "Ege Tedarik")

    def test_rapor_tarafa_gore_ayirir(self):
        from apps.basvurular.raporlar import sim_alacaklari

        self._basvuru(self.simli, self.turkcell)
        self._basvuru(self.simli, self.turkcell)
        self._basvuru(self.simli, self.vodafone)
        self._basvuru(self.simli, self.turkcell, tedarikci=self.tedarikci)

        rapor = sim_alacaklari()
        self.assertEqual(rapor["toplam"], 4)
        ozet = {s["ad"]: (s["tur"], s["adet"]) for s in rapor["satirlar"]}
        self.assertEqual(ozet["Turkcell"], ("Operatör", 2))
        self.assertEqual(ozet["Vodafone"], ("Operatör", 1))
        self.assertEqual(ozet["Ege Tedarik"], ("Tedarikçi", 1))

    def test_sim_gerektirmeyen_kategori_sayilmaz(self):
        from apps.basvurular.raporlar import sim_alacaklari

        self._basvuru(self.simsiz, self.turkcell)
        self.assertEqual(sim_alacaklari()["toplam"], 0)

    def test_tamamlanmamis_islem_sayilmaz(self):
        from apps.basvurular.raporlar import sim_alacaklari

        self._basvuru(self.simli, self.turkcell, aktif=False)
        self.assertEqual(sim_alacaklari()["toplam"], 0)

    def test_karsiligi_alinan_islem_dususur(self):
        from apps.basvurular.raporlar import sim_alacaklari

        b = self._basvuru(self.simli, self.turkcell)
        self.assertEqual(sim_alacaklari()["toplam"], 1)

        b.sim_karsiligi_alindi = True
        b.save()
        self.assertEqual(sim_alacaklari()["toplam"], 0)
        b.refresh_from_db()
        self.assertIsNotNone(b.sim_karsiligi_tarihi)

    def test_isaret_geri_alininca_tarih_temizlenir(self):
        b = self._basvuru(self.simli, self.turkcell)
        b.sim_karsiligi_alindi = True
        b.save()
        b.sim_karsiligi_alindi = False
        b.save()

        b.refresh_from_db()
        self.assertIsNone(b.sim_karsiligi_tarihi)


class AdminTarifeSecimiTestleri(TestCase):
    """Yanlış kategorinin tarifesi seçim kutusunda hiç görünmemeli."""

    def setUp(self):
        from apps.finans.models import Cuzdan
        from apps.katalog.models import Kampanya, Operator, Tarife

        BasvuruDurumu.objects.create(
            ad="Beklemede", slug="beklemede", baslangic_durumu=True
        )
        self.operator = Operator.objects.create(ad="Vodafone")
        self.kont = BasvuruKategorisi.objects.create(ad="Kontörlü Yeni Hat")
        self.mnt = BasvuruKategorisi.objects.create(ad="MNT")

        self.dogru = Tarife.objects.create(
            operator=self.operator, ad="Gençlik"
        )
        self.dogru.kategoriler.add(self.kont)
        self.yanlis = Tarife.objects.create(
            operator=self.operator, ad="Uyumlu 12 GB"
        )
        self.yanlis.kategoriler.add(self.mnt)
        self.kampanya = Kampanya.objects.create(tarife=self.dogru, ad="İlk 3 ay")
        self.yanlis_kampanya = Kampanya.objects.create(
            tarife=self.yanlis, ad="Taşıma kampanyası"
        )

        bayi = User.objects.create_user("bayi", password="parola12345")
        Cuzdan.objects.create(bayi=bayi)
        self.basvuru = Basvuru.objects.create(
            bayi=bayi, kategori=self.kont, operator=self.operator,
            isim="Ayşe", soyisim="Demir", kimlik_no="1",
            irtibat="5551112233", durum=BasvuruDurumu.objects.first(),
        )

        self.yonetici = User.objects.create_superuser("yon", "y@x.com", "parola12345")
        self.client.force_login(self.yonetici)

    def _secenekler(self, alan):
        import re

        yanit = self.client.get(
            f"/yonetim/basvurular/basvuru/{self.basvuru.pk}/change/"
        )
        blok = re.search(
            rf'<select[^>]*name="{alan}".*?</select>', yanit.content.decode(), re.S
        )
        return blok.group(0) if blok else ""

    def test_baska_kategorinin_tarifesi_listelenmez(self):
        secim = self._secenekler("tarife")
        self.assertIn("Gençlik", secim)
        self.assertNotIn("Uyumlu 12 GB", secim)

    def test_baska_kategorinin_kampanyasi_listelenmez(self):
        secim = self._secenekler("kampanya")
        self.assertIn("İlk 3 ay", secim)
        self.assertNotIn("Taşıma kampanyası", secim)

    def test_tarife_adinda_kategori_gorunur(self):
        """Seçim kutusunda hangi kategoriye ait olduğu okunabilmeli."""
        self.assertEqual(
            str(self.dogru), "Kontörlü Yeni Hat · Vodafone · Gençlik"
        )

    def test_yanlis_tarife_yine_de_reddedilir(self):
        """Kutu daraltıldı ama sunucu doğrulaması da yerinde durmalı."""
        from django.core.exceptions import ValidationError

        self.basvuru.tarife = self.yanlis
        with self.assertRaises(ValidationError):
            self.basvuru.full_clean(exclude=["referans_no"])


class BasvurudaKampanyaSecimi(TestCase):
    """Kampanya başvuru formunda seçilir; tarife kataloğunda görünmez.

    Kutuya yalnızca seçili tarifenin geçerli kampanyaları girer — SIM kart
    kutusundaki kuralın aynısı: listeye yalnızca seçilebilecek olan girer.
    """

    def setUp(self):
        import datetime

        from django.contrib.auth.models import User

        from apps.basvurular.models import BasvuruDurumu
        from apps.finans.models import Cuzdan
        from apps.katalog.models import (
            AlanTipi, BasvuruKategorisi, Kampanya, KategoriAlani, Operator, Tarife,
        )

        BasvuruDurumu.objects.create(
            ad="Beklemede", slug="beklemede", baslangic_durumu=True
        )
        self.bayi = User.objects.create_user("bayi", password="parola12345")
        Cuzdan.objects.create(bayi=self.bayi)

        self.operator = Operator.objects.create(ad="Turkcell")
        self.kategori = BasvuruKategorisi.objects.create(ad="Faturalı Yeni Hat")
        KategoriAlani.objects.create(
            kategori=self.kategori, kod="isim", etiket="İsim",
            cekirdek_alan="isim", tip=AlanTipi.METIN, zorunlu=True, sira=1,
        )

        self.tarife = Tarife.objects.create(
            operator=self.operator, ad="Platinum 30 GB"
        )
        self.tarife.kategoriler.add(self.kategori)
        self.oteki_tarife = Tarife.objects.create(
            operator=self.operator, ad="Ekonomi 5 GB"
        )
        self.oteki_tarife.kategoriler.add(self.kategori)
        self.kampanya = Kampanya.objects.create(
            tarife=self.tarife, ad="İlk 3 ay yarı fiyat"
        )
        self.oteki_kampanya = Kampanya.objects.create(
            tarife=self.oteki_tarife, ad="Ekonomiye özel hediye"
        )
        self.gecmis = Kampanya.objects.create(
            tarife=self.tarife, ad="Geçen yılki kampanya",
            bitis_tarihi=datetime.date(2020, 1, 1),
        )
        self.client.force_login(self.bayi)

    def _kutu(self, veri=None):
        import re

        from django.urls import reverse

        adres = reverse("basvurular:yeni", args=[self.kategori.slug])
        yanit = self.client.post(adres, veri) if veri else self.client.get(adres)
        blok = re.search(
            r'<select[^>]*name="kampanya".*?</select>', yanit.content.decode(), re.S
        )
        return blok.group(0) if blok else ""

    def test_tarife_secilmeden_kampanya_listelenmez(self):
        """Kategorinin bütün kampanyaları dökülüyordu; artık önce tarife."""
        kutu = self._kutu()

        self.assertIn("Önce tarife seç", kutu)
        self.assertNotIn("İlk 3 ay yarı fiyat", kutu)

    def test_secili_tarifenin_kampanyasi_listelenir(self):
        kutu = self._kutu({"operator": self.operator.pk, "tarife": self.tarife.pk})

        self.assertIn("İlk 3 ay yarı fiyat", kutu)
        self.assertNotIn("Ekonomiye özel hediye", kutu)

    def test_suresi_gecmis_kampanya_listelenmez(self):
        kutu = self._kutu({"operator": self.operator.pk, "tarife": self.tarife.pk})

        self.assertNotIn("Geçen yılki kampanya", kutu)

    def test_htmx_kutusu_tarifeye_gore_gelir(self):
        from django.urls import reverse

        yanit = self.client.get(
            reverse("basvurular:kampanyalar"), {"tarife": self.tarife.pk}
        )
        icerik = yanit.content.decode()

        self.assertIn("İlk 3 ay yarı fiyat", icerik)
        self.assertNotIn("Ekonomiye özel hediye", icerik)
        self.assertNotIn("Geçen yılki kampanya", icerik)

    def test_baska_tarifenin_kampanyasi_sunucuda_reddedilir(self):
        """Kutu daraltıldı ama sunucu doğrulaması da yerinde durmalı."""
        from apps.basvurular.forms import BasvuruFormu

        form = BasvuruFormu(
            data={
                "operator": self.operator.pk,
                "tarife": self.tarife.pk,
                "kampanya": self.oteki_kampanya.pk,
                "musteri_tipi": "turk",
                "alan__isim": "Ayşe",
            },
            kategori=self.kategori,
            bayi=self.bayi,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("kampanya", form.errors)

    def test_suresi_gecmis_kampanya_sunucuda_reddedilir(self):
        from apps.basvurular.forms import BasvuruFormu

        form = BasvuruFormu(
            data={
                "operator": self.operator.pk,
                "tarife": self.tarife.pk,
                "kampanya": self.gecmis.pk,
                "musteri_tipi": "turk",
                "alan__isim": "Ayşe",
            },
            kategori=self.kategori,
            bayi=self.bayi,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("kampanya", form.errors)


class TarifeKisaAciklamaUyarisi(TestCase):
    """Tarifenin kısa açıklaması seçildiği anda bayinin karşısına çıkar.

    Atlanmaması gereken bir uyarıyı listede küçük yazıyla göstermek
    yetmiyordu; bayi tezgâh başında ve aceleyle giriyor.
    """

    def setUp(self):
        from django.contrib.auth.models import User

        from apps.basvurular.models import BasvuruDurumu
        from apps.finans.models import Cuzdan
        from apps.katalog.models import (
            AlanTipi, BasvuruKategorisi, KategoriAlani, Operator, Tarife,
        )

        BasvuruDurumu.objects.create(
            ad="Beklemede", slug="beklemede", baslangic_durumu=True
        )
        self.bayi = User.objects.create_user("bayi", password="parola12345")
        Cuzdan.objects.create(bayi=self.bayi)

        self.operator = Operator.objects.create(ad="Turkcell")
        self.kategori = BasvuruKategorisi.objects.create(ad="Faturalı Yeni Hat")
        KategoriAlani.objects.create(
            kategori=self.kategori, kod="isim", etiket="İsim",
            cekirdek_alan="isim", tip=AlanTipi.METIN, zorunlu=True, sira=1,
        )

        self.uyarili = Tarife.objects.create(
            operator=self.operator, ad="Platinum 30 GB",
            kisa_aciklama="Bu tarifede taahhüt 24 ay; müşteriye söylemeyi unutma.",
        )
        self.uyarili.kategoriler.add(self.kategori)
        self.sade = Tarife.objects.create(operator=self.operator, ad="Ekonomi 5 GB")
        self.sade.kategoriler.add(self.kategori)

        self.client.force_login(self.bayi)

    def _sayfa(self):
        from django.urls import reverse

        adres = reverse("basvurular:yeni", args=[self.kategori.slug])
        return self.client.get(adres).content.decode()

    def test_uyari_secenekle_birlikte_gelir(self):
        icerik = self._sayfa()

        self.assertIn("taahhüt 24 ay", icerik)
        self.assertIn("data-uyari", icerik)

    def test_uyari_kutusu_sayfada_hazir_durur(self):
        icerik = self._sayfa()

        self.assertIn('id="tarife-uyarisi"', icerik)
        self.assertIn("Tamam", icerik)
        # Kutu boş açılır; metni seçime göre JavaScript doldurur.
        self.assertIn('id="tarife-uyari-metni"', icerik)

    def test_kisa_aciklamasi_olmayan_tarifede_uyari_tasinmaz(self):
        import re

        icerik = self._sayfa()
        sade_secenek = re.search(
            r'<option value="%s".*?</option>' % self.sade.pk, icerik, re.S
        ).group(0)

        self.assertNotIn("data-uyari", sade_secenek)

    def test_htmx_kutusunda_da_uyari_gelir(self):
        """Tarife listesi operatör seçilince HTMX ile yenileniyor."""
        from django.urls import reverse

        yanit = self.client.get(
            reverse("basvurular:tarifeler"),
            {"kategori": self.kategori.slug, "operator": self.operator.pk},
        )

        self.assertIn("taahhüt 24 ay", yanit.content.decode())


class BakiyeYetmezseBasvuruGirilemez(TestCase):
    """Bedeli olan işlem parası olmayana verilmez.

    Bayiden tahsil edilen bir tutar tanımlıysa bayi o parayı cüzdanında
    bulundurmadan başvuru giremez. Kapı üç yerde: kategori ekranı kategoriyi
    kapalı gösterir, form açılışı geri çevirir, gönderim sunucuda reddedilir.
    """

    def setUp(self):
        from decimal import Decimal

        from django.contrib.auth.models import User

        from apps.basvurular.models import BasvuruDurumu
        from apps.finans.models import Cuzdan, KuralYonu, UcretKurali
        from apps.katalog.models import (
            AlanTipi, BasvuruKategorisi, KategoriAlani, Operator, Tarife,
        )

        self.beklemede = BasvuruDurumu.objects.create(
            ad="Beklemede", slug="beklemede", baslangic_durumu=True
        )
        self.aktif = BasvuruDurumu.objects.create(
            ad="Aktif", slug="aktif", hakedis_tetikler=True
        )

        self.bayi = User.objects.create_user("bayi", password="parola12345")
        self.cuzdan = Cuzdan.objects.create(bayi=self.bayi, bakiye=Decimal("0.00"))

        self.operator = Operator.objects.create(ad="Turkcell")
        self.kategori = BasvuruKategorisi.objects.create(ad="Kontörlü Yeni Hat")
        KategoriAlani.objects.create(
            kategori=self.kategori, kod="isim", etiket="İsim",
            cekirdek_alan="isim", tip=AlanTipi.METIN, zorunlu=True, sira=1,
        )
        self.tarife = Tarife.objects.create(operator=self.operator, ad="Platinum")
        self.tarife.kategoriler.add(self.kategori)

        UcretKurali.objects.create(
            ad="Hat bedeli", yon=KuralYonu.TAHSILAT, tutar=Decimal("1150.00"),
            tetikleyici_durum=self.aktif, kategori=self.kategori,
        )
        self.client.force_login(self.bayi)

    def _bakiye_yukle(self, tutar):
        from decimal import Decimal

        self.cuzdan.bakiye = Decimal(tutar)
        self.cuzdan.save(update_fields=["bakiye"])

    def _form_adresi(self):
        from django.urls import reverse

        return reverse("basvurular:yeni", args=[self.kategori.slug])

    def test_kategori_ekraninda_kapali_gorunur(self):
        from django.urls import reverse

        yanit = self.client.get(reverse("basvurular:kategori-sec"))
        icerik = yanit.content.decode()

        self.assertIn("Bakiye yetersiz", icerik)
        self.assertIn("1.150,00", icerik)
        # Kategori gizlenmez, kapalı gösterilir.
        self.assertIn("Kontörlü Yeni Hat", icerik)
        self.assertNotIn(self._form_adresi(), icerik)

    def test_form_acilmaz_ve_uyari_verilir(self):
        yanit = self.client.get(self._form_adresi(), follow=True)
        icerik = yanit.content.decode()

        self.assertIn("bakiyen yetersiz", icerik)
        self.assertIn("yöneticinle iletişime geç", icerik)

    def test_bakiye_yetince_form_acilir(self):
        self._bakiye_yukle("1150.00")

        yanit = self.client.get(self._form_adresi())

        self.assertEqual(yanit.status_code, 200)
        self.assertContains(yanit, "İsim")

    def test_bakiye_yetince_kategori_secilebilir(self):
        from django.urls import reverse

        self._bakiye_yukle("1150.00")

        icerik = self.client.get(reverse("basvurular:kategori-sec")).content.decode()

        self.assertIn(self._form_adresi(), icerik)
        self.assertNotIn("Bakiye yetersiz", icerik)
        # Bedel bilgisi görünür: bayi ne ödeyeceğini bilerek girsin.
        self.assertIn("1.150,00", icerik)

    def test_gonderim_sunucuda_reddedilir(self):
        """Kapı formda da durur: doğrudan POST atmak işe yaramaz."""
        from apps.basvurular.forms import BasvuruFormu

        form = BasvuruFormu(
            data={
                "operator": self.operator.pk,
                "tarife": self.tarife.pk,
                "musteri_tipi": "turk",
                "alan__isim": "Ayşe",
            },
            kategori=self.kategori,
            bayi=self.bayi,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("bakiyen yetersiz", " ".join(form.errors["__all__"]))

    def test_bedeli_olmayan_kategori_engellenmez(self):
        from apps.katalog.models import BasvuruKategorisi

        bedava = BasvuruKategorisi.objects.create(ad="Şebeke İçi Geçiş")

        from django.urls import reverse

        yanit = self.client.get(reverse("basvurular:yeni", args=[bedava.slug]))

        self.assertEqual(yanit.status_code, 200)


class HatBedeliIptaldeGeriYuklenir(TestCase):
    """Bayiden kesilen hat bedeli, başvuru iptal olunca cüzdana geri döner.

    Bayi ürünün parasını peşin veriyor; işlem yürümezse para onda kalmaz.
    Defterden satır silinmez, karşısına ters kayıt yazılır.
    """

    def setUp(self):
        from decimal import Decimal

        from django.contrib.auth.models import User

        from apps.basvurular.models import BasvuruDurumu
        from apps.finans.models import Cuzdan, KuralYonu, UcretKurali
        from apps.katalog.models import BasvuruKategorisi, Operator, Tarife

        self.beklemede = BasvuruDurumu.objects.create(
            ad="Beklemede", slug="beklemede", baslangic_durumu=True
        )
        self.aktif = BasvuruDurumu.objects.create(
            ad="Aktif", slug="aktif", hakedis_tetikler=True
        )
        self.iptal = BasvuruDurumu.objects.create(
            ad="İptal", slug="iptal", olumsuz_sonuc=True
        )

        self.bayi = User.objects.create_user("bayi", password="parola12345")
        self.cuzdan = Cuzdan.objects.create(bayi=self.bayi, bakiye=Decimal("1150.00"))

        self.operator = Operator.objects.create(ad="Turkcell")
        self.kategori = BasvuruKategorisi.objects.create(ad="Kontörlü Yeni Hat")
        self.tarife = Tarife.objects.create(operator=self.operator, ad="Platinum")
        self.tarife.kategoriler.add(self.kategori)

        UcretKurali.objects.create(
            ad="Hat bedeli", yon=KuralYonu.TAHSILAT, tutar=Decimal("1150.00"),
            tetikleyici_durum=self.aktif, kategori=self.kategori,
        )
        UcretKurali.objects.create(
            ad="Bayi hakedişi", yon=KuralYonu.HAKEDIS, tutar=Decimal("250.00"),
            tetikleyici_durum=self.aktif, kategori=self.kategori,
        )

    def _basvuru(self):
        from apps.basvurular.models import Basvuru

        return Basvuru.objects.create(
            bayi=self.bayi, kategori=self.kategori, operator=self.operator,
            tarife=self.tarife, isim="Ayşe", soyisim="Demir", kimlik_no="1",
            irtibat="5551112233", durum=self.beklemede,
        )

    def test_aktifte_kesilir_iptalde_geri_yuklenir(self):
        from decimal import Decimal

        basvuru = self._basvuru()

        basvuru.durum = self.aktif
        basvuru.save()
        self.cuzdan.refresh_from_db()
        # 1150 kesildi, 250 hakediş yattı.
        self.assertEqual(self.cuzdan.bakiye, Decimal("250.00"))

        basvuru.durum = self.iptal
        basvuru.save()
        self.cuzdan.refresh_from_db()
        basvuru.refresh_from_db()

        self.assertEqual(self.cuzdan.bakiye, Decimal("1150.00"))
        self.assertEqual(self.cuzdan.borc, Decimal("0.00"))
        self.assertEqual(basvuru.tahsil_edilen, Decimal("0.00"))
        self.assertEqual(basvuru.hakedis, Decimal("0.00"))

    def test_bakiye_yetmedigi_icin_borca_yazilan_bedel_de_geri_alinir(self):
        """Bakiye arada harcanmışsa bedel borca yazılır; iptal borcu da siler."""
        from decimal import Decimal

        basvuru = self._basvuru()
        self.cuzdan.bakiye = Decimal("0.00")
        self.cuzdan.save(update_fields=["bakiye"])

        basvuru.durum = self.aktif
        basvuru.save()
        self.cuzdan.refresh_from_db()
        # 1150 borca yazıldı, 250 hakediş borcu kapatmaya gitti.
        self.assertEqual(self.cuzdan.borc, Decimal("900.00"))
        self.assertEqual(self.cuzdan.bakiye, Decimal("0.00"))

        basvuru.durum = self.iptal
        basvuru.save()
        self.cuzdan.refresh_from_db()

        self.assertEqual(self.cuzdan.borc, Decimal("0.00"))
        self.assertEqual(self.cuzdan.bakiye, Decimal("0.00"))

    def test_defterde_ters_kayit_durur(self):
        """Satır silinmez; kesinti ve iadesi ikisi de görünür."""
        from apps.finans.models import CuzdanHareketi, HareketTipi

        basvuru = self._basvuru()
        basvuru.durum = self.aktif
        basvuru.save()
        basvuru.durum = self.iptal
        basvuru.save()

        tipler = list(
            CuzdanHareketi.objects.filter(basvuru=basvuru).values_list("tip", flat=True)
        )

        self.assertIn(HareketTipi.TAHSILAT, tipler)
        self.assertEqual(tipler.count(HareketTipi.IPTAL), 2)


class GirisBedeliIlkGiristeKesilir(TestCase):
    """Bayi ürünü alırken öder: bedel başvuru girildiği anda kesilir.

    Tutar başlangıç durumuna ("İlk giriş") yazılmış tahsilat kuralından
    gelir. Aktivasyonda işleyen hakedişten ayrı bir hatta durur; ikisi aynı
    bayrağı paylaşsaydı biri diğerini bloke ederdi.
    """

    def setUp(self):
        from decimal import Decimal

        from django.contrib.auth.models import User

        from apps.basvurular.models import BasvuruDurumu
        from apps.finans.models import Cuzdan, KuralYonu, UcretKurali
        from apps.katalog.models import BasvuruKategorisi, Operator, Tarife

        self.ilk_giris = BasvuruDurumu.objects.create(
            ad="İlk giriş", slug="ilk-giris", baslangic_durumu=True, sira=10
        )
        self.islemde = BasvuruDurumu.objects.create(
            ad="İşlemde", slug="islemde", sira=20
        )
        self.aktif = BasvuruDurumu.objects.create(
            ad="Aktif", slug="aktif", hakedis_tetikler=True, sira=50
        )
        self.iptal = BasvuruDurumu.objects.create(
            ad="İptal", slug="iptal", olumsuz_sonuc=True, sira=70
        )

        self.bayi = User.objects.create_user("bayi", password="parola12345")
        self.cuzdan = Cuzdan.objects.create(bayi=self.bayi, bakiye=Decimal("1150.00"))

        self.operator = Operator.objects.create(ad="Turkcell")
        self.kategori = BasvuruKategorisi.objects.create(ad="Kontörlü Yeni Hat")
        self.tarife = Tarife.objects.create(operator=self.operator, ad="Platinum")
        self.tarife.kategoriler.add(self.kategori)

        UcretKurali.objects.create(
            ad="Hat bedeli", yon=KuralYonu.TAHSILAT, tutar=Decimal("1150.00"),
            tetikleyici_durum=self.ilk_giris, kategori=self.kategori,
        )
        UcretKurali.objects.create(
            ad="Bayi hakedişi", yon=KuralYonu.HAKEDIS, tutar=Decimal("250.00"),
            tetikleyici_durum=self.aktif, kategori=self.kategori,
        )

    def _basvuru(self):
        from apps.basvurular.models import Basvuru

        return Basvuru.objects.create(
            bayi=self.bayi, kategori=self.kategori, operator=self.operator,
            tarife=self.tarife, isim="Ayşe", soyisim="Demir", kimlik_no="1",
            irtibat="5551112233", durum=self.ilk_giris,
        )

    def test_basvuru_girilir_girilmez_kesilir(self):
        from decimal import Decimal

        basvuru = self._basvuru()

        self.cuzdan.refresh_from_db()
        basvuru.refresh_from_db()
        self.assertEqual(self.cuzdan.bakiye, Decimal("0.00"))
        self.assertEqual(basvuru.giris_bedeli, Decimal("1150.00"))
        self.assertTrue(basvuru.giris_bedeli_islendi)

    def test_aktifte_hakedis_ayrica_isler(self):
        """Eski motorda giriş bedeli kesilince aktivasyon hakedişi işlenmezdi."""
        from decimal import Decimal

        basvuru = self._basvuru()
        basvuru.durum = self.aktif
        basvuru.save()

        self.cuzdan.refresh_from_db()
        basvuru.refresh_from_db()
        # 1150 kesildi, 250 hakediş yattı.
        self.assertEqual(self.cuzdan.bakiye, Decimal("250.00"))
        self.assertEqual(basvuru.hakedis, Decimal("250.00"))
        self.assertEqual(basvuru.giris_bedeli, Decimal("1150.00"))

    def test_iptalde_giris_bedeli_de_iade_edilir(self):
        from decimal import Decimal

        basvuru = self._basvuru()
        basvuru.durum = self.aktif
        basvuru.save()
        basvuru.durum = self.iptal
        basvuru.save()

        self.cuzdan.refresh_from_db()
        basvuru.refresh_from_db()
        self.assertEqual(self.cuzdan.bakiye, Decimal("1150.00"))
        self.assertEqual(basvuru.giris_bedeli, Decimal("0.00"))
        self.assertEqual(basvuru.hakedis, Decimal("0.00"))

    def test_yanlis_onay_geri_alinca_giris_bedeli_durur(self):
        """Ürün hâlâ bayide; yalnızca aktivasyon parası geri alınır."""
        from decimal import Decimal

        basvuru = self._basvuru()
        basvuru.durum = self.aktif
        basvuru.save()

        basvuru.durum = self.islemde
        basvuru.save()

        self.cuzdan.refresh_from_db()
        basvuru.refresh_from_db()
        # Hakediş geri alındı, giriş bedeli durdu: 1150 kesik.
        self.assertEqual(self.cuzdan.bakiye, Decimal("0.00"))
        self.assertEqual(basvuru.hakedis, Decimal("0.00"))
        self.assertEqual(basvuru.giris_bedeli, Decimal("1150.00"))

    def test_geri_alinip_yeniden_onaylanabilir(self):
        from decimal import Decimal

        basvuru = self._basvuru()
        for durum in (self.aktif, self.islemde, self.aktif):
            basvuru.durum = durum
            basvuru.save()

        self.cuzdan.refresh_from_db()
        self.assertEqual(self.cuzdan.bakiye, Decimal("250.00"))

    def test_kar_giris_bedelini_de_sayar(self):
        from decimal import Decimal

        basvuru = self._basvuru()
        basvuru.durum = self.aktif
        basvuru.save()
        basvuru.refresh_from_db()

        # 1150 giriş bedeli − 250 hakediş = 900
        self.assertEqual(basvuru.kar, Decimal("900.00"))


class OperatorBasinaBedelVeUyari(TestCase):
    """Fiyat operatöre göre değişir; kart ve kapı da öyle davranır.

    Tek rakam göstermek yanıltıcıydı: Turkcell 1150, Vodafone 1000 iken
    kartta yalnızca biri görünüyordu. Bakiye kapısı da operatör kırılımında
    çalışır — bakiyesi Vodafone'a yetip Turkcell'e yetmeyen bayi forma
    girebilmeli, ama hangisini seçemeyeceğini baştan bilmeli.
    """

    def setUp(self):
        from decimal import Decimal

        from django.contrib.auth.models import User

        from apps.basvurular.models import BasvuruDurumu
        from apps.finans.models import Cuzdan, KuralYonu, UcretKurali
        from apps.katalog.models import (
            AlanTipi, BasvuruKategorisi, KategoriAlani, Operator, Tarife,
        )

        self.giris = BasvuruDurumu.objects.create(
            ad="Giriş", slug="beklemede", baslangic_durumu=True
        )
        self.bayi = User.objects.create_user("bayi", password="parola12345")
        self.cuzdan = Cuzdan.objects.create(bayi=self.bayi, bakiye=Decimal("1100.00"))

        self.turkcell = Operator.objects.create(ad="Turkcell", sira=10)
        self.vodafone = Operator.objects.create(ad="Vodafone", sira=20)
        self.tt = Operator.objects.create(ad="Türk Telekom", sira=30)

        self.kategori = BasvuruKategorisi.objects.create(ad="Kontörlü Yeni Hat")
        self.kategori.operatorler.set([self.turkcell, self.vodafone, self.tt])
        KategoriAlani.objects.create(
            kategori=self.kategori, kod="isim", etiket="İsim",
            cekirdek_alan="isim", tip=AlanTipi.METIN, zorunlu=True, sira=1,
        )
        for operator, tutar in (
            (self.turkcell, "1150.00"), (self.vodafone, "1000.00"), (self.tt, "600.00")
        ):
            UcretKurali.objects.create(
                ad=f"{operator.ad} hat bedeli", yon=KuralYonu.TAHSILAT,
                tutar=Decimal(tutar), tetikleyici_durum=self.giris,
                kategori=self.kategori, operator=operator,
            )
        self.client.force_login(self.bayi)

    def _bakiye(self, tutar):
        from decimal import Decimal

        self.cuzdan.bakiye = Decimal(tutar)
        self.cuzdan.save(update_fields=["bakiye"])

    def _kategori_ekrani(self):
        from django.urls import reverse

        return self.client.get(reverse("basvurular:kategori-sec")).content.decode()

    def _form(self):
        from django.urls import reverse

        return self.client.get(
            reverse("basvurular:yeni", args=[self.kategori.slug]), follow=True
        ).content.decode()

    def test_kartta_her_operatorun_fiyati_ayri_yazar(self):
        icerik = self._kategori_ekrani()

        self.assertIn("1.150,00", icerik)
        self.assertIn("1.000,00", icerik)
        self.assertIn("600,00", icerik)

    def test_bakiye_hepsine_yetiyorsa_uyari_cikmaz(self):
        self._bakiye("3000.00")

        # Kutunun kendisi aranır; id JavaScript'te her hâlükârda geçiyor.
        self.assertNotIn('<dialog id="bakiye-uyarisi"', self._form())

    def test_yetmeyen_operatorler_uyarida_sayilir(self):
        """1100 TL: Turkcell (1150) yetmiyor, diğerleri yetiyor."""
        icerik = self._form()

        self.assertIn('<dialog id="bakiye-uyarisi"', icerik)
        self.assertIn("Turkcell", icerik)
        self.assertNotIn("Turkcell, Vodafone", icerik)

    def test_iki_operator_yetmiyorsa_ikisi_de_sayilir(self):
        self._bakiye("900.00")

        icerik = self._form()

        self.assertIn("Turkcell ve Vodafone", icerik)

    def test_hicbirine_yetmiyorsa_kategori_kapali_gelir(self):
        self._bakiye("100.00")

        icerik = self._kategori_ekrani()

        self.assertIn("Bakiye yetersiz", icerik)

    def test_kapali_kartta_da_her_operatorun_fiyati_yazar(self):
        """Yalnızca en ucuzu göstermek hangi operatöre ne eksiği olduğunu gizliyordu."""
        self._bakiye("31.00")

        icerik = self._kategori_ekrani()

        self.assertIn("Bakiye yetersiz", icerik)
        self.assertIn("1.150,00", icerik)
        self.assertIn("1.000,00", icerik)
        self.assertIn("600,00", icerik)

    def test_yetmeyen_operator_sunucuda_da_reddedilir(self):
        """Uyarı bilgilendirme; kapıyı sunucu doğrulaması kapatır."""
        from apps.basvurular.forms import BasvuruFormu

        from apps.katalog.models import Tarife

        tarife = Tarife.objects.create(operator=self.turkcell, ad="Platinum")
        tarife.kategoriler.add(self.kategori)

        form = BasvuruFormu(
            data={
                "operator": self.turkcell.pk, "tarife": tarife.pk,
                "musteri_tipi": "turk", "alan__isim": "Ayşe",
            },
            kategori=self.kategori,
            bayi=self.bayi,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("bakiyen yetersiz", " ".join(form.errors["__all__"]))

    def test_yeten_operatorle_form_gecerli(self):
        from apps.basvurular.forms import BasvuruFormu
        from apps.katalog.models import Tarife

        tarife = Tarife.objects.create(operator=self.tt, ad="Ekonomi")
        tarife.kategoriler.add(self.kategori)

        form = BasvuruFormu(
            data={
                "operator": self.tt.pk, "tarife": tarife.pk,
                "musteri_tipi": "turk", "alan__isim": "Ayşe",
            },
            kategori=self.kategori,
            bayi=self.bayi,
        )

        self.assertTrue(form.is_valid(), form.errors)


class DetayGorunumAyarlari(TestCase):
    """Bayi başvuru detayında neleri göreceğini kendisi seçer.

    Satırlar tek yerden üretiliyor; ayar kutusundaki seçenekler de aynı
    listeden geliyor. Kategoriye alan eklenince ikisi birden büyür.
    """

    def setUp(self):
        from django.contrib.auth.models import User

        from apps.basvurular.models import Basvuru, BasvuruDurumu
        from apps.finans.models import Cuzdan
        from apps.katalog.models import (
            AlanTipi, BasvuruKategorisi, KategoriAlani, Operator, Tarife,
        )

        durum = BasvuruDurumu.objects.create(
            ad="Giriş", slug="beklemede", baslangic_durumu=True
        )
        self.bayi = User.objects.create_user("5551112233", password="parola12345")
        Cuzdan.objects.create(bayi=self.bayi)

        operator = Operator.objects.create(ad="Turkcell")
        self.kategori = BasvuruKategorisi.objects.create(ad="Kontörlü Yeni Hat")
        KategoriAlani.objects.create(
            kategori=self.kategori, kod="aks", etiket="AKS Kodu",
            tip=AlanTipi.METIN, sira=1,
        )
        tarife = Tarife.objects.create(operator=operator, ad="Platinum")
        tarife.kategoriler.add(self.kategori)

        self.basvuru = Basvuru.objects.create(
            bayi=self.bayi, kategori=self.kategori, operator=operator, tarife=tarife,
            isim="Ayşe", soyisim="Demir", kimlik_no="12345678901",
            irtibat="5559998877", durum=durum, ek_bilgiler={"aks": "AKS-42"},
        )
        self.client.force_login(self.bayi)

    def _detay(self):
        from django.urls import reverse

        return self.client.get(
            reverse("basvurular:detay", args=[self.basvuru.referans_no])
        ).content.decode()

    def _gorunen(self, basvuru=None):
        """Ekranda çizilen satırların anahtarları.

        Sayfa metninde arama yapmak yanıltıcı: ayar kutusu kapatılmış
        alanları da listeliyor, etiketleri orada da geçiyor.
        """
        from django.urls import reverse

        yanit = self.client.get(
            reverse("basvurular:detay", args=[(basvuru or self.basvuru).referans_no])
        )
        return {satir["anahtar"] for satir in yanit.context["satirlar"]}

    def _ayarla(self, acik_alanlar):
        from django.urls import reverse

        return self.client.post(
            reverse("basvurular:detay-gorunum", args=[self.basvuru.referans_no]),
            {"alan": acik_alanlar},
            follow=True,
        )

    def test_varsayilan_olarak_her_sey_gorunur(self):
        icerik = self._detay()

        for beklenen in ("Müşteri tipi", "Kimlik tipi", "Referans no", "Bayi",
                         "İrtibat", "AKS Kodu", "AKS-42"):
            self.assertIn(beklenen, icerik)

    def test_kategoriye_ozel_alan_kendi_etiketiyle_gelir(self):
        self.assertIn("AKS Kodu", self._detay())

    def test_kapatilan_alan_gorunmez(self):
        self._ayarla(["referans_no", "kategori", "durum"])

        gorunen = self._gorunen()
        self.assertNotIn("musteri_tipi", gorunen)
        self.assertIn("referans_no", gorunen)

    def test_secim_butun_basvurularda_gecerli(self):
        """Tercih bayiye ait; her başvuruda aynı görünüm."""
        from apps.basvurular.models import Basvuru, BasvuruDurumu
        from django.urls import reverse

        self._ayarla(["referans_no"])

        ikinci = Basvuru.objects.create(
            bayi=self.bayi, kategori=self.kategori,
            isim="Veli", soyisim="Kaya", kimlik_no="98765432109",
            irtibat="5551110000", durum=BasvuruDurumu.objects.first(),
        )
        self.assertNotIn("musteri_tipi", self._gorunen(ikinci))

    def test_ayar_kutusunda_kapatilanlar_da_listelenir(self):
        """Kapattığını geri açabilmeli; kutuda hepsi durur."""
        self._ayarla(["referans_no"])

        icerik = self._detay()
        self.assertIn('value="musteri_tipi"', icerik)

    def test_sonradan_eklenen_alan_kendiliginden_gorunur(self):
        """Kapatılanlar saklanıyor; yeni alan listeye açık girer."""
        self._ayarla(["referans_no"])
        self.basvuru.ek_bilgiler = {"aks": "AKS-42", "not": "Yeni alan"}
        self.basvuru.save(update_fields=["ek_bilgiler"])

        self.assertIn("Yeni alan", self._detay())

    def test_bos_deger_hic_listelenmez(self):
        """Olmayan bilgi ne ekranda ne ayar kutusunda yer kaplar."""
        self.assertNotIn("numara", self._gorunen())
        self.assertNotIn("İşlem numarası", self._detay())

    def test_baskasinin_basvurusunun_gorunumu_ayarlanamaz(self):
        from django.contrib.auth.models import User
        from django.urls import reverse

        baskasi = User.objects.create_user("5554443322", password="parola12345")
        self.client.force_login(baskasi)

        yanit = self.client.post(
            reverse("basvurular:detay-gorunum", args=[self.basvuru.referans_no]),
            {"alan": ["referans_no"]},
        )

        self.assertEqual(yanit.status_code, 404)
