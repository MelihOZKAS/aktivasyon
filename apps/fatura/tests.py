"""Fatura: kurum kuralı, robot sözleşmesi, ödeme ve karar."""

import json
from datetime import timedelta
from decimal import Decimal as TL
from io import StringIO

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.fatura.models import Kategori, Kurum, Odeme, OdemeDurumu, Robot, Sorgu, SorguDurumu
from apps.fatura.services import (
    FaturaHatasi,
    KararVerilemez,
    iptal_et,
    is_ver,
    katalog_yaz,
    nabiz,
    odeme_baslat,
    odendi_isaretle,
    sabit_odeme_baslat,
    sonuc_yaz,
    sorgu_baslat,
    suresi_dolanlari_kapat,
)
from apps.finans.models import Cuzdan
from apps.finans.services import SiparisVerilemez
from apps.magaza.models import Siparis, SiparisDurumu

ROBOT_VERISI = {
    "durum": "bulundu",
    "mesaj": "",
    "abone_adi": "M***** A*****",
    "tesisat_no": "5332590138",
    "kurum": "Vodafone",
    "odenmesi_gereken": 610.0,
    "faturalar": [
        {"fatura_no": "FD60950NCB9D53", "son_odeme_tarihi": "14.10.2026", "fatura_bedeli": "390,00",
         "fatura_bedeli_tl": 390.0, "g_hizmet_bedeli": 0.0, "islem_bedeli": 20.0, "toplam_tutar": 410.0,
         "odeme_token": "tok1"},
        {"fatura_no": "FD00000000002", "son_odeme_tarihi": "14.11.2026", "fatura_bedeli": "180,00",
         "fatura_bedeli_tl": 180.0, "g_hizmet_bedeli": 0.0, "islem_bedeli": 20.0, "toplam_tutar": 200.0,
         "odeme_token": "tok2"},
    ],
}


class Temel(TestCase):
    def setUp(self):
        self.gsm = Kategori.objects.create(ad="GSM", sira=1)
        self.vodafone = Kurum.objects.create(
            kod="vodafone", ad="Vodafone", kategori=self.gsm, sorgulu=True,
            alan_etiketi="Telefon Numarası", min_hane=10, max_hane=10, sadece_rakam=True,
            hizmet_bedeli=TL("5.00"), tavsiye=TL("10.00"),
        )
        self.hgs = Kurum.objects.create(
            kod="100-tl-yukle-plaka", ad="100 TL Yükle Plaka", sorgulu=False,
            alan_etiketi="Plaka", min_hane=7, max_hane=11, sadece_rakam=False,
            bayi_fiyati=TL("102.00"), tavsiye=TL("105.00"), alis_fiyati=TL("100.00"),
        )
        self.bayi = User.objects.create_user("5321112233", password="parola12345")
        self.cuzdan = Cuzdan.objects.create(bayi=self.bayi, bakiye=TL("1000.00"))
        self.robot = Robot.objects.create(ad="ev-laptop")
        self.anahtar = self.robot.yeni_anahtar()
        nabiz(self.robot)

    def bakiye(self):
        self.cuzdan.refresh_from_db()
        return self.cuzdan.bakiye

    def tamam_sorgu(self, numara="5332590138", bayi=None):
        """Robotun sonucunu yazdığı, ödenmeye hazır sorgu."""
        sorgu = Sorgu.objects.create(bayi=bayi or self.bayi, kurum=self.vodafone, numara=numara)
        sorgu.durum = SorguDurumu.SORGULANIYOR
        sorgu.save()
        return sonuc_yaz(self.robot, sorgu.pk, veri=ROBOT_VERISI)


class KuralTestleri(Temel):
    def test_telefon_temizlenir_bastaki_sifir_atilir(self):
        self.assertEqual(self.vodafone.numarayi_dogrula("0533 259 01 38"), "5332590138")
        self.assertEqual(self.vodafone.numarayi_dogrula("+90 533 259 01 38"), "5332590138")

    def test_rakam_ve_hane_kurali(self):
        with self.assertRaises(ValidationError):
            self.vodafone.numarayi_dogrula("53325901AB")
        with self.assertRaises(ValidationError):
            self.vodafone.numarayi_dogrula("533259")

    def test_plaka_harf_alir_buyuk_yazilir(self):
        self.assertEqual(self.hgs.numarayi_dogrula("34 abc 123"), "34ABC123")

    def test_fiyatsiz_sorgusuz_ve_kapali_kategori_satista_degil(self):
        self.assertIn(self.hgs, Kurum.objects.bayiye_acik(None))
        self.hgs.bayi_fiyati = None
        self.hgs.save()
        self.assertNotIn(self.hgs, Kurum.objects.bayiye_acik(None))
        self.gsm.aktif = False
        self.gsm.save()
        self.assertNotIn(self.vodafone, Kurum.objects.bayiye_acik(None))


