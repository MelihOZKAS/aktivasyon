"""Ülke adları ve bayrakları.

Sağlayıcı ülkeleri İngilizce adıyla verir ("Turkey", "Germany"); bayi
Türkçesini görmeli. Adlar `ulkeler_tr.json` içinde durur (CLDR'den türetildi,
264 kod); yönetici panelden değiştirebilir, dosya yalnızca ilk kayıtta okunur.

Bayrak için görsel dosya yok: iki harfli ISO kodu Unicode'un bölgesel
gösterge harflerine çevrilince telefon ve masaüstü bayrağı kendisi çizer.
"""

import json
from functools import lru_cache
from pathlib import Path

_DOSYA = Path(__file__).with_name("ulkeler_tr.json")
_GOSTERGE_TABANI = 0x1F1E6  # 🇦


@lru_cache(maxsize=1)
def turkce_adlar():
    with _DOSYA.open(encoding="utf-8") as dosya:
        return json.load(dosya)


def turkce_ad(kod, varsayilan=""):
    return turkce_adlar().get(kod.upper(), varsayilan or kod.upper())


def bayrak(kod):
    kod = (kod or "").upper()
    if len(kod) != 2 or not kod.isalpha():
        return ""
    return "".join(chr(_GOSTERGE_TABANI + ord(harf) - ord("A")) for harf in kod)
