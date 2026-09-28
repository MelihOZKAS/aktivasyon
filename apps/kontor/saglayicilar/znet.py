"""Znet / Gencan protokolü (`tl_servis.php`).

Türkiye'deki kontör bayi yazılımlarının çoğunun ortak dili. Bizim bayilere
açtığımız kapı da bu protokolü konuşur (`apps.kontor.api`).

Gönderim — `servis/tl_servis.php`:
    ?bayi_kodu=…&sifre=…&operator=vodafone&tip=ses&kontor=100&gsmno=532…&tekilnumara=…
    OK|1|Talebiniz alınmıştır|12.50     kabul; son alan düşülen tutar
    OK|3|Yetersiz bakiye|0.00            ret; işlem açılmadı

Sonuç — `servis/tl_kontrol.php`:
    ?bayi_kodu=…&sifre=…&tekilnumara=…
    1:Yüklendi:12.50                     başarılı
    2:islemde:0                          sürüyor
    3:Numara hatalı                      iptal

Eski sistemde `OK|8` gibi tanınmayan kodlar da askıya alınıyordu; burada
da aynı: yalnızca `1` kabul, yalnızca `3` ret sayılır, gerisi belirsizdir.
Cevaplar URL kodlu gelebiliyor ("Y%C3%BCklendi+-ONAYLANDI"); çözülür.
"""

import json
from urllib.parse import unquote_plus

from apps.kontor.saglayicilar import (
    Adaptor,
    Gonderim,
    GonderimSonucu,
    SaglayiciHatasi,
    SaglayiciPaketVerisi,
    Sorgu,
    SorguSonucu,
    tutar_coz,
)
from apps.kontor.saglayicilar.http import metin_istek


def gonderim_coz(ham):
    parcalar = [p.strip() for p in unquote_plus(ham or "").split("|")]
    mesaj = parcalar[2] if len(parcalar) > 2 else ""
    if parcalar[0].upper() == "OK" and len(parcalar) > 1:
        if parcalar[1] == "1":
            alis = tutar_coz(parcalar[3]) if len(parcalar) > 3 else None
            return GonderimSonucu(Gonderim.KABUL, mesaj=mesaj, alis=alis, ham=ham)
        if parcalar[1] == "3":
            return GonderimSonucu(Gonderim.RED, mesaj=mesaj or "Sağlayıcı reddetti.", ham=ham)
    return GonderimSonucu(Gonderim.BELIRSIZ, mesaj=mesaj or ham[:200], ham=ham)


def sorgu_coz(ham):
    parcalar = [p.strip() for p in unquote_plus(ham or "").split(":")]
    kod = parcalar[0]
    mesaj = parcalar[1] if len(parcalar) > 1 else ""
    if kod == "1":
        alis = tutar_coz(parcalar[2]) if len(parcalar) > 2 else None
        return SorguSonucu(Sorgu.BASARILI, mesaj=mesaj, alis=alis, ham=ham)
    if kod == "3":
        return SorguSonucu(Sorgu.IPTAL, mesaj=mesaj or "Sağlayıcı iptal etti.", ham=ham)
    # "2:islemde" ve tanınmayan her şey: bir sonraki turda yeniden sorulur.
    return SorguSonucu(Sorgu.ISLEMDE, mesaj=mesaj, ham=ham)


class Znet(Adaptor):
    """Znet ve Gencan aynı yazılımın iki adı: kullanıcı adı + şifreyle konuşur.

    Fiyat listesi `ClientWebService`'ten JSON gelir (`TopUpPrices`); bayi
    kodu, kullanıcı adı ve şifre üçü birden istenir. Listeyi vermeyen site
    hata döner, alış fiyatları o zaman rotaya elle yazılır.
    """

    kod = "znet"
    ad = "Znet / Gencan (tl_servis)"
    varsayilan_sema = "http"
    paket_listesi_var = True

    def _kimlik(self):
        return {"bayi_kodu": self.saglayici.kullanici_adi, "sifre": self.saglayici.sifre}

    def gonder(self, *, ref, hedef, uzak_kod, uzak_operator, uzak_tip):
        ham = metin_istek(
            f"{self.taban()}/servis/tl_servis.php",
            parametreler={
                **self._kimlik(),
                "operator": uzak_operator,
                "tip": uzak_tip,
                "kontor": uzak_kod,
                "gsmno": hedef,
                "tekilnumara": ref,
            },
            saglayici_adi=self.saglayici.ad,
        )
        return gonderim_coz(ham)

    def sorgula(self, *, ref, uzak_ref):
        ham = metin_istek(
            f"{self.taban()}/servis/tl_kontrol.php",
            parametreler={**self._kimlik(), "tekilnumara": ref},
            saglayici_adi=self.saglayici.ad,
        )
        return sorgu_coz(ham)

    def paketleri_getir(self):
        ham = metin_istek(
            f"{self.taban()}/ClientWebService",
            form={
                "Operation": "TopUpPrices",
                "request[DealerCode]": self.saglayici.bayi_kodu,
                "request[Username]": self.saglayici.kullanici_adi,
                "request[Password]": self.saglayici.sifre,
            },
            saglayici_adi=self.saglayici.ad,
        )
        return paket_listesi_coz(ham)


def paket_listesi_coz(ham):
    try:
        veri = json.loads(ham)
        paketler = veri["TopUpPricesResult"]["Packages"] or []
    except (ValueError, KeyError, TypeError):
        raise SaglayiciHatasi(f"Fiyat listesi okunamadı: {ham[:200]}")
    sonuc = []
    for paket in paketler:
        fiyat = tutar_coz(paket.get("Price"))
        kod = str(paket.get("ProductId") or "").strip()
        if not kod or fiyat is None:
            continue
        sonuc.append(
            SaglayiciPaketVerisi(
                kod=kod,
                ad=str(paket.get("PackageName") or kod).strip(),
                fiyat=fiyat,
                operator=str(paket.get("Operator") or "").strip(),
                tip=str(paket.get("Type") or "").strip(),
            )
        )
    return sonuc