class SorguTestleri(Temel):
    def test_robot_yoksa_sorgu_acilmaz(self):
        Robot.objects.update(son_nabiz=timezone.now() - timedelta(minutes=5))
        with self.assertRaisesMessage(FaturaHatasi, "şu an yapılamıyor"):
            sorgu_baslat(self.bayi, self.vodafone, "5332590138")
        self.assertFalse(Sorgu.objects.exists())

    def test_ayni_numara_az_once_sorgulandiysa_o_doner(self):
        a = sorgu_baslat(self.bayi, self.vodafone, "0533 259 01 38")
        b = sorgu_baslat(self.bayi, self.vodafone, "5332590138")
        self.assertEqual(a.pk, b.pk)
        self.assertEqual(a.numara, "5332590138")

    def test_kurala_uymayan_numara_robota_gitmez(self):
        with self.assertRaises(FaturaHatasi):
            sorgu_baslat(self.bayi, self.vodafone, "12")
        self.assertFalse(Sorgu.objects.exists())

    def test_alinmayan_ve_takilan_sorgu_kapanir(self):
        eski = Sorgu.objects.create(bayi=self.bayi, kurum=self.vodafone, numara="5332590138")
        Sorgu.objects.filter(pk=eski.pk).update(olusturma_tarihi=timezone.now() - timedelta(minutes=2))
        takilan = Sorgu.objects.create(
            bayi=self.bayi, kurum=self.vodafone, numara="5332590139",
            durum=SorguDurumu.SORGULANIYOR, alinma_tarihi=timezone.now() - timedelta(minutes=3),
        )
        suresi_dolanlari_kapat()
        eski.refresh_from_db()
        takilan.refresh_from_db()
        self.assertEqual((eski.durum, takilan.durum), (SorguDurumu.HATA, SorguDurumu.HATA))
        # Kapanan sorgu robota verilmez.
        self.assertIsNone(is_ver(self.robot))


class RobotApiTestleri(Temel):
    def iste(self, ad, govde=None, anahtar=None):
        baslik = {"HTTP_AUTHORIZATION": f"Bearer {anahtar if anahtar is not None else self.anahtar}"}
        adres = reverse(f"fatura:robot-{ad}")
        if govde is None:
            return self.client.get(adres, **baslik)
        return self.client.post(adres, data=json.dumps(govde), content_type="application/json", **baslik)

    def test_anahtarsiz_ya_da_yanlis_anahtar_401(self):
        self.assertEqual(self.client.get(reverse("fatura:robot-is")).status_code, 401)
        self.assertEqual(self.iste("is", anahtar="yanlis").status_code, 401)
        self.robot.aktif = False
        self.robot.save()
        self.assertEqual(self.iste("is").status_code, 401)

    def test_is_bir_robota_bir_kez_verilir(self):
        sorgu = sorgu_baslat(self.bayi, self.vodafone, "5332590138")
        cevap = self.iste("is").json()
        self.assertEqual(cevap["talep"], {
            "talep_id": sorgu.pk, "kurum_id": "vodafone", "kurum_adi": "Vodafone", "numara": "5332590138",
        })
        # İkinci robot (ya da ikinci istek) aynı sorguyu alamaz.
        ikinci = Robot.objects.create(ad="server-1")
        anahtar2 = ikinci.yeni_anahtar()
        self.assertEqual(self.iste("is", anahtar=anahtar2).json(), {"var": False})
        sorgu.refresh_from_db()
        self.assertEqual((sorgu.durum, sorgu.robot), (SorguDurumu.SORGULANIYOR, self.robot))

    def test_sonuc_yazilir_tutar_kayitta_durur(self):
        sorgu = sorgu_baslat(self.bayi, self.vodafone, "5332590138")
        self.iste("is")
        self.assertEqual(self.iste("sonuc", {"talep_id": sorgu.pk, "robot": "ev-laptop", "veri": ROBOT_VERISI}).status_code, 200)
        sorgu.refresh_from_db()
        self.assertEqual(sorgu.durum, SorguDurumu.TAMAM)
        self.assertEqual(sorgu.abone_adi, "M***** A*****")
        self.assertEqual([f["toplam_tutar"] for f in sorgu.faturalar], ["410.00", "200.00"])

    def test_saglayici_hatasi_bayiye_mesajiyla_gider(self):
        sorgu = sorgu_baslat(self.bayi, self.vodafone, "5332590138")
        self.iste("is")
        veri = {"durum": "hata", "mesaj": "23:00 - 06:00 ARASINDA FATURA TAHSİLATI YAPILAMAMAKTADIR", "faturalar": []}
        self.iste("sonuc", {"talep_id": sorgu.pk, "veri": veri})
        sorgu.refresh_from_db()
        self.assertEqual(sorgu.durum, SorguDurumu.HATA)
        self.assertIn("23:00", sorgu.mesaj)

    def test_robot_hatasi_bayiye_ham_gosterilmez_gec_sonuc_yutulur(self):
        sorgu = sorgu_baslat(self.bayi, self.vodafone, "5332590138")
        self.iste("is")
        self.iste("sonuc", {"talep_id": sorgu.pk, "basarisiz": True, "hata": "Oturum düştü"})
        sorgu.refresh_from_db()
        self.assertEqual(sorgu.durum, SorguDurumu.HATA)
        self.assertNotIn("Oturum", sorgu.mesaj)
        self.assertEqual(sorgu.sonuc["robot_hatasi"], "Oturum düştü")
        # Kapanmış sorguya gelen geç sonuç durumu değiştirmez.
        self.iste("sonuc", {"talep_id": sorgu.pk, "veri": ROBOT_VERISI})
        sorgu.refresh_from_db()
        self.assertEqual(sorgu.durum, SorguDurumu.HATA)

    def test_nabiz_oturum_durumunu_yazar(self):
        self.iste("kalp", {"robot": "ev-laptop", "durum": "mesgul", "oturum": "dustu"})
        self.robot.refresh_from_db()
        self.assertTrue(self.robot.mesgul)
        self.assertFalse(self.robot.oturum_canli)
        self.assertTrue(self.robot.cevrimici)

    def test_katalog_yeni_kurumu_kapali_acar_yonetimin_kararini_korur(self):
        self.vodafone.aktif = True
        self.vodafone.hizmet_bedeli = TL("7.00")
        self.vodafone.save()
        kurumlar = [
            {"id": "vodafone", "kurum_adi": "Vodafone", "alanlar": [{"etiket": "Telefon", "min": "10", "max": "11", "tur": "int"}]},
            {"id": "turkcell", "kurum_adi": "Turkcell", "aktif": True,
             "alanlar": [{"etiket": "Telefon Numarası", "min": "10", "max": "10", "tur": "int"}]},
        ]
        cevap = self.iste("katalog", {"robot": "ev-laptop", "kurumlar": kurumlar}).json()
        self.assertEqual(cevap, {"eklenen": 1, "guncellenen": 1})
        self.vodafone.refresh_from_db()
        self.assertEqual((self.vodafone.max_hane, self.vodafone.alan_etiketi), (11, "Telefon"))
        self.assertEqual(self.vodafone.hizmet_bedeli, TL("7.00"))   # yönetimin kararı
        self.assertFalse(Kurum.objects.get(kod="turkcell").aktif)   # yönetim bakmadan açılmaz


