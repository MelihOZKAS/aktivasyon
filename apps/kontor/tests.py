"""Kontör: tek gönderim ilkesi, yedeğe geçiş, askı, iade, bayi API'si.

Sağlayıcı ağa çıkmaz: `SahteAdaptor` kayıt defterine eklenir, her
sağlayıcının davranışı `DURUM` sözlüğünden (sağlayıcı adına göre) ayarlanır.
Gönderim arka plan iş parçacığı yerine aynı iş parçacığında çalışır
(`KONTOR_ARKA_PLAN = False`); TestCase kendi transaction'ı içinde
koştuğu için atomik denetimi de kapalıdır.
"""

from datetime import timedelta
import json
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import connection
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.finans.models import Cuzdan, CuzdanHareketi
from apps.finans.services import SiparisVerilemez
from apps.katalog.models import Operator
from apps.kontor import saglayicilar
from apps.kontor.models import (
    ApiErisimi,
    Deneme,
    DenemeDurumu,
    FiyatGrubu,
    Hedef,
    Islem,
    IslemDurumu,
    Kanal,
    Kategori,
    Paket,
    PaketFiyati,
    Rota,
    Saglayici,
    SaglayiciPaketi,
)
from apps.kontor.saglayicilar import (
    Adaptor,
    Gonderim,
    GonderimSonucu,
    SaglayiciHatasi,
    SaglayiciPaketVerisi,
    Sorgu,
    SorguSonucu,
    grafi,
    kntryeni,
    tutar_coz,
    znet,
)
from apps.kontor.services import (
    IslemMesgul,
    KararVerilemez,
    YuklemeYapilamaz,
    bekleyenleri_isle,
    elle_gonder,
    fiyat_listesini_cek,
    iptal_et,
    isle,
    sahiplik,
    kategori_listesi,
    satistaki_paketler,
    sonucu_sorgula,
    yukleme_baslat,
    yuklendi_say,
)
from apps.magaza.models import Siparis, SiparisDurumu

TL = Decimal

# Sağlayıcı adı → davranış. "gonderim": kabul/red/belirsiz/kopuk/zaman;
# "sorgu": basarili/islemde/iptal/hata.
DURUM = {}


def _ayar(ad, **degerler):
    DURUM.setdefault(ad, {"gonderim": "kabul", "sorgu": "islemde", "gonderilen": [], "sorulan": []})
    DURUM[ad].update(degerler)
    return DURUM[ad]


class SahteAdaptor(Adaptor):
    kod = "sahte"
    ad = "Sahte"
    denenmedi = False
    paket_listesi_var = True

    def _d(self):
        return _ayar(self.saglayici.ad)

    def gonder(self, *, ref, hedef, uzak_kod, uzak_operator, uzak_tip):
        d = self._d()
        d["gonderilen"].append((ref, hedef, uzak_kod, uzak_operator, uzak_tip))
        davranis = d["gonderim"]
        if davranis == "kopuk":
            raise SaglayiciHatasi("Bağlantı reddedildi", kesin_gitmedi=True)
        if davranis == "zaman":
            raise SaglayiciHatasi("20 saniyede cevap vermedi")
        if davranis == "red" or uzak_kod in d.get("red_kodlar", ()):
            mesaj = d.get("red_mesaj", "Numara hatalı")
            return GonderimSonucu(Gonderim.RED, mesaj=mesaj, ham=f"OK|3|{mesaj}|0.00")
        if davranis == "belirsiz":
            return GonderimSonucu(Gonderim.BELIRSIZ, mesaj="??", ham="OK|8|Bekleyin|0")
        return GonderimSonucu(Gonderim.KABUL, uzak_ref=f"U{ref}", alis=d.get("alis"), ham="OK|1|Alındı|9.50")

    def sorgula(self, *, ref, uzak_ref):
        d = self._d()
        d["sorulan"].append(ref)
        davranis = d["sorgu"]
        if davranis == "hata":
            raise SaglayiciHatasi("ulaşılamadı")
        if davranis == "basarili":
            return SorguSonucu(Sorgu.BASARILI, mesaj=d.get("mesaj", "Yüklendi"), alis=d.get("sorgu_alis"), ham="1:Yuklendi:9.50")
        if davranis == "iptal":
            return SorguSonucu(Sorgu.IPTAL, mesaj="Numara hatalı", ham="3:Numara hatalı")
        return SorguSonucu(Sorgu.ISLEMDE, ham="2:islemde:0")

    def paketleri_getir(self):
        return list(self._d().get("liste", []))


saglayicilar.saglayici_secenekleri()
saglayicilar.SAGLAYICILAR[SahteAdaptor.kod] = SahteAdaptor


TEST_ONBELLEK = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    "kontor_sorgu": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "kontor-test"},
}


@override_settings(KONTOR_ARKA_PLAN=False, KONTOR_ATOMIK_DENETIMI=False, CACHES=TEST_ONBELLEK)
class Temel(TestCase):
    def setUp(self):
        DURUM.clear()
        self.bir = Saglayici.objects.create(ad="Bir", tur="sahte", adres="bir.test", kullanici_adi="u", sifre="s")
        self.iki = Saglayici.objects.create(ad="İki", tur="sahte", adres="iki.test", kullanici_adi="u", sifre="s")
        _ayar("Bir")
        _ayar("İki")
        self.operator = Operator.objects.create(ad="Vodafone", renk="#e60000")
        self.kategori = Kategori.objects.create(
            ad="Vodafone Paket", operator=self.operator, api_operator="vodafone", api_tip="ses"
        )
        self.paket = Paket.objects.create(
            kategori=self.kategori, kod="100", ad="Kolay Paket 15", satis_fiyati=TL("110.00"),
            dakika=1000, internet_mb=15000, gun=30,
        )
        Rota.objects.create(paket=self.paket, saglayici=self.bir, sira=1, alis_fiyati=TL("100.00"))
        Rota.objects.create(paket=self.paket, saglayici=self.iki, sira=2, uzak_kod="V100", alis_fiyati=TL("102.00"))
        self.bayi = User.objects.create_user("5321112233", password="parola12345")
        self.cuzdan = Cuzdan.objects.create(bayi=self.bayi, bakiye=TL("500.00"))

    def yukle(self, hedef="0532 999 88 77", **kw):
        with self.captureOnCommitCallbacks(execute=True):
            islem = yukleme_baslat(self.bayi, self.paket, hedef, **kw)
        islem.refresh_from_db()
        return islem

    def bakiye(self):
        self.cuzdan.refresh_from_db()
        return self.cuzdan.bakiye


class AcmaTestleri(Temel):
    def test_para_duser_ve_ilk_saglayiciya_gider(self):
        islem = self.yukle()
        self.assertEqual(self.bakiye(), TL("390.00"))
        self.assertEqual(islem.durum, IslemDurumu.ISLEMDE)
        self.assertEqual(islem.hedef, "5329998877")
        self.assertEqual(islem.saglayici, self.bir)
        (ref, hedef, kod, op, tip), = DURUM["Bir"]["gonderilen"]
        self.assertEqual((hedef, kod, op, tip), ("5329998877", "100", "vodafone", "ses"))
        self.assertEqual(DURUM["İki"]["gonderilen"], [])

    def test_tam_kontorde_saglayiciya_tip_tam_gider(self):
        # Eski sistemde tam kontör ayrı tablodan eşleşip tip=tam ile gidiyordu.
        self.kategori.tam_kontor = True
        self.kategori.save()
        self.yukle()
        (_, _, kod, op, tip), = DURUM["Bir"]["gonderilen"]
        self.assertEqual((kod, op, tip), ("100", "vodafone", "tam"))
        # Rotada o sağlayıcı için ayrı tip yazılmışsa o gider.
        rota = Rota.objects.select_related("paket__kategori").get(saglayici=self.bir)
        rota.uzak_tip = "full"
        self.assertEqual(rota.gidecek_tip, "full")
        # Kapalıyken tip kodu gider.
        self.kategori.tam_kontor = False
        self.assertEqual(self.kategori.gonderim_tipi, "ses")

    def test_operator_kodu_bossa_kategorinin_operatoru_gider(self):
        # Kod boşken operator= boş gidiyordu; sağlayıcı "tam300" arayıp reddetti
        # (operatör + tip + kupür: "TurkcellTam300" olmalıydı).
        turkcell = Operator.objects.create(ad="Turkcell", renk="#ffc900")
        self.kategori.operator = turkcell
        self.kategori.api_operator = ""
        self.kategori.tam_kontor = True
        self.kategori.save()
        self.yukle()
        (_, _, kod, op, tip), = DURUM["Bir"]["gonderilen"]
        self.assertEqual((kod, op, tip), ("100", "turkcell", "tam"))
        # Türk Telekom protokolde "avea"dır; yazılmış kod her zaman önce gelir.
        self.kategori.operator = Operator.objects.create(ad="Türk Telekom", renk="#0057b8")
        self.assertEqual(self.kategori.gonderim_operatoru, "avea")
        self.kategori.api_operator = "tt"
        self.assertEqual(self.kategori.gonderim_operatoru, "tt")

    def test_operatoru_bilinmeyen_kategoride_tam_kontor_acilmaz(self):
        kategori = Kategori(ad="Tam TL", tam_kontor=True)
        with self.assertRaises(ValidationError) as hata:
            kategori.full_clean()
        self.assertIn("tam_kontor", hata.exception.message_dict)
        kategori.api_operator = "turkcell"
        kategori.full_clean()

    def test_bakiye_yetmezse_hicbir_sey_yazilmaz(self):
        self.cuzdan.bakiye = TL("50.00")
        self.cuzdan.save()
        with self.assertRaises(SiparisVerilemez):
            self.yukle()
        self.assertFalse(Islem.objects.exists())
        self.assertFalse(Siparis.objects.exists())
        self.assertEqual(DURUM["Bir"]["gonderilen"], [])

    def test_numara_bicimi_denetlenir(self):
        with self.assertRaises(YuklemeYapilamaz):
            self.yukle("12345")
        self.assertEqual(self.bakiye(), TL("500.00"))

    def test_ayni_anahtar_ikinci_islem_acmaz(self):
        a = self.yukle(anahtar="k1")
        b = self.yukle(anahtar="k1")
        self.assertEqual(a.pk, b.pk)
        self.assertEqual(len(DURUM["Bir"]["gonderilen"]), 1)
        self.assertEqual(self.bakiye(), TL("390.00"))

    def test_panelde_ayni_numaraya_ayni_paket_hemen_ikinci_kez_acilmaz(self):
        self.yukle()
        with self.assertRaisesMessage(YuklemeYapilamaz, "şu an yükleniyor"):
            self.yukle()
        self.assertEqual(self.bakiye(), TL("390.00"))

    def test_suren_islem_varken_sure_gecse_de_ikinci_kez_acilmaz(self):
        """Yavaş bağlantıda bayi dakikalar sonra yeniden basarsa da yüklenmez."""
        islem = self.yukle()
        Islem.objects.filter(pk=islem.pk).update(olusturma_tarihi=timezone.now() - timedelta(minutes=30))
        with self.assertRaisesMessage(YuklemeYapilamaz, "şu an yükleniyor"):
            self.yukle()
        self.assertEqual(self.bakiye(), TL("390.00"))

    def test_yuklendikten_hemen_sonra_ikinci_kez_acilmaz_sure_gecince_acilir(self):
        islem = self.yukle()
        _ayar("Bir", sorgu="basarili")
        isle(islem.pk, zorla=True)
        with self.assertRaisesMessage(YuklemeYapilamaz, "az önce yüklendi"):
            self.yukle()
        Islem.objects.filter(pk=islem.pk).update(olusturma_tarihi=timezone.now() - timedelta(minutes=3))
        self.yukle()
        self.assertEqual(self.bakiye(), TL("280.00"))

    def test_iptal_edilen_islemden_sonra_hemen_yeniden_denenebilir(self):
        _ayar("Bir", gonderim="red")
        _ayar("İki", gonderim="red")
        iptal_et(self.yukle())  # gönderilemedi → askı → yönetim iptal etti
        _ayar("Bir", gonderim="kabul")
        self.yukle()
        self.assertEqual(self.bakiye(), TL("390.00"))

    def test_cuzdan_kilitlenir(self):
        """Aynı bayinin eşzamanlı istekleri cüzdan kilidinde sıraya girer."""
        from unittest import mock

        with mock.patch("apps.kontor.services._cuzdani_getir", wraps=__import__(
            "apps.finans.services", fromlist=["_cuzdani_getir"])._cuzdani_getir) as kilit:
            self.yukle()
        kilit.assert_called_with(self.bayi.pk)

    def test_cift_gonderim_ayni_anahtarla_tek_islem_tek_kesinti(self):
        yanitlar = []
        self.client.force_login(self.bayi)
        for _ in range(3):
            with self.captureOnCommitCallbacks(execute=True):
                yanitlar.append(self.client.post(
                    reverse("kontor:yukle", args=[self.kategori.slug, "100"]),
                    {"hedef": "5329998877", "islem_anahtari": "ayni"},
                ))
        self.assertEqual(Islem.objects.count(), 1)
        self.assertEqual({y["Location"] for y in yanitlar}, {Islem.objects.get().get_absolute_url()})
        self.assertEqual(len(DURUM["Bir"]["gonderilen"]), 1)
        self.assertEqual(self.bakiye(), TL("390.00"))

    def _gruba_bagla(self, grup):
        self.cuzdan.kontor_grubu = grup
        self.cuzdan.save()
        self.bayi.refresh_from_db()

    def _grup(self, ad="Toptan", fiyat=None, **kw):
        grup = FiyatGrubu.objects.create(ad=ad, **kw)
        if fiyat is not None:
            PaketFiyati.objects.create(paket=self.paket, grup=grup, fiyat=fiyat)
        return grup

    def test_grup_fiyati_bayiden_kesilir(self):
        self._gruba_bagla(self._grup(fiyat=TL("106.00")))
        self.assertEqual(satistaki_paketler(self.kategori, self.bayi)[0].fiyat, TL("106.00"))
        self.yukle()
        self.assertEqual(self.bakiye(), TL("394.00"))

    def test_fiyati_yazilmayan_paket_gruba_satilmaz(self):
        self._gruba_bagla(self._grup())
        self.assertEqual(satistaki_paketler(self.kategori, self.bayi), [])
        with self.assertRaises(YuklemeYapilamaz):
            self.yukle()
        self.assertEqual(self.bakiye(), TL("500.00"))

    def test_net_fiyat_alisa_bakmaz(self):
        self._gruba_bagla(self._grup(fiyat=TL("444.15")))
        Rota.objects.update(alis_fiyati=None)
        self.assertEqual(satistaki_paketler(self.kategori, self.bayi)[0].fiyat, TL("444.15"))

    def test_varsayilan_grup_grupsuz_bayiye_gecer(self):
        self._grup(ad="Perakende", fiyat=TL("108.00"), varsayilan=True)
        self.assertEqual(satistaki_paketler(self.kategori, self.bayi)[0].fiyat, TL("108.00"))

    def test_grup_yoksa_paketin_fiyati(self):
        self.assertEqual(satistaki_paketler(self.kategori, self.bayi)[0].fiyat, TL("110.00"))

    def test_fiyatsiz_kategori_bayinin_listesinde_yok(self):
        grup = self._grup(fiyat=TL("105.00"))
        self._gruba_bagla(grup)
        self.assertEqual(list(kategori_listesi(bayi=self.bayi)), [self.kategori])
        PaketFiyati.objects.all().delete()
        self.assertEqual(list(kategori_listesi(bayi=self.bayi)), [])

    def test_bayi_kategori_sayfasi_sayfalanir_ve_aranir(self):
        for i in range(60):
            paket = Paket.objects.create(kategori=self.kategori, kod=f"K{i}", ad=f"Ek paket {i}", satis_fiyati=TL("5"))
            Rota.objects.create(paket=paket, saglayici=self.bir, alis_fiyati=TL("4"))
        self.client.force_login(self.bayi)
        adres = reverse("kontor:kategori", args=[self.kategori.slug])
        yanit = self.client.get(adres)
        self.assertEqual(len(yanit.context["paketler"]), 50)
        self.assertContains(yanit, "1 / 2 · 61 paket")
        yanit = self.client.get(adres + "?q=kolay")
        self.assertEqual([p.pk for p in yanit.context["paketler"]], [self.paket.pk])

    def test_tek_varsayilan_grup(self):
        FiyatGrubu.objects.create(ad="Perakende", varsayilan=True)
        ikinci = FiyatGrubu(ad="Toptan", varsayilan=True)
        with self.assertRaises(ValidationError):
            ikinci.full_clean()

    def test_saglayicisiz_paket_satilir_ve_askiya_duser(self):
        self.paket.rotalar.all().delete()
        self.assertEqual(satistaki_paketler(self.kategori, self.bayi), [self.paket])
        islem = self.yukle()
        self.assertEqual(islem.durum, IslemDurumu.ASKIDA)
        self.assertEqual(self.bakiye(), TL("390.00"))  # para düşülü, yönetim karar verir
        # Yönetim elle yükleyip "Yüklendi say" der.
        yuklendi_say(islem, alis=TL("100"))
        islem.refresh_from_db()
        self.assertEqual(islem.durum, IslemDurumu.BASARILI)

    def test_hesap_hedefi_serbest_pin_hedefsiz(self):
        oyun = Kategori.objects.create(ad="PUBG UC", hedef=Hedef.YOK)
        pin = Paket.objects.create(kategori=oyun, kod="UC60", ad="60 UC", satis_fiyati=TL("40"))
        Rota.objects.create(paket=pin, saglayici=self.bir)
        with self.captureOnCommitCallbacks(execute=True):
            islem = yukleme_baslat(self.bayi, pin, "ne yazılırsa yazılsın")
        self.assertEqual(islem.hedef, "")


