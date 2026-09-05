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

    def test_sim_alani_yalnizca_kendi_stogunu_listeler(self):
        """Bayi IMEI'yi elle yazmaz, listeden seçer.

        16 haneyi tezgâh başında yazmak hataya davetiye; üstelik listeye
        yalnızca girebileceği kartlar giriyor.
        """
        form = self.client.get(self._url()).context["form"]
        degerler = [d for d, _ in form.fields["alan__sim"].widget.choices]

        self.assertIn(self.benim.imei, degerler)
        self.assertNotIn(self.baskasinin.imei, degerler)
        self.assertNotIn(self.sahipsiz.imei, degerler)

    def test_kullanilan_kart_listeden_duser(self):
        self.client.post(self._url(), self._gonderi(self.benim.imei))

        form = self.client.get(self._url()).context["form"]
        degerler = [d for d, _ in form.fields["alan__sim"].widget.choices]

        self.assertNotIn(self.benim.imei, degerler)

    def test_stok_bosken_sebebi_yazilir(self):
        """Boş bir kutu 'bir şey bozuldu' gibi durur; sebebi görünmeli."""
        self.benim.bayi = None
        self.benim.save()

        form = self.client.get(self._url()).context["form"]
        etiketler = [e for _, e in form.fields["alan__sim"].widget.choices]

        self.assertEqual(etiketler, ["Stoğunuzda kullanılabilir SIM kart yok"])

    def test_sim_listesinde_zimmetli_bayi_gorunur(self):
        """Kullanıcı adı telefon numarası; listede firma ünvanı da okunmalı."""
        from apps.bayi.models import BayiProfili

        BayiProfili.objects.create(kullanici=self.bayi, unvan="Ege İletişim")
        yonetici = User.objects.create_superuser("yon3", "y3@x.com", "parola12345")
        self.client.force_login(yonetici)

        yanit = self.client.get("/yonetim/bayi/simkart/")

        self.assertContains(yanit, "Ege İletişim")
        self.assertContains(yanit, "stokta · zimmetsiz")

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
        veri = {
            "isim": "Melih",
            "soyisim": "Kaya",
            "irtibat": "5321234567",
            # Parola artık başvuru sırasında seçiliyor; hesap açılınca
            # kullanıcı bu parolayla giriyor.
            "parola": "CokGuclu-Parola-2026",
            "parola_tekrar": "CokGuclu-Parola-2026",
            "website": "",
        }
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
            operator=self.operator,
            ad="Platinum 30 GB", aciklama="Aylık 30 GB, sınırsız konuşma.",
        )
        self.tarife.kategoriler.add(self.kategori)
        self.kampanya = Kampanya.objects.create(
            tarife=self.tarife, ad="İlk 3 ay yarı fiyat"
        )
        self.url = reverse("bayi:tarifeler")
        self.client.force_login(self.bayi)

    def test_giris_gerekir(self):
        self.client.logout()
        yanit = self.client.get(self.url)
        self.assertEqual(yanit.status_code, 302)
        self.assertIn("/giris-yap/", yanit["Location"])

    def test_gorsel_baglanti_degildir(self):
        """Telefonda yanlışlıkla dokunmak dosyayı indiriyordu."""
        icerik = self.client.get(self.url).content.decode()

        self.assertNotIn('target="_blank"', icerik)

    def test_tarife_ve_aciklama_gorunur(self):
        yanit = self.client.get(self.url)
        self.assertContains(yanit, "Platinum 30 GB")
        self.assertContains(yanit, "Aylık 30 GB")
        self.assertContains(yanit, "Turkcell")

    def test_kampanya_bu_sayfada_gorunmez(self):
        """Kampanya katalogda değil, başvuru formunda seçilir.

        Bu sayfa bayinin müşteriye anlatırken açtığı katalog; kampanya ise
        başvuru girerken yapılan bir seçim. İkisi karışınca bayi kampanyayı
        burada görüp orada aramaya başlıyordu.
        """
        yanit = self.client.get(self.url)
        self.assertContains(yanit, "Platinum 30 GB")
        self.assertNotContains(yanit, "İlk 3 ay yarı fiyat")

    def test_bayiye_gorunur_kapaliysa_katalogda_listelenmez(self):
        self.tarife.bayiye_gorunur = False
        self.tarife.save(update_fields=["bayiye_gorunur"])

        self.assertNotContains(self.client.get(self.url), "Platinum 30 GB")

    def test_katalogda_gizli_tarife_basvuruda_hala_secilebilir(self):
        """Aktif olan tarife duyurulmasa da satılabilir; kapatmak Aktif'in işi."""
        from apps.basvurular.forms import BasvuruFormu

        self.tarife.bayiye_gorunur = False
        self.tarife.save(update_fields=["bayiye_gorunur"])

        form = BasvuruFormu(kategori=self.kategori, bayi=self.bayi)

        self.assertIn(self.tarife, form.fields["tarife"].queryset)

    def test_pasif_tarife_gorunmez(self):
        self.tarife.aktif = False
        self.tarife.save()
        self.assertNotContains(self.client.get(self.url), "Platinum 30 GB")

    def test_operator_sekmesiyle_filtrelenir(self):
        """Bayi önce operatörü seçiyor; sekmeler ona göre."""
        from apps.katalog.models import Operator, Tarife

        vodafone = Operator.objects.create(ad="Vodafone", renk="#e60000", sira=20)
        _tarife = Tarife.objects.create(
            operator=vodafone, ad="Red 20 GB"
        )
        _tarife.kategoriler.add(self.kategori)

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


