"""eSIM: eşitleme, fiyat, en ucuz sağlayıcı, sipariş ve iade.

Sağlayıcı ağa çıkmaz: `SahteAdaptor` kayıt defterine eklenir ve testler
onun davranışını `DURUM` sözlüğünden ayarlar.
"""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.bayi.models import GenelAyarlar
from apps.esim import saglayicilar
from apps.esim.models import Paket, Saglayici, Teslimat, TeslimatDurumu, Ulke, satis_fiyati_hesapla
from apps.esim.saglayicilar import Adaptor, PaketVerisi, ProfilVerisi, SaglayiciHatasi, YuklemeVerisi
from apps.esim.services import (
    KurTanimsiz,
    en_ucuzlar,
    esim_siparisi_ver,
    esim_yukle,
    kar_orani_uygula,
    musteri_etiketle,
    fiyatlari_guncelle,
    paketleri_esitle,
    profili_getir,
    teslimati_iptal_et,
    ulke_listesi,
    ulke_paketleri,
)
from apps.finans.models import Cuzdan, CuzdanHareketi, HareketTipi
from apps.finans.services import SiparisVerilemez
from apps.magaza.models import Siparis, SiparisDurumu

TL = Decimal

# Sahte sağlayıcının davranışı; her test setUp'ta sıfırlar.
DURUM = {}


def _sifirla():
    DURUM.clear()
    DURUM.update(
        paketler=[],
        siparisler=[],
        iptaller=[],
        reddet="",
        profil_hazir=True,
        iptal_reddet="",
        yukleme_yok=False,
        yukleme_reddet="",
        yuklemeler=[],
    )


class SahteAdaptor(Adaptor):
    kod = "sahte"
    ad = "Sahte Sağlayıcı"

    def paketleri_getir(self):
        return list(DURUM["paketler"])

    def bakiye(self):
        return Decimal("12.50")

    def siparis_ver(self, paket_kodu, islem_no, alis_usd):
        if DURUM["reddet"]:
            raise SaglayiciHatasi(DURUM["reddet"], "200007")
        DURUM["siparisler"].append((paket_kodu, islem_no, alis_usd))
        return f"B{len(DURUM['siparisler'])}", None

    def profil_getir(self, saglayici_siparis_no):
        if not DURUM["profil_hazir"]:
            return None
        return ProfilVerisi(
            esim_no="E123",
            iccid="8990000000000000001",
            ac="LPA:1$rsp.example.com$KOD-ABC",
            qr_url="https://ornek/qr.png",
            kisa_url="https://ornek/k",
            apn="internet",
        )

    def iptal_et(self, esim_no, *, iccid="", paket_kodu=""):
        if DURUM["iptal_reddet"]:
            raise SaglayiciHatasi(DURUM["iptal_reddet"], "200002")
        DURUM["iptaller"].append(esim_no)

    def yukleme_paketleri(self, esim_no, *, iccid="", paket_kodu=""):
        if DURUM["yukleme_yok"]:
            raise SaglayiciHatasi("Sahte yükleme desteklemiyor.")
        return [paket_verisi("TOPUP_1", ["TR"], 3, 30, "1.42"), paket_verisi("TOPUP_2", ["TR"], 1, 7, "0.46")]

    def yukle(self, esim_no, yukleme_kodu, islem_no, alis_usd, *, iccid=""):
        if DURUM["yukleme_reddet"]:
            raise SaglayiciHatasi(DURUM["yukleme_reddet"], "200007")
        DURUM["yuklemeler"].append((esim_no, yukleme_kodu, islem_no, alis_usd))
        return YuklemeVerisi(yukleme_no="Y1", toplam_hacim_bayt=4 * 1024**3, toplam_sure_gun=37)


saglayicilar.saglayici_secenekleri()  # kayıt defterini doldur
saglayicilar.SAGLAYICILAR[SahteAdaptor.kod] = SahteAdaptor


def paket_verisi(kod, ulkeler, hacim_gb, gun, usd, ad=None):
    return PaketVerisi(
        kod=kod,
        ad=ad or f"{'-'.join(ulkeler)} {hacim_gb}GB {gun}Days",
        ulkeler=list(ulkeler),
        hacim_bayt=int(hacim_gb * 1024**3),
        sure_gun=gun,
        alis_usd=Decimal(str(usd)),
        hiz="4G/5G",
        ulke_adlari={k: k for k in ulkeler},
    )


class Temel(TestCase):
    def setUp(self):
        _sifirla()
        ayar = GenelAyarlar.getir()
        ayar.usd_kuru = TL("40.0000")
        ayar.save()
        self.saglayici = Saglayici.objects.create(
            ad="Sahte", tur="sahte", erisim_kodu="x", varsayilan_kar_orani=TL("88.00")
        )
        self.bayi = User.objects.create_user("5321112233", password="parola12345")
        self.cuzdan = Cuzdan.objects.create(bayi=self.bayi, bakiye=TL("1000.00"))

    def _esitle(self, *paketler):
        DURUM["paketler"] = list(paketler)
        return paketleri_esitle(self.saglayici)


class FiyatTestleri(TestCase):
    def test_satis_kusurati_atar(self):
        # 0,46 × 40 × 1,88 = 34,592 → 34 (yukarı değil, aşağı: küsurat atılır)
        self.assertEqual(satis_fiyati_hesapla(TL("0.46"), TL("88"), TL("40")), TL("34"))

    def test_tavsiye_fiyati_kusurati_atar(self):
        from apps.esim.models import tavsiye_fiyati_hesapla

        # 34 × 1,22 = 41,48 → 41
        self.assertEqual(tavsiye_fiyati_hesapla(TL("34"), TL("22")), TL("41"))

    def test_kar_sifirsa_alisin_kendisi(self):
        self.assertEqual(satis_fiyati_hesapla(TL("2.5"), TL("0"), TL("40")), TL("100"))


