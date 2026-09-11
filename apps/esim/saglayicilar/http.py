"""Adaptörlerin ortak HTTP katmanı: urllib, JSON, zaman aşımı.

`requests` bağımlılığı yok (Telegram bildirimi de urllib kullanır). Her
adaptör yalnızca yol, gövde ve başlıklarını verir; ağ hatası ve JSON
çözümü burada tek yerde `SaglayiciHatasi`ne çevrilir.
"""

import json
import urllib.error
import urllib.parse
import urllib.request

from apps.esim.saglayicilar import SaglayiciHatasi

ZAMAN_ASIMI = 30


def json_istek(adres, *, yontem="GET", basliklar=None, govde=None, form=False, saglayici_adi=""):
    """İstek atar, `(HTTP durumu, çözülmüş gövde)` döndürür.

    4xx/5xx yanıtı hata **yükseltmez**, durum koduyla birlikte döner:
    sağlayıcının kendi hata mesajı gövdede yazıyor ve adaptör onu okumak
    ister. Ağa ulaşılamaması ya da gövdenin JSON olmaması hatadır.
    """
    basliklar = dict(basliklar or {})
    veri = None
    if govde is not None:
        if form:
            veri = urllib.parse.urlencode(govde).encode()
            basliklar.setdefault("Content-Type", "application/x-www-form-urlencoded")
        else:
            veri = json.dumps(govde, separators=(",", ":")).encode()
            basliklar.setdefault("Content-Type", "application/json")
    basliklar.setdefault("Accept", "application/json")

    istek = urllib.request.Request(adres, data=veri, headers=basliklar, method=yontem)
    try:
        with urllib.request.urlopen(istek, timeout=ZAMAN_ASIMI) as yanit:
            return yanit.status, _coz(yanit.read())
    except urllib.error.HTTPError as hata:
        return hata.code, _coz(hata.read())
    except (urllib.error.URLError, OSError) as hata:
        raise SaglayiciHatasi(f"{saglayici_adi or adres} ulaşılamadı: {hata}")


def _coz(ham):
    if not ham:
        return {}
    try:
        return json.loads(ham.decode())
    except ValueError:
        # HTML hata sayfası gibi JSON olmayan gövde: metni taşı.
        return {"_ham": ham.decode(errors="replace")[:300]}