class RolErisimTestleri(TestCase):
    """Bayi ve tedarikçi ekranları birbirine karışmamalı."""

    def setUp(self):
        from apps.bayi.models import BayiProfili
        from apps.basvurular.models import Basvuru, BasvuruDurumu
        from apps.katalog.models import BasvuruKategorisi, Operator

        self.beklemede = BasvuruDurumu.objects.create(
            ad="Beklemede", slug="beklemede", baslangic_durumu=True
        )
        self.islemde = BasvuruDurumu.objects.create(
            ad="İşlemde", slug="islemde", tedarikci_secebilir=True, sira=20
        )
        self.aktif = BasvuruDurumu.objects.create(
            ad="Aktif", slug="aktif", hakedis_tetikler=True,
            tedarikci_secebilir=True, sira=50,
        )
        self.mutabakat = BasvuruDurumu.objects.create(
            ad="Mutabakat", slug="mutabakat", sira=40
        )
        self.kategori = BasvuruKategorisi.objects.create(ad="MNT", tarife_zorunlu=False)
        self.operator = Operator.objects.create(ad="Turkcell")
        self.kategori.operatorler.add(self.operator)

        self.bayi = User.objects.create_user("saf_bayi", password="parola12345")
        Cuzdan.objects.create(bayi=self.bayi)
        BayiProfili.objects.create(
            kullanici=self.bayi, unvan="Bayi A", bayi_mi=True, tedarikci_mi=False
        )

        self.tedarikci = User.objects.create_user("saf_tedarikci", password="parola12345")
        Cuzdan.objects.create(bayi=self.tedarikci, bakiye=TL("5000.00"))
        BayiProfili.objects.create(
            kullanici=self.tedarikci, unvan="Tedarik X",
            bayi_mi=False, tedarikci_mi=True,
        )

        self.ikili = User.objects.create_user("ikili", password="parola12345")
        Cuzdan.objects.create(bayi=self.ikili)
        BayiProfili.objects.create(
            kullanici=self.ikili, unvan="İkili", bayi_mi=True, tedarikci_mi=True
        )

        self.basvuru = Basvuru.objects.create(
            bayi=self.bayi, kategori=self.kategori, operator=self.operator,
            tedarikci=self.tedarikci, isim="Ayşe", soyisim="Demir",
            kimlik_no="1", irtibat="5551112233", durum=self.beklemede,
        )

    def test_sadece_tedarikci_kendi_paneline_duser(self):
        yanit = self.client.post(
            reverse("bayi:giris"),
            {"username": "saf_tedarikci", "password": "parola12345"},
        )
        self.assertRedirects(yanit, reverse("bayi:tedarikci-panel"))

    def test_bayi_kendi_paneline_duser(self):
        yanit = self.client.post(
            reverse("bayi:giris"), {"username": "saf_bayi", "password": "parola12345"}
        )
        self.assertRedirects(yanit, reverse("bayi:panel"))

    def test_tedarikci_bayi_ekranlarina_giremez(self):
        self.client.force_login(self.tedarikci)
        for ad in ["bayi:panel", "bayi:hakedisler", "basvurular:kategori-sec",
                   "basvurular:liste"]:
            yanit = self.client.get(reverse(ad))
            self.assertEqual(yanit.status_code, 302, ad)
            self.assertIn(reverse("bayi:tedarikci-panel"), yanit["Location"], ad)

    def test_bayi_tedarikci_paneline_giremez(self):
        self.client.force_login(self.bayi)
        yanit = self.client.get(reverse("bayi:tedarikci-panel"))
        self.assertEqual(yanit.status_code, 302)
        self.assertIn(reverse("bayi:panel"), yanit["Location"])

    def test_ikili_rol_her_ikisini_de_gorur(self):
        self.client.force_login(self.ikili)
        self.assertEqual(self.client.get(reverse("bayi:panel")).status_code, 200)
        self.assertEqual(
            self.client.get(reverse("bayi:tedarikci-panel")).status_code, 200
        )

    def test_tedarikci_ustlendigi_islemi_gorur(self):
        self.client.force_login(self.tedarikci)
        yanit = self.client.get(reverse("bayi:tedarikci-panel"))
        self.assertContains(yanit, self.basvuru.referans_no)

    def test_tedarikci_ustlendigi_basvurunun_detayini_gorur(self):
        self.client.force_login(self.tedarikci)
        yanit = self.client.get(
            reverse("basvurular:detay", args=[self.basvuru.referans_no])
        )
        self.assertEqual(yanit.status_code, 200)

    def test_tedarikci_baskasinin_islemini_goremez(self):
        from apps.basvurular.models import Basvuru

        digeri = Basvuru.objects.create(
            bayi=self.bayi, kategori=self.kategori, operator=self.operator,
            isim="Gizli", soyisim="Kayıt", kimlik_no="9",
            irtibat="5559998877", durum=self.beklemede,
        )
        self.client.force_login(self.tedarikci)
        yanit = self.client.get(reverse("basvurular:detay", args=[digeri.referans_no]))
        self.assertEqual(yanit.status_code, 404)

    def test_tedarikci_ustlendigi_islemin_kimligini_gorur(self):
        """Aktivasyonu tedarikçi yapıyor; bilgileri kimlikten okuyacak."""
        import io
        import tempfile
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings
        from PIL import Image
        from apps.basvurular.models import BasvuruBelgesi

        tampon = io.BytesIO()
        Image.new("RGB", (4, 4), "white").save(tampon, format="PNG")

        with override_settings(MEDIA_ROOT=tempfile.mkdtemp()):
            belge = BasvuruBelgesi.objects.create(
                basvuru=self.basvuru, alan_kodu="kimlik_on", etiket="Kimlik Ön",
                dosya=SimpleUploadedFile("k.png", tampon.getvalue(), content_type="image/png"),
            )

            # Üstlendiği işlemin kimliğini görebilir.
            self.client.force_login(self.tedarikci)
            detay = self.client.get(
                reverse("basvurular:detay", args=[self.basvuru.referans_no])
            )
            self.assertEqual(detay.status_code, 200)
            self.assertContains(detay, "Belgeler")
            self.assertEqual(
                self.client.get(belge.get_absolute_url()).status_code, 200
            )

            # Başvuruyu getiren bayi de görebilir.
            self.client.force_login(self.bayi)
            self.assertEqual(
                self.client.get(belge.get_absolute_url()).status_code, 200
            )

            # Ama ilgisiz bir kullanıcı göremez.
            yabanci = User.objects.create_user("yabanci", password="parola12345")
            Cuzdan.objects.create(bayi=yabanci)
            self.client.force_login(yabanci)
            self.assertEqual(
                self.client.get(belge.get_absolute_url()).status_code, 404
            )

    def test_toplu_tedarikciye_satma(self):
        from apps.basvurular.models import Basvuru

        yonetici = User.objects.create_superuser("yon", "y@x.com", "parola12345")
        self.client.force_login(yonetici)

        self.client.post(
            "/yonetim/basvurular/basvuru/",
            {
                "action": "tedarikciye_ata",
                "_selected_action": [self.basvuru.pk],
                "uygula": "1",
                "tedarikci": self.tedarikci.pk,
            },
            follow=True,
        )
        self.basvuru.refresh_from_db()
        self.assertEqual(self.basvuru.tedarikci, self.tedarikci)

    def test_tedarikci_paneli_detaya_baglanir(self):
        """Aktivasyonu yapacaksa detayı açabilmeli; satır bağlantı olmalı."""
        self.client.force_login(self.tedarikci)
        yanit = self.client.get(reverse("bayi:tedarikci-panel"))
        self.assertContains(
            yanit, reverse("basvurular:detay", args=[self.basvuru.referans_no])
        )

    def test_tedarikci_durumu_degistirebilir(self):
        """Sonucu aktivasyonu yapan taraf yazar; yöneticiyi beklemez."""
        self.client.force_login(self.tedarikci)

        detay = self.client.get(
            reverse("basvurular:detay", args=[self.basvuru.referans_no])
        )
        self.assertContains(detay, "İşlemin sonucunu bildir")
        self.assertContains(detay, "İşlemde")
        # Seçemeyeceği durum kutuya hiç girmez.
        self.assertNotContains(detay, "Mutabakat")

        yanit = self.client.post(
            reverse("basvurular:durum-bildir", args=[self.basvuru.referans_no]),
            {"durum": self.islemde.pk, "aciklama": "Operatörde işleme alındı"},
        )
        self.assertRedirects(
            yanit, reverse("basvurular:detay", args=[self.basvuru.referans_no])
        )
        self.basvuru.refresh_from_db()
        self.assertEqual(self.basvuru.durum, self.islemde)

        # Kim değiştirdi ve ne yazdı, geçmişte durur.
        kayit = self.basvuru.durum_gecmisi.order_by("-tarih").first()
        self.assertEqual(kayit.degistiren, self.tedarikci)
        self.assertEqual(kayit.aciklama, "Operatörde işleme alındı")

    def test_tedarikci_izinsiz_duruma_gecemez(self):
        """Liste veridir; işaretlenmemiş durum elle gönderilse de geçmez."""
        self.client.force_login(self.tedarikci)
        self.client.post(
            reverse("basvurular:durum-bildir", args=[self.basvuru.referans_no]),
            {"durum": self.mutabakat.pk},
        )
        self.basvuru.refresh_from_db()
        self.assertEqual(self.basvuru.durum, self.beklemede)

    def test_sonuclanmis_islemin_durumu_tedarikciden_degismez(self):
        """Para işlendikten sonra geri almak yönetim kararıdır."""
        self.basvuru.durum = self.aktif
        self.basvuru.save()

        self.client.force_login(self.tedarikci)
        self.client.post(
            reverse("basvurular:durum-bildir", args=[self.basvuru.referans_no]),
            {"durum": self.islemde.pk},
        )
        self.basvuru.refresh_from_db()
        self.assertEqual(self.basvuru.durum, self.aktif)

    def test_baskasinin_islemine_durum_yazilamaz(self):
        from apps.basvurular.models import Basvuru

        digeri = Basvuru.objects.create(
            bayi=self.bayi, kategori=self.kategori, operator=self.operator,
            isim="Gizli", soyisim="Kayıt", kimlik_no="9",
            irtibat="5559998877", durum=self.beklemede,
        )
        self.client.force_login(self.tedarikci)
        yanit = self.client.post(
            reverse("basvurular:durum-bildir", args=[digeri.referans_no]),
            {"durum": self.islemde.pk},
        )
        self.assertEqual(yanit.status_code, 404)
        digeri.refresh_from_db()
        self.assertEqual(digeri.durum, self.beklemede)

    def test_bayi_kendi_basvurusunun_durumunu_degistiremez(self):
        """Durum değiştirmek bayinin işi değil; kutu ona hiç çizilmez."""
        self.client.force_login(self.bayi)
        yanit = self.client.post(
            reverse("basvurular:durum-bildir", args=[self.basvuru.referans_no]),
            {"durum": self.islemde.pk},
        )
        self.assertEqual(yanit.status_code, 404)

        detay = self.client.get(
            reverse("basvurular:detay", args=[self.basvuru.referans_no])
        )
        self.assertNotContains(detay, "İşlemin sonucunu bildir")

    def test_tedarikci_basvuruyu_getiren_bayiyi_gormez(self):
        """İşlemi üstlenir, müşteriyle ilgilenir; bayi kimliği onun işi değil."""
        self.client.force_login(self.tedarikci)
        yanit = self.client.get(
            reverse("basvurular:detay", args=[self.basvuru.referans_no])
        )
        self.assertNotContains(yanit, "Bayi A")
        self.assertNotContains(yanit, "saf_bayi")

        # Başvuruyu getiren bayi kendi ekranında görmeye devam eder.
        self.client.force_login(self.bayi)
        kendi = self.client.get(
            reverse("basvurular:detay", args=[self.basvuru.referans_no])
        )
        self.assertContains(kendi, "Bayi A")

    def test_tedarikci_bayinin_hakedisini_gormez(self):
        """Bayinin kâr marjı tedarikçiye açılmaz."""
        self.basvuru.durum = self.aktif
        self.basvuru.hakedis = TL("175.00")
        self.basvuru.para_islendi = True
        self.basvuru.save()

        self.client.force_login(self.tedarikci)
        yanit = self.client.get(
            reverse("basvurular:detay", args=[self.basvuru.referans_no])
        )
        self.assertNotContains(yanit, "Hakedişin")

    def test_profilsiz_kullanici_bayi_sayilir(self):
        """Eski kayıtlar rol kontrolüyle kilitlenmemeli."""
        eski = User.objects.create_user("profilsiz", password="parola12345")
        Cuzdan.objects.create(bayi=eski)
        self.client.force_login(eski)
        self.assertEqual(self.client.get(reverse("bayi:panel")).status_code, 200)


