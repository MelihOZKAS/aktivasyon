"""Teknografi protokolü (`islemal.asp`).

Gönderim — `api/islemal.asp`:
    ?bayikodu=…&kadi=…&sifre=…&ope=<ürün kodu>&turu=5&miktar=0&telno=532…&ref=…
    OK 123456                            kabul; ikinci alan Grafi'nin işlem no'su

Sonuç — `api/islemkontrol.asp` (işlem no ile sorulur):
    OK |12,50|…                          başarılı; "|" sonrası düşülen tutar
    99 …                                 sürüyor
    98 …                                 iptal

Ürün kodu operatörü de belirler; operatör/tip alanı gönderilmez.
Gönderimde "OK" dışında gelen cevap, "HATA" ile başlamıyorsa belirsiz
sayılır — eski sistem de bunları askıya alıyordu.
"""

import re
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

RED_ONEKLERI = ("HATA", "ERROR", "ERR")


def gonderim_coz(ham):
    metin = unquote_plus(ham or "").strip()
    parcalar = metin.split()
    if parcalar and parcalar[0].upper() == "OK" and len(parcalar) > 1:
        return GonderimSonucu(Gonderim.KABUL, uzak_ref=parcalar[1].strip("|"), ham=ham)
    if metin.upper().startswith(RED_ONEKLERI):
        return GonderimSonucu(Gonderim.RED, mesaj=metin[:200], ham=ham)
    return GonderimSonucu(Gonderim.BELIRSIZ, mesaj=metin[:200], ham=ham)


def sorgu_coz(ham):
    metin = unquote_plus(ham or "").strip()
    ilk = re.split(r"[\s|]+", metin, maxsplit=1)[0].upper() if metin else ""
    if ilk == "OK":
        dilimler = metin.split("|")
        alis = tutar_coz(dilimler[1]) if len(dilimler) > 1 else None
        return SorguSonucu(Sorgu.BASARILI, alis=alis, ham=ham)
    if ilk == "98":
        mesaj = metin[2:].strip(" |") or "Sağlayıcı iptal etti."
        return SorguSonucu(Sorgu.IPTAL, mesaj=mesaj[:200], ham=ham)
    return SorguSonucu(Sorgu.ISLEMDE, ham=ham)


def paket_listesi_coz(ham):
    """`ad;kod;5;0;fiyat;tip;bayi kodu;` yedişerli gruplar."""
    alanlar = (ham or "").split(";")
    sonuc = []
    for i in range(0, len(alanlar) - 6, 7):
        ad, kod, _, _, fiyat, tip, _ = (a.strip() for a in alanlar[i : i + 7])
        tutar = tutar_coz(fiyat)
        if not kod or tutar is None:
            continue
        sonuc.append(SaglayiciPaketVerisi(kod=kod, ad=ad or kod, fiyat=tutar, tip=tip))
    if not sonuc and ham:
        raise SaglayiciHatasi(f"Fiyat listesi okunamadı: {ham[:200]}")
    return sonuc


class Grafi(Adaptor):
    kod = "grafi"
    ad = "Teknografi (islemal.asp)"
    paket_listesi_var = True

    def _kimlik(self):
        return {
            "bayikodu": self.saglayici.bayi_kodu,
            "kadi": self.saglayici.kullanici_adi,
            "sifre": self.saglayici.sifre,
        }

    def gonder(self, *, ref, hedef, uzak_kod, uzak_operator, uzak_tip):
        ham = metin_istek(
            f"{self.taban()}/api/islemal.asp",
            parametreler={
                **self._kimlik(),
                "ope": uzak_kod,
                "turu": 5,
                "miktar": 0,
                "telno": hedef,
                "ref": ref,
            },
            saglayici_adi=self.saglayici.ad,
        )
        return gonderim_coz(ham)

    def sorgula(self, *, ref, uzak_ref):
        if not uzak_ref:
            raise SaglayiciHatasi("Teknografi işlem numarası yok; sonuç sorulamaz.")
        ham = metin_istek(
            f"{self.taban()}/api/islemkontrol.asp",
            parametreler={**self._kimlik(), "islem": uzak_ref},
            saglayici_adi=self.saglayici.ad,
        )
        return sorgu_coz(ham)

    def paketleri_getir(self):
        ham = metin_istek(
            f"{self.taban()}/api/paket_listesi.asp",
            parametreler=self._kimlik(),
            saglayici_adi=self.saglayici.ad,
        )
        return paket_listesi_coz(ham)
