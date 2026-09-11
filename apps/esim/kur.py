"""USD kuru: TCMB'den çekilir, Genel Ayarlar'a yazılır.

eSIM alışları USD, satış ₺. Kur eskiyse fiyat maliyetin altına düşebilir;
bu yüzden kur elle de girilebilir ama günlük güncellenmesi beklenir
(`manage.py kur_guncelle`, paket listesindeki düğme).

TCMB `today.xml` hafta sonu ve tatilde son iş gününün kurunu verir; bu
istenen davranıştır. Satış kuru (`ForexSelling`) alınır: bankadan dolar
alırken ödenen fiyat odur.
"""

import logging
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation

from django.utils import timezone

logger = logging.getLogger(__name__)

TCMB_ADRESI = "https://www.tcmb.gov.tr/kurlar/today.xml"
ZAMAN_ASIMI = 15


class KurAlinamadi(Exception):
    pass


def tcmb_usd_satis():
    """TCMB'nin bugünkü USD döviz satış kuru, `Decimal`."""
    try:
        with urllib.request.urlopen(TCMB_ADRESI, timeout=ZAMAN_ASIMI) as yanit:
            govde = yanit.read()
    except (urllib.error.URLError, OSError) as hata:
        raise KurAlinamadi(f"TCMB'ye ulaşılamadı: {hata}")

    try:
        kok = ET.fromstring(govde)
    except ET.ParseError as hata:
        raise KurAlinamadi(f"TCMB yanıtı okunamadı: {hata}")

    for para in kok.findall("Currency"):
        if para.get("CurrencyCode") != "USD":
            continue
        metin = (para.findtext("ForexSelling") or "").strip()
        try:
            kur = Decimal(metin)
        except InvalidOperation:
            raise KurAlinamadi(f"TCMB USD satış kuru okunamadı: {metin!r}")
        if kur <= 0:
            raise KurAlinamadi("TCMB USD satış kuru sıfır geldi.")
        return kur
    raise KurAlinamadi("TCMB yanıtında USD yok.")


def kuru_guncelle():
    """TCMB'den çekip Genel Ayarlar'a yazar; yeni kuru döndürür."""
    from apps.bayi.models import GenelAyarlar

    kur = tcmb_usd_satis()
    ayar = GenelAyarlar.getir()
    ayar.usd_kuru = kur.quantize(Decimal("0.0001"))
    ayar.usd_kuru_tarihi = timezone.now()
    ayar.save(update_fields=["usd_kuru", "usd_kuru_tarihi", "guncelleme_tarihi"])
    return ayar.usd_kuru