class EsitlemeTestleri(Temel):
    def test_paketler_ve_ulkeler_acilir(self):
        eklenen, guncellenen, dusen = self._esitle(
            paket_verisi("P1", ["TR"], 1, 7, "0.46"),
            paket_verisi("P2", ["DE", "FR"], 5, 30, "9.00"),
        )
        self.assertEqual((eklenen, guncellenen, dusen), (2, 0, 0))
        self.assertEqual(Ulke.objects.get(kod="TR").ad, "Türkiye")
        self.assertEqual(Ulke.objects.get(kod="DE").ad, "Almanya")

        p2 = Paket.objects.get(kod="P2")
        self.assertEqual(p2.kapsam, "DE,FR")
        self.assertEqual(p2.ulke_sayisi, 2)
        self.assertTrue(p2.bolgesel)
        self.assertEqual(set(p2.ulkeler.values_list("kod", flat=True)), {"DE", "FR"})
        # Yeni paket sağlayıcının varsayılan oranıyla ve aktif açılır.
        self.assertEqual(p2.kar_orani, TL("88.00"))
        self.assertTrue(p2.aktif)

    def test_ikinci_esitleme_fiyati_gunceller_karari_korur(self):
        self._esitle(paket_verisi("P1", ["TR"], 1, 7, "0.46"))
        paket = Paket.objects.get(kod="P1")
        paket.kar_orani = TL("50")
        paket.aktif = False
        paket.save()

        eklenen, guncellenen, dusen = self._esitle(paket_verisi("P1", ["TR"], 1, 7, "0.60"))
        paket.refresh_from_db()
        self.assertEqual((eklenen, guncellenen, dusen), (0, 1, 0))
        self.assertEqual(paket.alis_usd, TL("0.6000"))
        self.assertEqual(paket.kar_orani, TL("50.00"))
        self.assertFalse(paket.aktif)

    def test_listeden_dusen_paket_silinmez_satilmaz(self):
        self._esitle(paket_verisi("P1", ["TR"], 1, 7, "0.46"), paket_verisi("P2", ["TR"], 3, 30, "1.5"))
        _, _, dusen = self._esitle(paket_verisi("P1", ["TR"], 1, 7, "0.46"))
        self.assertEqual(dusen, 1)
        p2 = Paket.objects.get(kod="P2")
        self.assertFalse(p2.saglayicida_var)
        self.assertFalse(p2.satilabilir)
        self.assertEqual(Paket.objects.satilabilir().count(), 1)

    def test_kar_orani_toplu_uygulanir(self):
        self._esitle(paket_verisi("P1", ["TR"], 1, 7, "0.46"), paket_verisi("P2", ["TR"], 3, 30, "1.5"))
        adet = kar_orani_uygula(Paket.objects.all(), TL("120"))
        self.assertEqual(adet, 2)
        self.assertEqual(set(Paket.objects.values_list("kar_orani", flat=True)), {TL("120.00")})


class EnUcuzSaglayiciTestleri(Temel):
    def setUp(self):
        super().setUp()
        self.ikinci = Saglayici.objects.create(
            ad="İkinci", tur="sahte", erisim_kodu="y", varsayilan_kar_orani=TL("88.00")
        )

    def _esitle_ikinci(self, *paketler):
        DURUM["paketler"] = list(paketler)
        return paketleri_esitle(self.ikinci)

    def test_ayni_paketten_ucuz_olan_gosterilir(self):
        self._esitle(paket_verisi("A", ["TR"], 1, 7, "0.60"), paket_verisi("B", ["DE"], 1, 7, "0.40"))
        self._esitle_ikinci(paket_verisi("C", ["TR"], 1, 7, "0.45"), paket_verisi("D", ["DE"], 1, 7, "0.55"))

        tr, _ = ulke_paketleri(Ulke.objects.get(kod="TR"), TL("40"))
        de, _ = ulke_paketleri(Ulke.objects.get(kod="DE"), TL("40"))
        self.assertEqual([p.saglayici for p in tr], [self.ikinci])
        self.assertEqual([p.saglayici for p in de], [self.saglayici])

    def test_farkli_hacim_ayri_satir(self):
        self._esitle(paket_verisi("A", ["TR"], 1, 7, "0.60"))
        self._esitle_ikinci(paket_verisi("C", ["TR"], 3, 7, "1.20"))
        tr, _ = ulke_paketleri(Ulke.objects.get(kod="TR"), TL("40"))
        self.assertEqual(len(tr), 2)

    def test_kapali_saglayici_yarismaz(self):
        self._esitle(paket_verisi("A", ["TR"], 1, 7, "0.60"))
        self._esitle_ikinci(paket_verisi("C", ["TR"], 1, 7, "0.45"))
        self.ikinci.aktif = False
        self.ikinci.save()
        tr, _ = ulke_paketleri(Ulke.objects.get(kod="TR"), TL("40"))
        self.assertEqual([p.kod for p in tr], ["A"])

    def test_ulke_listesi_en_dusuk_fiyati_verir(self):
        self._esitle(paket_verisi("A", ["TR"], 1, 7, "0.60"), paket_verisi("B", ["TR"], 5, 30, "3.00"))
        liste = ulke_listesi(TL("40"))
        self.assertEqual(len(liste), 1)
        self.assertEqual(liste[0]["kod"], "TR")
        self.assertEqual(liste[0]["en_dusuk"], TL("45"))  # 0,60 × 40 × 1,88 = 45,12
        self.assertEqual(liste[0]["bayrak"], "🇹🇷")


