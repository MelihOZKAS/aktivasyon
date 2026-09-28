"""Adaptörlerin ortak HTTP katmanı: düz metin, zaman aşımı, hata ayrımı.

Kontör sağlayıcıları JSON değil düz metin konuşur ("OK|1|…", "1:…:12,50").
Burada tek iş yapılır: isteği atmak ve **isteğin sağlayıcıya varıp
varmadığını** ayırt etmek. Bağlantı hiç kurulamadıysa (`kesin_gitmedi`)
gönderim sıradaki sağlayıcıya aktarılabilir; zaman aşımında istek varmış
olabilir, servis onu askıya alır.
"""

import socket
import urllib.error
import urllib.parse
import urllib.request

from apps.kontor.saglayicilar import SaglayiciHatasi

# Bayi tezgâhta bekliyor; sağlayıcı bundan uzun susuyorsa sorun var.
ZAMAN_ASIMI = 20


def metin_istek(adres, *, parametreler=None, form=None, saglayici_adi=""):
    """GET (parametreler) ya da form POST'u atar, gövdeyi metin döndürür."""
    if parametreler:
        adres = f"{adres}?{urllib.parse.urlencode(parametreler)}"
    veri = urllib.parse.urlencode(form).encode() if form is not None else None
    istek = urllib.request.Request(
        adres, data=veri, headers={"User-Agent": "aktivasyon-kontor/1"}
    )
    etiket = saglayici_adi or urllib.parse.urlsplit(adres).netloc
    try:
        with urllib.request.urlopen(istek, timeout=ZAMAN_ASIMI) as yanit:
            ham = yanit.read()
            karakter = yanit.headers.get_content_charset() or "utf-8"
    except urllib.error.HTTPError as hata:
        # 4xx: adres ya da istek yanlış, işlem açılmadı. 5xx: sunucu çöktü;
        # işlemi açıp cevap veremeden düşmüş olabilir.
        raise SaglayiciHatasi(
            f"{etiket} HTTP {hata.code} döndü.", kesin_gitmedi=400 <= hata.code < 500
        )
    except urllib.error.URLError as hata:
        raise SaglayiciHatasi(
            f"{etiket} ulaşılamadı: {hata.reason}", kesin_gitmedi=_varmadi(hata.reason)
        )
    except (socket.timeout, TimeoutError):
        raise SaglayiciHatasi(f"{etiket} {ZAMAN_ASIMI} saniyede cevap vermedi.")
    except OSError as hata:
        raise SaglayiciHatasi(f"{etiket} ulaşılamadı: {hata}")
    return ham.decode(karakter, errors="replace").strip()


def _varmadi(sebep):
    """Bağlantı kurulmadan düşen hatalar: istek sağlayıcıya hiç varmadı."""
    return isinstance(sebep, (ConnectionRefusedError, socket.gaierror))