class OdemeTestleri(Temel):
    def test_tutar_sorgunun_kaydindan_hizmet_bedeli_eklenir(self):
        sorgu = self.tamam_sorgu()
        odeme = odeme_baslat(self.bayi, sorgu, ["FD60950NCB9D53"])
        # 410 sağlayıcı + 5 hizmet = 415; müşteriye 410 + 10 = 420 (gruptan bağımsız).
        self.assertEqual(odeme.siparis.tutar, TL("415.00"))
        self.assertEqual((odeme.saglayici_tutari, odeme.hizmet_bedeli, odeme.tavsiye_fiyati), (TL("410.00"), TL("5.00"), TL("420.00")))
        self.assertEqual(self.bakiye(), TL("585.00"))
        self.assertEqual(odeme.durum, OdemeDurumu.BEKLIYOR)
        self.assertEqual(odeme.faturalar[0]["odeme_token"], "tok1")

    def test_ayni_fatura_iki_kez_odenmez_iptalden_sonra_odenir(self):
        sorgu = self.tamam_sorgu()
        odeme = odeme_baslat(self.bayi, sorgu, ["FD60950NCB9D53"])
        with self.assertRaisesMessage(FaturaHatasi, "zaten ödendi"):
            odeme_baslat(self.bayi, sorgu, ["FD60950NCB9D53", "FD00000000002"])
        iptal_et(odeme, sebep="Kurum kapalı")
        odeme_baslat(self.bayi, sorgu, ["FD60950NCB9D53"])

    def test_bakiye_yetmezse_hicbir_sey_acilmaz(self):
        self.cuzdan.bakiye = TL("100.00")
        self.cuzdan.save()
        with self.assertRaises(SiparisVerilemez):
            odeme_baslat(self.bayi, self.tamam_sorgu(), ["FD60950NCB9D53"])
        self.assertFalse(Odeme.objects.exists())
        self.assertFalse(Siparis.objects.exists())
        self.assertEqual(self.bakiye(), TL("100.00"))

    def test_eski_bilinmeyen_ve_baskasinin_sorgusu_odenmez(self):
        sorgu = self.tamam_sorgu()
        with self.assertRaises(FaturaHatasi):
            odeme_baslat(self.bayi, sorgu, ["UYDURMA"])
        baska = User.objects.create_user("5320000000", password="parola12345")
        Cuzdan.objects.create(bayi=baska, bakiye=TL("1000.00"))
        with self.assertRaises(FaturaHatasi):
            odeme_baslat(baska, sorgu, ["FD60950NCB9D53"])
        Sorgu.objects.filter(pk=sorgu.pk).update(sonuc_tarihi=timezone.now() - timedelta(hours=1))
        sorgu.refresh_from_db()
        with self.assertRaisesMessage(FaturaHatasi, "eskidi"):
            odeme_baslat(self.bayi, sorgu, ["FD60950NCB9D53"])

    def test_ayni_anahtar_ikinci_odeme_acmaz(self):
        sorgu = self.tamam_sorgu()
        a = odeme_baslat(self.bayi, sorgu, ["FD60950NCB9D53"], anahtar="k1")
        b = odeme_baslat(self.bayi, sorgu, ["FD60950NCB9D53"], anahtar="k1")
        self.assertEqual(a.pk, b.pk)
        self.assertEqual(self.bakiye(), TL("585.00"))

    def test_sorgusuz_kalem_sabit_fiyatla_odenir_tekrar_korunur(self):
        odeme = sabit_odeme_baslat(self.bayi, self.hgs, "34abc123")
        self.assertEqual((odeme.siparis.tutar, odeme.numara, odeme.hizmet_bedeli), (TL("102.00"), "34ABC123", TL("2.00")))
        self.assertEqual(self.bakiye(), TL("898.00"))
        with self.assertRaisesMessage(FaturaHatasi, "az önce"):
            sabit_odeme_baslat(self.bayi, self.hgs, "34 ABC 123")
        with self.assertRaises(FaturaHatasi):
            sabit_odeme_baslat(self.bayi, self.vodafone, "5332590138")   # sorgulu

    def test_odendi_para_yerinde_iptal_iade(self):
        sorgu = self.tamam_sorgu()
        a = odeme_baslat(self.bayi, sorgu, ["FD60950NCB9D53"])
        b = odeme_baslat(self.bayi, sorgu, ["FD00000000002"])
        self.assertEqual(self.bakiye(), TL("380.00"))   # 1000 - 415 - 205
        odendi_isaretle(a, not_="Dekont 123")
        a.refresh_from_db()
        self.assertEqual((a.durum, a.siparis.durum), (OdemeDurumu.ODENDI, SiparisDurumu.TESLIM))
        iptal_et(b, sebep="Fatura kurumda kapanmış")
        b.refresh_from_db()
        self.assertEqual((b.durum, b.siparis.durum), (OdemeDurumu.IPTAL, SiparisDurumu.IPTAL))
        self.assertEqual(self.bakiye(), TL("585.00"))   # yalnızca iptal edilen döndü
        with self.assertRaises(KararVerilemez):
            iptal_et(a, sebep="geç")
        with self.assertRaises(KararVerilemez):
            odendi_isaretle(b)