class SiparisTestleri(Temel):
    def setUp(self):
        super().setUp()
        self._esitle(paket_verisi("P1", ["TR"], 1, 7, "0.46"))
        self.paket = Paket.objects.get(kod="P1")
        # 0,46 × 40 × 1,88 = 34,59 → 34 ₺ (küsurat atılır)
        self.satis = TL("34")

    def test_siparis_para_duser_profil_gelir(self):
        teslimat = esim_siparisi_ver(self.bayi, self.paket, anahtar="k1")

        self.cuzdan.refresh_from_db()
        self.assertEqual(self.cuzdan.bakiye, TL("966.00"))
        self.assertEqual(teslimat.durum, TeslimatDurumu.HAZIR)
        self.assertEqual(teslimat.ac, "LPA:1$rsp.example.com$KOD-ABC")
        self.assertEqual(teslimat.smdp_adresi, "rsp.example.com")
        self.assertEqual(teslimat.aktivasyon_kodu, "KOD-ABC")
        self.assertEqual(teslimat.alis_tl, TL("18.40"))
        self.assertEqual(teslimat.kar, TL("15.60"))

        siparis = teslimat.siparis
        self.assertEqual(siparis.durum, SiparisDurumu.TESLIM)
        self.assertEqual(siparis.tutar, self.satis)
        self.assertTrue(siparis.para_islendi)
        self.assertEqual(siparis.urun_adi, "eSIM · TR 1GB 7Days")
        self.assertIsNone(siparis.urun)

        # Sağlayıcıya bizim anahtarımız ve alış fiyatı gitti.
        self.assertEqual(DURUM["siparisler"], [("P1", teslimat.islem_no, TL("0.4600"))])

    def test_ayni_anahtar_ikinci_siparis_acmaz(self):
        a = esim_siparisi_ver(self.bayi, self.paket, anahtar="k1")
        b = esim_siparisi_ver(self.bayi, self.paket, anahtar="k1")
        self.assertEqual(a.pk, b.pk)
        self.assertEqual(Siparis.objects.count(), 1)
        self.assertEqual(len(DURUM["siparisler"]), 1)

    def test_saglayici_reddederse_para_geri_doner(self):
        DURUM["reddet"] = "Insufficient account balance"
        teslimat = esim_siparisi_ver(self.bayi, self.paket)

        self.cuzdan.refresh_from_db()
        self.assertEqual(self.cuzdan.bakiye, TL("1000.00"))
        self.assertEqual(teslimat.durum, TeslimatDurumu.HATA)
        self.assertIn("Insufficient", teslimat.hata)
        self.assertEqual(teslimat.siparis.durum, SiparisDurumu.IPTAL)
        self.assertFalse(teslimat.siparis.para_islendi)
        self.assertIn("iade", teslimat.siparis.yonetim_notu)
        # Defter silinmez: hareket ve ters kaydı birlikte durur.
        self.assertEqual(
            CuzdanHareketi.objects.filter(siparis=teslimat.siparis).count(), 2
        )
        self.assertTrue(
            CuzdanHareketi.objects.filter(siparis=teslimat.siparis, tip=HareketTipi.IPTAL).exists()
        )

    def test_bakiye_yetmezse_saglayiciya_gidilmez(self):
        self.cuzdan.bakiye = TL("10.00")
        self.cuzdan.save()
        with self.assertRaises(SiparisVerilemez):
            esim_siparisi_ver(self.bayi, self.paket)
        self.assertEqual(Siparis.objects.count(), 0)
        self.assertEqual(Teslimat.objects.count(), 0)
        self.assertEqual(DURUM["siparisler"], [])

    def test_kur_yoksa_siparis_yok(self):
        ayar = GenelAyarlar.getir()
        ayar.usd_kuru = 0
        ayar.save()
        with self.assertRaises(KurTanimsiz):
            esim_siparisi_ver(self.bayi, self.paket)
        self.assertEqual(Siparis.objects.count(), 0)

    def test_pasif_paket_satilmaz(self):
        self.paket.aktif = False
        self.paket.save()
        with self.assertRaises(SiparisVerilemez):
            esim_siparisi_ver(self.bayi, self.paket)

    def test_profil_sonra_gelir(self):
        DURUM["profil_hazir"] = False
        teslimat = esim_siparisi_ver(self.bayi, self.paket)
        self.assertEqual(teslimat.durum, TeslimatDurumu.HAZIRLANIYOR)
        self.assertEqual(teslimat.siparis.durum, SiparisDurumu.VERILDI)
        self.assertEqual(teslimat.saglayici_siparis_no, "B1")

        DURUM["profil_hazir"] = True
        teslimat = profili_getir(teslimat, zorla=True)
        self.assertEqual(teslimat.durum, TeslimatDurumu.HAZIR)
        self.assertEqual(teslimat.iccid, "8990000000000000001")
        teslimat.siparis.refresh_from_db()
        self.assertEqual(teslimat.siparis.durum, SiparisDurumu.TESLIM)

    def test_sik_sorgu_saglayiciya_gitmez(self):
        DURUM["profil_hazir"] = False
        teslimat = esim_siparisi_ver(self.bayi, self.paket)
        DURUM["profil_hazir"] = True
        # Zorlamadan hemen ardından: aralık dolmadı, sorulmaz.
        teslimat = profili_getir(teslimat)
        self.assertEqual(teslimat.durum, TeslimatDurumu.HAZIRLANIYOR)


class IptalTestleri(Temel):
    def setUp(self):
        super().setUp()
        self._esitle(paket_verisi("P1", ["TR"], 1, 7, "0.46"))
        self.teslimat = esim_siparisi_ver(self.bayi, Paket.objects.get(kod="P1"))

    def test_saglayici_kabul_ederse_para_iade(self):
        teslimati_iptal_et(self.teslimat, olusturan=self.bayi)
        self.cuzdan.refresh_from_db()
        self.assertEqual(self.cuzdan.bakiye, TL("1000.00"))
        self.assertEqual(DURUM["iptaller"], ["E123"])
        self.teslimat.refresh_from_db()
        self.assertEqual(self.teslimat.durum, TeslimatDurumu.IPTAL)
        self.assertEqual(self.teslimat.siparis.durum, SiparisDurumu.IPTAL)

    def test_saglayici_reddederse_para_yerinde_kalir(self):
        DURUM["iptal_reddet"] = "This operation is not allowed due to the order status."
        with self.assertRaises(SaglayiciHatasi):
            teslimati_iptal_et(self.teslimat, olusturan=self.bayi)
        self.cuzdan.refresh_from_db()
        self.assertEqual(self.cuzdan.bakiye, TL("966.00"))
        self.teslimat.refresh_from_db()
        self.assertEqual(self.teslimat.durum, TeslimatDurumu.HAZIR)
        self.assertEqual(self.teslimat.siparis.durum, SiparisDurumu.TESLIM)


