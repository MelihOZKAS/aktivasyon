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

from apps.fatura.models import Kategori, Kurum, Odeme, OdemeDurumu, Robot, RobotHesabi, Sorgu, SorguDurumu
from apps.fatura.services import (
    FaturaHatasi,
    KararVerilemez,
    cevrimici_robotlar,
    hesap_sec_ve_say,
    iptal_et,
    is_ver,
    kapali_mesaji,
    katalog_yaz,
    nabiz,
    odeme_baslat,
    odendi_isaretle,
    robot_cevrimici_mi,
    sabit_odeme_baslat,
    saglayici_limiti_doldu,
    siradaki_is,
    sonuc_yaz,
    vade_durumu,
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
        # Robot artık hesaplarıyla sorgular; iş alabilmesi için en az bir hesap.
        self.hesap = RobotHesabi.objects.create(robot=self.robot, kullanici_adi="5301112233", sifre="x")
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
    def test_vade_durumu(self):
        from datetime import date
        bugun = date(2026, 10, 14)
        self.assertEqual(vade_durumu("13.10.2026", bugun), "gecikmis")
        self.assertEqual(vade_durumu("14.10.2026", bugun), "bugun")
        self.assertEqual(vade_durumu("14/10/2026 00:00", bugun), "bugun")
        self.assertEqual(vade_durumu("2026-10-15", bugun), "")
        self.assertEqual(vade_durumu("15.10.2026", bugun), "")
        self.assertEqual(vade_durumu("", bugun), "")
        self.assertEqual(vade_durumu("belirsiz", bugun), "")

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


    def test_paket_isi_yalnizca_paket_yapan_robota_once_gelen_once(self):
        from apps.kontor.models import RobotSorgusu, RobotSorgusuDurumu

        paket_isi = RobotSorgusu.objects.create(numara="5050488485", operator="avea")
        # Eski sürüm robot (isler yok) paket işi almaz, paket için hazır sayılmaz.
        self.assertEqual(self.iste("is").json(), {"var": False})
        self.robot.refresh_from_db()
        self.assertFalse(self.robot.paket_sorgusu)

        adres = reverse("fatura:robot-is") + "?isler=fatura,paket"
        baslik = {"HTTP_AUTHORIZATION": f"Bearer {self.anahtar}"}
        sorgu = sorgu_baslat(self.bayi, self.vodafone, "5332590138")
        Sorgu.objects.filter(pk=sorgu.pk).update(olusturma_tarihi=timezone.now() - timedelta(seconds=5))
        # Fatura sorgusu önce açıldı: önce o.
        self.assertEqual(self.client.get(adres, **baslik).json()["tur"], "fatura")
        cevap = self.client.get(adres, **baslik).json()
        self.assertEqual(cevap, {
            "var": True, "tur": "paket",
            "hesap": {"id": self.hesap.pk, "kullanici_adi": "5301112233"},
            "talep": {"talep_id": paket_isi.pk, "numara": "5050488485", "operator": "avea"},
        })
        self.robot.refresh_from_db()
        self.assertTrue(self.robot.paket_sorgusu)

        veri = {"operator": "Avea", "paketler": [{"kod": "1744.00", "ad": "60 GB", "fiyat": "1549.00"}]}
        self.iste("sonuc", {"tur": "paket", "talep_id": paket_isi.pk, "veri": veri})
        paket_isi.refresh_from_db()
        self.assertEqual(paket_isi.durum, RobotSorgusuDurumu.TAMAM)
        self.assertEqual(paket_isi.paketler[0]["kod"], "1744")
        # Türsüz sonuç (eski robot) fatura kuyruğuna yazılır, paket işine dokunmaz.
        self.iste("sonuc", {"talep_id": sorgu.pk, "veri": ROBOT_VERISI})
        sorgu.refresh_from_db()
        self.assertEqual(sorgu.durum, SorguDurumu.TAMAM)


class OdemeTestleri(Temel):
    def test_tutar_sorgunun_kaydindan_hizmet_bedeli_eklenir(self):
        sorgu = self.tamam_sorgu()
        odeme = odeme_baslat(self.bayi, sorgu, ["FD60950NCB9D53"])
        # Taban faturanın bedeli (390), sağlayıcının işlem bedelli toplamı (410) değil:
        # 390 + 5 hizmet = 395; müşteriye 390 + 10 = 400 (gruptan bağımsız).
        self.assertEqual(odeme.siparis.tutar, TL("395.00"))
        self.assertEqual((odeme.saglayici_tutari, odeme.hizmet_bedeli, odeme.tavsiye_fiyati), (TL("390.00"), TL("5.00"), TL("400.00")))
        self.assertEqual(self.bakiye(), TL("605.00"))
        self.assertEqual(odeme.durum, OdemeDurumu.BEKLIYOR)
        self.assertEqual(odeme.faturalar[0]["odeme_token"], "tok1")

    def test_saglayicinin_islem_bedeli_tabana_girmez(self):
        """Canlıdaki örnek: fatura 487, sağlayıcının işlem bedeli 20 (toplam 507), grup +7,50, müşteriye +20."""
        from apps.fatura.services import fatura_tutari

        self.vodafone.hizmet_bedeli, self.vodafone.tavsiye = TL("7.50"), TL("20.00")
        self.vodafone.save()
        veri = {"faturalar": [{"fatura_no": "FD61051O8DFDFE", "son_odeme_tarihi": "20.10.2026",
                               "fatura_bedeli_tl": 487.0, "g_hizmet_bedeli": 0.0, "islem_bedeli": 20.0,
                               "toplam_tutar": 507.0}]}
        sorgu = Sorgu.objects.create(bayi=self.bayi, kurum=self.vodafone, numara="5327114056",
                                     durum=SorguDurumu.SORGULANIYOR)
        sonuc_yaz(self.robot, sorgu.pk, veri=veri)
        sorgu.refresh_from_db()
        self.client.force_login(self.bayi)
        yanit = self.client.get(sorgu.get_absolute_url())
        self.assertContains(yanit, 'data-bayi="494.500000"')
        self.assertContains(yanit, 'data-musteri="507.000000"')
        odeme = odeme_baslat(self.bayi, sorgu, ["FD61051O8DFDFE"])
        self.assertEqual((odeme.siparis.tutar, odeme.saglayici_tutari, odeme.hizmet_bedeli), (TL("494.50"), TL("487.00"), TL("7.50")))
        self.assertEqual(odeme.tavsiye_fiyati, TL("507.00"))
        # Bedel okunamamış eski kayıtta toplam kullanılır.
        self.assertEqual(fatura_tutari({"fatura_bedeli": "", "toplam_tutar": "410.00"}), TL("410.00"))

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
        self.assertEqual(self.bakiye(), TL("605.00"))

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
        self.assertEqual(self.bakiye(), TL("420.00"))   # 1000 - (390 + 5) - (180 + 5)
        odendi_isaretle(a, not_="Dekont 123")
        a.refresh_from_db()
        self.assertEqual((a.durum, a.siparis.durum), (OdemeDurumu.ODENDI, SiparisDurumu.TESLIM))
        iptal_et(b, sebep="Fatura kurumda kapanmış")
        b.refresh_from_db()
        self.assertEqual((b.durum, b.siparis.durum), (OdemeDurumu.IPTAL, SiparisDurumu.IPTAL))
        self.assertEqual(self.bakiye(), TL("605.00"))   # yalnızca iptal edilen döndü
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
        self.assertEqual(odeme.siparis.tutar, TL("395.00"))
        self.assertContains(self.client.get(odeme.get_absolute_url()), "Ödeniyor")
        # Ödenen fatura yeniden seçilemez.
        self.assertContains(self.client.get(sorgu.get_absolute_url()), "ödendi / ödeniyor")

    def test_fatura_kendiliginden_secilmez_vadesi_renklenir(self):
        bugun = timezone.localdate()
        faturalar = []
        for no, gun in (("GECMIS1", -3), ("BUGUN1", 0), ("ILERI1", 5)):
            faturalar.append({**ROBOT_VERISI["faturalar"][0], "fatura_no": no,
                              "son_odeme_tarihi": (bugun + timedelta(days=gun)).strftime("%d.%m.%Y")})
        sorgu = Sorgu.objects.create(bayi=self.bayi, kurum=self.vodafone, numara="5332590138",
                                     durum=SorguDurumu.SORGULANIYOR)
        sonuc_yaz(self.robot, sorgu.pk, veri={**ROBOT_VERISI, "faturalar": faturalar})
        yanit = self.client.get(sorgu.get_absolute_url())
        html = yanit.content.decode()
        self.assertNotRegex(html, r"<input[^>]*\bchecked\b")
        self.assertContains(yanit, "fatura-gecikmis", count=1)
        self.assertContains(yanit, "günü geçti", count=1)
        self.assertContains(yanit, "fatura-son-gun", count=1)
        self.assertContains(yanit, "Bugün son gün", count=1)
        # Sıra korunur: geçmiş, bugün, ileri — renk doğru kartta.
        self.assertLess(html.index("fatura-gecikmis"), html.index("GECMIS1"))
        self.assertLess(html.index("GECMIS1"), html.index("fatura-son-gun"))
        self.assertLess(html.index("fatura-son-gun"), html.index("BUGUN1"))

    def test_tek_fatura_da_secilmez(self):
        tek = {**ROBOT_VERISI, "faturalar": ROBOT_VERISI["faturalar"][:1]}
        sorgu = Sorgu.objects.create(bayi=self.bayi, kurum=self.vodafone, numara="5332590138",
                                     durum=SorguDurumu.SORGULANIYOR)
        sonuc_yaz(self.robot, sorgu.pk, veri=tek)
        html = self.client.get(sorgu.get_absolute_url()).content.decode()
        self.assertIn("FD60950NCB9D53", html)
        self.assertNotRegex(html, r"<input[^>]*\bchecked\b")

    def test_hatali_numara_formda_kalir(self):
        yanit = self.client.post(reverse("fatura:sorgula", args=["vodafone"]), {"numara": "12"})
        self.assertRedirects(yanit, reverse("fatura:kurum", args=["vodafone"]) + "?numara=12")
        self.assertFalse(Sorgu.objects.exists())

    def test_fatura_siparisi_magazada_gorunmez(self):
        odeme_baslat(self.bayi, self.tamam_sorgu(), ["FD60950NCB9D53"])
        self.assertNotContains(self.client.get(reverse("magaza:siparislerim")), "Fatura ·")
        self.assertContains(self.client.get(reverse("fatura:odemeler")), "5332590138")

    def test_dekont_musteri_fiyatiyla_butun_faturalar(self):
        odeme = odeme_baslat(self.bayi, self.tamam_sorgu(), ["FD60950NCB9D53", "FD00000000002"])
        adres = reverse("fatura:odeme-dekont", args=[odeme.referans_no])
        # Ödeme sürerken de verilir; durum yazar.
        self.assertContains(self.client.get(odeme.get_absolute_url()), adres)
        yanit = self.client.get(adres)
        # Müşteriye: 390 + 180 fatura, 2 × 10 hizmet bedeli = 590. Bayinin ödediği (580) girmez.
        for metin in ("FATURA ÖDEME DEKONTU", "Vodafone", "5332590138", "M***** A*****", "FD60950NCB9D53",
                      "FD00000000002", "390,00", "180,00", "Hizmet bedeli", "20,00", "590,00 ₺", "Ödeniyor"):
            self.assertContains(yanit, metin)
        self.assertNotContains(yanit, "580,00")
        self.assertNotContains(yanit, "Ara toplam")   # tek ödeme

        iptal_et(odeme, sebep="kurum kapalı")
        self.assertEqual(self.client.get(adres).status_code, 404)
        self.assertNotContains(self.client.get(odeme.get_absolute_url()), adres)

    def test_sepet_dekontu_secilen_odemeler_tek_toplamla(self):
        a = odeme_baslat(self.bayi, self.tamam_sorgu(), ["FD60950NCB9D53"])
        b = sabit_odeme_baslat(self.bayi, self.hgs, "34abc123")
        iptal = odeme_baslat(self.bayi, self.tamam_sorgu(numara="5332590100"), ["FD00000000002"])
        iptal_et(iptal, sebep="olmadı")
        baska = User.objects.create_user("5320000000", password="parola12345")
        Cuzdan.objects.create(bayi=baska, bakiye=TL("1000.00"))
        yabanci = sabit_odeme_baslat(baska, self.hgs, "34abc999")

        liste = self.client.get(reverse("fatura:odemeler"))
        self.assertContains(liste, 'form="dekont-sepeti"', count=2)   # iptal edilenin kutusu yok
        yanit = self.client.get(reverse("fatura:dekont"), {"odeme": [
            a.referans_no, b.referans_no, iptal.referans_no, yabanci.referans_no, a.referans_no,
        ]})
        # 400 (390 + 10) + HGS müşteri fiyatı 105 = 505; iptal ve başkasının ödemesi düşer.
        self.assertContains(yanit, "505,00 ₺")
        self.assertContains(yanit, "Ara toplam", count=1)
        self.assertContains(yanit, "34ABC123")
        self.assertNotContains(yanit, iptal.referans_no)
        self.assertNotContains(yanit, yabanci.referans_no)
        self.assertEqual(self.client.get(reverse("fatura:dekont"), {"odeme": [iptal.referans_no]}).status_code, 404)

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
        self.assertEqual(self.bakiye(), TL("605.00"))

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
        self.assertEqual(self.bakiye(), TL("605.00"))
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
        self.assertEqual(toptan.siparis.tutar, TL("392.00"))      # fatura 390 + Toptan 2
        self.assertEqual(toptan.tavsiye_fiyati, TL("400.00"))     # fatura 390 + müşteriye 10
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
        self.assertEqual(odeme.siparis.tutar, TL("390.00"))

    def test_sorgu_ekrani_bayinin_grup_fiyatini_gosterir(self):
        self.client.force_login(self.bayi)
        yanit = self.client.get(self.tamam_sorgu().get_absolute_url())
        self.assertContains(yanit, 'data-bayi="392.000000"')     # Toptan: fatura 390 + 2
        self.assertContains(yanit, 'data-musteri="400.000000"')  # müşteri: 390 + 10, gruptan bağımsız

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

    def test_hepsine_ayni_bedel_yalnizca_sorgulu_kurumlara(self):
        from apps.fatura.models import GrupFiyati

        turkcell = Kurum.objects.create(
            kod="turkcell", ad="Turkcell", kategori=self.gsm, sorgulu=True, min_hane=10, max_hane=10,
        )
        self.client.force_login(User.objects.create_superuser("yonetici", password="x"))
        adres = reverse("admin:fatura_faturafiyatgrubu_fiyatlar", args=[self.toptan.pk])
        self.assertContains(self.client.get(adres), "2 kuruma yaz")
        self.client.post(adres, {"_hepsine": "1", "hepsine_tutar": "7,5"})
        tutarlar = dict(GrupFiyati.objects.filter(grup=self.toptan).values_list("kurum__kod", "tutar"))
        self.assertEqual(tutarlar, {"vodafone": TL("7.50"), "turkcell": TL("7.50"), "100-tl-yukle-plaka": TL("101.00")})
        # Başka grubun rakamına dokunulmaz.
        self.assertFalse(GrupFiyati.objects.filter(grup=self.perakende).exists())
        # Anlaşılmayan rakam hiçbir şey yazmaz.
        self.client.post(adres, {"_hepsine": "1", "hepsine_tutar": "on lira"})
        self.assertEqual(GrupFiyati.objects.get(kurum=turkcell, grup=self.toptan).tutar, TL("7.50"))

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


class HesapSayaciTestleri(Temel):
    """Hesap başına günlük sorgu sayacı: gönderim anında +1, fatura/kontör ayrı, 00:00 sıfır."""

    def test_hesap_sec_ve_say_gonderim_aninda_arttirir_dengeli_dagitir(self):
        self.robot.paket_sorgusu = True
        self.robot.save()
        iki = RobotHesabi.objects.create(robot=self.robot, kullanici_adi="5302223344", sifre="x", sira=2)
        # En az kullanılmış hesap seçilir: ilk ikisi iki ayrı hesaba gider.
        h1 = hesap_sec_ve_say(self.robot, "fatura")
        h2 = hesap_sec_ve_say(self.robot, "fatura")
        self.assertEqual({h1.pk, h2.pk}, {self.hesap.pk, iki.pk})
        for h in (self.hesap, iki):
            h.refresh_from_db()
            self.assertEqual((h.bugunku_fatura, h.bugunku_kontor), (1, 0))
        # Kontör ayrı sayılır.
        hesap_sec_ve_say(self.robot, "paket")
        self.assertEqual(sum(h.bugunku_kontor for h in RobotHesabi.objects.filter(robot=self.robot)), 1)

    def test_gun_degisince_sifir(self):
        hesap_sec_ve_say(self.robot, "fatura")
        self.hesap.refresh_from_db()
        self.assertEqual(self.hesap.bugunku_fatura, 1)
        RobotHesabi.objects.filter(pk=self.hesap.pk).update(sayac_gunu=timezone.localdate() - timedelta(days=1))
        self.hesap.refresh_from_db()
        self.assertEqual(self.hesap.bugunku_fatura, 0)   # dünün sayısı bugüne yazılmaz

    def test_limit_dolan_hesap_atlanir_hepsi_dolunca_is_yok(self):
        RobotHesabi.objects.filter(pk=self.hesap.pk).update(fatura_limiti=1)
        iki = RobotHesabi.objects.create(robot=self.robot, kullanici_adi="5302223344", sifre="x", sira=2, fatura_limiti=1)
        a = hesap_sec_ve_say(self.robot, "fatura")   # biri dolar
        b = hesap_sec_ve_say(self.robot, "fatura")   # öbürü dolar
        self.assertEqual({a.pk, b.pk}, {self.hesap.pk, iki.pk})
        self.robot.refresh_from_db()
        self.assertFalse(self.robot.hak_kalan_mi("fatura"))   # ikisi de dolu
        self.assertIsNone(hesap_sec_ve_say(self.robot, "fatura"))
        self.assertFalse(robot_cevrimici_mi())

    def test_sorgu_gonderiminde_sayilir_hesaba_atanir(self):
        sorgu = sorgu_baslat(self.bayi, self.vodafone, "5332590138")
        verilen = is_ver(self.robot)
        self.assertEqual(verilen.hesap, self.hesap)
        self.hesap.refresh_from_db()
        self.assertEqual(self.hesap.bugunku_fatura, 1)   # sonucu beklemeden sayıldı
        # is_ cevabı hesabı taşır.
        sorgu2 = sorgu_baslat(self.bayi, self.vodafone, "5339990000")
        cevap = self.client.get(
            reverse("fatura:robot-is"), HTTP_AUTHORIZATION=f"Bearer {self.anahtar}"
        ).json()
        self.assertEqual(cevap["hesap"], {"id": self.hesap.pk, "kullanici_adi": "5301112233"})

    def test_hesapsiz_robot_is_alamaz_ve_cevrimdisi_sayilir(self):
        self.hesap.delete()
        self.assertFalse(robot_cevrimici_mi())
        with self.assertRaisesMessage(FaturaHatasi, "yapılamıyor"):
            sorgu_baslat(self.bayi, self.vodafone, "5332590138")

    def test_hesaplar_nabiz_cevabinda_doner(self):
        self.hesap.guvenlik_resmi = "kivi"
        self.hesap.save()
        RobotHesabi.objects.create(robot=self.robot, kullanici_adi="5302223344", sifre="gizli", sira=2, aktif=False)
        cevap = self.client.post(
            reverse("fatura:robot-kalp"),
            data=json.dumps({"robot": "ev-laptop", "durum": "bos", "oturum": "canli"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.anahtar}",
        ).json()
        # Yalnızca aktif hesap; şifre ve güvenlik resmi robota gider.
        self.assertEqual(len(cevap["hesaplar"]), 1)
        self.assertEqual(cevap["hesaplar"][0], {"id": self.hesap.pk, "kullanici_adi": "5301112233", "sifre": "x", "guvenlik_resmi": "kivi"})


class SaglayiciLimitiTestleri(Temel):
    """Sağlayıcı 'Sorgu limitinizi doldurdunuz' deyince O HESAP bugünlük kapanır."""

    def test_fatura_limiti_hesabi_kapatir_sorgu_yeniden_denenebilir(self):
        sorgu = sorgu_baslat(self.bayi, self.vodafone, "5332590138")
        is_ver(self.robot)   # hesaba atandı, +1
        veri = {"durum": "limit", "mesaj": "Sorgu limiti doldu.", "faturalar": []}
        sonuc_yaz(self.robot, sorgu.pk, veri=veri)
        sorgu.refresh_from_db()
        self.hesap.refresh_from_db()
        self.assertEqual(sorgu.durum, SorguDurumu.HATA)   # yeniden denenebilir
        self.assertTrue(self.hesap.saglayici_doldu_mu("fatura"))
        self.assertTrue(self.hesap.limit_doldu("fatura"))
        self.assertFalse(self.hesap.limit_doldu("paket"))
        self.assertFalse(robot_cevrimici_mi())   # tek hesap, o da dolu
        # Gün değişince kendiliğinden açılır.
        yarin = timezone.localdate() + timedelta(days=1)
        self.assertFalse(self.hesap.saglayici_doldu_mu("fatura", bugun=yarin))

    def test_kontor_limiti_hesabi_kapatir(self):
        from apps.kontor.models import RobotSorgusu, RobotSorgusuDurumu
        from apps.kontor.sorgu import kontorbizde

        self.robot.paket_sorgusu = True
        self.robot.save()
        RobotSorgusu.objects.create(numara="5050488485", operator="avea")
        is_ = kontorbizde.is_ver(self.robot)
        self.assertEqual(is_.hesap, self.hesap)
        kontorbizde.sonuc_yaz(self.robot, is_.pk, veri={"operator": "avea", "paketler": [], "durum": "limit"})
        is_.refresh_from_db()
        self.hesap.refresh_from_db()
        self.assertEqual(is_.durum, RobotSorgusuDurumu.HATA)
        self.assertTrue(self.hesap.saglayici_doldu_mu("paket"))
        self.assertFalse(self.hesap.saglayici_doldu_mu("fatura"))

    def test_sinirsiz_hesapta_da_saglayici_limiti_kapatir(self):
        # Hesabın limiti 0 (sınırsız) olsa da sağlayıcı dolu derse durur.
        self.assertIsNone(self.hesap.kalan_hak("fatura"))
        saglayici_limiti_doldu(self.hesap.pk, "fatura")
        self.hesap.refresh_from_db()
        self.assertTrue(self.hesap.limit_doldu("fatura"))

    def test_bir_hesap_dolunca_digeri_devam_eder(self):
        iki = RobotHesabi.objects.create(robot=self.robot, kullanici_adi="5302223344", sifre="x", sira=2)
        saglayici_limiti_doldu(self.hesap.pk, "fatura")
        # Biri dolu ama öbürü açık: robot hâlâ fatura yapabilir, iş açık hesaba gider.
        self.assertTrue(robot_cevrimici_mi())
        sorgu = sorgu_baslat(self.bayi, self.vodafone, "5332590138")
        verilen = is_ver(self.robot)
        self.assertEqual(verilen.hesap, iki)


class RobotYetkiTestleri(Temel):
    """İş yalnızca atandığı robottan sonuç kabul eder (anahtar sızsa bile)."""

    def test_baska_robot_sonuc_yazamaz_hesabi_kapatamaz(self):
        yabanci = Robot.objects.create(ad="server-9")
        RobotHesabi.objects.create(robot=yabanci, kullanici_adi="5309998877", sifre="x")
        sorgu = sorgu_baslat(self.bayi, self.vodafone, "5332590138")
        is_ver(self.robot)   # kendi hesabıma atandı
        # Yabancı robot aynı talep_id'ye "limit" yazmaya çalışır.
        sonuc_yaz(yabanci, sorgu.pk, veri={"durum": "limit", "faturalar": []})
        sorgu.refresh_from_db()
        self.hesap.refresh_from_db()
        self.assertEqual(sorgu.durum, SorguDurumu.SORGULANIYOR)   # dokunulmadı
        self.assertFalse(self.hesap.saglayici_doldu_mu("fatura"))  # hesabım kapanmadı
        # Doğru robot yazınca işler.
        sonuc_yaz(self.robot, sorgu.pk, veri=ROBOT_VERISI)
        sorgu.refresh_from_db()
        self.assertEqual(sorgu.durum, SorguDurumu.TAMAM)

    def test_baska_robot_paket_sonucu_yazamaz(self):
        from apps.kontor.models import RobotSorgusu, RobotSorgusuDurumu
        from apps.kontor.sorgu import kontorbizde

        self.robot.paket_sorgusu = True
        self.robot.save()
        yabanci = Robot.objects.create(ad="server-9", paket_sorgusu=True)
        RobotHesabi.objects.create(robot=yabanci, kullanici_adi="5309998877", sifre="x")
        RobotSorgusu.objects.create(numara="5050488485", operator="avea")
        is_ = kontorbizde.is_ver(self.robot)
        kontorbizde.sonuc_yaz(yabanci, is_.pk, veri={"operator": "avea", "paketler": [], "durum": "limit"})
        is_.refresh_from_db()
        self.hesap.refresh_from_db()
        self.assertEqual(is_.durum, RobotSorgusuDurumu.SORGULANIYOR)
        self.assertFalse(self.hesap.saglayici_doldu_mu("paket"))


# -- Sağlayıcıya gönderim ---------------------------------------------------


class _Yanit:
    def __init__(self, govde):
        self.govde = govde.encode()
        from unittest import mock

        self.headers = mock.Mock(get_content_charset=lambda: "utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.govde


class SahteSite:
    """`urlopen` yerine: servisin adına (`fatura_ekle`, `fatura_top_kontrol`…) göre cevap.

    Listede birden çok cevap varsa sırayla verilir, sonuncusu tekrarlanır.
    """

    def __init__(self, **cevaplar):
        self.cevaplar = {ad: list(c) if isinstance(c, list) else [c] for ad, c in cevaplar.items()}
        self.istekler = []

    def __call__(self, istek, timeout=None):
        adres = istek.full_url
        self.istekler.append(adres)
        servis = adres.split("/servis/")[1].split(".php")[0]
        liste = self.cevaplar[servis]
        return _Yanit(liste.pop(0) if len(liste) > 1 else liste[0])

    def servis(self, ad):
        return [a for a in self.istekler if f"/servis/{ad}.php" in a]


@__import__("django.test").test.override_settings(FATURA_ARKA_PLAN=False, FATURA_ATOMIK_DENETIMI=False)
class SaglayiciGonderimTestleri(Temel):
    """Ödeme açılınca faturalar sağlayıcının fatura API'sine gider, sonucu sorulur."""

    def setUp(self):
        super().setUp()
        from apps.kontor.models import Saglayici

        self.saglayici = Saglayici.objects.create(
            ad="Kontorbizde", tur="znet", adres="https://bayi.kb.test", kullanici_adi="5458301536",
            sifre="gizli-sifre", fatura_odemesi=True, ref_sayaci=5000,
        )
        self.vodafone.uzak_id = "9"
        self.vodafone.save()

    def ode(self, site, faturalar=("FD60950NCB9D53",)):
        from unittest import mock

        with mock.patch("urllib.request.urlopen", side_effect=site), self.captureOnCommitCallbacks(execute=True):
            odeme = odeme_baslat(self.bayi, self.tamam_sorgu(), list(faturalar))
        odeme.refresh_from_db()
        return odeme

    def isle(self, site):
        from unittest import mock

        from apps.fatura.services import bekleyenleri_isle

        with mock.patch("urllib.request.urlopen", side_effect=site):
            bekleyenleri_isle()

    def sorulabilir_yap(self):
        from apps.fatura.models import Gonderim

        Gonderim.objects.update(son_sorgu=timezone.now() - timedelta(minutes=1))

    def test_fatura_kurum_numarasiyla_gider_odenince_kapanir(self):
        site = SahteSite(fatura_ekle=["OK|0.30|2644.78|390.30", "OK|0.30|2464.48|180.30"])
        odeme = self.ode(site, faturalar=["FD60950NCB9D53", "FD00000000002"])
        self.assertTrue(odeme.otomatik)
        self.assertEqual(odeme.durum, OdemeDurumu.BEKLIYOR)
        birinci, ikinci = odeme.gonderimler.order_by("pk")
        self.assertEqual((birinci.durum, birinci.dusen, birinci.maliyet), ("islemde", TL("390.30"), TL("0.30")))
        self.assertEqual(ikinci.fatura_no, "FD00000000002")
        istek = site.servis("fatura_ekle")[0]
        for parca in ("kod=5458301536", "kurum_id=9", f"tahsilat_api_islem_id={birinci.ref}",
                      "fatura_no=FD60950NCB9D53", "fatura_tutari=390.00", "son_odeme_tarihi=2026-10-14",
                      "tesisat_no=5332590138"):
            self.assertIn(parca, istek)
        # Şifre kayıtta gizli, istekte var.
        self.assertIn("sifre=***", birinci.gonderim_istegi)
        self.assertNotIn("gizli-sifre", birinci.gonderim_istegi)
        # Sağlayıcıda süren ödeme yönetimin elinde değil: rozet saymaz.
        from apps.fatura.services import yonetim_bekleyenler

        self.assertFalse(yonetim_bekleyenler().exists())

        # Toplu sorgu: biri ödendi, öbürü bekliyor (bekleyen yazılmaz) → ödeme sürer.
        self.sorulabilir_yap()
        self.isle(SahteSite(fatura_top_kontrol=f"{birinci.ref}|2||##"))
        odeme.refresh_from_db()
        self.assertEqual(odeme.durum, OdemeDurumu.BEKLIYOR)
        self.sorulabilir_yap()
        site = SahteSite(fatura_top_kontrol=f"{ikinci.ref}|2||##", fatura_kontrol="2:ONAYLI")
        self.isle(site)
        odeme.refresh_from_db()
        self.assertEqual(odeme.durum, OdemeDurumu.ODENDI)
        self.assertEqual(odeme.siparis.durum, SiparisDurumu.TESLIM)
        self.assertEqual(self.bakiye(), TL("420.00"))  # 390 + 5 ve 180 + 5 düştü, iade yok

    def test_sonuc_25_saniyeden_sik_sorulmaz(self):
        site = SahteSite(fatura_ekle="OK|0.30|1000.00|390.30")
        self.ode(site)
        sorgu = SahteSite(fatura_kontrol="1:BEKLIYOR")
        self.isle(sorgu)
        self.isle(sorgu)
        self.assertEqual(len(sorgu.servis("fatura_kontrol")), 1)

    def test_saglayici_iptal_ederse_tutar_iade_edilir_sebep_bayiye(self):
        odeme = self.ode(SahteSite(fatura_ekle="OK|0.30|1000.00|390.30"))
        self.assertEqual(self.bakiye(), TL("605.00"))
        self.isle(SahteSite(fatura_kontrol="3:Fatura kurumda ödenmiş görünüyor"))
        odeme.refresh_from_db()
        self.assertEqual(odeme.durum, OdemeDurumu.IPTAL)
        self.assertEqual(odeme.sonuc_notu, "Fatura kurumda ödenmiş görünüyor")
        self.assertEqual(self.bakiye(), TL("1000.00"))

    def test_gonderilemeyen_iade_edilmez_yonetimde_kalir_elle_gonderilir(self):
        from apps.fatura.models import Gonderim
        from apps.fatura.services import yonetim_bekleyenler

        odeme = self.ode(SahteSite(fatura_ekle="3|Bakiyeniz yetersiz"))
        gonderim = odeme.gonderimler.get()
        self.assertEqual((gonderim.durum, gonderim.mesaj), ("reddedildi", "Bakiyeniz yetersiz"))
        odeme.refresh_from_db()
        self.assertEqual(odeme.durum, OdemeDurumu.BEKLIYOR)
        self.assertEqual(self.bakiye(), TL("605.00"))
        self.assertEqual(list(yonetim_bekleyenler()), [odeme])
        # İşçi reddedilmiş faturayı kendiliğinden yeniden göndermez.
        site = SahteSite(fatura_ekle="OK|0.30|1000.00|390.30")
        self.isle(site)
        self.assertEqual(site.servis("fatura_ekle"), [])

        # Yönetim bakiyeyi düzeltip Karar ekranından yeniden gönderir.
        from unittest import mock

        self.client.force_login(User.objects.create_superuser("yonetici", password="x"))
        adres = reverse("admin:fatura_odeme_karar", args=[odeme.pk])
        yanit = self.client.get(adres)
        self.assertContains(yanit, "3|Bakiyeniz yetersiz")
        self.assertContains(yanit, "Sağlayıcıya gönder")
        with mock.patch("urllib.request.urlopen", side_effect=site):
            self.client.post(adres, {"karar": "gonder"})
        yeni = Gonderim.objects.order_by("pk").last()
        self.assertEqual((yeni.elle, yeni.durum), (True, "islemde"))
        self.assertNotEqual(yeni.ref, gonderim.ref)
        self.assertFalse(yonetim_bekleyenler().exists())
        # Sağlayıcıda sürerken ikinci kez gönderilmez.
        with mock.patch("urllib.request.urlopen", side_effect=site):
            self.client.post(adres, {"karar": "gonder"})
        self.assertEqual(Gonderim.objects.count(), 2)

    def test_belirsiz_cevap_yeniden_gonderilmez_sorgulaninca_surer(self):
        from unittest import mock

        odeme = self.ode(SahteSite(fatura_ekle="4|Daha Önce Gönderilmiş (166189)"))
        gonderim = odeme.gonderimler.get()
        self.assertEqual(gonderim.durum, "belirsiz")
        self.client.force_login(User.objects.create_superuser("yonetici", password="x"))
        adres = reverse("admin:fatura_odeme_karar", args=[odeme.pk])
        self.assertContains(self.client.get(adres), "ödenmiş de olabilir")
        with mock.patch("urllib.request.urlopen", side_effect=SahteSite(fatura_kontrol="1:BEKLIYOR")):
            self.client.post(adres, {"karar": "sorgula"})
        gonderim.refresh_from_db()
        self.assertEqual((gonderim.durum, gonderim.sonuc_cevabi), ("islemde", "1:BEKLIYOR"))

    def test_zaman_asiminda_belirsiz_baglanti_kurulamazsa_gonderilemedi(self):
        import socket
        import urllib.error
        from unittest import mock

        with mock.patch("urllib.request.urlopen", side_effect=socket.timeout()), \
                self.captureOnCommitCallbacks(execute=True):
            odeme = odeme_baslat(self.bayi, self.tamam_sorgu(), ["FD60950NCB9D53"])
        self.assertEqual(odeme.gonderimler.get().durum, "belirsiz")
        hata = urllib.error.URLError(ConnectionRefusedError())
        with mock.patch("urllib.request.urlopen", side_effect=hata), self.captureOnCommitCallbacks(execute=True):
            odeme = odeme_baslat(self.bayi, self.tamam_sorgu(), ["FD00000000002"])
        self.assertEqual(odeme.gonderimler.get().durum, "reddedildi")

    def test_kurum_numarasi_ya_da_saglayici_yoksa_yonetim_elle_oder(self):
        from apps.fatura.services import yonetim_bekleyenler

        self.vodafone.uzak_id = ""
        self.vodafone.save()
        site = SahteSite(fatura_ekle="OK|0.30|1000.00|390.30")
        odeme = self.ode(site)
        self.assertFalse(odeme.otomatik)
        self.assertEqual(site.istekler, [])
        self.assertEqual(list(yonetim_bekleyenler()), [odeme])
        self.client.force_login(User.objects.create_superuser("yonetici", password="x"))
        yanit = self.client.get(reverse("admin:fatura_odeme_karar", args=[odeme.pk]))
        self.assertContains(yanit, "sağlayıcıdaki numarası boş")

        self.vodafone.uzak_id = "9"
        self.vodafone.save()
        self.saglayici.fatura_odemesi = False
        self.saglayici.save()
        self.assertFalse(self.ode(site, faturalar=["FD00000000002"]).otomatik)
        self.assertEqual(site.istekler, [])

    def test_iscinin_devraldigi_ve_eskiyen_odeme(self):
        from unittest import mock

        from apps.fatura.services import OTOMATIK_GONDERIM_SURESI

        # Açılıştaki iş parçacığı ölmüş: gönderim yok. İşçi 10 sn sonra devralır.
        with mock.patch("apps.fatura.services.arka_planda_gonder"), self.captureOnCommitCallbacks(execute=True):
            odeme = odeme_baslat(self.bayi, self.tamam_sorgu(), ["FD60950NCB9D53"])
        site = SahteSite(fatura_ekle="OK|0.30|1000.00|390.30", fatura_kontrol="1:BEKLIYOR")
        self.isle(site)
        self.assertEqual(site.servis("fatura_ekle"), [])  # henüz iş parçacığının süresi
        Odeme.objects.filter(pk=odeme.pk).update(olusturma_tarihi=timezone.now() - timedelta(seconds=20))
        self.isle(site)
        self.assertEqual(len(site.servis("fatura_ekle")), 1)
        self.isle(site)
        self.assertEqual(len(site.servis("fatura_ekle")), 1)  # bir kez

        # Beş dakikadan eskisi yönetimindir: elle ödüyor olabilir.
        with mock.patch("apps.fatura.services.arka_planda_gonder"), self.captureOnCommitCallbacks(execute=True):
            eski = odeme_baslat(self.bayi, self.tamam_sorgu(), ["FD00000000002"])
        Odeme.objects.filter(pk=eski.pk).update(
            olusturma_tarihi=timezone.now() - OTOMATIK_GONDERIM_SURESI - timedelta(seconds=1)
        )
        self.isle(site)
        self.assertEqual(len(site.servis("fatura_ekle")), 1)

    def test_yarida_kalan_gonderim_belirsize_duser(self):
        from apps.fatura.models import Gonderim

        odeme = self.ode(SahteSite(fatura_ekle="OK|0.30|1000.00|390.30"))
        Gonderim.objects.update(durum="gonderiliyor", olusturma_tarihi=timezone.now() - timedelta(minutes=3))
        self.isle(SahteSite(fatura_kontrol="1:BEKLIYOR"))
        self.assertEqual(odeme.gonderimler.get().durum, "belirsiz")

    def test_yonetim_listesi_ve_rozet(self):
        from apps.rozetler import bekleyen_fatura_odemeleri

        self.ode(SahteSite(fatura_ekle="3|Kurum kapalı"))
        self.ode(SahteSite(fatura_ekle="OK|0.30|1000.00|180.30"), faturalar=["FD00000000002"])
        self.assertEqual(str(bekleyen_fatura_odemeleri(None)), "1")
        self.client.force_login(User.objects.create_superuser("yonetici", password="x"))
        yanit = self.client.get(reverse("admin:fatura_odeme_changelist"))
        self.assertContains(yanit, "Gönderilemedi")
        self.assertContains(yanit, "Sağlayıcıda")
        yanit = self.client.get(reverse("admin:fatura_odeme_changelist") + "?karar=bekliyor")
        self.assertContains(yanit, "Gönderilemedi")
        self.assertNotContains(yanit, "Sağlayıcıda</span>")


class KurumNumarasiTestleri(Temel):
    """Kurumun sağlayıcıdaki numarası: robotun token'ından ve sağlayıcının listesinden."""

    def test_robot_katalogu_token_icindeki_numarayi_yazar(self):
        import base64

        token = base64.b64encode("&id=120&kurum_adi=TTNET Mobil&api_durum=a&api_adi=92".encode()).decode()
        katalog_yaz([{"id": "ttnet-mobil", "kurum_adi": "TTNET Mobil", "token": token}])
        self.assertEqual(Kurum.objects.get(kod="ttnet-mobil").uzak_id, "120")
        # Kurulumun tohumu var olana dokunmaz ama boş numarayı doldurur.
        self.assertEqual(self.vodafone.uzak_id, "")
        katalog_yaz([{"id": "vodafone", "kurum_adi": "Vodafone", "uzak_id": "9", "min_hane": 7}],
                    var_olani_guncelle=False)
        self.vodafone.refresh_from_db()
        self.assertEqual((self.vodafone.uzak_id, self.vodafone.min_hane), ("9", 10))

    def test_kurulum_tohumunda_numaralar_var(self):
        call_command("fatura_kurumlari", stdout=StringIO())
        self.assertEqual(Kurum.objects.get(kod="turkcell").uzak_id, "8")
        self.assertFalse(Kurum.objects.filter(uzak_id="").exclude(kod__in=["vodafone", "100-tl-yukle-plaka"]).exists())

    def test_saglayicidan_eslestir(self):
        from unittest import mock

        from apps.fatura.services import kurumlari_eslestir
        from apps.kontor.models import Saglayici

        with self.assertRaisesMessage(FaturaHatasi, "Fatura sağlayıcısı seçili değil"):
            kurumlari_eslestir()
        Saglayici.objects.create(ad="KB", tur="znet", adres="kb.test", kullanici_adi="u", sifre="s", fatura_odemesi=True)
        Kurum.objects.create(kod="bag-kur", ad="Bağ-kur")
        liste = "8,2,Turkcell,0.30,#9,3,Vodafone,0.30,#103,90,Bağ-kur,3.00,#200,90,Bağ-kur,3.00,#"
        with mock.patch("urllib.request.urlopen", side_effect=SahteSite(kurum_listesi=liste)):
            adet, guncellenen, eslesmeyen = kurumlari_eslestir()
        self.assertEqual((adet, guncellenen), (4, 1))
        self.vodafone.refresh_from_db()
        self.assertEqual(self.vodafone.uzak_id, "9")
        # Aynı adda iki kayıt: hangisi olduğu bilinmez, eşleştirilmez.
        self.assertIn("Bağ-kur", eslesmeyen)

        self.client.force_login(User.objects.create_superuser("yonetici", password="x"))
        self.assertContains(self.client.get(reverse("admin:fatura_kurum_changelist")), "Sağlayıcıdan eşleştir")

    def test_fatura_saglayicisi_tektir_ve_fatura_alan_yazilim_olmali(self):
        from apps.kontor.models import Saglayici

        bir = Saglayici.objects.create(ad="KB", tur="znet", adres="kb.test", kullanici_adi="u", sifre="s", fatura_odemesi=True)
        iki = Saglayici(ad="KB2", tur="znet", adres="kb2.test", kullanici_adi="u", sifre="s", fatura_odemesi=True)
        with self.assertRaisesMessage(ValidationError, "“KB” sağlayıcısına gidiyor"):
            iki.full_clean()
        bir.fatura_odemesi = False
        bir.save()
        iki.full_clean()
        iki.tur = "grafi"
        with self.assertRaisesMessage(ValidationError, "fatura ödemesi almıyor"):
            iki.full_clean()