class EkranTestleri(Temel):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.bayi)

    def test_ana_sayfa_bolum_ve_kurum(self):
        yanit = self.client.get(reverse("fatura:index"))
        self.assertContains(yanit, "GSM")
        self.assertContains(yanit, "Vodafone")
        self.assertContains(yanit, "Diğer")   # kategorisiz HGS
        self.assertContains(yanit, "100 TL Yükle Plaka")

    def test_kurum_formu_kurali_tasir(self):
        yanit = self.client.get(reverse("fatura:kurum", args=["vodafone"]))
        self.assertContains(yanit, "Telefon Numarası")
        self.assertContains(yanit, 'inputmode="numeric"')
        self.assertContains(yanit, "10 hane")

    def test_robot_kapaliyken_uyari(self):
        Robot.objects.update(son_nabiz=None)
        yanit = self.client.get(reverse("fatura:kurum", args=["vodafone"]))
        self.assertContains(yanit, "şu an kapalı")
        self.assertNotContains(yanit, "Faturayı sorgula")

    def test_sorgu_odeme_akisi(self):
        yanit = self.client.post(reverse("fatura:sorgula", args=["vodafone"]), {"numara": "0533 259 01 38"})
        sorgu = Sorgu.objects.get()
        self.assertRedirects(yanit, sorgu.get_absolute_url())
        self.assertContains(self.client.get(sorgu.get_absolute_url()), "Fatura sorgulanıyor")
        Sorgu.objects.filter(pk=sorgu.pk).update(durum=SorguDurumu.SORGULANIYOR, alinma_tarihi=timezone.now())
        sonuc_yaz(self.robot, sorgu.pk, veri=ROBOT_VERISI)
        yanit = self.client.get(reverse("fatura:sorgu-durum", args=[sorgu.referans_no]))
        self.assertContains(yanit, "FD60950NCB9D53")
        self.assertContains(yanit, "M***** A*****")
        self.assertNotContains(yanit, "hx-trigger")   # sonuç geldi, yoklama durdu
        # Formdaki tutar değil, sorgunun kaydı geçerli: elle eklenen alan yok sayılır.
        yanit = self.client.post(
            reverse("fatura:sorgu-ode", args=[sorgu.referans_no]),
            {"fatura": ["FD60950NCB9D53"], "tutar": "1", "islem_anahtari": "x1"},
        )
        odeme = Odeme.objects.get()
        self.assertRedirects(yanit, odeme.get_absolute_url())
        self.assertEqual(odeme.siparis.tutar, TL("415.00"))
        self.assertContains(self.client.get(odeme.get_absolute_url()), "Ödeniyor")
        # Ödenen fatura yeniden seçilemez.
        self.assertContains(self.client.get(sorgu.get_absolute_url()), "ödendi / ödeniyor")

    def test_hatali_numara_formda_kalir(self):
        yanit = self.client.post(reverse("fatura:sorgula", args=["vodafone"]), {"numara": "12"})
        self.assertRedirects(yanit, reverse("fatura:kurum", args=["vodafone"]) + "?numara=12")
        self.assertFalse(Sorgu.objects.exists())

    def test_fatura_siparisi_magazada_gorunmez(self):
        odeme_baslat(self.bayi, self.tamam_sorgu(), ["FD60950NCB9D53"])
        self.assertNotContains(self.client.get(reverse("magaza:siparislerim")), "Fatura ·")
        self.assertContains(self.client.get(reverse("fatura:odemeler")), "5332590138")

    def test_baskasinin_sorgusu_ve_odemesi_404(self):
        baska = User.objects.create_user("5320000000", password="parola12345")
        sorgu = self.tamam_sorgu(bayi=baska)
        self.assertEqual(self.client.get(sorgu.get_absolute_url()).status_code, 404)