class BayiEkranTestleri(Temel):
    def setUp(self):
        super().setUp()
        self._esitle(
            paket_verisi("P1", ["TR"], 1, 7, "0.46"),
            paket_verisi("P2", ["TR", "DE", "FR"], 5, 30, "9.00", ad="Avrupa 5GB"),
        )
        self.paket = Paket.objects.get(kod="P1")
        self.client.force_login(self.bayi)

    def test_menude_esim_var_magazada_yok(self):
        """eSIM mağazadan ayrı bölüm: menüde kendi maddesi, mağaza sayfasında kartı yok."""
        icerik = self.client.get(reverse("magaza:liste")).content.decode()
        self.assertIn(reverse("esim:ulkeler"), icerik)  # kenar menü
        self.assertNotIn("Yurt dışı internet", icerik)

    def test_ulke_listesi(self):
        icerik = self.client.get(reverse("esim:ulkeler")).content.decode()
        self.assertIn("Türkiye", icerik)
        self.assertIn("Almanya", icerik)
        self.assertIn("🇹🇷", icerik)

    def test_ulke_sayfasi_paket_ve_fiyat(self):
        icerik = self.client.get(reverse("esim:ulke", args=["tr"])).content.decode()
        self.assertIn("1 GB", icerik)
        self.assertIn("34 ₺", icerik)
        self.assertIn("Bölgesel paketler", icerik)
        self.assertIn("3 ülke", icerik)
        # Sağlayıcı adı bayiye gösterilmez.
        self.assertNotIn("Sahte", icerik)

    def test_kapali_ulke_404(self):
        Ulke.objects.filter(kod="TR").update(aktif=False)
        self.assertEqual(self.client.get(reverse("esim:ulke", args=["tr"])).status_code, 404)

    def test_kur_yoksa_kapali_ekran(self):
        GenelAyarlar.objects.filter(pk=1).update(usd_kuru=0)
        yanit = self.client.get(reverse("esim:ulkeler"))
        self.assertEqual(yanit.status_code, 200)
        self.assertIn("hesaplanamıyor", yanit.content.decode())

    def test_satin_al_ve_qr(self):
        adres = reverse("esim:satin-al", args=["tr", self.paket.pk])
        yanit = self.client.post(adres, {"islem_anahtari": "abc"})
        siparis = Siparis.objects.get()
        self.assertRedirects(yanit, reverse("esim:siparis", args=[siparis.referans_no]))

        icerik = self.client.get(reverse("esim:siparis", args=[siparis.referans_no])).content.decode()
        self.assertIn("eSIM hazır", icerik)
        self.assertIn("data:image/svg+xml", icerik)
        self.assertIn("rsp.example.com", icerik)
        self.assertIn("KOD-ABC", icerik)
        self.assertIn("wa.me", icerik)
        # eSIM listesinde var, mağazanın sipariş listesinde yok.
        self.assertIn(
            reverse("esim:siparis", args=[siparis.referans_no]),
            self.client.get(reverse("esim:siparisler")).content.decode(),
        )
        self.assertNotIn(
            siparis.referans_no,
            self.client.get(reverse("magaza:siparislerim")).content.decode(),
        )

    def test_baskasinin_esimi_404(self):
        teslimat = esim_siparisi_ver(self.bayi, self.paket)
        digeri = User.objects.create_user("5329998877", password="parola12345")
        self.client.force_login(digeri)
        adres = reverse("esim:siparis", args=[teslimat.siparis.referans_no])
        self.assertEqual(self.client.get(adres).status_code, 404)

    def test_bakiye_yetmezse_dugme_yerine_sebep(self):
        self.cuzdan.bakiye = TL("5.00")
        self.cuzdan.save()
        icerik = self.client.get(reverse("esim:paket", args=["tr", self.paket.pk])).content.decode()
        self.assertIn("yetmiyor", icerik)
        self.assertNotIn("Satın al ve QR", icerik)

    def test_bolgesel_paket_sayfasi(self):
        p2 = Paket.objects.get(kod="P2")
        yanit = self.client.get(reverse("esim:paket", args=["bolgesel", p2.pk]))
        self.assertEqual(yanit.status_code, 200)
        self.assertIn("Almanya", yanit.content.decode())


class YonetimTestleri(Temel):
    def setUp(self):
        super().setUp()
        self._esitle(paket_verisi("P1", ["TR"], 1, 7, "0.46"), paket_verisi("P2", ["TR"], 3, 30, "1.5"))
        self.yonetici = User.objects.create_superuser("yonetici", password="parola12345")
        self.client.force_login(self.yonetici)

    def test_kar_orani_islemi(self):
        adres = reverse("admin:esim_paket_changelist")
        pkler = list(Paket.objects.values_list("pk", flat=True))
        # Önce ara ekran, sonra uygulama.
        yanit = self.client.post(
            adres, {"action": "kar_orani_uygula_islemi", "_selected_action": pkler}
        )
        self.assertContains(yanit, "Kâr oranı")
        self.client.post(
            adres,
            {"action": "kar_orani_uygula_islemi", "_selected_action": pkler, "uygula": "1", "oran": "120"},
        )
        self.assertEqual(set(Paket.objects.values_list("kar_orani", flat=True)), {TL("120.00")})

    def test_liste_satis_fiyatini_yazar(self):
        icerik = self.client.get(reverse("admin:esim_paket_changelist")).content.decode()
        self.assertIn("34 ₺", icerik)
        self.assertIn("Kuru güncelle", icerik)

    def test_esim_siparisi_magaza_listesinde_teslim_dugmesi_yok(self):
        teslimat = esim_siparisi_ver(self.bayi, Paket.objects.get(kod="P1"))
        icerik = self.client.get(reverse("admin:magaza_siparis_changelist")).content.decode()
        self.assertNotIn("Teslim edildi</button>", icerik)
        self.assertIn(reverse("admin:esim_teslimat_iptal", args=[teslimat.pk]), icerik)


