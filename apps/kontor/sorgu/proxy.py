"""Numara sorgusu için rastgele proxy.

Operatörün sorgu servisi aynı IP'den gelen sık isteği kısıtlayabiliyor; her
sorgu listeden rastgele seçilen bir proxy'den gider. Anahtar Genel
Ayarlar'dadır (`proxy_api_anahtari`); boşsa proxy kullanılmaz, sorgu
doğrudan sunucudan gider.

**Sağlayıcının adı hiçbir ekranda geçmez** — yönetimin isteği: nereden
proxy alındığı bilinmesin. Alan etiketi, hata mesajları ve log satırları
nötrdür; adres yalnızca burada, kodda durur.

Liste her sorguda çekilmez: `LISTE_SURESI` (12 saat) boyunca dosya
önbelleğinde (`CACHES["kontor_sorgu"]`) kalır, gunicorn işçileri ve kontör
işçisi aynı listeyi görür (yönetici: "her seferinde çekmeye gerek yok").
Liste o sürede eskiyebilir; sorgu art arda proxy'ye bağlanamazsa
`listeyi_unut` önbelleği siler, bir sonraki sorgu taze listeyi çeker.
Anahtar değişince önbellek anahtarı da değişir, yeni liste hemen çekilir. Yeni dış istek olduğu için `requests` değil urllib kullanır
(CLAUDE.md: `requests` yalnızca Vodafone istemcisi için var).
"""

import hashlib
import json
import logging
import random
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

LISTE_ADRESI = "https://proxy.webshare.io/api/v2/proxy/list/"
LISTE_SURESI = 12 * 60 * 60  # sn
SAYFA_BOYU = 100
EN_COK_SAYFA = 10
ZAMAN_ASIMI = 8


class ProxyAlinamadi(Exception):
    """Anahtar girilmiş ama liste alınamadı; mesaj sağlayıcıyı anmaz."""


def _anahtar():
    from apps.bayi.models import GenelAyarlar

    return (GenelAyarlar.getir().proxy_api_anahtari or "").strip()


def _onbellek():
    from django.core.cache import caches

    return caches["kontor_sorgu"]


def _onbellek_anahtari(api_anahtari):
    ozet = hashlib.sha256(api_anahtari.encode()).hexdigest()[:16]
    return f"kontor-proxy-listesi:{ozet}"


def _sayfa(adres, api_anahtari):
    istek = urllib.request.Request(adres, headers={"Authorization": f"Token {api_anahtari}"})
    try:
        with urllib.request.urlopen(istek, timeout=ZAMAN_ASIMI) as yanit:
            return json.loads(yanit.read().decode("utf-8"))
    except urllib.error.HTTPError as hata:
        if hata.code in (401, 403):
            raise ProxyAlinamadi("Proxy API anahtarı geçersiz; Genel Ayarlar'dan kontrol edin.")
        raise ProxyAlinamadi(f"Proxy listesi alınamadı (HTTP {hata.code}).")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as hata:
        raise ProxyAlinamadi(f"Proxy listesi alınamadı: {getattr(hata, 'reason', hata)}")


def liste_cek(api_anahtari):
    """Geçerli proxy'ler: `http://kullanici:parola@adres:port` adresleri."""
    adres = f"{LISTE_ADRESI}?{urllib.parse.urlencode({'mode': 'direct', 'page': 1, 'page_size': SAYFA_BOYU})}"
    adresler = []
    for _ in range(EN_COK_SAYFA):
        veri = _sayfa(adres, api_anahtari)
        for kayit in veri.get("results") or []:
            if kayit.get("valid") is False or not kayit.get("proxy_address") or not kayit.get("port"):
                continue
            kullanici = urllib.parse.quote(str(kayit.get("username") or ""), safe="")
            parola = urllib.parse.quote(str(kayit.get("password") or ""), safe="")
            kimlik = f"{kullanici}:{parola}@" if kullanici else ""
            adresler.append(f"http://{kimlik}{kayit['proxy_address']}:{kayit['port']}")
        adres = veri.get("next")
        if not adres:
            break
    if not adresler:
        raise ProxyAlinamadi("Proxy listesi boş geldi.")
    return adresler


def listeyi_unut():
    """Önbellekteki listeyi siler: proxy'ler bağlanmıyorsa liste eskimiştir."""
    api_anahtari = _anahtar()
    if not api_anahtari:
        return
    try:
        _onbellek().delete(_onbellek_anahtari(api_anahtari))
    except Exception:
        logger.exception("Proxy listesi önbellekten silinemedi")


def rastgele_proxy(*, haric=()):
    """Listeden rastgele bir proxy adresi; anahtar yoksa `None`.

    `haric`: bu sorguda denenip bağlanılamayanlar — yeniden seçilmesin.
    Anahtar girilmiş ama liste alınamıyorsa `ProxyAlinamadi`: sorgu sunucunun
    kendi IP'sine sessizce düşmez.
    """
    api_anahtari = _anahtar()
    if not api_anahtari:
        return None
    anahtar = _onbellek_anahtari(api_anahtari)
    adresler = None
    try:
        adresler = _onbellek().get(anahtar)
    except Exception:
        logger.exception("Proxy listesi önbellekten okunamadı")
    if not adresler:
        adresler = liste_cek(api_anahtari)
        try:
            _onbellek().set(anahtar, adresler, LISTE_SURESI)
        except Exception:
            logger.exception("Proxy listesi önbelleğe yazılamadı")
    adaylar = [a for a in adresler if a not in haric] or adresler
    return random.choice(adaylar)