class YanMenuRozetleri(TestCase):
    """Bekleyen iş sayısı yan menüde görünmeli; iş yokken rozet çizilmemeli."""

    def setUp(self):
        from django.contrib.auth.models import User

        self.yonetici = User.objects.create_superuser(
            "rozet.yonetici", password="parola12345"
        )
        self.client.force_login(self.yonetici)

    def _menu(self):
        cevap = self.client.get("/yonetim/")
        self.assertEqual(cevap.status_code, 200)
        icerik = cevap.content.decode()
        # Menü gerçekten çizilmiş olmalı; boş sayfada her assert geçer.
        self.assertIn("Bayi Başvuruları", icerik)
        return icerik

    def test_bekleyen_yoksa_rozet_cizilmez(self):
        from apps import rozetler

        self.assertEqual(rozetler.bekleyen_bayi_basvurulari(None), "")
        self.assertEqual(rozetler.bekleyen_basvurular(None), "")

        icerik = self._menu()
        # Rozetin nokta yolu ekrana basılmamalı; unfold'un varsayılan
        # şablonu boş değerde tam olarak bunu yapıyordu.
        self.assertNotIn("apps.rozetler", icerik)

    def test_yeni_bayi_basvurusu_sayilir(self):
        from apps import rozetler
        from apps.bayi.models import BayiBasvurusu, BayiBasvuruDurumu

        for sira in range(3):
            BayiBasvurusu.objects.create(
                isim=f"Aday{sira}", soyisim="Test", irtibat="5551112233"
            )
        # Görüşülen başvuru artık bekleyen değildir.
        BayiBasvurusu.objects.create(
            isim="Görüşüldü", soyisim="Test", irtibat="5551112233",
            durum=BayiBasvuruDurumu.GORUSULDU,
        )

        self.assertEqual(rozetler.bekleyen_bayi_basvurulari(None), "3")
        self.assertIn(">3<", self._menu())

    def test_basvuru_durumu_degisince_rozetten_duser(self):
        from apps import rozetler
        from apps.basvurular.models import Basvuru, BasvuruDurumu
        from apps.katalog.models import BasvuruKategorisi

        beklemede = BasvuruDurumu.objects.create(
            ad="Beklemede", slug="beklemede", baslangic_durumu=True
        )
        islemde = BasvuruDurumu.objects.create(ad="İşlemde", slug="islemde")
        kategori = BasvuruKategorisi.objects.create(ad="MNT")

        basvuru = Basvuru.objects.create(
            bayi=self.yonetici, kategori=kategori, durum=beklemede, isim="Ali"
        )
        self.assertEqual(rozetler.bekleyen_basvurular(None), "1")

        basvuru.durum = islemde
        basvuru.save()
        self.assertEqual(rozetler.bekleyen_basvurular(None), "")

    def test_yuz_ustu_kisaltilir(self):
        from unittest.mock import patch

        from apps import rozetler

        with patch.object(rozetler, "UST_SINIR", 2):
            from apps.bayi.models import BayiBasvurusu

            for sira in range(5):
                BayiBasvurusu.objects.create(
                    isim=f"Aday{sira}", soyisim="Test", irtibat="5551112233"
                )
            self.assertEqual(rozetler.bekleyen_bayi_basvurulari(None), "2+")