# -- Adaptörler ------------------------------------------------------------
#
# Ağ yok: `json_istek` sahte yanıt verir. eSIM Access canlı anahtarla
# denendi; eSIM Go ve Airalo belgedeki örnek yanıtlarla ayrıştırma
# testinden geçer — canlı anahtar gelince ilk eşitleme göz önünde yapılır.

from unittest import mock

from apps.esim.saglayicilar import airalo, esimgo


class SahteSaglayiciKaydi:
    """Adaptörün ihtiyaç duyduğu alanlar; veritabanına gitmez."""

    def __init__(self, **alanlar):
        self.erisim_kodu = "ERISIM"
        self.gizli_anahtar = "GIZLI"
        self.oturum_anahtari = ""
        self.oturum_bitis = None
        self.__dict__.update(alanlar)

    def save(self, **kwargs):
        pass


class EsimGoTestleri(TestCase):
    def setUp(self):
        self.adaptor = esimgo.EsimGo(SahteSaglayiciKaydi())

    def test_katalog_ayristirma(self):
        katalog = [
            {
                "name": "esim_1GB_7D_GB_V2",
                "description": "eSIM, 1GB, 7 Days, United Kingdom, V2",
                "countries": [{"name": "United Kingdom", "region": "Europe", "iso": "GB"}],
                "dataAmount": 1000, "duration": 7, "unlimited": False, "price": 4.5,
                "billingType": "FixedCost",
            },
            {"name": "esim_UL_7D", "countries": [{"iso": "GB"}], "unlimited": True, "price": 9},
        ]
        with mock.patch.object(esimgo, "json_istek", return_value=(200, katalog)) as istek:
            paketler = self.adaptor.paketleri_getir()
        self.assertEqual(len(paketler), 1)
        p = paketler[0]
        self.assertEqual((p.kod, p.ulkeler, p.sure_gun, p.alis_usd), ("esim_1GB_7D_GB_V2", ["GB"], 7, TL("4.5")))
        self.assertEqual(p.hacim_bayt, 1000 * 1024**2)
        self.assertEqual(istek.call_args.kwargs["basliklar"]["X-API-Key"], "ERISIM")

    def test_siparis_profili_hemen_verir(self):
        yanit = {
            "order": [{"esims": [{"iccid": "8912345678901234567", "matchingId": "AB-12C3DE-4FGHIJ5",
                                  "smdpAddress": "http://rsp.mockprovider.com"}],
                       "type": "bundle", "item": "esim_5GB_30D_EU_V3", "quantity": 1}],
            "total": 9.99, "currency": "USD", "status": "completed",
            "orderReference": "1a2b3c4d-5e6f", "assigned": True,
        }
        with mock.patch.object(esimgo, "json_istek", return_value=(200, yanit)) as istek:
            siparis_no, profil = self.adaptor.siparis_ver("esim_5GB_30D_EU_V3", "islem-1", TL("9.99"))
        self.assertEqual(siparis_no, "1a2b3c4d-5e6f")
        self.assertEqual(profil.iccid, "8912345678901234567")
        self.assertEqual(profil.ac, "LPA:1$rsp.mockprovider.com$AB-12C3DE-4FGHIJ5")
        govde = istek.call_args.kwargs["govde"]
        self.assertEqual(govde["type"], "transaction")
        self.assertEqual(govde["order"][0]["item"], "esim_5GB_30D_EU_V3")

    def test_hata_mesaji_tasinir(self):
        with mock.patch.object(esimgo, "json_istek", return_value=(429, {"message": "Rate limit exceeded"})):
            with self.assertRaisesMessage(SaglayiciHatasi, "Rate limit exceeded"):
                self.adaptor.bakiye()