class TekGonderimTestleri(Temel):
    """Aynı işlem aynı sağlayıcıya kendiliğinden ikinci kez gitmez."""

    def test_basarili_sonuc_islemi_kapatir(self):
        islem = self.yukle()
        _ayar("Bir", sorgu="basarili", mesaj="Yüklendi-ONAY", sorgu_alis=TL("99.50"))
        islem = isle(islem.pk, zorla=True)
        self.assertEqual(islem.durum, IslemDurumu.BASARILI)
        self.assertEqual(islem.alis_tutari, TL("99.50"))
        self.assertEqual(islem.kar, TL("10.50"))
        self.assertEqual(islem.siparis.durum, SiparisDurumu.TESLIM)
        self.assertEqual(self.bakiye(), TL("390.00"))
        self.assertEqual(len(DURUM["Bir"]["gonderilen"]), 1)

    def test_alis_bildirilmezse_rotanin_alisi_yazilir(self):
        islem = self.yukle()
        _ayar("Bir", sorgu="basarili")
        islem = isle(islem.pk, zorla=True)
        self.assertEqual(islem.alis_tutari, TL("100.00"))

    def test_islemde_iken_tekrar_sorulur_ama_gonderilmez(self):
        islem = self.yukle()
        for _ in range(3):
            isle(islem.pk, zorla=True)
        self.assertEqual(len(DURUM["Bir"]["sorulan"]), 3)
        self.assertEqual(len(DURUM["Bir"]["gonderilen"]), 1)
        self.assertEqual(DURUM["İki"]["gonderilen"], [])

    def test_sorgu_araligi_sik_sormayi_engeller(self):
        from apps.kontor.services import SORGU_ARALIGI

        islem = self.yukle()
        isle(islem.pk)
        isle(islem.pk)
        self.assertEqual(len(DURUM["Bir"]["sorulan"]), 1)
        # İşlemdeki işlem 25 sn'de bir sorulur: 20 sn sonra gitmez, 25 sn sonra gider.
        self.assertEqual(SORGU_ARALIGI, timedelta(seconds=25))
        Islem.objects.filter(pk=islem.pk).update(son_sorgu=timezone.now() - timedelta(seconds=20))
        isle(islem.pk)
        self.assertEqual(len(DURUM["Bir"]["sorulan"]), 1)
        Islem.objects.filter(pk=islem.pk).update(son_sorgu=timezone.now() - timedelta(seconds=25))
        isle(islem.pk)
        self.assertEqual(len(DURUM["Bir"]["sorulan"]), 2)

    def test_kesin_ret_siradakine_gecer(self):
        _ayar("Bir", gonderim="red")
        islem = self.yukle()
        self.assertEqual(islem.durum, IslemDurumu.ISLEMDE)
        self.assertEqual(islem.saglayici, self.iki)
        self.assertEqual(DURUM["İki"]["gonderilen"][0][2], "V100")  # rotanın kendi kodu

    def test_baglanti_kurulamazsa_siradakine_gecer(self):
        _ayar("Bir", gonderim="kopuk")
        islem = self.yukle()
        self.assertEqual(islem.saglayici, self.iki)

    def test_hepsi_gonderimi_reddederse_iptal_degil_askiya_duser(self):
        # Kod yanlış eşleşmiş olabilir: her satış bayiye "yüklenemedi" demesin.
        _ayar("Bir", gonderim="red", red_mesaj="Aktif Kontor VodafoneSes8401")
        _ayar("İki", gonderim="red")
        islem = self.yukle()
        self.assertEqual(islem.durum, IslemDurumu.ASKIDA)
        self.assertEqual(
            islem.sonuc_mesaji,
            f"Gönderilemedi — {self.bir.ad}: OK|3|Aktif Kontor VodafoneSes8401|0.00 · "
            f"{self.iki.ad}: OK|3|Numara hatalı|0.00",
        )
        self.assertEqual(islem.siparis.durum, SiparisDurumu.VERILDI)
        self.assertEqual(self.bakiye(), TL("390.00"))

    def test_zaman_asiminda_askiya_alinir_baska_yere_gitmez(self):
        _ayar("Bir", gonderim="zaman")
        islem = self.yukle()
        self.assertEqual(islem.durum, IslemDurumu.ASKIDA)
        self.assertEqual(DURUM["İki"]["gonderilen"], [])
        self.assertEqual(self.bakiye(), TL("390.00"))  # para düşülü kalır
        # İşçi askıdakine dokunmaz.
        bekleyenleri_isle()
        self.assertEqual(len(DURUM["Bir"]["gonderilen"]), 1)
        self.assertEqual(DURUM["İki"]["gonderilen"], [])

    def test_anlasilmayan_cevapta_askiya_alinir(self):
        _ayar("Bir", gonderim="belirsiz")
        islem = self.yukle()
        self.assertEqual(islem.durum, IslemDurumu.ASKIDA)
        self.assertEqual(DURUM["İki"]["gonderilen"], [])

    def test_sorgu_iptal_derse_siradakine_gecer(self):
        islem = self.yukle()
        _ayar("Bir", sorgu="iptal")
        islem = isle(islem.pk, zorla=True)
        self.assertEqual(islem.durum, IslemDurumu.ISLEMDE)
        self.assertEqual(islem.saglayici, self.iki)
        self.assertEqual(len(DURUM["Bir"]["gonderilen"]), 1)

    def test_sorguda_iptal_sonra_gonderim_reddi_askiya_duser(self):
        _ayar("İki", gonderim="red")
        islem = self.yukle()
        _ayar("Bir", sorgu="iptal")
        islem = isle(islem.pk, zorla=True)
        # Bir'de operatör iptal etti, İki gönderimi hiç açmadı: yönetim baksın.
        self.assertEqual(islem.durum, IslemDurumu.ASKIDA)
        self.assertIn("OK|3|Numara hatalı|0.00", islem.sonuc_mesaji)

    def test_eski_gonderim_retleri_operatorun_iptalini_askiya_cevirmez(self):
        # Canlıda: operator= boş gittiği için iki gönderim reddedildi (askı),
        # düzeltilip elle gönderildi, sağlayıcı kabul etti, sorgu "3::" dedi.
        # İşlem eski retler yüzünden yine askıya düşüyordu; iptal + iade olmalı.
        _ayar("Bir", gonderim="red")
        _ayar("İki", gonderim="red")
        islem = self.yukle()
        self.assertEqual(islem.durum, IslemDurumu.ASKIDA)
        _ayar("Bir", gonderim="kabul", sorgu="iptal")
        elle_gonder(islem, self.bir)
        islem = isle(islem.pk, zorla=True)
        self.assertEqual(islem.durum, IslemDurumu.IPTAL)
        self.assertEqual(islem.sonuc_mesaji, "3:Numara hatalı")
        self.assertEqual(self.bakiye(), TL("500.00"))

    def test_tek_saglayici_sorguda_iptal_derse_sebebi_yazilir(self):
        Rota.objects.filter(saglayici=self.iki).delete()
        islem = self.yukle()
        _ayar("Bir", sorgu="iptal")
        islem = isle(islem.pk, zorla=True)
        self.assertEqual(islem.durum, IslemDurumu.IPTAL)
        self.assertEqual(islem.sonuc_mesaji, "3:Numara hatalı")
        self.assertIn("3:Numara hatalı", islem.siparis.yonetim_notu)

    def test_saglayicida_bakiye_bitince_iptal_degil_askiya_duser(self):
        _ayar("Bir", gonderim="red", red_mesaj="Yetersiz bakiye")
        _ayar("İki", gonderim="red")
        islem = self.yukle()
        # Bir'in bakiyesi yetmedi, sıradaki yine denendi; o da aldırmadı.
        self.assertEqual(len(DURUM["İki"]["gonderilen"]), 1)
        self.assertEqual(islem.durum, IslemDurumu.ASKIDA)
        self.assertIn("OK|3|Yetersiz bakiye|0.00", islem.sonuc_mesaji)
        self.assertIn(self.bir.ad, islem.sonuc_mesaji)
        self.assertEqual(self.bakiye(), TL("390.00"))  # para bayiden düşülü kalır

        # Bakiye yüklendi: yönetim aynı sağlayıcıya yeniden gönderir.
        _ayar("Bir", gonderim="kabul")
        deneme = elle_gonder(islem, self.bir)
        islem.refresh_from_db()
        self.assertEqual((deneme.durum, islem.durum), (DenemeDurumu.ISLEMDE, IslemDurumu.ISLEMDE))

    def test_hicbir_saglayiciya_baglanilamazsa_askiya_duser(self):
        _ayar("Bir", gonderim="kopuk")
        _ayar("İki", gonderim="kopuk")
        islem = self.yukle()
        self.assertEqual(islem.durum, IslemDurumu.ASKIDA)
        self.assertEqual(self.bakiye(), TL("390.00"))

    def test_sorgu_hatasi_islemi_bozmaz(self):
        islem = self.yukle()
        _ayar("Bir", sorgu="hata")
        islem = isle(islem.pk, zorla=True)
        self.assertEqual(islem.durum, IslemDurumu.ISLEMDE)
        self.assertEqual(DURUM["İki"]["gonderilen"], [])

    def test_yarim_kalan_gonderim_yeniden_gonderilmez(self):
        """Süreç istek atarken öldü: deneme "Gönderiliyor"da kaldı."""
        islem = self.yukle()
        islem.denemeler.update(durum=DenemeDurumu.GONDERILIYOR)
        Islem.objects.filter(pk=islem.pk).update(
            durum=IslemDurumu.SIRADA, olusturma_tarihi=timezone.now() - timedelta(minutes=1)
        )
        bekleyenleri_isle()
        islem.refresh_from_db()
        self.assertEqual(islem.durum, IslemDurumu.ASKIDA)
        self.assertEqual(len(DURUM["Bir"]["gonderilen"]), 1)
        self.assertEqual(DURUM["İki"]["gonderilen"], [])
        self.assertEqual(islem.denemeler.get().durum, DenemeDurumu.BELIRSIZ)

    def test_sahiplik_varken_isle_dokunmaz(self):
        islem = self.yukle()
        with sahiplik(islem.pk):
            self.assertIsNone(isle(islem.pk, zorla=True))
            with self.assertRaises(IslemMesgul):
                sonucu_sorgula(islem)
        self.assertEqual(DURUM["Bir"]["sorulan"], [])

    def test_referanslar_saglayici_sayacindan_artarak_verilir(self):
        self.bir.ref_sayaci = 50000
        self.bir.save()
        self.yukle()
        self.assertEqual(DURUM["Bir"]["gonderilen"][0][0], "50000")
        self.bir.refresh_from_db()
        self.assertEqual(self.bir.ref_sayaci, 50001)