class BayiBasvurusundaParola(TestCase):
    """Başvuran parolasını kendisi seçer; hesap açılınca onunla girer."""

    ADRES = "/bayi-basvurusu/"

    def _veri(self, **degisiklik):
        veri = {
            "isim": "Melih",
            "soyisim": "Kaya",
            "irtibat": "5551234567",
            "parola": "CokGuclu-Parola-2026",
            "parola_tekrar": "CokGuclu-Parola-2026",
            "website": "",
        }
        veri.update(degisiklik)
        return veri

    def test_parola_duz_metin_saklanmaz(self):
        from django.contrib.auth.hashers import check_password

        from apps.bayi.models import BayiBasvurusu

        self.client.post(self.ADRES, self._veri())

        basvuru = BayiBasvurusu.objects.get()
        self.assertNotIn("CokGuclu-Parola-2026", basvuru.parola_ozeti)
        self.assertTrue(check_password("CokGuclu-Parola-2026", basvuru.parola_ozeti))

    def test_parolalar_uyusmazsa_kayit_olmaz(self):
        from apps.bayi.models import BayiBasvurusu

        cevap = self.client.post(
            self.ADRES, self._veri(parola_tekrar="baska-bir-sey-2026")
        )

        self.assertEqual(BayiBasvurusu.objects.count(), 0)
        self.assertContains(cevap, "Parolalar aynı değil")

    def test_zayif_parola_reddedilir(self):
        from apps.bayi.models import BayiBasvurusu

        self.client.post(self.ADRES, self._veri(parola="12345", parola_tekrar="12345"))

        self.assertEqual(BayiBasvurusu.objects.count(), 0)

    def test_ayni_numarayla_ikinci_basvuru_alinmaz(self):
        from apps.bayi.models import BayiBasvurusu

        self.client.post(self.ADRES, self._veri())
        cevap = self.client.post(self.ADRES, self._veri(isim="Başkası"))

        self.assertEqual(BayiBasvurusu.objects.count(), 1)
        self.assertContains(cevap, "bekleyen bir başvurunuz var")

    def test_numara_kullaniciysa_uyarilir(self):
        from django.contrib.auth.models import User

        from apps.bayi.models import BayiBasvurusu

        User.objects.create_user("5551234567", password="parola12345")
        cevap = self.client.post(self.ADRES, self._veri())

        self.assertEqual(BayiBasvurusu.objects.count(), 0)
        self.assertContains(cevap, "açılmış bir hesap var")

    def test_telegram_bildirimine_parola_girmez(self):
        from unittest.mock import patch

        with patch("apps.bayi.views.bayi_basvurusu_bildir") as bildirim:
            self.client.post(self.ADRES, self._veri())

        basvuru = bildirim.call_args.args[0]
        self.assertNotIn("CokGuclu-Parola-2026", str(basvuru.__dict__))