class AiraloTestleri(TestCase):
    def setUp(self):
        self.kayit = SahteSaglayiciKaydi()
        self.adaptor = airalo.Airalo(self.kayit)

    def _jetonlu(self, *yanitlar):
        """İlk çağrı jeton, sonrakiler sırayla verilen yanıtlar."""
        jeton = (200, {"data": {"token_type": "Bearer", "expires_in": 86400, "access_token": "JETON"}})
        return mock.patch.object(airalo, "json_istek", side_effect=[jeton, *yanitlar])

    def test_jeton_alinir_ve_saklanir(self):
        katalog = {"data": [], "meta": {"last_page": 1}}
        with self._jetonlu((200, katalog), (200, katalog)) as istek:
            self.adaptor.paketleri_getir()
        self.assertEqual(self.kayit.oturum_anahtari, "JETON")
        self.assertIsNotNone(self.kayit.oturum_bitis)
        ilk = istek.call_args_list[0].kwargs
        self.assertTrue(ilk["form"])
        self.assertEqual(ilk["govde"]["client_id"], "ERISIM")
        self.assertEqual(istek.call_args_list[1].kwargs["basliklar"]["Authorization"], "Bearer JETON")
        # Jeton bir kez alındı, iki katalog isteği yapıldı (local + global).
        self.assertEqual(istek.call_count, 3)

    def test_katalog_ayristirma_net_fiyat(self):
        katalog = {
            "data": [{
                "country_code": "TR", "title": "Turkey",
                "operators": [{
                    "id": 172, "title": "Airalo TR", "type": "local",
                    "packages": [{
                        "id": "merhaba-7days-1gb", "type": "data", "price": 9.5, "net_price": 4.75,
                        "amount": 1024, "day": 7, "is_unlimited": False, "title": "1 GB - 7 Days",
                    }],
                }],
            }],
            "meta": {"current_page": 1, "last_page": 1, "total": 1},
        }
        bos = {"data": [], "meta": {"last_page": 1}}
        with self._jetonlu((200, katalog), (200, bos)):
            paketler = self.adaptor.paketleri_getir()
        self.assertEqual(len(paketler), 1)
        p = paketler[0]
        self.assertEqual((p.kod, p.ulkeler, p.sure_gun), ("merhaba-7days-1gb", ["TR"], 7))
        self.assertEqual(p.alis_usd, TL("4.75"))  # perakende 9,5 değil, toptan
        self.assertEqual(p.hacim_bayt, 1024 * 1024**2)

    def test_siparis_lpa_dizgisi(self):
        yanit = {
            "data": {
                "id": 9666, "code": "20230227-009666", "package_id": "kallur-digital-7days-1gb",
                "sims": [{"iccid": "891000000000009125", "lpa": "lpa.airalo.com", "matching_id": "TEST",
                          "qrcode": "LPA:1$lpa.airalo.com$TEST", "qrcode_url": "https://sandbox.airalo.com/qr",
                          "apn_type": "automatic", "apn_value": None}],
            },
            "meta": {"message": "success"},
        }
        with self._jetonlu((200, yanit)):
            siparis_no, profil = self.adaptor.siparis_ver("kallur-digital-7days-1gb", "islem-1", TL("1.8"))
        self.assertEqual(siparis_no, "9666")
        self.assertEqual(profil.ac, "LPA:1$lpa.airalo.com$TEST")
        self.assertEqual(profil.iccid, "891000000000009125")

    def test_iade_talebi_otomatik_iade_yapmaz(self):
        yanit = {"data": {"refund_id": "12345", "created_at": "2024-10-12 09:30"}, "meta": {"message": "success"}}
        with self._jetonlu((202, yanit)):
            with self.assertRaisesMessage(SaglayiciHatasi, "12345"):
                self.adaptor.iptal_et("", iccid="891000000000009125")

    def test_dogrulama_hatasi_alan_adiyla(self):
        yanit = {"data": {"package_id": "The selected package id is invalid."},
                 "meta": {"message": "the parameter is invalid"}}
        with self._jetonlu((422, yanit)):
            with self.assertRaisesMessage(SaglayiciHatasi, "package_id"):
                self.adaptor.siparis_ver("yok", "islem-1", TL("1"))


class EsimAccessImzaTestleri(TestCase):
    def test_imza_belgedeki_ornekle_tutar(self):
        """Belgedeki örnek: Timestamp=1628670421 RequestID=4ce9… AccessCode=11111 Secret=1111."""
        from apps.esim.saglayicilar.esimaccess import EsimAccess

        adaptor = EsimAccess(SahteSaglayiciKaydi(erisim_kodu="11111", gizli_anahtar="1111"))
        with mock.patch("apps.esim.saglayicilar.esimaccess.time.time", return_value=1628670.421), \
             mock.patch("apps.esim.saglayicilar.esimaccess.uuid.uuid4") as u:
            u.return_value.hex = "4ce9d9cdac9e4e17b3a2c66c358c1ce2"
            basliklar = adaptor._imza(b'{"imsi":"326543826"}')
        self.assertEqual(basliklar["RT-Timestamp"], "1628670421")
        self.assertEqual(
            basliklar["RT-Signature"],
            "7eb765e27df5373dea2dbc8c41a7d9557743e46c8054750f3d851b3fd01d0835",
        )


class BayatlikUyarisiTestleri(Temel):
    """Cron yok: kur ve katalog eskiyince paket listesinin başlığı uyarır."""

    def setUp(self):
        super().setUp()
        self._esitle(paket_verisi("P1", ["TR"], 1, 7, "0.46"))
        self.client.force_login(User.objects.create_superuser("yonetici", password="parola12345"))

    def test_taze_kur_ve_katalog_uyarmaz(self):
        GenelAyarlar.objects.filter(pk=1).update(usd_kuru_tarihi=timezone.now())
        icerik = self.client.get(reverse("admin:esim_paket_changelist")).content.decode()
        self.assertNotIn("eski, güncelle", icerik)
        self.assertNotIn("Eşitle'ye bas", icerik)

    def test_eski_kur_ve_katalog_uyarir(self):
        eski = timezone.now() - timedelta(days=3)
        GenelAyarlar.objects.filter(pk=1).update(usd_kuru_tarihi=eski)
        Saglayici.objects.filter(pk=self.saglayici.pk).update(son_esitleme=eski)
        icerik = self.client.get(reverse("admin:esim_paket_changelist")).content.decode()
        self.assertIn("eski, güncelle", icerik)
        self.assertIn("Eşitle'ye bas", icerik)


