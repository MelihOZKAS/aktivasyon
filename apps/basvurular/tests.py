"""Dinamik form ve başvuru akışı testleri."""

import io
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.basvurular.models import Basvuru, BasvuruDurumu
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


class DinamikFormTestleri(TestCase):
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
            kategori=self.kategori, operator=self.operator, ad="Red 20 GB"
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

    def _gonderi(self, **degisiklikler):
        veri = {
            "kategori": self.kategori.pk,
            "operator": self.operator.pk,
            "tarife": self.tarife.pk,
            "kampanya": "",
            "musteri_tipi": "turk",
            "kimlik_tipi": "tc",
            "kimlik_no": "12345678901",
            "isim": "Ayşe",
            "soyisim": "Demir",
            "irtibat": "5551112233",
            "numara": "",
            "adres": "Örnek Mah. No:1",
            "bayi_aciklamasi": "",
            "ek__aks": "AKS-1234",
            "ek__sim_imei": "8990011223344",
            "ek__kimlik_on": kucuk_png(),
        }
        veri.update(degisiklikler)
        return veri

    def test_form_kategoriye_gore_alanlari_uretir(self):
        yanit = self.client.get(reverse("basvurular:yeni"), {"kategori": self.kategori.pk})
        self.assertEqual(yanit.status_code, 200)
        form = yanit.context["form"]
        self.assertIn("ek__aks", form.fields)
        self.assertIn("ek__sim_imei", form.fields)
        self.assertIn("ek__kimlik_on", form.fields)

    def test_basvuru_gonderilir_ve_ek_bilgiler_kaydedilir(self):
        yanit = self.client.post(reverse("basvurular:yeni"), self._gonderi())
        self.assertEqual(yanit.status_code, 302)

        basvuru = Basvuru.objects.get()
        self.assertEqual(basvuru.bayi, self.bayi)
        self.assertEqual(basvuru.durum, self.beklemede)
        self.assertEqual(basvuru.ek_bilgiler["aks"], "AKS-1234")
        self.assertEqual(basvuru.ek_bilgiler["sim_imei"], "8990011223344")
        self.assertEqual(basvuru.belgeler.count(), 1)
        self.assertEqual(basvuru.belgeler.first().alan_kodu, "kimlik_on")

    def test_zorunlu_dinamik_alan_bos_birakilamaz(self):
        yanit = self.client.post(reverse("basvurular:yeni"), self._gonderi(**{"ek__aks": ""}))
        self.assertEqual(yanit.status_code, 200)
        self.assertIn("ek__aks", yanit.context["form"].errors)
        self.assertEqual(Basvuru.objects.count(), 0)

    def test_kategoriye_ait_olmayan_operator_reddedilir(self):
        baska = Operator.objects.create(ad="Turkcell")
        yanit = self.client.post(reverse("basvurular:yeni"), self._gonderi(operator=baska.pk))
        self.assertEqual(yanit.status_code, 200)
        self.assertIn("operator", yanit.context["form"].errors)

    def test_operatoru_uyusmayan_tarife_reddedilir(self):
        """Operatör kategoride geçerli ama seçilen tarife başka operatöre ait."""
        turkcell = Operator.objects.create(ad="Turkcell")
        self.kategori.operatorler.add(turkcell)

        yanit = self.client.post(reverse("basvurular:yeni"), self._gonderi(operator=turkcell.pk))
        self.assertEqual(yanit.status_code, 200)
        self.assertIn("tarife", yanit.context["form"].errors)
        self.assertEqual(Basvuru.objects.count(), 0)

    def test_dogrulama_deseni_uygulanir(self):
        KategoriAlani.objects.filter(kod="aks").update(dogrulama_deseni=r"^AKS-\d{4}$")
        yanit = self.client.post(reverse("basvurular:yeni"), self._gonderi(**{"ek__aks": "yanlis"}))
        self.assertIn("ek__aks", yanit.context["form"].errors)

    def test_basvuru_girisinde_para_islenmez(self):
        UcretKurali.objects.create(
            ad="Hakediş", yon=KuralYonu.HAKEDIS, tutar=Decimal("150.00"),
            kategori=self.kategori, tetikleyici_durum=self.aktif,
        )
        self.client.post(reverse("basvurular:yeni"), self._gonderi())

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
        yanit = self.client.get(reverse("basvurular:detay", args=[basvuru.pk]))
        self.assertEqual(yanit.status_code, 404)

    def test_liste_arama_ile_filtrelenir(self):
        self.client.post(reverse("basvurular:yeni"), self._gonderi())
        Basvuru.objects.create(
            bayi=self.bayi, kategori=self.kategori, operator=self.operator,
            tarife=self.tarife, kimlik_no="55555555555", isim="Mehmet", soyisim="Kaya",
            irtibat="5321112233", durum=self.beklemede,
        )
        yanit = self.client.get(reverse("basvurular:liste"), {"q": "Ayşe"})
        self.assertEqual(len(yanit.context["sayfa"].object_list), 1)

    def test_htmx_tarife_secenekleri_operatore_gore_gelir(self):
        yanit = self.client.get(
            reverse("basvurular:tarife-secenekleri"),
            {"kategori": self.kategori.pk, "operator": self.operator.pk},
        )
        self.assertContains(yanit, "Red 20 GB")

    def test_giris_yapmadan_erisim_engellenir(self):
        self.client.logout()
        for ad in ["basvurular:liste", "basvurular:yeni", "bayi:panel", "bayi:cuzdan"]:
            yanit = self.client.get(reverse(ad))
            self.assertEqual(yanit.status_code, 302, ad)
            self.assertIn("/giris-yap/", yanit["Location"], ad)

    def test_anasayfa_herkese_acik(self):
        self.client.logout()
        yanit = self.client.get(reverse("bayi:anasayfa"))
        self.assertEqual(yanit.status_code, 200)
        self.assertContains(yanit, "Faturalı Yeni Hat")