class YonetimTestleri(Temel):
    def setUp(self):
        super().setUp()
        self.client.force_login(User.objects.create_superuser("yonetici", password="x"))

    def test_karar_ekrani_odendi_ve_iptal(self):
        sorgu = self.tamam_sorgu()
        a = odeme_baslat(self.bayi, sorgu, ["FD60950NCB9D53"])
        b = odeme_baslat(self.bayi, sorgu, ["FD00000000002"])
        self.assertContains(self.client.get(reverse("admin:fatura_odeme_changelist")), "Karar")
        adres = reverse("admin:fatura_odeme_karar", args=[a.pk])
        self.assertContains(self.client.get(adres), "FD60950NCB9D53")
        self.client.post(adres, {"karar": "odendi", "not": "Dekont 9"})
        a.refresh_from_db()
        self.assertEqual(a.durum, OdemeDurumu.ODENDI)
        # Sebepsiz iptal kabul edilmez: bayi neden iade aldığını görmeli.
        self.client.post(reverse("admin:fatura_odeme_karar", args=[b.pk]), {"karar": "iptal", "sebep": ""})
        b.refresh_from_db()
        self.assertEqual(b.durum, OdemeDurumu.BEKLIYOR)
        self.client.post(reverse("admin:fatura_odeme_karar", args=[b.pk]), {"karar": "iptal", "sebep": "Kapanmış"})
        b.refresh_from_db()
        self.assertEqual(b.durum, OdemeDurumu.IPTAL)
        self.assertEqual(self.bakiye(), TL("585.00"))

    def test_robot_anahtari_post_ile_uretilir_bir_kez_gosterilir(self):
        adres = reverse("admin:fatura_robot_anahtar", args=[self.robot.pk])
        self.assertNotContains(self.client.get(adres), '"api_key"')
        eski = self.robot.anahtar_ozeti
        yanit = self.client.post(adres)
        self.assertContains(yanit, '"api_key"')
        self.robot.refresh_from_db()
        self.assertNotEqual(self.robot.anahtar_ozeti, eski)

    def test_anahtar_blogu_robot_adresini_yazar(self):
        from django.test import override_settings

        adres = reverse("admin:fatura_robot_anahtar", args=[self.robot.pk])
        with override_settings(FATURA_ROBOT_ADRESI="https://www.aktivasyoncu.com.tr"):
            self.assertContains(self.client.post(adres), '"django_url": "https://www.aktivasyoncu.com.tr"')

    def test_izinsiz_personel_karar_veremez_anahtar_uretemez(self):
        odeme = odeme_baslat(self.bayi, self.tamam_sorgu(), ["FD60950NCB9D53"])
        personel = User.objects.create_user("personel", password="x", is_staff=True)
        self.client.force_login(personel)
        karar = reverse("admin:fatura_odeme_karar", args=[odeme.pk])
        anahtar = reverse("admin:fatura_robot_anahtar", args=[self.robot.pk])
        eski_ozet = Robot.objects.get(pk=self.robot.pk).anahtar_ozeti
        for adres in (karar, anahtar):
            self.assertEqual(self.client.get(adres).status_code, 403)
        self.assertEqual(self.client.post(karar, {"karar": "iptal", "sebep": "deneme"}).status_code, 403)
        self.assertEqual(self.client.post(anahtar).status_code, 403)
        odeme.refresh_from_db()
        self.assertEqual(odeme.durum, OdemeDurumu.BEKLIYOR)
        self.assertEqual(self.bakiye(), TL("585.00"))
        self.assertEqual(Robot.objects.get(pk=self.robot.pk).anahtar_ozeti, eski_ozet)

    def test_listeler_acilir(self):
        self.tamam_sorgu()
        for ad in ("kurum", "kategori", "robot", "sorgu", "odeme"):
            self.assertEqual(self.client.get(reverse(f"admin:fatura_{ad}_changelist")).status_code, 200, ad)