class GrupOraniTestleri(Temel):
    """Fiyat kademesi: gruptaki bayi paket oranını değil grubunkini görür."""

    def setUp(self):
        super().setUp()
        from apps.finans.models import BayiGrubu

        self._esitle(paket_verisi("P1", ["TR"], 1, 7, "0.46"))  # paket oranı %88 → 34 ₺
        self.paket = Paket.objects.get(kod="P1")
        self.vip = BayiGrubu.objects.create(ad="VIP", esim_kar_orani=TL("10"))
        self.bos = BayiGrubu.objects.create(ad="Standart")  # oran yok → paketinki

    def _gruba_al(self, grup):
        self.cuzdan.grup = grup
        self.cuzdan.save()
        self.bayi = User.objects.get(pk=self.bayi.pk)  # cüzdan önbelleği tazelensin

    def test_grup_orani_paketi_ezer(self):
        self._gruba_al(self.vip)
        # 0,46 × 40 × 1,10 = 20,24 → 20 ₺
        tekil, _ = ulke_paketleri(Ulke.objects.get(kod="TR"), TL("40"), TL("10"))
        self.assertEqual(tekil[0].satis, TL("20"))
        teslimat = esim_siparisi_ver(self.bayi, self.paket)
        self.assertEqual(teslimat.siparis.tutar, TL("20"))
        self.assertEqual(teslimat.kar_orani, TL("10"))
        self.cuzdan.refresh_from_db()
        self.assertEqual(self.cuzdan.bakiye, TL("980.00"))

    def test_orani_bos_grup_paket_oranini_kullanir(self):
        self._gruba_al(self.bos)
        teslimat = esim_siparisi_ver(self.bayi, self.paket)
        self.assertEqual(teslimat.siparis.tutar, TL("34"))
        self.assertEqual(teslimat.kar_orani, TL("88.00"))

    def test_grupsuz_bayi_paket_oranini_gorur(self):
        teslimat = esim_siparisi_ver(self.bayi, self.paket)
        self.assertEqual(teslimat.siparis.tutar, TL("34"))

    def test_ekranlar_grup_fiyatini_yazar(self):
        self._gruba_al(self.vip)
        self.client.force_login(self.bayi)
        self.assertIn("20 ₺", self.client.get(reverse("esim:ulkeler")).content.decode())
        self.assertIn("20 ₺", self.client.get(reverse("esim:ulke", args=["tr"])).content.decode())
        self.assertIn("20 ₺", self.client.get(reverse("esim:paket", args=["tr", self.paket.pk])).content.decode())

    def test_paket_listesi_grup_oranlarini_yazar(self):
        self.client.force_login(User.objects.create_superuser("yonetici", password="parola12345"))
        icerik = self.client.get(reverse("admin:esim_paket_changelist")).content.decode()
        self.assertIn("VIP", icerik)
        self.assertIn("%10", icerik)


class TavsiyeFiyatiTestleri(Temel):
    """Bayi müşteriye ne diyeceğini görür: bizden aldığı × (1 + oran), küsurat atılmış."""

    def setUp(self):
        super().setUp()
        self._esitle(paket_verisi("P1", ["TR"], 1, 7, "0.46"))  # bayiye 34 ₺
        self.paket = Paket.objects.get(kod="P1")
        self.client.force_login(self.bayi)

    def test_oran_sifirsa_gosterilmez(self):
        icerik = self.client.get(reverse("esim:paket", args=["tr", self.paket.pk])).content.decode()
        self.assertNotIn("tavsiye edilen", icerik)
        teslimat = esim_siparisi_ver(self.bayi, self.paket)
        self.assertEqual(teslimat.tavsiye_fiyati, 0)

    def test_oran_varsa_kesilmis_fiyat_ve_kazanc(self):
        GenelAyarlar.objects.filter(pk=1).update(esim_tavsiye_kar_orani=TL("22"))
        # 34 × 1,22 = 41,48 → 41; kazanç 7
        icerik = self.client.get(reverse("esim:paket", args=["tr", self.paket.pk])).content.decode()
        self.assertIn("tavsiye edilen fiyat", icerik)
        self.assertIn("41 ₺", icerik)
        self.assertIn("kazancın 7 ₺", icerik)
        self.assertIn("Tavsiye satış 41 ₺", self.client.get(reverse("esim:ulke", args=["tr"])).content.decode())

        teslimat = esim_siparisi_ver(self.bayi, self.paket)
        self.assertEqual(teslimat.tavsiye_fiyati, TL("41"))
        icerik = self.client.get(reverse("esim:siparis", args=[teslimat.siparis.referans_no])).content.decode()
        self.assertIn("41 ₺", icerik)