class BasvurudanHesapAcma(TestCase):
    def setUp(self):
        from apps.bayi.models import BayiBasvurusu
        from apps.finans.models import BayiGrubu

        self.client.post(
            "/bayi-basvurusu/",
            {
                "isim": "Melih",
                "soyisim": "Kaya",
                "irtibat": "5551234567",
                "parola": "CokGuclu-Parola-2026",
                "parola_tekrar": "CokGuclu-Parola-2026",
                "website": "",
            },
        )
        self.basvuru = BayiBasvurusu.objects.get()
        # Fiyat kademesi olmadan hesap açılmaz; yönetimin onayda seçtiği alan.
        self.grup = BayiGrubu.objects.create(ad="Standart Bayi")
        self.basvuru.bayi_grubu = self.grup
        self.basvuru.save(update_fields=["bayi_grubu"])

    def test_secilen_parolayla_giris_yapilir(self):
        from apps.bayi.services import bayi_hesabi_ac

        kullanici, yeni = bayi_hesabi_ac(self.basvuru)

        self.assertTrue(yeni)
        self.assertEqual(kullanici.get_username(), "5551234567")
        self.assertTrue(kullanici.check_password("CokGuclu-Parola-2026"))
        self.assertTrue(
            self.client.login(username="5551234567", password="CokGuclu-Parola-2026")
        )

    def test_profil_ve_cuzdan_da_acilir(self):
        from apps.bayi.services import bayi_hesabi_ac

        kullanici, _ = bayi_hesabi_ac(self.basvuru)

        self.assertTrue(kullanici.bayi_profili.bayi_mi)
        self.assertEqual(kullanici.bayi_profili.telefon, "5551234567")
        self.assertEqual(kullanici.cuzdan.bakiye, 0)
        self.assertEqual(kullanici.cuzdan.grup, self.grup)

    def test_basvuruda_secilen_fiyat_kademesi_cuzdana_gecer(self):
        """Onayda seçilen grup cüzdana yazılır: iki ekranda iki kez uğraşılmaz."""
        from apps.bayi.services import bayi_hesabi_ac
        from apps.finans.models import BayiGrubu

        grup = BayiGrubu.objects.create(ad="Altın Bayi")
        self.basvuru.bayi_grubu = grup
        self.basvuru.save(update_fields=["bayi_grubu"])

        kullanici, _ = bayi_hesabi_ac(self.basvuru)

        self.assertEqual(kullanici.cuzdan.grup, grup)

    def test_kademesiz_basvurudan_hesap_acilmaz(self):
        """Kademesiz cüzdanda hakediş kuralları işlemez; kapı orada durur.

        Bir süre yalnızca uyarı vardı: hesap açılıyor, yönetici uyarıyı
        okumayınca bayi işlem yapıyor ve karşılığında hiçbir şey almıyordu.
        """
        from apps.bayi.models import BayiBasvuruDurumu, BayiBasvurusu
        from apps.bayi.services import HesapAcilamadi, bayi_hesabi_ac

        self.basvuru.bayi_grubu = None
        self.basvuru.save(update_fields=["bayi_grubu"])

        with self.assertRaises(HesapAcilamadi):
            bayi_hesabi_ac(self.basvuru)

        self.basvuru.refresh_from_db()
        self.assertIsNone(self.basvuru.olusturulan_kullanici)
        self.assertNotEqual(self.basvuru.durum, BayiBasvuruDurumu.ONAYLANDI)

    def test_basvuru_onaylandi_olur_ve_hesaba_baglanir(self):
        from apps.bayi.models import BayiBasvuruDurumu
        from apps.bayi.services import bayi_hesabi_ac

        kullanici, _ = bayi_hesabi_ac(self.basvuru)
        self.basvuru.refresh_from_db()

        self.assertEqual(self.basvuru.durum, BayiBasvuruDurumu.ONAYLANDI)
        self.assertEqual(self.basvuru.olusturulan_kullanici, kullanici)

    def test_ikinci_cagri_yeni_hesap_acmaz(self):
        from django.contrib.auth.models import User

        from apps.bayi.services import bayi_hesabi_ac

        bayi_hesabi_ac(self.basvuru)
        self.basvuru.refresh_from_db()
        _, yeni = bayi_hesabi_ac(self.basvuru)

        self.assertFalse(yeni)
        self.assertEqual(User.objects.filter(username="5551234567").count(), 1)

    def test_kullanici_adi_doluysa_anlasilir_hata(self):
        from django.contrib.auth.models import User

        from apps.bayi.services import HesapAcilamadi, bayi_hesabi_ac

        User.objects.create_user("5551234567", password="parola12345")

        with self.assertRaises(HesapAcilamadi):
            bayi_hesabi_ac(self.basvuru)

    def test_parolasiz_eski_basvuruda_hesap_girise_kapali_acilir(self):
        from apps.bayi.services import bayi_hesabi_ac

        self.basvuru.parola_ozeti = ""
        self.basvuru.save(update_fields=["parola_ozeti"])

        kullanici, _ = bayi_hesabi_ac(self.basvuru)

        self.assertFalse(kullanici.has_usable_password())

    def test_eski_bicimli_numara_hesap_acarken_duzeltilir(self):
        """Normalleştirme gelmeden önce alınmış başvurular da tek biçime iner.

        `irtibat` "05551234567" kalırsa hesap o adla açılır; bayi numarasını
        `5551234567` diye yazar ve giremez.
        """
        from apps.bayi.models import BayiBasvurusu
        from apps.bayi.services import bayi_hesabi_ac

        # save() normalleştirdiği için kolona doğrudan yazıyoruz.
        BayiBasvurusu.objects.filter(pk=self.basvuru.pk).update(
            irtibat="0555 123 45 67"
        )
        self.basvuru.refresh_from_db()

        kullanici, _ = bayi_hesabi_ac(self.basvuru)

        self.assertEqual(kullanici.get_username(), "5551234567")
        self.assertTrue(
            self.client.login(username="5551234567", password="CokGuclu-Parola-2026")
        )