class KurulumTestleri(TestCase):
    def test_tohum_otuz_uc_kurum_acar_var_olana_dokunmaz(self):
        call_command("fatura_kurumlari", stdout=StringIO())
        self.assertEqual(Kurum.objects.count(), 33)
        self.assertEqual(Kategori.objects.count(), 8)
        vodafone = Kurum.objects.get(kod="vodafone")
        self.assertEqual((vodafone.kategori.ad, vodafone.min_hane, vodafone.sadece_rakam, vodafone.aktif), ("GSM", 10, True, True))
        hgs = Kurum.objects.get(kod="100-tl-yukle-plaka")
        self.assertFalse(hgs.sorgulu)
        self.assertNotIn(hgs, Kurum.objects.bayiye_acik(None))   # fiyatı yok
        vodafone.max_hane = 12
        vodafone.save()
        call_command("fatura_kurumlari", stdout=StringIO())
        vodafone.refresh_from_db()
        self.assertEqual(vodafone.max_hane, 12)
        self.assertEqual(Kurum.objects.count(), 33)

    def test_katalog_yaz_kodsuz_kaydi_atlar(self):
        self.assertEqual(katalog_yaz([{"kurum_adi": "Kodsuz"}, "bozuk"]), (0, 0))


class MesaiTestleri(Temel):
    """Robot çalışma saatleri dışında susar; bayi saatleri görür, "bağlı değil" değil."""

    def saat(self, saat, dakika=0):
        from datetime import datetime
        from unittest.mock import patch
        from zoneinfo import ZoneInfo

        return patch(
            "django.utils.timezone.localtime",
            return_value=datetime(2026, 10, 10, saat, dakika, tzinfo=ZoneInfo("Europe/Istanbul")),
        )

    def test_nabiz_mesaiyi_kaydeder(self):
        self.client.post(
            reverse("fatura:robot-kalp"),
            data=json.dumps({"robot": "ev-laptop", "durum": "bos", "oturum": "canli", "mesai": "08:00-23:00"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.anahtar}",
        )
        self.robot.refresh_from_db()
        self.assertEqual(self.robot.mesai_metni, "08:00–23:00")
        # Bozuk değer var olanı silmez.
        nabiz(self.robot, mesai="saçma")
        self.robot.refresh_from_db()
        self.assertEqual(self.robot.mesai_metni, "08:00–23:00")

    def test_mesai_disinda_bayi_saatleri_gorur(self):
        nabiz(self.robot, mesai="08:00-23:00")
        Robot.objects.update(son_nabiz=timezone.now() - timedelta(hours=1))   # gece sustu
        with self.saat(23, 30), self.assertRaisesMessage(FaturaHatasi, "08:00–23:00 arasında"):
            sorgu_baslat(self.bayi, self.vodafone, "5332590138")
        self.client.force_login(self.bayi)
        with self.saat(6, 15):
            self.assertContains(self.client.get(reverse("fatura:kurum", args=["vodafone"])), "08:00–23:00 arasında")

    def test_mesai_icinde_robot_yoksa_genel_mesaj(self):
        nabiz(self.robot, mesai="08:00-23:00")
        Robot.objects.update(son_nabiz=timezone.now() - timedelta(hours=1))
        with self.saat(14), self.assertRaisesMessage(FaturaHatasi, "şu an yapılamıyor"):
            sorgu_baslat(self.bayi, self.vodafone, "5332590138")

    def test_gece_yarisini_asan_aralik(self):
        from datetime import time

        self.robot.mesai_baslangic, self.robot.mesai_bitis = time(22), time(6)
        self.assertTrue(self.robot.mesai_icinde(time(23)))
        self.assertTrue(self.robot.mesai_icinde(time(5, 59)))
        self.assertFalse(self.robot.mesai_icinde(time(12)))


class GrupFiyatTestleri(Temel):
    """Fatura fiyatı kontördeki gibi: grubun sayfasından, boş = o gruba satılmaz."""

    def setUp(self):
        super().setUp()
        from apps.fatura.models import GrupFiyati
        from apps.kontor.models import FiyatGrubu

        self.perakende = FiyatGrubu.objects.create(ad="Perakende", varsayilan=True)
        self.toptan = FiyatGrubu.objects.create(ad="Toptan")
        self.cuzdan.kontor_grubu = self.toptan
        self.cuzdan.save()
        GrupFiyati.objects.create(kurum=self.vodafone, grup=self.toptan, tutar=TL("2.00"))
        GrupFiyati.objects.create(kurum=self.hgs, grup=self.toptan, tutar=TL("101.00"))

    def baska_bayi(self, numara, grup=None):
        bayi = User.objects.create_user(numara, password="parola12345")
        Cuzdan.objects.create(bayi=bayi, bakiye=TL("1000.00"), kontor_grubu=grup)
        return bayi

    def test_grubundaki_fiyati_oder_musteri_fiyati_gruptan_bagimsiz(self):
        toptan = odeme_baslat(self.bayi, self.tamam_sorgu(), ["FD60950NCB9D53"])
        self.assertEqual(toptan.siparis.tutar, TL("412.00"))      # 410 + Toptan 2
        self.assertEqual(toptan.tavsiye_fiyati, TL("420.00"))     # 410 + müşteriye 10
        self.assertEqual(sabit_odeme_baslat(self.bayi, self.hgs, "34ABC123").siparis.tutar, TL("101.00"))

    def test_rakami_yazilmayan_gruba_satilmaz(self):
        # Perakende'de satır yok: kontördeki gibi o gruba satılmaz; kurumun
        # kendi rakamı (hizmet 5, HGS 102) gruplar varken hiçbir bayiye uymaz.
        # Grubu boş bayi varsayılan gruba (Perakende) düşer.
        for i, bayi in enumerate((self.baska_bayi("5320000001", self.perakende), self.baska_bayi("5320000002"))):
            with self.assertRaisesMessage(FaturaHatasi, "kapalı"):
                sorgu_baslat(bayi, self.vodafone, "5332590138")
            with self.assertRaisesMessage(FaturaHatasi, "satışta değil"):
                sabit_odeme_baslat(bayi, self.hgs, f"34ABC12{i}")
            self.client.force_login(bayi)
            ana = self.client.get(reverse("fatura:index"))
            self.assertNotContains(ana, "Vodafone")
            self.assertNotContains(ana, "100 TL Yükle Plaka")
            self.assertEqual(self.client.get(reverse("fatura:kurum", args=["vodafone"])).status_code, 404)
        # 0 yazılınca sorgulu kurum fatura tutarı aynen satılır.
        from apps.fatura.models import GrupFiyati

        GrupFiyati.objects.create(kurum=self.vodafone, grup=self.perakende, tutar=TL("0"))
        perakendeci = self.baska_bayi("5320000009", self.perakende)
        odeme = odeme_baslat(perakendeci, self.tamam_sorgu(numara="5332590199", bayi=perakendeci), ["FD60950NCB9D53"])
        self.assertEqual(odeme.siparis.tutar, TL("410.00"))

    def test_sorgu_ekrani_bayinin_grup_fiyatini_gosterir(self):
        self.client.force_login(self.bayi)
        yanit = self.client.get(self.tamam_sorgu().get_absolute_url())
        self.assertContains(yanit, 'data-bayi="412.000000"')     # Toptan: 410 + 2
        self.assertContains(yanit, 'data-musteri="420.000000"')  # müşteri: 410 + 10, gruptan bağımsız

    def test_fatura_fiyati_faturanin_kendi_grup_sayfasindan_yazilir(self):
        from apps.fatura.models import GrupFiyati

        self.client.force_login(User.objects.create_superuser("yonetici", password="x"))
        # Fatura → Fiyat Grupları: aynı gruplar, faturanın kendi listesi.
        liste = self.client.get(reverse("admin:fatura_faturafiyatgrubu_changelist"))
        self.assertContains(liste, "Perakende")
        self.assertContains(liste, "Fiyatı yazılı kurum")
        # Grubu açınca yalnızca fatura kurumları (kontör paketi yok).
        degisiklik = reverse("admin:fatura_faturafiyatgrubu_change", args=[self.perakende.pk])
        adres = reverse("admin:fatura_faturafiyatgrubu_fiyatlar", args=[self.perakende.pk])
        self.assertRedirects(self.client.get(degisiklik), adres)
        yanit = self.client.get(adres)
        self.assertContains(yanit, 'name="fatura_%d"' % self.vodafone.pk)
        self.assertContains(yanit, "Müşteri fiyatı (aynen)")      # kontörün aracı, fatura etiketiyle
        self.assertNotContains(yanit, 'name="fiyat_')               # kontör paket kutusu yok
        v, h = f"fatura_{self.vodafone.pk}", f"fatura_{self.hgs.pk}"
        self.client.post(adres, {v: "3,50", h: "99"})
        self.assertEqual(GrupFiyati.objects.get(kurum=self.vodafone, grup=self.perakende).tutar, TL("3.50"))
        self.assertEqual(GrupFiyati.objects.get(kurum=self.hgs, grup=self.perakende).tutar, TL("99.00"))
        # Boş = satırı sil (bu gruba satılmaz); formda kutusu olmayan kuruma dokunulmaz.
        self.client.post(adres, {v: ""})
        self.assertFalse(GrupFiyati.objects.filter(kurum=self.vodafone, grup=self.perakende).exists())
        self.assertTrue(GrupFiyati.objects.filter(kurum=self.hgs, grup=self.perakende).exists())
        # Sorgusuz kalemde net fiyat 0 olamaz; hiçbir şey yazılmaz, hata gösterilir.
        self.assertContains(self.client.post(adres, {h: "0", v: "1"}), "0 olamaz")
        self.assertEqual(GrupFiyati.objects.get(kurum=self.hgs, grup=self.perakende).tutar, TL("99.00"))
        self.assertFalse(GrupFiyati.objects.filter(kurum=self.vodafone, grup=self.perakende).exists())
        # Grup kontörle ortak: faturadan silinemez (kontör paket fiyatları da giderdi).
        sil = reverse("admin:fatura_faturafiyatgrubu_delete", args=[self.perakende.pk])
        self.assertEqual(self.client.get(sil).status_code, 403)

    def test_kontor_grup_sayfasinda_fatura_yok(self):
        """"Fatura'ya bastım kontör fiyatları geliyor": iki sayfa ayrı, düzen aynı."""
        from apps.fatura.models import GrupFiyati

        self.client.force_login(User.objects.create_superuser("yonetici", password="x"))
        adres = reverse("admin:kontor_fiyatgrubu_paketler", args=[self.perakende.pk])
        self.assertNotContains(self.client.get(adres), 'name="fatura_')
        self.client.post(adres, {f"fatura_{self.vodafone.pk}": "1"})
        self.assertFalse(GrupFiyati.objects.filter(kurum=self.vodafone, grup=self.perakende).exists())

    def test_kurum_ekrani_kontor_paketi_gibi(self):
        self.client.force_login(User.objects.create_superuser("yonetici", password="x"))
        liste = self.client.get(reverse("admin:fatura_kurum_changelist"))
        self.assertContains(liste, "-tavsiye")                    # müşteriye satırdan düzenlenir
        self.assertContains(liste, "Toptan: +2.00")                # grup rakamı yalnızca okunur
        self.assertContains(liste, "satılmaz")                     # Perakende'de rakam yok
        form = self.client.get(reverse("admin:fatura_kurum_change", args=[self.vodafone.pk]))
        self.assertContains(form, 'name="tavsiye"')
        # Varsayılan grup varken kurumun kendi rakamı hiçbir bayiye uymaz: alan gizli.
        self.assertNotContains(form, 'name="hizmet_bedeli"')

    def test_yalnizca_kontor_izni_olan_fatura_fiyatini_yazamaz(self):
        from django.contrib.auth.models import Permission

        personel = User.objects.create_user("kontorcu", password="x", is_staff=True)
        personel.user_permissions.add(Permission.objects.get(codename="change_fiyatgrubu"))
        self.client.force_login(personel)
        self.assertEqual(
            self.client.get(reverse("admin:kontor_fiyatgrubu_paketler", args=[self.perakende.pk])).status_code, 200
        )
        self.assertEqual(
            self.client.get(reverse("admin:fatura_faturafiyatgrubu_fiyatlar", args=[self.perakende.pk])).status_code,
            403,
        )

    def test_yalnizca_fatura_izni_grubu_degistiremez_fiyat_yazar(self):
        """Fatura izni fatura rakamını yazar; ortak grubun ayarı (varsayılan) kontörü de etkiler."""
        from django.contrib.auth.models import Permission

        from apps.fatura.models import GrupFiyati

        personel = User.objects.create_user("faturaci", password="x", is_staff=True)
        personel.user_permissions.add(
            Permission.objects.get(codename="change_faturafiyatgrubu"),
            Permission.objects.get(codename="view_faturafiyatgrubu"),
            Permission.objects.get(codename="add_faturafiyatgrubu"),
        )
        self.client.force_login(personel)
        adres = reverse("admin:fatura_faturafiyatgrubu_fiyatlar", args=[self.perakende.pk])
        yanit = self.client.get(adres)
        self.assertNotContains(yanit, 'name="_grup"')                 # grup formu yok
        self.assertContains(yanit, 'name="fatura_%d"' % self.vodafone.pk)
        self.client.post(adres, {f"fatura_{self.vodafone.pk}": "2"})
        self.assertEqual(GrupFiyati.objects.get(kurum=self.vodafone, grup=self.perakende).tutar, TL("2.00"))
        # Elle gönderilen grup ayarı reddedilir; varsayılan yerinde kalır.
        cevap = self.client.post(adres, {"_grup": "1", "ad": "Perakende", "varsayilan": ""})
        self.assertEqual(cevap.status_code, 403)
        self.perakende.refresh_from_db()
        self.assertTrue(self.perakende.varsayilan)
        # Faturadan grup eklemek de kontör izni ister.
        self.assertEqual(self.client.get(reverse("admin:fatura_faturafiyatgrubu_add")).status_code, 403)

    def test_izinsiz_personel_grup_sayfasini_acamaz(self):
        self.client.force_login(User.objects.create_user("personel", password="x", is_staff=True))
        for ad in ("kontor_fiyatgrubu_paketler", "fatura_faturafiyatgrubu_fiyatlar"):
            self.assertEqual(self.client.get(reverse(f"admin:{ad}", args=[self.perakende.pk])).status_code, 403, ad)