class YuklemeTestleri(Temel):
    """Satılmış eSIM'e paket yükleme: para anında düşer, sağlayıcı reddederse döner."""

    def setUp(self):
        super().setUp()
        self._esitle(paket_verisi("P1", ["TR"], 1, 7, "0.46"))
        self.teslimat = esim_siparisi_ver(self.bayi, Paket.objects.get(kod="P1"))  # 34 ₺ → 966
        self.client.force_login(self.bayi)

    def test_yukleme_bakiyeden_duser_ve_kaydedilir(self):
        # 1,42 × 40 × 1,88 = 106,78 → 106 ₺
        yukleme = esim_yukle(self.bayi, self.teslimat, "TOPUP_1", anahtar="y1")
        self.assertEqual(yukleme.durum, "tamam")
        self.assertEqual(yukleme.siparis.tutar, TL("106"))
        self.assertEqual(yukleme.siparis.durum, SiparisDurumu.TESLIM)
        self.assertEqual(yukleme.toplam_hacim_bayt, 4 * 1024**3)
        self.cuzdan.refresh_from_db()
        self.assertEqual(self.cuzdan.bakiye, TL("860.00"))
        self.assertEqual(DURUM["yuklemeler"], [("E123", "TOPUP_1", yukleme.islem_no, TL("1.42"))])
        # Aynı anahtar ikinci yükleme açmaz.
        self.assertEqual(esim_yukle(self.bayi, self.teslimat, "TOPUP_1", anahtar="y1").pk, yukleme.pk)

    def test_saglayici_reddederse_iade(self):
        DURUM["yukleme_reddet"] = "the balance is insufficient"
        yukleme = esim_yukle(self.bayi, self.teslimat, "TOPUP_1")
        self.assertEqual(yukleme.durum, "hata")
        self.assertEqual(yukleme.siparis.durum, SiparisDurumu.IPTAL)
        self.cuzdan.refresh_from_db()
        self.assertEqual(self.cuzdan.bakiye, TL("966.00"))

    def test_bakiye_yetmezse_saglayiciya_gidilmez(self):
        self.cuzdan.bakiye = TL("50.00")
        self.cuzdan.save()
        with self.assertRaises(SiparisVerilemez):
            esim_yukle(self.bayi, self.teslimat, "TOPUP_1")
        self.assertEqual(DURUM["yuklemeler"], [])
        self.assertEqual(Siparis.objects.count(), 1)

    def test_gecersiz_paket_kodu_reddedilir(self):
        with self.assertRaises(SiparisVerilemez):
            esim_yukle(self.bayi, self.teslimat, "UYDURMA")

    def test_baskasinin_esimine_yuklenemez(self):
        digeri = User.objects.create_user("5329998877", password="parola12345")
        Cuzdan.objects.create(bayi=digeri, bakiye=TL("1000"))
        with self.assertRaises(SiparisVerilemez):
            esim_yukle(digeri, self.teslimat, "TOPUP_1")

    def test_grup_orani_yuklemede_de_gecer(self):
        from apps.finans.models import BayiGrubu

        self.cuzdan.grup = BayiGrubu.objects.create(ad="VIP", esim_kar_orani=TL("10"))
        self.cuzdan.save()
        bayi = User.objects.get(pk=self.bayi.pk)
        # 1,42 × 40 × 1,10 = 62,48 → 62
        self.assertEqual(esim_yukle(bayi, self.teslimat, "TOPUP_1").siparis.tutar, TL("62"))

    def test_ekran_liste_ve_yukleme(self):
        adres = reverse("esim:yukle", args=[self.teslimat.siparis.referans_no])
        icerik = self.client.get(adres).content.decode()
        self.assertIn("3 GB", icerik)
        self.assertIn("106 ₺", icerik)
        yanit = self.client.post(adres, {"paket": "TOPUP_2", "islem_anahtari": "abc"})
        self.assertRedirects(yanit, reverse("esim:siparis", args=[self.teslimat.siparis.referans_no]))
        icerik = self.client.get(reverse("esim:siparis", args=[self.teslimat.siparis.referans_no])).content.decode()
        self.assertIn("Yüklendi", icerik)
        self.assertIn("eSIM yükleme", self.client.get(reverse("esim:siparisler")).content.decode())

    def test_desteklemeyen_saglayici_sebep_yazar(self):
        DURUM["yukleme_yok"] = True
        icerik = self.client.get(reverse("esim:yukle", args=[self.teslimat.siparis.referans_no])).content.decode()
        self.assertIn("desteklemiyor", icerik)
        self.assertNotIn("Yükle</button>", icerik)

    def test_hazir_olmayan_esime_yuklenemez(self):
        DURUM["profil_hazir"] = False
        bekleyen = esim_siparisi_ver(self.bayi, Paket.objects.get(kod="P1"))
        with self.assertRaises(SiparisVerilemez):
            esim_yukle(self.bayi, bekleyen, "TOPUP_1")


class MusteriEtiketiTestleri(Temel):
    """Bayi eSIM'e müşteri adı/telefonu yazar, listede arayıp bulur."""

    def setUp(self):
        super().setUp()
        self._esitle(paket_verisi("P1", ["TR"], 1, 7, "0.46"))
        self.teslimat = esim_siparisi_ver(self.bayi, Paket.objects.get(kod="P1"))
        self.client.force_login(self.bayi)

    def test_etiket_kaydedilir_telefon_normalize(self):
        adres = reverse("esim:etiket", args=[self.teslimat.siparis.referans_no])
        self.client.post(adres, {"musteri_adi": " Ayşe Yılmaz ", "musteri_telefonu": "0532 123 45 67"})
        self.teslimat.refresh_from_db()
        self.assertEqual(self.teslimat.musteri_adi, "Ayşe Yılmaz")
        self.assertEqual(self.teslimat.musteri_telefonu, "5321234567")

    def test_listede_ad_ve_telefonla_bulunur(self):
        musteri_etiketle(self.teslimat, ad="Ayşe Yılmaz", telefon="5321234567")
        referans = self.teslimat.siparis.referans_no
        for q in ("Ayşe", "0532 123 45 67", "8990000000000000001"):
            icerik = self.client.get(reverse("esim:siparisler"), {"q": q}).content.decode()
            self.assertIn(referans, icerik, q)
        self.assertNotIn(referans, self.client.get(reverse("esim:siparisler"), {"q": "Mehmet"}).content.decode())

    def test_baskasinin_esimi_etiketlenemez(self):
        digeri = User.objects.create_user("5329998877", password="parola12345")
        self.client.force_login(digeri)
        adres = reverse("esim:etiket", args=[self.teslimat.siparis.referans_no])
        self.assertEqual(self.client.post(adres, {"musteri_adi": "X"}).status_code, 404)


class FiyatGuncelleTestleri(Temel):
    """Sağlayıcıdaki oran + "Fiyatları güncelle" = bütün paketler o oranda."""

    def setUp(self):
        super().setUp()
        self._esitle(paket_verisi("P1", ["TR"], 1, 7, "0.46"), paket_verisi("P2", ["TR"], 3, 30, "1.5"))
        Paket.objects.filter(kod="P2").update(kar_orani=TL("50"))
        self.saglayici.varsayilan_kar_orani = TL("100")
        self.saglayici.save()

    def test_hepsi_varsayilana_ceker(self):
        self.assertEqual(fiyatlari_guncelle(self.saglayici), 2)
        self.assertEqual(set(Paket.objects.values_list("kar_orani", flat=True)), {TL("100.00")})

    def test_dugme_post_ile_calisir_get_ile_degil(self):
        self.client.force_login(User.objects.create_superuser("yonetici", password="parola12345"))
        adres = reverse("admin:esim_saglayici_fiyat_guncelle", args=[self.saglayici.pk])
        self.client.get(adres)
        self.assertEqual(Paket.objects.get(kod="P2").kar_orani, TL("50.00"))
        yanit = self.client.post(adres, follow=True)
        self.assertContains(yanit, "2 paketin kâr oranı %100")
        self.assertEqual(Paket.objects.get(kod="P2").kar_orani, TL("100.00"))
        # Düğme listede paket olan sağlayıcıda görünür.
        self.assertContains(self.client.get(reverse("admin:esim_saglayici_changelist")), "Fiyatları güncelle")
