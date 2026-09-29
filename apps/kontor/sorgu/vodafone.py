"""Vodafone numara sorgusu: istemciyi sistemin sorgu biçimine bağlar.

İstek atan kod `vodafone_istemci.py`'dedir (yönetimin yazdığı istemci,
olduğu gibi duruyor). Burası yalnızca iki adımı çağırır — publicToken al,
Kolay Paketleri getir — ve cevabı `SorguPaketi` listesine çevirir.

Hat sahibinin maskeli adı (`getMaskedUserName`) yalnızca kategoride
"hat sahibini göster" açıkken istenir; ekranda gösterilir, saklanmaz.
Alınamazsa paket sorgusu yine sonuç verir — ad teyit içindir, şart değil.

Eşleşme `reasonCode` alanıyladır (17776…): kataloğumuzdaki paketin kupür
kodu (`Paket.kod`) bu rakamdır, sağlayıcıya giden kod da odur. Bir süre
`id` alanı okunuyordu; o alan Vodafone'un iç adıdır
(`/Prepaid/KolayPack/KP_INTEGRATED_OFFER_7`, `BKPM046`) ve katalog bu
kodlarla dolmuştu. `reasonCode`u olmayan paket atlanır — `id`ye geri
düşülmez, yanlış kod sessizce kataloğa girmesin.
"""

from decimal import Decimal, InvalidOperation

from apps.kontor.sorgu import SorguHatasi, SorguPaketi, SorguSonucu, kaynak


def paketleri_coz(cevap):
    """`getKolayPacks` cevabı → `list[SorguPaketi]`. Ağa çıkmaz; test edilebilir."""
    paketler = []
    for kategori in (cevap or {}).get("kolayPackCategory") or []:
        for paket in kategori.get("kolayPacks") or []:
            kod = str(paket.get("reasonCode") or "").strip()
            if not kod:
                continue
            ucret = paket.get("usageFee") or {}
            try:
                fiyat = Decimal(str(ucret.get("value"))) if ucret.get("value") is not None else None
            except InvalidOperation:
                fiyat = None
            paketler.append(
                SorguPaketi(
                    kod=kod,
                    ad=str(paket.get("description") or "").strip(),
                    aciklama=str(paket.get("detail") or "").strip(),
                    fiyat=fiyat,
                )
            )
    return paketler


# İstek bayinin sayfa isteği içinde çalışır; gunicorn işçisi o sürede başka
# kimseye hizmet edemez (üç işçi var). İki adım × 8 sn = en kötü 16 sn:
# Vodafone yavaşlarsa bayi sebebini görür, site kilitlenmez.
ZAMAN_ASIMI = 8


@kaynak("vodafone", "Vodafone Kolay Paket sorgusu")
def sorgula(numara, *, sahip=False):
    import requests

    from apps.kontor.sorgu.vodafone_istemci import VodafoneSorgu

    istemci = VodafoneSorgu(timeout=ZAMAN_ASIMI)
    try:
        token = (istemci.get_public_token(numara) or {}).get("publicToken")
        if not token:
            raise SorguHatasi("Vodafone bu numara için sorgu anahtarı vermedi; numara Vodafone'da olmayabilir.")
        paketler = paketleri_coz(istemci.get_kolay_packs(token))
        return SorguSonucu(paketler, sahip=_sahip(istemci, numara) if sahip else "")
    except requests.RequestException as hata:
        raise SorguHatasi(f"Vodafone'a ulaşılamadı: {hata}")
    except ValueError:
        raise SorguHatasi("Vodafone'un cevabı okunamadı.")


def _sahip(istemci, numara):
    """Maskeli ad; alınamazsa boş — paket sonucu bunun yüzünden düşmez."""
    try:
        cevap = istemci.get_masked_user_name(numara) or {}
    except Exception:
        return ""
    if (cevap.get("result") or {}).get("result") != "SUCCESS":
        return ""
    return str(cevap.get("maskedUserName") or "").strip()[:80]