class KararTestleri(Temel):
    def askida(self):
        _ayar("Bir", gonderim="zaman")
        return self.yukle()

    def test_sorgula_basarili_derse_kapanir(self):
        islem = self.askida()
        _ayar("Bir", sorgu="basarili")
        self.assertEqual(sonucu_sorgula(islem), "basarili")
        islem.refresh_from_db()
        self.assertEqual(islem.durum, IslemDurumu.BASARILI)

    def test_askidaki_sorgu_iptal_derse_askida_kalir_gonderilmez(self):
        islem = self.askida()
        _ayar("Bir", sorgu="iptal")
        self.assertEqual(sonucu_sorgula(islem), "iptal")
        islem.refresh_from_db()
        self.assertEqual(islem.durum, IslemDurumu.ASKIDA)
        self.assertEqual(DURUM["İki"]["gonderilen"], [])

    def test_askidaki_sorgu_islemde_derse_takip_surer(self):
        islem = self.askida()
        self.assertEqual(sonucu_sorgula(islem), "islemde")
        islem.refresh_from_db()
        self.assertEqual(islem.durum, IslemDurumu.ISLEMDE)

    def test_yuklendi_say(self):
        islem = self.askida()
        yuklendi_say(islem, alis=TL("98.00"), mesaj="PIN 1234", olusturan=self.bayi)
        islem.refresh_from_db()
        self.assertEqual((islem.durum, islem.alis_tutari, islem.sonuc_mesaji), (IslemDurumu.BASARILI, TL("98.00"), "PIN 1234"))
        self.assertEqual(self.bakiye(), TL("390.00"))

    def test_iptal_iade_eder_ve_bir_kez_yapilir(self):
        islem = self.askida()
        iptal_et(islem, mesaj="Numara hatalı")
        self.assertEqual(self.bakiye(), TL("500.00"))
        with self.assertRaises(KararVerilemez):
            iptal_et(islem)
        self.assertEqual(self.bakiye(), TL("500.00"))

    def test_elle_gonderim_yalnizca_secilen_saglayiciya_bir_kez(self):
        islem = self.askida()
        deneme = elle_gonder(islem, self.iki)
        self.assertTrue(deneme.elle)
        islem.refresh_from_db()
        self.assertEqual(islem.durum, IslemDurumu.ISLEMDE)
        self.assertEqual(len(DURUM["İki"]["gonderilen"]), 1)

    def test_elle_gonderim_reddedilirse_askida_kalir(self):
        islem = self.askida()
        _ayar("İki", gonderim="red")
        elle_gonder(islem, self.iki)
        islem.refresh_from_db()
        self.assertEqual(islem.durum, IslemDurumu.ASKIDA)
        self.assertEqual(self.bakiye(), TL("390.00"))

    def test_elle_gonderim_yalnizca_askidakine(self):
        islem = self.yukle()
        with self.assertRaises(KararVerilemez):
            elle_gonder(islem, self.iki)


class FiyatListesiTestleri(Temel):
    def test_liste_cekilir_rota_alisi_guncellenir(self):
        _ayar(
            "İki",
            liste=[SaglayiciPaketVerisi("V100", "Kolay 15", TL("97.25"), "vodafone", "ses"),
                   SaglayiciPaketVerisi("X", "Başka", TL("5"))],
        )
        adet, guncellenen = fiyat_listesini_cek(self.iki)
        self.assertEqual((adet, guncellenen), (2, 1))
        self.assertEqual(Rota.objects.get(saglayici=self.iki).alis_fiyati, TL("97.25"))
        self.assertEqual(SaglayiciPaketi.objects.filter(saglayici=self.iki).count(), 2)
        self.paket.refresh_from_db()
        self.assertEqual(self.paket.satis_fiyati, TL("110.00"))  # satışa dokunulmaz


class ProtokolTestleri(TestCase):
    def test_tutar(self):
        self.assertEqual(tutar_coz("12,50"), TL("12.50"))
        self.assertEqual(tutar_coz("{9.75}"), TL("9.75"))
        self.assertEqual(tutar_coz("1.250,50"), TL("1250.50"))
        self.assertIsNone(tutar_coz("abc"))

    def test_znet_gonderim(self):
        kabul = znet.gonderim_coz("OK|1|Talebiniz alındı|12.50")
        self.assertEqual((kabul.durum, kabul.alis), (Gonderim.KABUL, TL("12.50")))
        self.assertEqual(znet.gonderim_coz("OK|3|Yetersiz bakiye|0.00").durum, Gonderim.RED)
        self.assertEqual(znet.gonderim_coz("OK|8|Bekleyin|0").durum, Gonderim.BELIRSIZ)
        self.assertEqual(znet.gonderim_coz("<html>500</html>").durum, Gonderim.BELIRSIZ)

    def test_znet_sorgu(self):
        sonuc = znet.sorgu_coz("1:Y%C3%BCklendi+-ONAYLANDI:9,50")
        self.assertEqual((sonuc.durum, sonuc.mesaj, sonuc.alis), (Sorgu.BASARILI, "Yüklendi -ONAYLANDI", TL("9.50")))
        self.assertEqual(znet.sorgu_coz("2:islemde:0").durum, Sorgu.ISLEMDE)
        self.assertEqual(znet.sorgu_coz("3:Numara hatalı").durum, Sorgu.IPTAL)
        self.assertEqual(znet.sorgu_coz("").durum, Sorgu.ISLEMDE)

    def test_znet_fiyat_listesi(self):
        ham = '{"TopUpPricesResult":{"Packages":[{"PackageName":"100 TL","ProductId":"100","Price":"95,50","Operator":"vodafone","Type":"tl"}]}}'
        (p,) = znet.paket_listesi_coz(ham)
        self.assertEqual((p.kod, p.fiyat, p.operator), ("100", TL("95.50"), "vodafone"))
        with self.assertRaises(SaglayiciHatasi):
            znet.paket_listesi_coz("Hatalı")

    def test_teknografi(self):
        kabul = grafi.gonderim_coz("OK 123456")
        self.assertEqual((kabul.durum, kabul.uzak_ref), (Gonderim.KABUL, "123456"))
        self.assertEqual(grafi.gonderim_coz("HATA Bakiye yetersiz").durum, Gonderim.RED)
        self.assertEqual(grafi.gonderim_coz("Bilinmeyen").durum, Gonderim.BELIRSIZ)
        basarili = grafi.sorgu_coz("OK |12,50|Yüklendi")
        self.assertEqual((basarili.durum, basarili.alis), (Sorgu.BASARILI, TL("12.50")))
        self.assertEqual(grafi.sorgu_coz("99 islemde").durum, Sorgu.ISLEMDE)
        self.assertEqual(grafi.sorgu_coz("98 iptal").durum, Sorgu.IPTAL)
        (p,) = grafi.paket_listesi_coz("Vodafone 100;100;5;0;95,50;tl;100;")
        self.assertEqual((p.kod, p.fiyat), ("100", TL("95.50")))

    def test_kntryeni(self):
        kabul = kntryeni.gonderim_coz("_OK[98765] {12.50} tamam")
        self.assertEqual((kabul.durum, kabul.uzak_ref, kabul.alis), (Gonderim.KABUL, "98765", TL("12.50")))
        red = kntryeni.gonderim_coz("_HATA:Yetersiz bakiye")
        self.assertEqual((red.durum, red.mesaj), (Gonderim.RED, "Yetersiz bakiye"))
        self.assertEqual(kntryeni.gonderim_coz("???").durum, Gonderim.BELIRSIZ)
        self.assertEqual(kntryeni.sorgu_coz("98765 [1] ok").durum, Sorgu.BASARILI)
        self.assertEqual(kntryeni.sorgu_coz("98765 [2] iptal").durum, Sorgu.IPTAL)
        self.assertEqual(kntryeni.sorgu_coz("98765 [0]").durum, Sorgu.ISLEMDE)

    def test_adres_semasi(self):
        s = Saglayici(ad="x", tur="znet", adres="ornek.com/", kullanici_adi="a", sifre="b")
        self.assertEqual(s.adaptor().taban(), "http://ornek.com")
        s.adres = "https://ornek.com"
        self.assertEqual(s.adaptor().taban(), "https://ornek.com")


class BayiApiTestleri(Temel):
    def setUp(self):
        super().setUp()
        self.erisim = ApiErisimi.objects.create(kullanici=self.bayi)
        self.sifre = self.erisim.yeni_anahtar()

    def servis(self, **kw):
        veri = {
            "bayi_kodu": "5321112233", "sifre": self.sifre, "operator": "Vodafone", "tip": "ses",
            "kontor": "100.00", "gsmno": "5329998877", "tekilnumara": "777", **kw,
        }
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.get(reverse("kontor:api-servis"), veri).content.decode()

    def kontrol(self, ref="777", sifre=None):
        return self.client.get(
            reverse("kontor:api-kontrol"),
            {"bayi_kodu": "5321112233", "sifre": sifre or self.sifre, "tekilnumara": ref},
        ).content.decode()

    def test_bayi_kodu_varsayilan_telefon(self):
        self.assertEqual(self.erisim.bayi_kodu, "5321112233")
        self.assertNotIn(self.sifre, self.erisim.anahtar_ozeti)

    def test_siparis_ve_sonuc(self):
        self.assertEqual(self.servis(), "OK|1|Talebiniz işleme alındı.|110.00")
        self.assertEqual(self.bakiye(), TL("390.00"))
        islem = Islem.objects.get()
        self.assertEqual((islem.kanal, islem.bayi_ref), (Kanal.API, "777"))
        self.assertEqual(self.kontrol(), "2:islemde:0")
        _ayar("Bir", sorgu="basarili", mesaj="Yüklendi")
        Islem.objects.update(son_sorgu=None)
        self.assertEqual(self.kontrol(), "1:Yüklendi:110.00")

    def test_tam_kontor_bayi_programinin_kodunu_degistirmez(self):
        # Bayi programı kategoriyi yine tip koduyla (ses) bulur; sağlayıcıya tam gider.
        self.kategori.tam_kontor = True
        self.kategori.save()
        self.assertTrue(self.servis().startswith("OK|1|"))
        self.assertEqual(DURUM["Bir"]["gonderilen"][0][4], "tam")

    def test_ayni_referans_ikinci_yukleme_yapmaz(self):
        self.servis()
        self.assertEqual(self.servis(), "OK|1|Talebiniz işleme alındı.|110.00")
        self.assertEqual(Islem.objects.count(), 1)
        self.assertEqual(len(DURUM["Bir"]["gonderilen"]), 1)
        self.assertEqual(self.bakiye(), TL("390.00"))

    def test_ayni_referans_baska_numarayla_reddedilir(self):
        self.servis()
        self.assertTrue(self.servis(gsmno="5320000000").startswith("OK|3|"))
        self.assertEqual(Islem.objects.count(), 1)

    def test_hatali_sifre(self):
        self.assertEqual(self.servis(sifre="yanlis"), "OK|3|Hatalı bayi kodu veya şifre.|0.00")
        self.assertEqual(self.kontrol(sifre="yanlis"), "3:Hatalı bayi kodu veya şifre:0")
        self.assertFalse(Islem.objects.exists())

    def test_hesap_parolasi_api_sifresi_degildir(self):
        self.assertTrue(self.servis(sifre="parola12345").startswith("OK|3|Hatalı"))

    def test_kapali_erisim(self):
        self.erisim.aktif = False
        self.erisim.save()
        self.assertTrue(self.servis().startswith("OK|3|Hatalı"))

    def test_tanimsiz_paket_ve_bakiye(self):
        self.assertTrue(self.servis(kontor="999").startswith("OK|3|Tanımsız paket"))
        self.cuzdan.bakiye = TL("10")
        self.cuzdan.save()
        cevap = self.servis(tekilnumara="778")
        self.assertTrue(cevap.startswith("OK|3|Bakiyen"), cevap)

    def test_iptal_sonucu(self):
        Rota.objects.filter(saglayici=self.iki).delete()
        _ayar("Bir", sorgu="iptal")
        # Program kabulü alır, operatörün iptalini sonuç sorgusunda öğrenir.
        self.assertTrue(self.servis().startswith("OK|1|"))
        self.assertTrue(self.kontrol().startswith("3:"))
        self.assertEqual(self.bakiye(), TL("500.00"))

    def test_gonderilemeyen_programa_islemde_gorunur(self):
        _ayar("Bir", gonderim="red")
        _ayar("İki", gonderim="red")
        self.assertTrue(self.servis().startswith("OK|1|"))
        self.assertEqual(self.kontrol(), "2:islemde:0")

    def test_bayiye_gizli_paket_programa_satilmaz(self):
        Paket.objects.filter(pk=self.paket.pk).update(bayiye_gorunur=False)
        self.assertTrue(self.servis().startswith("OK|3|"))
        self.assertEqual(self.bakiye(), TL("500.00"))

    def test_askida_bayiye_islemde_gorunur(self):
        _ayar("Bir", gonderim="zaman")
        self.servis()
        self.assertEqual(self.kontrol(), "2:islemde:0")

    def test_bilinmeyen_referans(self):
        self.assertTrue(self.kontrol("yok").startswith("3:"))


class EkranTestleri(Temel):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.bayi)

    def test_kategori_ve_paket_ekranlari(self):
        yanit = self.client.get(reverse("kontor:kategoriler"))
        self.assertContains(yanit, "Vodafone Paket")
        yanit = self.client.get(self.kategori.get_absolute_url())
        self.assertContains(yanit, "Kolay Paket 15")
        self.assertContains(yanit, "1.000 DK · 15 GB · 30 gün")
        yanit = self.client.get(reverse("kontor:paket", args=[self.kategori.slug, "100"]))
        self.assertContains(yanit, 'name="islem_anahtari"')

    def test_yukle_ve_sonuc_sayfasi(self):
        with self.captureOnCommitCallbacks(execute=True):
            yanit = self.client.post(
                reverse("kontor:yukle", args=[self.kategori.slug, "100"]),
                {"hedef": "0532 999 88 77", "islem_anahtari": "a1"},
            )
        islem = Islem.objects.get()
        self.assertRedirects(yanit, islem.get_absolute_url(), fetch_redirect_response=False)
        yanit = self.client.get(islem.get_absolute_url())
        self.assertContains(yanit, "Yükleniyor")
        self.assertContains(yanit, "hx-get")
        _ayar("Bir", sorgu="basarili", mesaj="PIN-ABCD")
        Islem.objects.update(son_sorgu=None)
        yanit = self.client.get(reverse("kontor:islem-durum", args=[islem.siparis.referans_no]))
        self.assertContains(yanit, "PIN-ABCD")
        self.assertNotContains(yanit, "hx-get")

    def test_hatali_numara_sebebini_yazar_numara_kaybolmaz(self):
        yanit = self.client.post(
            reverse("kontor:yukle", args=[self.kategori.slug, "100"]), {"hedef": "123"}, follow=True
        )
        self.assertContains(yanit, "10 haneli")
        self.assertContains(yanit, 'value="123"')

    def test_bakiye_yetmezse_dugme_yerine_sebep(self):
        self.cuzdan.bakiye = TL("5")
        self.cuzdan.save()
        yanit = self.client.get(reverse("kontor:paket", args=[self.kategori.slug, "100"]))
        self.assertContains(yanit, "Bakiyen bu pakete yetmiyor")

    def test_baskasinin_islemi_404(self):
        islem = self.yukle()
        baska = User.objects.create_user("5320000000", password="x")
        self.client.force_login(baska)
        self.assertEqual(self.client.get(islem.get_absolute_url()).status_code, 404)

    def test_kontor_siparisi_magaza_listesinde_gorunmez(self):
        self.yukle()
        yanit = self.client.get(reverse("magaza:siparislerim"))
        self.assertNotContains(yanit, "Kolay Paket 15")

    def test_arama(self):
        self.yukle()
        yanit = self.client.get(reverse("kontor:islemler"), {"q": "0532 999 88 77"})
        self.assertContains(yanit, "0532 999 88 77")


