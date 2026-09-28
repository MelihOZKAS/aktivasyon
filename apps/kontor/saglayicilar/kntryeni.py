"""kntryeni protokolü.

Gönderim — `api/ent_hedef_al.php`:
    ?kod=…&sifre=…&numara=532…&kontor=<ürün kodu>&operator=vodafone&kref=…
    _OK[98765] {12.50} …                 kabul; köşeli parantezde işlem no, süslüde tutar
    _HATA:Yetersiz bakiye                ret

Sonuç — `api/ent_hedef_ver.php` (işlem no ile sorulur):
    … [1] …                              başarılı (ikinci alan)
    … [2] …                              iptal
    başka her şey                        sürüyor
"""

import re
from urllib.parse import unquote_plus

from apps.kontor.saglayicilar import (
    Adaptor,
    Gonderim,
    GonderimSonucu,
    SaglayiciHatasi,
    Sorgu,
    SorguSonucu,
    tutar_coz,
)
from apps.kontor.saglayicilar.http import metin_istek

KABUL_DESENI = re.compile(r"^_OK\[(?P<ref>[^\]]*)\]")


def gonderim_coz(ham):
    metin = unquote_plus(ham or "").strip()
    parcalar = metin.split()
    eslesme = KABUL_DESENI.match(metin)
    if eslesme:
        alis = tutar_coz(parcalar[1]) if len(parcalar) > 1 else None
        return GonderimSonucu(
            Gonderim.KABUL, uzak_ref=eslesme.group("ref"), alis=alis, ham=ham
        )
    if metin.upper().startswith("_HATA"):
        mesaj = metin.split(":", 1)[1].strip() if ":" in metin else metin
        return GonderimSonucu(Gonderim.RED, mesaj=mesaj[:200] or "Sağlayıcı reddetti.", ham=ham)
    return GonderimSonucu(Gonderim.BELIRSIZ, mesaj=metin[:200], ham=ham)


def sorgu_coz(ham):
    metin = unquote_plus(ham or "").strip()
    parcalar = metin.split()
    durum = parcalar[1] if len(parcalar) > 1 else ""
    if durum == "[1]":
        return SorguSonucu(Sorgu.BASARILI, ham=ham)
    if durum == "[2]":
        mesaj = " ".join(parcalar[2:]) or "Sağlayıcı iptal etti."
        return SorguSonucu(Sorgu.IPTAL, mesaj=mesaj[:200], ham=ham)
    return SorguSonucu(Sorgu.ISLEMDE, ham=ham)


class KontorYeni(Adaptor):
    kod = "kntryeni"
    ad = "kntryeni (ent_hedef_al)"

    def _kimlik(self):
        return {"kod": self.saglayici.kullanici_adi, "sifre": self.saglayici.sifre}

    def gonder(self, *, ref, hedef, uzak_kod, uzak_operator, uzak_tip):
        ham = metin_istek(
            f"{self.taban()}/api/ent_hedef_al.php",
            parametreler={
                **self._kimlik(),
                "numara": hedef,
                "kontor": uzak_kod,
                "operator": uzak_operator,
                "kref": ref,
            },
            saglayici_adi=self.saglayici.ad,
        )
        return gonderim_coz(ham)

    def sorgula(self, *, ref, uzak_ref):
        if not uzak_ref:
            raise SaglayiciHatasi("kntryeni işlem numarası yok; sonuç sorulamaz.")
        ham = metin_istek(
            f"{self.taban()}/api/ent_hedef_ver.php",
            parametreler={**self._kimlik(), "ref": uzak_ref},
            saglayici_adi=self.saglayici.ad,
        )
        return sorgu_coz(ham)