class YonetimdenOnaylama(TestCase):
    """Durumu “Onaylandı” yapmak hesabı da açar.

    Hesabın ayrıca listeden bir işlemle açılmasını beklemek sessiz bir
    tuzaktı: yönetici onayladığını sanıyor, bayi giriş ekranında hata
    görüyordu.
    """

    ADRES = "/yonetim/bayi/bayibasvurusu/{}/change/"

    def setUp(self):
        from django.contrib.auth.models import User

        from apps.bayi.models import BayiBasvurusu

        self.client.post(
            "/bayi-basvurusu/",
            {
                "isim": "Melih",
                "soyisim": "Kaya",
                "irtibat": "5551234567",
                "parola": "CokGuclu-Parola-2026",
                "parola_tekrar": "CokGuclu-Parola-2026",
                "website": "",
            },
        )
        self.basvuru = BayiBasvurusu.objects.get()
        self.yonetici = User.objects.create_superuser("yonetici", password="Panel-2026x")
        self.client.force_login(self.yonetici)

        from apps.finans.models import BayiGrubu

        self.grup = BayiGrubu.objects.create(ad="Standart Bayi")

    def _onayla(self, bayi_grubu=None):
        """Kademe verilmezse varsayılan grup seçilir; "" kademesiz onay demek."""
        return self.client.post(
            self.ADRES.format(self.basvuru.pk),
            {
                "durum": "onaylandi",
                "bayi_grubu": self.grup.pk if bayi_grubu is None else bayi_grubu,
                "notlar": "",
                "olusturulan_kullanici": "",
            },
            follow=True,
        )

    def test_kademesiz_onay_kaydedilmez(self):
        """Kayıt "Onaylandı" görünüp hesabın açılmaması sessiz tuzaktı."""
        from apps.bayi.models import BayiBasvuruDurumu

        cevap = self._onayla(bayi_grubu="")
        self.basvuru.refresh_from_db()

        self.assertContains(cevap, "fiyat kademesini seçin")
        self.assertNotEqual(self.basvuru.durum, BayiBasvuruDurumu.ONAYLANDI)
        self.assertIsNone(self.basvuru.olusturulan_kullanici)

    def test_onayda_secilen_kademe_cuzdana_yazilir(self):
        self._onayla()
        self.basvuru.refresh_from_db()

        self.assertEqual(
            self.basvuru.olusturulan_kullanici.cuzdan.grup, self.grup
        )

    def test_durum_onaylandi_yapilinca_hesap_acilir(self):
        self._onayla()
        self.basvuru.refresh_from_db()

        self.assertIsNotNone(self.basvuru.olusturulan_kullanici)
        self.assertEqual(
            self.basvuru.olusturulan_kullanici.get_username(), "5551234567"
        )

    def test_acilan_hesapla_secilen_parolayla_girilir(self):
        self._onayla()
        self.client.logout()

        cevap = self.client.post(
            "/giris-yap/",
            {"username": "0555 123 45 67", "password": "CokGuclu-Parola-2026"},
        )

        self.assertEqual(cevap.status_code, 302)
        self.assertEqual(cevap["Location"], "/panel/")

    def test_ikinci_kayit_yeni_hesap_acmaz(self):
        from django.contrib.auth.models import User

        self._onayla()
        self._onayla()

        self.assertEqual(User.objects.filter(username="5551234567").count(), 1)

    def test_parolasiz_basvuruda_uyari_gosterilir(self):
        from apps.bayi.models import BayiBasvurusu

        BayiBasvurusu.objects.filter(pk=self.basvuru.pk).update(parola_ozeti="")

        cevap = self._onayla()

        self.assertContains(cevap, "parolası yok")

    def test_kullanici_adi_doluysa_hesap_acilmaz_ve_hata_gosterilir(self):
        from django.contrib.auth.models import User

        User.objects.create_user("5551234567", password="baska-parola-123")

        cevap = self._onayla()
        self.basvuru.refresh_from_db()

        self.assertContains(cevap, "zaten alınmış")
        self.assertIsNone(self.basvuru.olusturulan_kullanici)