@override_settings(KONTOR_ARKA_PLAN=False, KONTOR_ATOMIK_DENETIMI=False)
class YonetimTestleri(Temel):
    def setUp(self):
        super().setUp()
        self.yonetici = User.objects.create_superuser("yonetici", password="x")
        self.client.force_login(self.yonetici)

    def test_zarardaki_paket_kirmizi_ve_suzgecte(self):
        diger = Paket.objects.create(kategori=self.kategori, kod="200", ad="Karli Paket", satis_fiyati=TL("150"))
        Rota.objects.create(paket=diger, saglayici=self.bir, sira=1, alis_fiyati=TL("100"))
        adres = reverse("admin:kontor_paket_changelist")
        self.assertNotContains(self.client.get(adres), "data-zarar")
        Rota.objects.filter(paket=self.paket, saglayici=self.bir).update(alis_fiyati=TL("120"))  # satış 110
        self.assertContains(self.client.get(adres), "data-zarar hidden", count=1)
        yanit = self.client.get(adres, {"zarar": "evet"})
        self.assertContains(yanit, "Kolay Paket 15")
        self.assertNotContains(yanit, "Karli Paket")
        # Gruplu: grubun net fiyatı alışın altındaysa zarardadır; süzgeç ve satır aynı kural.
        grup = FiyatGrubu.objects.create(ad="Perakende", varsayilan=True)
        PaketFiyati.objects.create(paket=diger, grup=grup, fiyat=TL("90"))
        PaketFiyati.objects.create(paket=self.paket, grup=grup, fiyat=TL("130"))
        yanit = self.client.get(adres, {"zarar": "evet"})
        self.assertContains(yanit, "Karli Paket")
        self.assertNotContains(yanit, "Kolay Paket 15")
        self.assertContains(yanit, "data-zarar hidden", count=1)

    def test_karar_ekrani_ve_iptal(self):
        _ayar("Bir", gonderim="zaman")
        islem = self.yukle()
        adres = reverse("admin:kontor_islem_karar", args=[islem.pk])
        yanit = self.client.get(adres)
        self.assertContains(yanit, "Bu işlem askıda")
        self.assertEqual(self.bakiye(), TL("390.00"))  # GET hiçbir şey yapmaz
        self.client.post(adres, {"karar": "iptal", "mesaj": "Numara yanlış"})
        islem.refresh_from_db()
        self.assertEqual(islem.durum, IslemDurumu.IPTAL)
        self.assertEqual(self.bakiye(), TL("500.00"))

    def test_karar_ekraninda_giden_istek_ve_gelen_cevap(self):
        from unittest import mock

        class Yanit:
            headers = mock.Mock(get_content_charset=lambda: "utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b"OK|3|Aktif Kontor VodafoneSes8401|0.00|"

        Saglayici.objects.filter(pk=self.bir.pk).update(tur="znet", sifre="gizli-sifre")
        _ayar("İki", gonderim="red")
        with mock.patch("urllib.request.urlopen", return_value=Yanit()) as urlopen:
            islem = self.yukle()
        self.assertEqual(islem.durum, IslemDurumu.ASKIDA)
        self.assertIn("gizli-sifre", urlopen.call_args[0][0].full_url)  # gerçek istekte şifre var

        deneme = islem.denemeler.get(saglayici=self.bir)
        self.assertEqual(
            deneme.gonderim_istegi,
            f"GET http://bir.test/servis/tl_servis.php?bayi_kodu=u&sifre=***&operator={self.kategori.api_operator}"
            f"&tip={self.kategori.api_tip}&kontor={self.paket.kod}&gsmno={islem.hedef}&tekilnumara={deneme.ref}",
        )
        yanit = self.client.get(reverse("admin:kontor_islem_karar", args=[islem.pk]))
        from django.utils.html import escape

        self.assertContains(yanit, escape(deneme.gonderim_istegi))
        self.assertContains(yanit, "OK|3|Aktif Kontor VodafoneSes8401|0.00|")
        self.assertContains(yanit, "gönderilemedi")
        self.assertContains(yanit, "karşı site kodu girilmemiş")
        self.assertNotContains(yanit, "gizli-sifre")

    def test_listeler_acilir(self):
        self.yukle()
        for ad in ("islem", "paket", "kategori", "saglayici", "apierisimi", "fiyatgrubu"):
            yanit = self.client.get(reverse(f"admin:kontor_{ad}_changelist"))
            self.assertEqual(yanit.status_code, 200, ad)
        islem = Islem.objects.get()
        self.assertEqual(self.client.get(reverse("admin:kontor_islem_change", args=[islem.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin:kontor_paket_change", args=[self.paket.pk])).status_code, 200)

    def test_islem_listesinde_paket_kodu_ve_giden_kod(self):
        _ayar("Bir", gonderim="red")  # İki'ye rotanın kendi kodu (V100) gider
        self.yukle()
        yanit = self.client.get(reverse("admin:kontor_islem_changelist"))
        self.assertContains(yanit, f"Kod {self.paket.kod} → giden V100")

    def test_magaza_yonetiminde_kontor_siparisi_yok(self):
        islem = self.yukle()
        yanit = self.client.get(reverse("admin:magaza_siparis_change", args=[islem.siparis.pk]))
        self.assertNotEqual(yanit.status_code, 200)

    def test_fiyat_gruplari_ve_alislar_ekrani(self):
        toptan = FiyatGrubu.objects.create(ad="Toptan")
        FiyatGrubu.objects.create(ad="Perakende", varsayilan=True)
        PaketFiyati.objects.create(paket=self.paket, grup=toptan, fiyat=TL("105.00"))
        yanit = self.client.get(reverse("admin:kontor_paket_changelist"))
        self.assertContains(yanit, "Toptan: <b>105.00</b>")
        self.assertContains(yanit, "Perakende: <b>—</b>")
        self.assertEqual(self.client.get(reverse("admin:kontor_fiyatgrubu_changelist")).status_code, 200)
        yanit = self.client.get(
            reverse("admin:kontor_saglayici_change", args=[self.iki.pk]) + f"?operator={self.operator.pk}"
        )
        self.assertContains(yanit, 'value="V100"')
        # Varsayılan grup varken grupsuz fiyat alanı formda yok.
        yanit = self.client.get(reverse("admin:kontor_paket_change", args=[self.paket.pk]))
        self.assertNotContains(yanit, 'name="satis_fiyati"')

    def test_paket_sayfasi_neden_satilmadigini_yazar(self):
        adres = reverse("admin:kontor_paket_change", args=[self.paket.pk])
        self.assertContains(self.client.get(adres), "Evet")
        self.paket.rotalar.all().delete()
        yanit = self.client.get(adres)
        self.assertContains(yanit, "askıya düşer")
        FiyatGrubu.objects.create(ad="Parakende")
        self.assertContains(self.client.get(adres), "Hiçbir fiyat grubunda Bayi Satış Tutarı yazılı değil")

    def test_gorulen_paketlerde_en_yeni_ustte(self):
        from apps.kontor.models import GorulenPaket

        for kod in ("1", "2", "3"):
            GorulenPaket.objects.create(
                kaynak="vodafone", kod=kod, ad=f"P{kod}", kategori=self.kategori, son_gorulme=timezone.now()
            )
        yanit = self.client.get(reverse("admin:kontor_gorulenpaket_changelist"))
        self.assertEqual([g.kod for g in yanit.context["cl"].result_list], ["3", "2", "1"])

    def test_saglayici_sayfasinda_karsi_kod_ve_alis(self):
        adres = reverse("admin:kontor_saglayici_change", args=[self.bir.pk])
        # Operatör seçilmeden paket listesi gelmez.
        yanit = self.client.get(adres)
        self.assertContains(yanit, "Paketleri görmek için operatör seç")
        self.assertNotContains(yanit, f'name="kod_{self.paket.pk}"')
        yanit = self.client.get(adres + f"?operator={self.operator.pk}")
        self.assertContains(yanit, f'name="kod_{self.paket.pk}"')
        # Bizim kod yalnızca görünür; düzenlenecek alanı yok.
        self.assertNotContains(yanit, f'name="paket_kod_{self.paket.pk}"')
        yeni = Paket.objects.create(kategori=self.kategori, kod="200", ad="Yeni paket")
        kaydet = reverse("admin:kontor_saglayici_paketler", args=[self.bir.pk]) + f"?operator={self.operator.pk}"
        veri = {
            "paket": [self.paket.pk, yeni.pk],
            f"kod_{self.paket.pk}": "Z-100", f"alis_{self.paket.pk}": "98,50", f"gonder_{self.paket.pk}": "1",
            f"kod_{yeni.pk}": "Z-200", f"alis_{yeni.pk}": "40", f"gonder_{yeni.pk}": "1",
        }
        self.assertEqual(self.client.post(kaydet, veri).status_code, 302)
        rota = Rota.objects.get(paket=self.paket, saglayici=self.bir)
        self.assertEqual((rota.uzak_kod, rota.alis_fiyati, rota.aktif), ("Z-100", TL("98.50"), True))
        # Bağlı olmayan paket bu sağlayıcıya bağlandı, sıranın sonuna.
        yeni_rota = Rota.objects.get(paket=yeni, saglayici=self.bir)
        self.assertEqual((yeni_rota.uzak_kod, yeni_rota.alis_fiyati, yeni_rota.sira), ("Z-200", TL("40"), 1))
        # Karşı kod bizimkiyle aynıysa saklanmaz; Gönder kaldırılınca rota pasif.
        veri.update({f"kod_{self.paket.pk}": "100"})
        del veri[f"gonder_{self.paket.pk}"]
        self.client.post(kaydet, veri)
        rota.refresh_from_db()
        self.assertEqual((rota.uzak_kod, rota.aktif), ("", False))

    def test_paket_sayfasinda_karsi_kod_duzenlenmez(self):
        yanit = self.client.get(reverse("admin:kontor_paket_change", args=[self.paket.pk]))
        self.assertNotContains(yanit, 'name="rotalar-0-uzak_kod"')
        self.assertNotContains(yanit, 'name="rotalar-0-alis_fiyati"')

    def test_saglayicisiz_islem_karar_ekranindan_gonderilir(self):
        self.paket.rotalar.all().delete()
        islem = self.yukle()
        self.assertEqual(islem.durum, IslemDurumu.ASKIDA)
        adres = reverse("admin:kontor_islem_karar", args=[islem.pk])
        yanit = self.client.get(adres)
        self.assertContains(yanit, "bağlı değil")
        self.assertContains(yanit, "İki")
        self.client.post(adres, {"karar": "gonder", "saglayici": self.iki.pk})
        self.assertEqual(DURUM["İki"]["gonderilen"][-1][2], "100")  # paketin kendi kodu
        islem.refresh_from_db()
        self.assertEqual(islem.durum, IslemDurumu.ISLEMDE)

    def test_grup_sayfasi_bayi_satis_tutari(self):
        grup = FiyatGrubu.objects.create(ad="Toptan")
        adres = reverse("admin:kontor_fiyatgrubu_paketler", args=[grup.pk])
        # Grubun sayfası = paket fiyatları; ayrı bir form yok.
        yanit = self.client.get(reverse("admin:kontor_fiyatgrubu_change", args=[grup.pk]))
        self.assertRedirects(yanit, adres, fetch_redirect_response=False)
        yanit = self.client.get(adres)
        self.assertContains(yanit, "Bayi Satış Tutarı")
        self.assertNotContains(yanit, "Yöntem")
        alan = f"fiyat_{self.paket.pk}"
        self.assertEqual(self.client.post(adres, {alan: "444,15"}).status_code, 302)
        self.assertEqual(PaketFiyati.objects.get(grup=grup, paket=self.paket).fiyat, TL("444.15"))
        self.client.post(adres, {alan: "1.250,50"})
        self.assertEqual(PaketFiyati.objects.get(grup=grup).fiyat, TL("1250.50"))
        # Kutu boşaltılınca fiyat silinir, paket bu gruba satılmaz.
        self.client.post(adres, {alan: ""})
        self.assertFalse(PaketFiyati.objects.filter(grup=grup).exists())

    def test_grup_sayfasinda_operator_fiyati(self):
        from datetime import timedelta

        from apps.kontor.models import GorulenPaket

        simdi = timezone.now()
        GorulenPaket.objects.create(
            kaynak="x", kod=self.paket.kod, kategori=self.kategori, fiyat=TL("350.00"), son_gorulme=simdi - timedelta(days=2)
        )
        GorulenPaket.objects.create(
            kaynak="y", kod=self.paket.kod, kategori=self.kategori, fiyat=TL("359.90"), son_gorulme=simdi
        )
        grup = FiyatGrubu.objects.create(ad="Toptan")
        yanit = self.client.get(reverse("admin:kontor_fiyatgrubu_paketler", args=[grup.pk]))
        self.assertContains(yanit, 'data-operator="359.90"')  # en son görülen
        self.assertContains(yanit, "Operatör fiyatı + %")
        self.assertContains(yanit, "Operatör fiyatı (aynen)")

    def test_grup_ayarlari_ayni_sayfadan_kaydedilir(self):
        grup = FiyatGrubu.objects.create(ad="Perakende")
        adres = reverse("admin:kontor_fiyatgrubu_paketler", args=[grup.pk])
        yanit = self.client.post(adres, {"_grup": "1", "ad": "Parakende", "aciklama": "", "varsayilan": "on"})
        self.assertEqual(yanit.status_code, 302)
        grup.refresh_from_db()
        self.assertEqual((grup.ad, grup.varsayilan), ("Parakende", True))

    def test_grup_paket_fiyatlari_bozuk_deger_kaydetmez(self):
        grup = FiyatGrubu.objects.create(ad="Toptan")
        adres = reverse("admin:kontor_fiyatgrubu_paketler", args=[grup.pk])
        yanit = self.client.post(adres, {f"fiyat_{self.paket.pk}": "abc"})
        self.assertContains(yanit, "Rakam anlaşılamadı")
        self.assertFalse(PaketFiyati.objects.exists())

    def test_grup_paket_fiyatlari_suzulur_ve_sayfalanir(self):
        grup = FiyatGrubu.objects.create(ad="Toptan")
        for i in range(60):
            Paket.objects.create(kategori=self.kategori, kod=f"K{i}", ad=f"Ek paket {i}")
        adres = reverse("admin:kontor_fiyatgrubu_paketler", args=[grup.pk])
        yanit = self.client.get(adres)
        self.assertContains(yanit, "1 / 2 · 61 paket")
        yanit = self.client.get(adres + "?q=Kolay")
        self.assertContains(yanit, "Kolay Paket 15")
        self.assertNotContains(yanit, "Ek paket 1<")
        # POST yalnızca o sayfadaki paketleri yazar: 2. sayfadaki kural korunur.
        ikinci = Paket.objects.order_by("sira", "ad").last()
        PaketFiyati.objects.create(paket=ikinci, grup=grup, fiyat=TL("5"))
        self.client.post(adres, {})
        self.assertTrue(PaketFiyati.objects.filter(paket=ikinci).exists())

    def test_api_sifresi_post_ile_uretilir(self):
        erisim = ApiErisimi.objects.create(kullanici=self.bayi)
        adres = reverse("admin:kontor_apierisimi_sifre", args=[erisim.pk])
        self.client.get(adres)
        erisim.refresh_from_db()
        self.assertEqual(erisim.anahtar_ozeti, "")
        yanit = self.client.post(adres)
        erisim.refresh_from_db()
        self.assertTrue(erisim.anahtar_ozeti)
        self.assertContains(yanit, "Bayi kodu: 5321112233")


class AtomikDenetimTesti(Temel):
    @override_settings(KONTOR_ATOMIK_DENETIMI=True)
    def test_transaction_icinden_gonderim_reddedilir(self):
        self.assertTrue(connection.in_atomic_block)
        with self.assertRaises(RuntimeError):
            with self.captureOnCommitCallbacks(execute=True):
                yukleme_baslat(self.bayi, self.paket, "5329998877")


# -- Numara sorgusu --------------------------------------------------------

from apps.kontor.sorgu import SorguHatasi, SorguPaketi, kaynak  # noqa: E402
from apps.kontor.sorgu import SorguSonucu as NumaraSonucu  # noqa: E402

SORGU = {"cagri": 0, "hata": False}


@kaynak("test-sorgu", "Test sorgusu")
def _test_sorgusu(numara, *, sahip=False):
    SORGU["cagri"] += 1
    SORGU["sahip_istendi"] = sahip
    if SORGU["hata"]:
        raise SorguHatasi("Kaynak cevap vermedi.")
    paketler = [
        SorguPaketi(kod="100", ad="Kolay 15", fiyat=SORGU.get("fiyat_100")),
        SorguPaketi(kod="999", ad="Bizde yok", gun=7, fiyat=SORGU.get("fiyat", TL("50"))),
    ]
    return NumaraSonucu(paketler, sahip="Ah*** Yı***" if sahip else "")


class SorguTestleri(Temel):
    def setUp(self):
        super().setUp()
        from django.core.cache import caches

        caches["kontor_sorgu"].clear()
        SORGU.update(cagri=0, hata=False, fiyat_100=None)
        self.kategori.sorgu_kaynagi = "test-sorgu"
        self.kategori.save()
        self.client.force_login(self.bayi)
        self.adres = reverse("kontor:sorgu", args=[self.kategori.slug])

    def test_eslesen_paket_fiyatla_ve_numarayla_gelir(self):
        yanit = self.client.get(self.adres, {"hedef": "0532 999 88 77"})
        self.assertContains(yanit, "Kolay Paket 15")
        self.assertContains(yanit, "110,00")
        self.assertContains(yanit, "?hedef=5329998877")
        # Bizde satışta olmayan paket bayiye gösterilmez.
        self.assertNotContains(yanit, "Bizde yok")
        self.assertNotContains(yanit, "satışta olmayan")

    def _fiyat_degisimi_mesajlari(self, *numaralar):
        from unittest.mock import patch

        with override_settings(TELEGRAM_BOT_TOKEN="x:y", TELEGRAM_SOHBET_ID="@g", TELEGRAM_ARKA_PLAN=False), patch(
            "apps.bildirim.telegram._gonder", return_value=(True, "")
        ) as gonder:
            for numara in numaralar:
                with self.captureOnCommitCallbacks(execute=True):
                    self.client.get(self.adres, {"hedef": numara})
        return [c.args[0] for c in gonder.call_args_list]

    def test_bizdeki_paketin_operator_fiyati_degisince_telegrama_gider(self):
        self.addCleanup(SORGU.pop, "fiyat", None)
        SORGU.update(fiyat_100=TL("300"), fiyat=TL("50"))
        self.assertEqual(self._fiyat_degisimi_mesajlari("5329998877"), [])  # ilk görülme
        # 999 bizde yok: onun fiyatı da değişti ama bildirilmez.
        SORGU.update(fiyat_100=TL("320"), fiyat=TL("60"))
        # Başka numara aynı değişimi görürse ikinci mesaj gitmez (günde bir kez).
        (metin,) = self._fiyat_degisimi_mesajlari("5329998866", "5329998855")
        self.assertIn("Operatör fiyatı değişti", metin)
        self.assertIn("Kolay Paket 15", metin)
        self.assertIn("300.00 → 320.00 ₺ (+20.00)", metin)
        self.assertIn("Alışımız:</b> 100.00 ₺", metin)
        self.assertNotIn("Bizde yok", metin)
        self.assertNotIn("Zararda", metin)

    def test_fiyat_degisimi_zarardaki_grubu_soyler(self):
        SORGU["fiyat_100"] = TL("300")
        self._fiyat_degisimi_mesajlari("5329998877")
        Rota.objects.filter(paket=self.paket, saglayici=self.bir).update(alis_fiyati=TL("120"))  # satış 110
        SORGU["fiyat_100"] = TL("330")
        (metin,) = self._fiyat_degisimi_mesajlari("5329998866")
        self.assertIn("Zararda:</b> Satış 110.00 ₺ &lt; alış 120.00 ₺", metin)

    def test_pasif_paketin_fiyat_degisimi_bildirilmez(self):
        SORGU["fiyat_100"] = TL("300")
        self._fiyat_degisimi_mesajlari("5329998877")
        Paket.objects.filter(pk=self.paket.pk).update(aktif=False)
        SORGU["fiyat_100"] = TL("320")
        self.assertEqual(self._fiyat_degisimi_mesajlari("5329998866"), [])

    def test_tam_kontorde_sorgu_yapilmaz(self):
        # Tam kontörün alternatifi yok; sorgu operatöre boşuna gitmek olurdu.
        self.kategori.tam_kontor = True
        self.kategori.gonderim_oncesi_sorgu = True
        self.kategori.save()
        self.assertNotContains(self.client.get(self.kategori.get_absolute_url()), self.adres)
        self.assertContains(self.client.get(self.adres, {"hedef": "5329998877"}), "Tam kontörde numara sorgusu yapılmaz")
        islem = self.yukle("5329998877")
        self.assertEqual(SORGU["cagri"], 0)
        self.assertEqual(islem.plan, [self.paket.pk])
        self.assertEqual(DURUM["Bir"]["gonderilen"][0][4], "tam")

    def test_ayni_numara_onbellekten(self):
        self.client.get(self.adres, {"hedef": "5329998877"})
        self.client.get(self.adres, {"hedef": "5329998877"})
        self.assertEqual(SORGU["cagri"], 1)

    def test_yenile_onbellegi_atlar_ama_dakikada_bir(self):
        from apps.kontor.services import _onbellek, _sorgu_anahtari

        self.client.get(self.adres, {"hedef": "5329998877"})
        self.client.get(self.adres, {"hedef": "5329998877", "yenile": "1"})
        self.assertEqual(SORGU["cagri"], 1)  # bir dakika dolmadı, eldeki gösterilir
        anahtar = _sorgu_anahtari("test-sorgu", "5329998877", True)
        kayit = _onbellek().get(anahtar)
        kayit["zaman"] -= timedelta(minutes=2)
        _onbellek().set(anahtar, kayit)
        yanit = self.client.get(self.adres, {"hedef": "5329998877", "yenile": "1"})
        self.assertEqual(SORGU["cagri"], 2)
        self.assertContains(yanit, "Yenile")
        self.assertContains(yanit, "Son sorgu")

    def test_basarili_yuklemeden_sonra_onbellek_silinir(self):
        self.client.get(self.adres, {"hedef": "5329998877"})
        islem = self.yukle("5329998877")
        _ayar("Bir", sorgu="basarili")
        with self.captureOnCommitCallbacks(execute=True):
            isle(islem.pk, zorla=True)
        self.client.get(self.adres, {"hedef": "5329998877"})
        self.assertEqual(SORGU["cagri"], 2)

    def test_hata_satisi_durdurmaz(self):
        SORGU["hata"] = True
        yanit = self.client.get(self.adres, {"hedef": "5329998877"})
        self.assertContains(yanit, "Kaynak cevap vermedi.")
        self.assertContains(self.client.get(self.kategori.get_absolute_url()), "Kolay Paket 15")

    def test_hatali_numara(self):
        yanit = self.client.get(self.adres, {"hedef": "12"})
        self.assertContains(yanit, "10 haneli")
        self.assertEqual(SORGU["cagri"], 0)

    def test_hat_sahibi_gosterilir_ama_saklanmaz(self):
        yanit = self.client.get(self.adres, {"hedef": "5329998877"})
        self.assertContains(yanit, "Ah*** Yı***")
        self.assertTrue(SORGU["sahip_istendi"])
        from apps.kontor.models import GorulenPaket

        self.assertFalse(GorulenPaket.objects.filter(ad__contains="Ah***").exists())

    def test_ayar_kapaliysa_sahip_istenmez(self):
        self.kategori.sorgu_sahibi_goster = False
        self.kategori.save()
        yanit = self.client.get(self.adres, {"hedef": "5329998877"})
        self.assertNotContains(yanit, "Hat sahibi")
        self.assertFalse(SORGU["sahip_istendi"])

    def test_gorulen_paketler_takip_edilir(self):
        from django.core.cache import caches

        from apps.kontor.models import GorulenPaket
        from apps.rozetler import yeni_kontor_paketleri

        self.client.get(self.adres, {"hedef": "5329998877"})
        self.assertEqual(set(GorulenPaket.objects.values_list("kod", flat=True)), {"100", "999"})
        self.assertEqual(yeni_kontor_paketleri(None), "1")  # 100 katalogda, 999 yeni

        caches["kontor_sorgu"].clear()
        SORGU["fiyat"] = TL("60")
        self.client.get(self.adres, {"hedef": "5329998877"})
        yeni = GorulenPaket.objects.get(kod="999")
        self.assertEqual((yeni.fiyat, yeni.onceki_fiyat), (TL("60"), TL("50")))
        self.assertEqual(GorulenPaket.objects.filter(kod="999").count(), 1)

        yeni.yok_say = True
        yeni.save()
        self.assertEqual(yeni_kontor_paketleri(None), "")

    def test_onbellekten_gelen_sonuc_sayilmaz(self):
        from apps.kontor.models import GorulenPaket

        self.client.get(self.adres, {"hedef": "5329998877"})
        ilk = GorulenPaket.objects.get(kod="999").son_gorulme
        self.client.get(self.adres, {"hedef": "5329998877"})
        self.assertEqual(GorulenPaket.objects.get(kod="999").son_gorulme, ilk)

    def test_ayni_gun_degismeyen_paket_yazilmaz(self):
        from datetime import timedelta

        from apps.kontor.models import GorulenPaket

        self.client.get(self.adres, {"hedef": "5329998877"})
        ilk = GorulenPaket.objects.get(kod="999").son_gorulme
        from apps.kontor.services import gorulenleri_yaz

        kayit = GorulenPaket.objects.get(kod="999")
        paketler = [SorguPaketi(kod="999", ad=kayit.ad, aciklama=kayit.aciklama, fiyat=kayit.fiyat)]
        with self.assertNumQueries(1):  # yalnızca okuma
            gorulenleri_yaz("test-sorgu", self.kategori, paketler)
        self.assertEqual(GorulenPaket.objects.get(kod="999").son_gorulme, ilk)
        # Dünden kalmışsa tarih güncellenir.
        GorulenPaket.objects.filter(kod="999").update(son_gorulme=ilk - timedelta(days=1))
        gorulenleri_yaz("test-sorgu", self.kategori, paketler)
        self.assertEqual(timezone.localdate(GorulenPaket.objects.get(kod="999").son_gorulme), timezone.localdate())

    def test_kataloga_ekle(self):
        from apps.kontor.models import GorulenPaket

        self.client.get(self.adres, {"hedef": "5329998877"})
        yonetici = User.objects.create_superuser("yonetici", password="x")
        self.client.force_login(yonetici)
        gorulen = GorulenPaket.objects.get(kod="999")
        self.assertEqual(self.client.get(reverse("admin:kontor_gorulenpaket_changelist"), {"katalog": "yeni"}).status_code, 200)
        yanit = self.client.post(reverse("admin:kontor_gorulenpaket_ekle", args=[gorulen.pk]))
        paket = Paket.objects.get(kategori=self.kategori, kod="999")
        self.assertRedirects(yanit, reverse("admin:kontor_paket_change", args=[paket.pk]), fetch_redirect_response=False)
        self.assertEqual(paket.ad, "Bizde yok")
        # Fiyatsız: bayiye görünmez.
        self.assertNotIn(paket, satistaki_paketler(self.kategori, self.bayi))

    def test_kaynaksiz_kategoride_kutu_yok(self):
        self.kategori.sorgu_kaynagi = ""
        self.kategori.save()
        self.assertNotContains(self.client.get(self.kategori.get_absolute_url()), "Sorgula")


class VodafoneSorguTestleri(TestCase):
    """Vodafone adaptörü: istemci sahte, ağa çıkılmaz."""

    CEVAP = {
        "kolayPackCategory": [
            {
                "description": "İnternet",
                "kolayPacks": [
                    {"id": "/Prepaid/KolayPack/KP_INTEGRATED_OFFER_7", "reasonCode": "17776",
                     "description": "Kolay Paket 15", "detail": "15 GB 30 gün",
                     "usageFee": {"value": 349.9, "unit": "TL"}},
                    # reasonCode'suz paket atlanır; id'ye (Vodafone'un iç adı) düşülmez.
                    {"id": "BKPM046", "description": "Kodsuz"},
                ],
            }
        ]
    }

    def test_cevap_cozulur(self):
        from apps.kontor.sorgu.vodafone import paketleri_coz

        (paket,) = paketleri_coz(self.CEVAP)
        self.assertEqual((paket.kod, paket.ad, paket.aciklama), ("17776", "Kolay Paket 15", "15 GB 30 gün"))
        self.assertEqual(paket.fiyat, TL("349.9"))
        self.assertEqual(paketleri_coz({}), [])

    def test_paylasilan_kod_paket_adiyla_ayrilir(self):
        """5G Tam Senlik'in dördü de 13239: tek pakete çökmesin."""
        from apps.kontor.sorgu.vodafone import paketleri_coz

        def paket(kod, ad, fiyat, id_):
            return {"id": id_, "reasonCode": kod, "description": ad, "usageFee": {"value": fiyat}}

        cevap = {"kolayPackCategory": [
            {"description": "Senin için seçtiğimiz paket", "kolayPacks": [
                paket("13239", "5G Tam Senlik 20 GB", "930.0", "/Prepaid/KolayPack/KP_INTEGRATED_OFFER_2"),
                paket("17960", "5G Haftalik Sınırsız TikTok", "129.0", "BKPM041"),
            ]},
            {"description": "Kullanımına Özel Paketler", "kolayPacks": [
                paket("13239", "5G Tam Senlik 40 GB", "1300.0", "/Prepaid/KolayPack/KP_INTEGRATED_OFFER_1"),
                paket("13239", "5G Tam Senlik 15 GB", "830.0", "/Prepaid/KolayPack/KP_INTEGRATED_OFFER_3"),
            ]},
        ]}
        self.assertEqual(
            [(p.kod, p.fiyat) for p in paketleri_coz(cevap)],
            [
                ("13239-5g-tam-senlik-20-gb-930", TL("930.0")),
                ("17960", TL("129.0")),  # tekil kod olduğu gibi kalır
                ("13239-5g-tam-senlik-40-gb-1300", TL("1300.0")),
                ("13239-5g-tam-senlik-15-gb-830", TL("830.0")),
            ],
        )
        # Numarada tek başına çıksa da kod aynı kalır (bilinen paylaşılan kod).
        tek = {"kolayPackCategory": [{"kolayPacks": [paket("13239", "5G Tam Senlik 20 GB", "930", "X")]}]}
        self.assertEqual(paketleri_coz(tek)[0].kod, "13239-5g-tam-senlik-20-gb-930")
        # Kişiye özel fiyat: aynı paket başka numarada başka tutarla ayrı pakettir.
        baska = {"kolayPackCategory": [{"kolayPacks": [paket("13239", "5G Tam Senlik 30 GB", "1150.0", "Y")]}]}
        self.assertEqual(paketleri_coz(baska)[0].kod, "13239-5g-tam-senlik-30-gb-1150")
        kusurlu = {"kolayPackCategory": [{"kolayPacks": [paket("13239", "5G Tam Senlik 1 GB", "419.90", "Z")]}]}
        self.assertEqual(paketleri_coz(kusurlu)[0].kod, "13239-5g-tam-senlik-1-gb-419.9")

    def test_token_ve_paket_adimlari(self):
        from unittest import mock

        from apps.kontor.sorgu import kaynak_getir

        with mock.patch("apps.kontor.sorgu.vodafone_istemci.VodafoneSorgu") as sinif:
            istemci = sinif.return_value
            istemci.get_public_token.return_value = {"publicToken": "PUB-KOLAY-x"}
            istemci.get_kolay_packs.return_value = self.CEVAP
            sonuc = kaynak_getir("vodafone").fonksiyon("5321234567")
        istemci.get_public_token.assert_called_once_with("5321234567")
        istemci.get_kolay_packs.assert_called_once_with("PUB-KOLAY-x")
        istemci.get_masked_user_name.assert_not_called()  # istenmediyse ad çekilmez
        self.assertEqual([p.kod for p in sonuc.paketler], ["17776"])
        self.assertEqual(sonuc.sahip, "")

    def test_sahip_istenirse_maskeli_ad(self):
        from unittest import mock

        from apps.kontor.sorgu import kaynak_getir

        with mock.patch("apps.kontor.sorgu.vodafone_istemci.VodafoneSorgu") as sinif:
            istemci = sinif.return_value
            istemci.get_public_token.return_value = {"publicToken": "PUB-KOLAY-x"}
            istemci.get_kolay_packs.return_value = self.CEVAP
            istemci.get_masked_user_name.return_value = {
                "result": {"result": "SUCCESS"}, "maskedUserName": " Ah*** Yı*** "
            }
            self.assertEqual(kaynak_getir("vodafone").fonksiyon("5321234567", sahip=True).sahip, "Ah*** Yı***")
            # Ad alınamazsa paket sonucu yine gelir.
            istemci.get_masked_user_name.side_effect = ValueError("bozuk")
            sonuc = kaynak_getir("vodafone").fonksiyon("5321234567", sahip=True)
            self.assertEqual((sonuc.sahip, len(sonuc.paketler)), ("", 1))

    def test_token_yoksa_sebep_yazilir(self):
        from unittest import mock

        from apps.kontor.sorgu import kaynak_getir

        with mock.patch("apps.kontor.sorgu.vodafone_istemci.VodafoneSorgu") as sinif:
            sinif.return_value.get_public_token.return_value = {}
            with self.assertRaisesMessage(SorguHatasi, "Vodafone'da olmayabilir"):
                kaynak_getir("vodafone").fonksiyon("5321234568")

    def test_ag_hatasi_sorgu_hatasina_cevrilir(self):
        from unittest import mock

        import requests

        from apps.kontor.sorgu import kaynak_getir

        with mock.patch("apps.kontor.sorgu.vodafone_istemci.VodafoneSorgu") as sinif:
            sinif.return_value.get_public_token.side_effect = requests.ConnectionError("yok")
            with self.assertRaisesMessage(SorguHatasi, "ulaşılamadı"):
                kaynak_getir("vodafone").fonksiyon("5321234567")




class PaylasilanKodTemizligiTestleri(Temel):
    """0020: düz 13239 koduyla açılmış eski kayıtlar yeni koda taşınır."""

    def temizle(self):
        import importlib

        from django.apps import apps

        importlib.import_module("apps.kontor.migrations.0020_paylasilan_kod_temizligi").temizle(apps, None)

    def test_esi_olan_eski_paket_birlesir_esi_olmayan_kod_degistirir(self):
        from apps.kontor.models import GorulenPaket

        grup = FiyatGrubu.objects.create(ad="Parakende")
        eski = Paket.objects.create(kategori=self.kategori, kod="13239", ad="5G Tam Senlik 1 GB", tavsiye_fiyati=TL("420"))
        Rota.objects.create(paket=eski, saglayici=self.iki, alis_fiyati=TL("400"))
        PaketFiyati.objects.create(paket=eski, grup=grup, fiyat=TL("415"))
        yeni = Paket.objects.create(kategori=self.kategori, kod="13239-5g-tam-senlik-1-gb", ad="5G Tam Senlik 1 GB")
        Rota.objects.create(paket=yeni, saglayici=self.bir, alis_fiyati=TL("411.60"))
        # Başka kategoride eşi olmayan eski paket.
        diger = Kategori.objects.create(ad="Vodafone İnternet", operator=self.operator, api_operator="vodafone", api_tip="int")
        yalniz = Paket.objects.create(kategori=diger, kod="13239", ad="5G Tam Senlik 3 GB", satis_fiyati=TL("5"))
        GorulenPaket.objects.create(kaynak="vodafone", kod="13239", kategori=self.kategori, son_gorulme=timezone.now())

        self.temizle()

        self.assertFalse(Paket.objects.filter(pk=eski.pk).exists())  # işlemi yoktu: silindi
        self.assertEqual(
            sorted(yeni.rotalar.values_list("saglayici__ad", flat=True)), ["Bir", "İki"]
        )  # yenisinde olmayan sağlayıcı taşındı
        self.assertEqual(PaketFiyati.objects.get(paket=yeni, grup=grup).fiyat, TL("415"))
        yeni.refresh_from_db()
        self.assertEqual(yeni.tavsiye_fiyati, TL("420"))
        yalniz.refresh_from_db()
        self.assertEqual(yalniz.kod, "13239-5g-tam-senlik-3-gb")
        self.assertFalse(GorulenPaket.objects.filter(kod="13239").exists())

    def test_0021_tutarsiz_kod_gorulen_fiyatla_tasinir(self):
        import importlib

        from django.apps import apps

        from apps.kontor.models import GorulenPaket

        paket = Paket.objects.create(kategori=self.kategori, kod="13239-5g-tam-senlik-30-gb", ad="5G Tam Senlik 30 GB")
        Rota.objects.create(paket=paket, saglayici=self.bir, uzak_kod="KB30", alis_fiyati=TL("922.20"))
        GorulenPaket.objects.create(
            kaynak="vodafone", kod="13239-5g-tam-senlik-30-gb", kategori=self.kategori,
            fiyat=TL("1060.0"), onceki_fiyat=TL("1150"), son_gorulme=timezone.now(),
        )
        # Fiyatı hiç görülmemiş paket ve tekil kodlu paket olduğu gibi kalır.
        bilinmeyen = Paket.objects.create(kategori=self.kategori, kod="13239-5g-tam-senlik-3-gb", ad="3 GB")

        importlib.import_module("apps.kontor.migrations.0021_paylasilan_koda_tutar").tasi(apps, None)

        paket.refresh_from_db()
        self.assertEqual(paket.kod, "13239-5g-tam-senlik-30-gb-1060")
        self.assertEqual(paket.rotalar.get().uzak_kod, "KB30")  # karşı site kodu korunur
        gorulen = GorulenPaket.objects.get()
        self.assertEqual((gorulen.kod, gorulen.onceki_fiyat), ("13239-5g-tam-senlik-30-gb-1060", None))
        bilinmeyen.refresh_from_db()
        self.assertEqual(bilinmeyen.kod, "13239-5g-tam-senlik-3-gb")
        self.assertEqual(self.paket.kod, "100")

    def test_islemi_olan_eski_paket_silinmez_gizlenir(self):
        eski = Paket.objects.create(kategori=self.kategori, kod="13239", ad="5G Tam Senlik 1 GB", satis_fiyati=TL("50"))
        Rota.objects.create(paket=eski, saglayici=self.bir)
        Paket.objects.create(kategori=self.kategori, kod="13239-5g-tam-senlik-1-gb", ad="5G Tam Senlik 1 GB")
        self.paket = eski
        self.yukle()
        self.temizle()
        eski.refresh_from_db()
        self.assertEqual((eski.aktif, eski.bayiye_gorunur), (False, False))

    def test_gorulenlerde_eklenen_ve_yeni_birlikte_gorunur(self):
        from apps.kontor.models import GorulenPaket

        GorulenPaket.objects.create(kaynak="x", kod=self.paket.kod, kategori=self.kategori, son_gorulme=timezone.now())
        GorulenPaket.objects.create(kaynak="x", kod="999", kategori=self.kategori, ad="Yeni paket", son_gorulme=timezone.now())
        yonetici = User.objects.create_superuser("yonetici", password="x")
        self.client.force_login(yonetici)
        yanit = self.client.get(reverse("admin:kontor_gorulenpaket_changelist"))
        self.assertContains(yanit, "✓ Eklendi")
        self.assertContains(yanit, "Kataloğa ekle")
        self.assertContains(yanit, "Yeni paket")

class BayiRotasiTestleri(Temel):
    """Bayinin kategorisine özel sağlayıcı: genel sıra yerine bu sıra."""

    def setUp(self):
        super().setUp()
        from apps.kontor.models import BayiRotasi

        self.BayiRotasi = BayiRotasi
        self.uc = Saglayici.objects.create(ad="Üç", tur="sahte", adres="uc.test", kullanici_adi="u", sifre="s")
        _ayar("Üç")

    def giden(self, ad):
        return [g[2] for g in DURUM[ad]["gonderilen"]]

    def test_ozel_saglayiciya_rotadaki_kodla_gider(self):
        self.BayiRotasi.objects.create(bayi=self.bayi, kategori=self.kategori, saglayici=self.iki)
        islem = self.yukle()
        self.assertEqual(islem.saglayici, self.iki)
        self.assertEqual(self.giden("İki"), ["V100"])  # paketin İki'deki karşı site kodu
        self.assertEqual(self.giden("Bir"), [])  # genel sıranın ilki denenmez

    def test_bagli_olmayan_saglayiciya_paketin_kodu_gider(self):
        self.BayiRotasi.objects.create(bayi=self.bayi, kategori=self.kategori, saglayici=self.uc)
        islem = self.yukle()
        self.assertEqual(islem.saglayici, self.uc)
        self.assertEqual(self.giden("Üç"), ["100"])

    def test_sirayla_denenir_genel_siraya_gecilmez(self):
        self.BayiRotasi.objects.create(bayi=self.bayi, kategori=self.kategori, saglayici=self.uc, sira=1)
        self.BayiRotasi.objects.create(bayi=self.bayi, kategori=self.kategori, saglayici=self.iki, sira=2)
        _ayar("Üç", gonderim="red")
        _ayar("İki", gonderim="red")
        islem = self.yukle()
        self.assertEqual((self.giden("Üç"), self.giden("İki"), self.giden("Bir")), (["100"], ["V100"], []))
        self.assertEqual(islem.durum, IslemDurumu.ASKIDA)  # gönderilemedi: yönetim karar verir
        # Karar ekranı bayinin sağlayıcılarını üstte sunar; Üç pakete bağlı değil, paketin kodu gider.
        yonetici = User.objects.create_superuser("yonetici", password="x")
        self.client.force_login(yonetici)
        yanit = self.client.get(reverse("admin:kontor_islem_karar", args=[islem.pk])).content.decode()
        self.assertIn("Bayiye özel · Üç", yanit)
        self.assertLess(yanit.index("Bayiye özel · Üç"), yanit.index("Bayiye özel · İki"))

    def test_baska_bayi_ve_pasif_satir_genel_sirayi_kullanir(self):
        baska = User.objects.create_user("5329990000", password="x")
        self.BayiRotasi.objects.create(bayi=baska, kategori=self.kategori, saglayici=self.uc)
        self.BayiRotasi.objects.create(bayi=self.bayi, kategori=self.kategori, saglayici=self.iki, aktif=False)
        islem = self.yukle()
        self.assertEqual(islem.saglayici, self.bir)
        self.assertEqual(self.giden("Üç"), [])

    def test_ekranlar_acilir(self):
        self.BayiRotasi.objects.create(bayi=self.bayi, kategori=self.kategori, saglayici=self.iki)
        yonetici = User.objects.create_superuser("yonetici", password="x")
        self.client.force_login(yonetici)
        yanit = self.client.get(reverse("admin:auth_user_change", args=[self.bayi.pk]))
        self.assertContains(yanit, "bayiye özel sağlayıcı")
        self.assertEqual(self.client.get(reverse("admin:kontor_bayirotasi_changelist")).status_code, 200)



@override_settings(CACHES=TEST_ONBELLEK)
class ProxyTestleri(TestCase):
    """Numara sorgusu Genel Ayarlar'daki anahtarla rastgele proxy'den gider."""

    LISTE = {
        "next": None,
        "results": [
            {"username": "u1", "password": "p1", "proxy_address": "1.1.1.1", "port": 6001, "valid": True},
            {"username": "u2", "password": "p2", "proxy_address": "2.2.2.2", "port": 6002, "valid": True},
            {"username": "u3", "password": "p3", "proxy_address": "3.3.3.3", "port": 6003, "valid": False},
        ],
    }

    def setUp(self):
        from django.core.cache import caches

        from apps.bayi.models import GenelAyarlar

        caches["kontor_sorgu"].clear()
        ayar = GenelAyarlar.getir()
        ayar.proxy_api_anahtari = "gizli-anahtar"
        ayar.save()

    def _yanit(self, veri):
        from unittest import mock

        yanit = mock.MagicMock()
        yanit.__enter__.return_value.read.return_value = json.dumps(veri).encode()
        return yanit

    def test_anahtar_yoksa_proxy_yok(self):
        from apps.bayi.models import GenelAyarlar
        from apps.kontor.sorgu.proxy import rastgele_proxy

        GenelAyarlar.objects.update(proxy_api_anahtari="")
        self.assertIsNone(rastgele_proxy())

    def test_liste_bir_kez_cekilir_gecersiz_atlanir(self):
        from unittest import mock

        from apps.kontor.sorgu.proxy import rastgele_proxy

        with mock.patch("urllib.request.urlopen", return_value=self._yanit(self.LISTE)) as urlopen:
            secilenler = {rastgele_proxy() for _ in range(30)}
        self.assertEqual(urlopen.call_count, 1)  # sonrası önbellekten
        self.assertEqual(urlopen.call_args[0][0].get_header("Authorization"), "Token gizli-anahtar")
        self.assertEqual(secilenler, {"http://u1:p1@1.1.1.1:6001", "http://u2:p2@2.2.2.2:6002"})

    def test_sorgu_proxyden_gider_baglanmazsa_baskasi_denenir(self):
        from unittest import mock

        import requests

        from apps.kontor.sorgu import kaynak_getir

        with mock.patch("urllib.request.urlopen", return_value=self._yanit(self.LISTE)), \
                mock.patch("apps.kontor.sorgu.vodafone_istemci.VodafoneSorgu") as sinif:
            ilk, ikinci = mock.MagicMock(), mock.MagicMock()
            sinif.side_effect = [ilk, ikinci]
            ilk.get_public_token.side_effect = requests.exceptions.ProxyError("kapalı")
            ikinci.get_public_token.return_value = {"publicToken": "T"}
            ikinci.get_kolay_packs.return_value = VodafoneSorguTestleri.CEVAP
            sonuc = kaynak_getir("vodafone").fonksiyon("5321234567")
        self.assertEqual([p.kod for p in sonuc.paketler], ["17776"])
        self.assertNotEqual(ilk.session.proxies["https"], ikinci.session.proxies["https"])

    def test_hic_baglanamazsa_notr_mesaj_ve_liste_yenilenir(self):
        from unittest import mock

        import requests

        from apps.kontor.sorgu import kaynak_getir

        with mock.patch("urllib.request.urlopen", return_value=self._yanit(self.LISTE)) as urlopen, \
                mock.patch("apps.kontor.sorgu.vodafone_istemci.VodafoneSorgu") as sinif:
            sinif.return_value.get_public_token.side_effect = requests.exceptions.ProxyError("u1:p1@1.1.1.1")
            with self.assertRaises(SorguHatasi) as hata:
                kaynak_getir("vodafone").fonksiyon("5321234567")
            self.assertEqual(urlopen.call_count, 1)
            with self.assertRaises(SorguHatasi):
                kaynak_getir("vodafone").fonksiyon("5321234567")
            self.assertEqual(urlopen.call_count, 2)  # eskimiş liste silindi, taze çekildi
        mesaj = str(hata.exception)
        for gizli in ("webshare", "p1", "1.1.1.1"):
            self.assertNotIn(gizli, mesaj.lower())

    def test_gecersiz_anahtar_saglayiciyi_anmaz(self):
        import urllib.error
        from unittest import mock

        from apps.kontor.sorgu.proxy import ProxyAlinamadi, rastgele_proxy

        hata = urllib.error.HTTPError("https://x", 401, "Unauthorized", {}, None)
        with mock.patch("urllib.request.urlopen", side_effect=hata):
            with self.assertRaisesMessage(ProxyAlinamadi, "anahtarı geçersiz"):
                rastgele_proxy()

    def test_ayar_ekraninda_anahtar_maskeli(self):
        from apps.bayi.models import GenelAyarlar

        yonetici = User.objects.create_superuser("yonetici", password="x")
        self.client.force_login(yonetici)
        yanit = self.client.get(reverse("admin:bayi_genelayarlar_change", args=[GenelAyarlar.TEKIL_PK]))
        self.assertContains(yanit, 'type="password"')
        self.assertContains(yanit, "Proxy API anahtarı")
        self.assertNotContains(yanit, "webshare", status_code=200)

ALT_SORGU = {"kodlar": [], "hata": False, "cagri": 0}


@kaynak("alt-sorgu", "Alternatif test sorgusu")
def _alt_sorgusu(numara, *, sahip=False):
    ALT_SORGU["cagri"] += 1
    if ALT_SORGU["hata"]:
        raise SorguHatasi("Kaynak cevap vermedi.")
    return [SorguPaketi(kod=k, ad=f"P{k}") for k in ALT_SORGU["kodlar"]]


@override_settings(KONTOR_ARKA_PLAN=False, KONTOR_ATOMIK_DENETIMI=False, CACHES=TEST_ONBELLEK)
class AlternatifTestleri(Temel):
    """Bayi X'i alır; numara aynısını ya da fazlasını ucuza veren Y'yi alabiliyorsa Y gider."""

    def setUp(self):
        super().setUp()
        from django.core.cache import caches

        caches["kontor_sorgu"].clear()
        ALT_SORGU.update(kodlar=[], hata=False, cagri=0)
        self.kategori.sorgu_kaynagi = "alt-sorgu"
        self.kategori.gonderim_oncesi_sorgu = True
        self.kategori.sorgu_sahibi_goster = False
        self.kategori.save()
        # Ana paket: 1000 DK · 15 GB · 30 gün, alış 100 (Bir) / 102 (İki), satış 110.
        self.ucuz = self._paket("200", internet_mb=20000, alis="90")  # fazlası, ucuz → alternatif
        self._paket("300", internet_mb=10000, alis="80")  # az internet → değil
        self._paket("400", internet_mb=20000, alis="105")  # pahalı → değil
        self.en_ucuz = self._paket("500", internet_mb=15000, alis="85")  # aynısı, en ucuz

    def _paket(self, kod, *, internet_mb, alis):
        paket = Paket.objects.create(
            kategori=self.kategori, kod=kod, ad=f"Paket {kod}", satis_fiyati=TL("110"),
            dakika=1000, internet_mb=internet_mb, gun=30,
        )
        Rota.objects.create(paket=paket, saglayici=self.bir, sira=1, alis_fiyati=TL(alis))
        return paket

    def giden_kodlar(self):
        return [g[2] for g in DURUM["Bir"]["gonderilen"]] + [g[2] for g in DURUM["İki"]["gonderilen"]]

    def test_gonderim_oncesi_sorgu_kapaliysa_sorulmaz_ana_paket_gider(self):
        self.kategori.gonderim_oncesi_sorgu = False
        self.kategori.save()
        ALT_SORGU["kodlar"] = ["500", "200"]  # ucuz alternatifler numarada var
        self.yukle()
        self.assertEqual(ALT_SORGU["cagri"], 0)
        self.assertEqual(self.giden_kodlar(), ["100"])

    def test_gonderim_oncesi_sorgu_kaynaksiz_acilamaz(self):
        from django.core.exceptions import ValidationError

        self.kategori.sorgu_kaynagi = ""
        with self.assertRaises(ValidationError) as hata:
            self.kategori.full_clean()
        self.assertIn("gonderim_oncesi_sorgu", hata.exception.message_dict)

    def test_alternatifler_ucuzdan_pahaliya(self):
        self.assertEqual(self.paket.alternatifleri(), [self.en_ucuz, self.ucuz])
        # Referans dakika, GB ve gün; SMS'e bakılmaz.
        self.paket.sms = 250
        self.paket.save()
        self.assertEqual(self.paket.alternatifleri(), [self.en_ucuz, self.ucuz])
        self.en_ucuz.alternatif_yapilmasin = True
        self.en_ucuz.save()
        self.assertEqual(self.paket.alternatifleri(), [self.ucuz])
        self.paket.alternatif_yapilmasin = True
        self.assertEqual(self.paket.alternatifleri(), [])

    def test_numaranin_alabildigi_ucuz_alternatif_gider(self):
        ALT_SORGU["kodlar"] = ["100", "200"]  # 500 numarada yok
        islem = self.yukle()
        self.assertEqual(self.giden_kodlar(), ["200"])
        _ayar("Bir", sorgu="basarili", mesaj="Paket 200 yüklendi")
        islem = isle(islem.pk, zorla=True)
        self.assertEqual(islem.durum, IslemDurumu.BASARILI)
        self.assertTrue(islem.alternatif_gonderildi)
        # Bayi istediğini görür ve onun fiyatını öder; kâr alternatifin alışıyla.
        self.assertEqual(islem.paket_adi, "Kolay Paket 15")
        self.assertEqual(islem.sonuc_mesaji, "Yüklendi.")
        self.assertEqual(self.bakiye(), TL("390.00"))
        self.assertEqual(islem.alis_tutari, TL("90"))
        self.assertEqual(islem.kar, TL("20.00"))

    def test_alternatif_reddedilirse_sonra_ana_paket(self):
        ALT_SORGU["kodlar"] = ["100", "200", "500"]
        _ayar("Bir", red_kodlar={"500", "200"})
        islem = self.yukle()
        # İki alternatif de kesin retle döndü; sıra ana pakete gelir, Bir kabul eder.
        self.assertEqual(self.giden_kodlar(), ["500", "200", "100"])
        self.assertEqual(islem.durum, IslemDurumu.ISLEMDE)
        self.assertFalse(islem.alternatif_gonderildi)

    def test_ana_paket_ve_alternatif_numarada_yoksa_iptal_ve_iade(self):
        ALT_SORGU["kodlar"] = ["300", "999"]
        islem = self.yukle()
        self.assertEqual(islem.durum, IslemDurumu.IPTAL)
        self.assertEqual(self.giden_kodlar(), [])
        self.assertIn("alamıyor", islem.sonuc_mesaji)
        self.assertEqual(self.bakiye(), TL("500.00"))

    def test_sorguda_hep_goster_sorguda_yoksa_da_listelenir_ve_gonderilir(self):
        self.paket.sorguda_hep_goster = True
        self.paket.save()
        ALT_SORGU["kodlar"] = ["300"]  # ana paket de alternatifler de sorguda yok
        from apps.kontor.services import numarayi_sorgula

        eslesen = [p.kod for p in numarayi_sorgula(self.kategori, "5329998877", self.bayi)["eslesen"]]
        self.assertCountEqual(eslesen, ["300", "100"])
        # Alınınca "numara alamıyor" diye iptal edilmez, ana paket gider.
        islem = self.yukle(hedef="5329998877")
        self.assertEqual(islem.durum, IslemDurumu.ISLEMDE)
        self.assertEqual(self.giden_kodlar(), ["100"])

    def test_bayiye_gizli_paket_gorunmez_satilmaz_ama_alternatif_olur(self):
        from apps.kontor.services import kategori_listesi, numarayi_sorgula

        self.en_ucuz.bayiye_gorunur = False
        self.en_ucuz.sorguda_hep_goster = True  # gizlilik bu işaretten de üstündür
        self.en_ucuz.save()
        ALT_SORGU["kodlar"] = ["100", "500"]
        self.client.force_login(self.bayi)

        self.assertNotIn("500", [p.kod for p in satistaki_paketler(self.kategori, self.bayi)])
        self.assertNotIn("500", [p.kod for p in numarayi_sorgula(self.kategori, "5329998877", self.bayi)["eslesen"]])
        self.assertNotContains(self.client.get(self.kategori.get_absolute_url()), "Paket 500")
        adres = reverse("kontor:paket", args=[self.kategori.slug, "500"])
        self.assertEqual(self.client.get(adres).status_code, 404)
        with self.assertRaises(YuklemeYapilamaz):
            yukleme_baslat(self.bayi, self.en_ucuz, "5329998877")

        # Bayi 100'ü alır; numara gizli 500'ü alabiliyor ve ucuz: o gider.
        self.yukle(hedef="5329998877")
        self.assertEqual(self.giden_kodlar(), ["500"])

        # Yalnızca gizli paketi kalan kategori listede görünmez.
        Paket.objects.filter(kategori=self.kategori).update(bayiye_gorunur=False)
        self.assertNotIn(self.kategori, list(kategori_listesi(bayi=self.bayi)))

    def test_sorguda_hep_goster_alternatifi_sorgusuz_gondermez(self):
        # İşaretli alternatif sorguda yoksa bayinin paketinin yerine geçmez.
        self.en_ucuz.sorguda_hep_goster = True
        self.en_ucuz.save()
        ALT_SORGU["kodlar"] = ["100"]
        self.yukle()
        self.assertEqual(self.giden_kodlar(), ["100"])

    def test_ana_paket_numarada_yok_ama_alternatif_var(self):
        ALT_SORGU["kodlar"] = ["200"]
        _ayar("Bir", red_kodlar={"200"})
        islem = self.yukle()
        # Alternatif gönderilemedi, ana paket numarada yok: denenmez; gönderim
        # reddi eşleştirme hatası olabilir, iptal değil askı.
        self.assertEqual(self.giden_kodlar(), ["200"])
        self.assertEqual(islem.durum, IslemDurumu.ASKIDA)
        self.assertEqual(self.bakiye(), TL("390.00"))

    def test_sorgu_hata_verirse_ana_paket_gider(self):
        ALT_SORGU["hata"] = True
        self.yukle()
        self.assertEqual(self.giden_kodlar(), ["100"])

    def test_bayinin_sorgusu_onbellekten_kullanilir(self):
        ALT_SORGU["kodlar"] = ["100", "500"]
        from apps.kontor.services import numarayi_sorgula

        numarayi_sorgula(self.kategori, "5329998877", self.bayi)
        self.yukle(hedef="5329998877")
        self.assertEqual(ALT_SORGU["cagri"], 1)
        self.assertEqual(self.giden_kodlar(), ["500"])

    def test_alternatif_yapilmasin_sorguya_gitmez(self):
        self.paket.alternatif_yapilmasin = True
        self.paket.save()
        ALT_SORGU["kodlar"] = ["100", "500"]
        self.yukle()
        self.assertEqual(ALT_SORGU["cagri"], 0)
        self.assertEqual(self.giden_kodlar(), ["100"])

    def test_bayi_ekraninda_alternatif_gorunmez(self):
        ALT_SORGU["kodlar"] = ["100", "500"]
        islem = self.yukle()
        _ayar("Bir", sorgu="basarili", mesaj="Paket 500 yüklendi")
        isle(islem.pk, zorla=True)
        self.client.force_login(self.bayi)
        yanit = self.client.get(islem.get_absolute_url())
        self.assertContains(yanit, "Kolay Paket 15")
        self.assertNotContains(yanit, "Paket 500")


class TavsiyeTestleri(Temel):
    def setUp(self):
        super().setUp()
        self.paket.tavsiye_fiyati = TL("349.90")
        self.paket.save()
        self.client.force_login(self.bayi)

    def test_fiyatlandir_kazanci_hesaplar(self):
        (paket,) = satistaki_paketler(self.kategori, self.bayi)
        self.assertEqual((paket.fiyat, paket.tavsiye, paket.kazanc), (TL("110.00"), TL("349.90"), TL("239.90")))

    def test_paketler_tavsiye_fiyatina_gore_ucuzdan_pahaliya(self):
        # self.paket: tavsiye 349,90. Tavsiyesi olmayan pakette bayinin fiyatı sayılır.
        Paket.objects.create(kategori=self.kategori, kod="A", ad="A Pahalı", satis_fiyati=TL("50"), tavsiye_fiyati=TL("999"))
        Paket.objects.create(kategori=self.kategori, kod="B", ad="B Ucuz", satis_fiyati=TL("50"), tavsiye_fiyati=TL("129"))
        Paket.objects.create(kategori=self.kategori, kod="C", ad="C Tavsiyesiz", satis_fiyati=TL("200"))
        sira = [p.kod for p in satistaki_paketler(self.kategori, self.bayi)]
        self.assertEqual(sira, ["B", "C", "100", "A"])  # 129, 200, 349,90, 999
        # Kategori sayfası da aynı sırayla çizer.
        yanit = self.client.get(self.kategori.get_absolute_url())
        icerik = yanit.content.decode()
        self.assertLess(icerik.index("B Ucuz"), icerik.index("C Tavsiyesiz"))
        self.assertLess(icerik.index("Kolay Paket 15"), icerik.index("A Pahalı"))

    def test_bayi_ekraninda_yalnizca_girilen_icerik(self):
        self.paket.aciklama = "750 DK, 250 SMS, 28 Gün Geçerli, Vergi Dahil"  # operatörden gelen
        self.paket.save()
        pin = Paket.objects.create(kategori=self.kategori, kod="P", ad="Pin", satis_fiyati=TL("40"), aciklama="Tek kullanımlık kod")
        for adres in (self.kategori.get_absolute_url(), reverse("kontor:paket", args=[self.kategori.slug, self.paket.kod])):
            yanit = self.client.get(adres)
            self.assertContains(yanit, "1.000 DK · 15 GB · 30 gün")
            self.assertNotContains(yanit, "Vergi Dahil")
        # İçeriği girilmemiş pakette kart boş kalmasın: açıklama yazılır.
        self.assertContains(self.client.get(self.kategori.get_absolute_url()), "Tek kullanımlık kod")
        self.assertContains(self.client.get(reverse("kontor:paket", args=[self.kategori.slug, pin.kod])), "Tek kullanımlık kod")

    def test_ekranda_buyuk_rakam_tavsiye_alis_gozun_arkasinda(self):
        yanit = self.client.get(self.kategori.get_absolute_url())
        self.assertContains(yanit, "349,90")
        self.assertContains(yanit, "data-goz")
        self.assertContains(yanit, "data-alis hidden")
        yanit = self.client.get(reverse("kontor:paket", args=[self.kategori.slug, "100"]))
        self.assertContains(yanit, "kazancın 239,90")

    def test_sorgu_sonucunda_her_kartin_gozu_ve_alisi_var(self):
        # Göz bir süre yalnızca paket listesinin üstündeydi; numara sorgusunun
        # sonucunda hiç yoktu ve bayi sorguda kaça aldığını göremiyordu.
        from django.core.cache import caches

        caches["kontor_sorgu"].clear()
        SORGU.update(cagri=0, hata=False)
        self.kategori.sorgu_kaynagi = "test-sorgu"
        self.kategori.save()
        yanit = self.client.get(reverse("kontor:sorgu", args=[self.kategori.slug]), {"hedef": "5329998877"})
        self.assertContains(yanit, "data-goz", count=1)
        self.assertContains(yanit, "data-alis hidden")
        self.assertContains(yanit, "Alışın")
        self.assertContains(yanit, "110,00")
        self.assertContains(yanit, "239,90")
        self.assertContains(yanit, "?hedef=5329998877")
        # Göz düğmesi bağlantının içinde değil: kart kutu, bağlantı onun içinde.
        icerik = yanit.content.decode()
        self.assertLess(icerik.index("</a>"), icerik.index("data-goz"))
        # Sorgu sonucu betik taşımaz; sayfadaki tek betik HTMX'le gelen kartları da bağlar.
        self.assertNotContains(yanit, "<script")
        self.assertContains(self.client.get(self.kategori.get_absolute_url()), "kontor-alis-acik", count=1)

    def test_tavsiye_yoksa_goz_yok(self):
        self.paket.tavsiye_fiyati = None
        self.paket.save()
        # Betik sayfada durur (sorgu sonucu ona bağlanır); düğme çizilmez.
        self.assertNotContains(self.client.get(self.kategori.get_absolute_url()), "<button type=\"button\" data-goz")

    def test_islem_tavsiyeyi_saklar(self):
        islem = self.yukle()
        self.paket.tavsiye_fiyati = TL("399")
        self.paket.save()
        islem.refresh_from_db()
        self.assertEqual(islem.tavsiye_fiyati, TL("349.90"))
        self.assertContains(self.client.get(islem.get_absolute_url()), "Müşteriye tavsiye")

    def test_tavsiye_operatorden_alinir(self):
        from apps.kontor.models import GorulenPaket
        from apps.kontor.services import gorulen_paketi_kataloga_ekle, tavsiyeyi_hesapla

        GorulenPaket.objects.create(
            kaynak="x", kod="100", kategori=self.kategori, fiyat=TL("359.90"), son_gorulme=timezone.now()
        )
        baska = Paket.objects.create(kategori=self.kategori, kod="200", ad="Görülmemiş")
        secili = Paket.objects.filter(pk__in=[self.paket.pk, baska.pk])
        self.assertEqual(tavsiyeyi_hesapla(secili), (1, 1))  # varsayılan: operatör fiyatı, aynen
        self.paket.refresh_from_db()
        self.assertEqual(self.paket.tavsiye_fiyati, TL("359.90"))
        # Görülmemiş paketin tavsiyesine dokunulmaz.
        baska.refresh_from_db()
        self.assertIsNone(baska.tavsiye_fiyati)

        tavsiyeyi_hesapla(secili, islem="yuzde", deger=TL("10"))
        self.paket.refresh_from_db()
        self.assertEqual(self.paket.tavsiye_fiyati, TL("395.89"))  # 359,90 × 1,10 = 395,89
        tavsiyeyi_hesapla(secili, islem="tutar", deger=TL("-9.90"))
        self.paket.refresh_from_db()
        self.assertEqual(self.paket.tavsiye_fiyati, TL("350.00"))
        # Alış tabanı: sıradaki ilk açık sağlayıcının alışı (100,00).
        tavsiyeyi_hesapla(secili.prefetch_related("rotalar__saglayici"), taban="alis", islem="yuzde", deger=TL("25"))
        self.paket.refresh_from_db()
        self.assertEqual(self.paket.tavsiye_fiyati, TL("125.00"))

        yeni = GorulenPaket.objects.create(
            kaynak="x", kod="300", kategori=self.kategori, ad="Yeni", fiyat=TL("99.90"), son_gorulme=timezone.now()
        )
        paket, _ = gorulen_paketi_kataloga_ekle(yeni)
        self.assertEqual(paket.tavsiye_fiyati, TL("99.90"))

    def test_paket_listesinde_tavsiye_hesaplanir(self):
        from apps.kontor.models import GorulenPaket

        GorulenPaket.objects.create(
            kaynak="x", kod=self.paket.kod, kategori=self.kategori, fiyat=TL("200.00"), son_gorulme=timezone.now()
        )
        yonetici = User.objects.create_superuser("yonetici", password="x")
        self.client.force_login(yonetici)
        adres = reverse("admin:kontor_paket_changelist")
        yanit = self.client.get(adres)
        self.assertContains(yanit, "Operatör fiyatı")
        self.assertContains(yanit, "200.00")
        secim = {"action": "tavsiyeyi_hesapla", "_selected_action": [self.paket.pk]}
        # Önce ara form; % seçip rakam yazılmazsa kaydedilmez.
        self.assertContains(self.client.post(adres, secim), "Tavsiye satışı hesapla")
        yanit = self.client.post(adres, {**secim, "uygula": "1", "taban": "operator", "islem": "yuzde", "deger": ""})
        self.assertContains(yanit, "Yüzdeyi ya da tutarı yazın")
        self.client.post(adres, {**secim, "uygula": "1", "taban": "operator", "islem": "yuzde", "deger": "7,5"})
        self.paket.refresh_from_db()
        self.assertEqual(self.paket.tavsiye_fiyati, TL("215.00"))



class OyunBolumuTestleri(Temel):
    def setUp(self):
        super().setUp()
        self.oyun = Kategori.objects.create(ad="PUBG Mobile UC", oyun=True, hedef=Hedef.YOK)
        self.pin = Paket.objects.create(kategori=self.oyun, kod="UC60", ad="60 UC", satis_fiyati=TL("40"))
        Rota.objects.create(paket=self.pin, saglayici=self.bir)
        self.client.force_login(self.bayi)

    def test_oyun_ve_kontor_ayri_listelenir(self):
        kontor = self.client.get(reverse("kontor:kategoriler"))
        self.assertContains(kontor, "Vodafone Paket")
        self.assertNotContains(kontor, "PUBG Mobile UC")
        oyunlar = self.client.get(reverse("kontor:oyunlar"))
        self.assertContains(oyunlar, "PUBG Mobile UC")
        self.assertNotContains(oyunlar, "Vodafone Paket")

    def test_adresler_bolume_gore(self):
        self.assertEqual(self.oyun.get_absolute_url(), "/oyun/pubg-mobile-uc/")
        self.assertEqual(self.pin.get_absolute_url(), "/oyun/pubg-mobile-uc/UC60/")
        self.assertEqual(self.paket.get_absolute_url(), "/kontor/vodafone-paket/100/")
        yanit = self.client.get(self.oyun.get_absolute_url())
        self.assertContains(yanit, 'href="/oyun/pubg-mobile-uc/UC60/"')
        self.assertContains(yanit, "Oyun &amp; Pin")

    def test_yanlis_bolumden_gelen_dogrusuna_yonlenir(self):
        yanit = self.client.get("/kontor/pubg-mobile-uc/")
        self.assertRedirects(yanit, "/oyun/pubg-mobile-uc/", fetch_redirect_response=False)
        yanit = self.client.get("/oyun/vodafone-paket/100/")
        self.assertRedirects(yanit, "/kontor/vodafone-paket/", fetch_redirect_response=False)

    def test_pin_oyun_adresinden_alinir(self):
        with self.captureOnCommitCallbacks(execute=True):
            yanit = self.client.post(self.pin.yukle_url, {"islem_anahtari": "o1"})
        islem = Islem.objects.get()
        self.assertRedirects(yanit, islem.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual((islem.hedef, islem.kategori), ("", self.oyun))
        self.assertEqual(self.bakiye(), TL("460.00"))
        # Son işlemler de bölümüne göre ayrılır.
        self.assertContains(self.client.get(reverse("kontor:oyunlar")), "60 UC")
        self.assertNotContains(self.client.get(reverse("kontor:kategoriler")), "60 UC")

    def test_menude_iki_ayri_madde(self):
        yanit = self.client.get(reverse("kontor:oyunlar"))
        self.assertContains(yanit, 'href="/oyun/"')
        self.assertContains(yanit, 'href="/kontor/"')