class TelefonNormallestirme(TestCase):
    """Kullanıcı adı telefon olduğu için numara tek biçimde saklanmalı."""

    def test_bosluk_ulke_kodu_ve_bastaki_sifir_atilir(self):
        from apps.bayi.telefon import normalize

        for yazim in (
            "0532 123 45 67",
            "+90 532 123 45 67",
            "90 532 123 45 67",
            "532-123-45-67",
            "(0532) 123 45 67",
            " 05321234567 ",
            "5321234567",
        ):
            self.assertEqual(normalize(yazim), "5321234567", yazim)

    def test_harf_iceren_kullanici_adi_bozulmaz(self):
        from apps.bayi.telefon import normalize

        for ad in ("fadil", "bayi.kaya", "tedarikci.ege"):
            self.assertEqual(normalize(ad), ad)

    def test_bos_deger_gecer(self):
        from apps.bayi.telefon import normalize

        self.assertEqual(normalize(""), "")
        self.assertIsNone(normalize(None))

    def test_admin_kullanici_adini_numaraya_cevirir(self):
        from django.contrib.auth.models import User

        from apps.bayi.admin import BayiKullaniciEklemeFormu

        form = BayiKullaniciEklemeFormu(
            data={
                "username": "0532 123 45 67",
                "password1": "CokGuclu-Parola-2026",
                "password2": "CokGuclu-Parola-2026",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()

        self.assertTrue(User.objects.filter(username="5321234567").exists())

    def test_admin_gercek_kullanici_adina_dokunmaz(self):
        from django.contrib.auth.models import User

        from apps.bayi.admin import BayiKullaniciEklemeFormu

        form = BayiKullaniciEklemeFormu(
            data={
                "username": "fadil",
                "password1": "CokGuclu-Parola-2026",
                "password2": "CokGuclu-Parola-2026",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()

        self.assertTrue(User.objects.filter(username="fadil").exists())

    def test_profil_telefonu_tek_bicimde_saklanir(self):
        from django.contrib.auth.models import User

        from apps.bayi.models import BayiProfili

        kullanici = User.objects.create_user("5321234567", password="parola12345")
        profil = BayiProfili.objects.create(
            kullanici=kullanici, telefon="0532 123 45 67"
        )

        profil.refresh_from_db()
        self.assertEqual(profil.telefon, "5321234567")

    def test_basvuru_numarasi_form_disindan_da_temizlenir(self):
        from apps.bayi.models import BayiBasvurusu

        basvuru = BayiBasvurusu.objects.create(
            isim="Melih", soyisim="Kaya", irtibat="+90 532 123 45 67"
        )

        basvuru.refresh_from_db()
        self.assertEqual(basvuru.irtibat, "5321234567")
        self.assertEqual(basvuru.kullanici_adi, "5321234567")


class TelefonlaGiris(TestCase):
    """Bayi numarasını nasıl yazarsa yazsın girebilmeli."""

    ADRES = "/giris-yap/"

    def setUp(self):
        from django.contrib.auth.models import User

        User.objects.create_user("5321234567", password="CokGuclu-Parola-2026")

    def _dene(self, kullanici_adi):
        self.client.logout()
        cevap = self.client.post(
            self.ADRES,
            {"username": kullanici_adi, "password": "CokGuclu-Parola-2026"},
        )
        return cevap.wsgi_request.user.is_authenticated

    def test_bosluklu_ve_sifirli_yazim_kabul_edilir(self):
        for yazim in ("0532 123 45 67", "+90 532 123 45 67", "5321234567"):
            self.assertTrue(self._dene(yazim), yazim)

    def test_yanlis_parola_yine_reddedilir(self):
        cevap = self.client.post(
            self.ADRES, {"username": "0532 123 45 67", "password": "yanlis"}
        )
        self.assertFalse(cevap.wsgi_request.user.is_authenticated)

    def test_harfli_kullanici_adi_calismaya_devam_eder(self):
        from django.contrib.auth.models import User

        User.objects.create_user("fadil", password="CokGuclu-Parola-2026")
        self.assertTrue(self._dene("fadil"))


class YeniParolaDugmesi(TestCase):
    """Bayi parolasını unutunca yönetici tek düğmeyle yenisini verir.

    E-posta ile sıfırlama yok: üretilen parola ekranda bir kez gösterilir,
    yönetici bayiye iletir.
    """

    def setUp(self):
        from django.contrib.auth.models import User

        self.bayi = User.objects.create_user("5524144444", password="eski-parola-99")
        self.yonetici = User.objects.create_superuser("fadil", password="Panel-2026x")
        self.client.force_login(self.yonetici)
        self.adres = f"/yonetim/auth/user/{self.bayi.pk}/yeni-parola/"

    def test_get_onay_sorar_parolayi_degistirmez(self):
        cevap = self.client.get(self.adres)
        self.bayi.refresh_from_db()

        self.assertEqual(cevap.status_code, 200)
        self.assertTrue(self.bayi.check_password("eski-parola-99"))

    def test_post_yeni_parola_uretir_ve_gosterir(self):
        from apps.bayi.parola import KELIMELER

        cevap = self.client.post(self.adres)
        self.bayi.refresh_from_db()

        self.assertEqual(cevap.status_code, 200)
        self.assertFalse(self.bayi.check_password("eski-parola-99"))

        # Ekranda gösterilen parola gerçekten hesabın parolası olmalı.
        icerik = cevap.content.decode()
        parola = next(
            satir.strip()
            for satir in icerik.splitlines()
            if satir.strip().startswith("Parola: ")
        ).removeprefix("Parola: ").split("<")[0]
        self.assertTrue(self.bayi.check_password(parola))
        self.assertIn(parola.split("-")[0], KELIMELER)

    def test_kendi_parolasini_yenileyen_yonetici_oturumdan_dusmez(self):
        adres = f"/yonetim/auth/user/{self.yonetici.pk}/yeni-parola/"

        self.client.post(adres)
        cevap = self.client.get("/yonetim/")

        self.assertEqual(cevap.status_code, 200)

    def test_yetkisiz_kullanici_parola_uretemez(self):
        self.client.force_login(self.bayi)

        cevap = self.client.post(self.adres)
        self.bayi.refresh_from_db()

        self.assertIn(cevap.status_code, (302, 403))
        self.assertTrue(self.bayi.check_password("eski-parola-99"))

    def test_uretilen_parola_her_seferinde_farkli(self):
        from apps.bayi.parola import uret

        self.assertGreater(len({uret() for _ in range(50)}), 45)


class AcilanHesapKutusu(TestCase):
    """Başvuru ekranındaki hesap kutusu kullanıcı silmemeli.

    Kutunun yanındaki kırmızı çöp kutusu seçimi değil kullanıcının kendisini
    siliyordu; yanlış hesap seçilince ilk refleks ona basmak oluyor.
    """

    def test_silme_dugmesi_gosterilmez(self):
        from django.contrib.auth.models import User

        from apps.bayi.models import BayiBasvurusu

        yonetici = User.objects.create_superuser("fadil", password="Panel-2026x")
        basvuru = BayiBasvurusu.objects.create(
            isim="Melih", soyisim="Kaya", irtibat="5551234567"
        )
        self.client.force_login(yonetici)

        icerik = self.client.get(
            f"/yonetim/bayi/bayibasvurusu/{basvuru.pk}/change/"
        ).content.decode()

        self.assertNotIn("delete_olusturulan_kullanici", icerik)
        self.assertNotIn("add_olusturulan_kullanici", icerik)


class PaneldeAylikHakedis(TestCase):
    """Panelin "Bu ay hakediş" rakamı başvurulardan okunur.

    Yalnızca HAKEDIS tipli defter satırlarını toplamak iki yerde yanlış
    sonuç veriyordu: iptalin ters kaydı sayılmadığı için bakiye sıfırlanmışken
    panelde hakediş duruyordu, borcu kapatan hakediş de BORC_TAHSIL satırına
    düştüğü için eksik görünüyordu.
    """

    def setUp(self):
        from decimal import Decimal

        from apps.basvurular.models import BasvuruDurumu
        from apps.finans.models import KuralYonu, UcretKurali
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
        self.cuzdan = Cuzdan.objects.create(bayi=self.bayi, bakiye=Decimal("0.00"))

        self.operator = Operator.objects.create(ad="Turkcell")
        self.kategori = BasvuruKategorisi.objects.create(ad="Faturalı Yeni Hat")
        self.tarife = Tarife.objects.create(
            operator=self.operator, ad="Platinum"
        )
        self.tarife.kategoriler.add(self.kategori)
        UcretKurali.objects.create(
            ad="Hakediş", yon=KuralYonu.HAKEDIS, tutar=Decimal("250.00"),
            tetikleyici_durum=self.aktif, kategori=self.kategori,
        )
        self.client.force_login(self.bayi)

    def _basvuru(self, durum=None):
        from apps.basvurular.models import Basvuru

        return Basvuru.objects.create(
            bayi=self.bayi, kategori=self.kategori, operator=self.operator,
            tarife=self.tarife, isim="Ayşe", soyisim="Demir", kimlik_no="1",
            irtibat="5551112233", durum=durum or self.beklemede,
        )

    def _panel_hakedisi(self):
        return self.client.get(reverse("bayi:panel")).context["aylik_hakedis"]

    def test_aktif_basvurunun_hakedisi_gorunur(self):
        from decimal import Decimal

        basvuru = self._basvuru()
        basvuru.durum = self.aktif
        basvuru.save()

        self.assertEqual(self._panel_hakedisi(), Decimal("250.00"))

    def test_iptal_edilen_basvurunun_hakedisi_dusulur(self):
        """Bakiye sıfırlanmışken panelde hakediş durup kalıyordu."""
        basvuru = self._basvuru()
        basvuru.durum = self.aktif
        basvuru.save()
        basvuru.durum = self.iptal
        basvuru.save()

        self.cuzdan.refresh_from_db()
        self.assertEqual(self.cuzdan.bakiye, 0)
        self.assertEqual(self._panel_hakedisi(), 0)

    def test_borcu_kapatan_hakedis_tam_gorunur(self):
        """Hakedişin borca giden kısmı da bayinin kazancıdır."""
        from decimal import Decimal

        self.cuzdan.borc = Decimal("100.00")
        self.cuzdan.save(update_fields=["borc"])

        basvuru = self._basvuru()
        basvuru.durum = self.aktif
        basvuru.save()

        self.cuzdan.refresh_from_db()
        self.assertEqual(self.cuzdan.bakiye, Decimal("150.00"))
        self.assertEqual(self.cuzdan.borc, 0)
        # Cüzdana 150 girdi ama bayinin bu aydaki hakedişi 250'dir.
        self.assertEqual(self._panel_hakedisi(), Decimal("250.00"))


class SatirIslemleriGorunur(TestCase):
    """Kullanıcı listesindeki işlem düğmeleri açılır menüde saklanmaz.

    unfold bunları "..." arkasına koyuyordu; yönetici her bayi için önce
    menüyü açmak zorundaydı. Günlük iş bu düğmelere basmak.
    """

    def setUp(self):
        self.bayi = User.objects.create_user("5551112233", password="parola12345")
        self.yonetici = User.objects.create_superuser("yonetici", password="Panel-2026x")
        self.client.force_login(self.yonetici)

    def test_dugmeler_listede_dogrudan_gorunur(self):
        icerik = self.client.get(reverse("admin:auth_user_changelist")).content.decode()

        self.assertIn("Yeni parola", icerik)
        self.assertIn("Bakiye / borç", icerik)
        # Açılır menünün üç noktası kalmadı.
        self.assertNotIn("more_horiz", icerik)

    def test_dugmeler_dogru_adrese_gider(self):
        from django.urls import reverse as ters

        icerik = self.client.get(reverse("admin:auth_user_changelist")).content.decode()

        self.assertIn(ters("admin:auth_user_yeni_parola", args=[self.bayi.pk]), icerik)
        self.assertIn(ters("admin:auth_user_cuzdan_islemi", args=[self.bayi.pk]), icerik)


class CuzdanHareketiOncekiSonraki(TestCase):
    """Bayi her hareketin bakiyeye ve borca etkisini görsün.

    Yalnızca tutarı göstermek "benim bakiyem neden bu" sorusunu cevapsız
    bırakıyor, bayi arayıp soruyordu.
    """

    def setUp(self):
        from decimal import Decimal

        from apps.finans.models import CuzdanHareketi, HareketTipi

        self.bayi = User.objects.create_user("bayi", password="parola12345")
        self.cuzdan = Cuzdan.objects.create(bayi=self.bayi, bakiye=Decimal("150.00"))

        CuzdanHareketi.objects.create(
            cuzdan=self.cuzdan, tip=HareketTipi.HAKEDIS, tutar=Decimal("150.00"),
            onceki_bakiye=Decimal("0.00"), sonraki_bakiye=Decimal("150.00"),
            onceki_borc=Decimal("0.00"), sonraki_borc=Decimal("0.00"),
            idempotency_anahtari="h1", aciklama="Hakediş",
        )
        self.client.force_login(self.bayi)

    def _sayfa(self):
        return self.client.get(reverse("bayi:cuzdan")).content.decode()

    def test_bakiyenin_onceki_ve_sonraki_hali_yazar(self):
        icerik = self._sayfa()

        self.assertIn("0,00 →", icerik)
        self.assertIn("150,00 ₺", icerik)

    def test_borc_degismediyse_satir_cikmaz(self):
        """Hiç borcu olmayan bayi sıfır kalabalığı görmesin."""
        icerik = self._sayfa()

        self.assertNotIn("Borç</dt>", icerik)

    def test_borc_degistiyse_satir_cikar(self):
        from decimal import Decimal

        from apps.finans.models import CuzdanHareketi, HareketTipi

        CuzdanHareketi.objects.create(
            cuzdan=self.cuzdan, tip=HareketTipi.BORC_EKLE, tutar=Decimal("400.00"),
            onceki_bakiye=Decimal("150.00"), sonraki_bakiye=Decimal("150.00"),
            onceki_borc=Decimal("0.00"), sonraki_borc=Decimal("400.00"),
            idempotency_anahtari="h2", aciklama="Borç",
        )

        icerik = self._sayfa()

        self.assertIn("400,00 ₺", icerik)
