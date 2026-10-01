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

**`reasonCode` her zaman tekil değildir.** "Sana özel" (entegre teklif)
paketlerin bir kısmı aynı kodu taşır: 5G Tam Senlik 1…40 GB'nin sekizi de
`13239`. Kodla tekilleştiren sorgu hepsini tek pakete çökertiyor, yalnızca
biri görünüyordu. Paylaşılan kodda iç kod `kod-paket-adı-tutar` olur
(`13239-5g-tam-senlik-30-gb-1060`). **Tutar koda girer** çünkü bu teklifler
kişiye özel fiyatlıdır: aynı 30 GB bir numarada 1.150, diğerinde 1.060 ₺
geliyordu ve tek koda düşünce fiyatı sürekli değişiyordu. Her fiyat ayrı
pakettir — kendi bayi fiyatı, karşı site kodu ve alışıyla; yeni bir fiyat
Operatörde Görülen'e "Yeni" olarak düşer.
`id` (`KP_INTEGRATED_OFFER_2`) kullanılmaz: müşteriye göre değişen bir yuva
numarasıdır. Bir numarada bu paketlerden yalnızca biri çıkabilir; kod o
zaman da aynı kalsın diye bilinen paylaşılan kodlar `PAYLASILAN_KODLAR`'da
durur. Sağlayıcıya bu iç kod değil, rotadaki karşı site kodu gider.
"""

from collections import Counter
from decimal import Decimal, InvalidOperation

from apps.katalog.utils import turkce_slug
from apps.kontor.sorgu import SorguHatasi, SorguPaketi, SorguSonucu, kaynak

# Birden çok paketin ortak kullandığı bilinen `reasonCode`lar. Bir cevapta
# tekrar eden kod da kendiliğinden paylaşılan sayılır; buradaki liste, pakette
# tek başına göründüğü numarada da kodun aynı kalması içindir.
PAYLASILAN_KODLAR = {"13239"}


def tutar_metni(fiyat):
    """Koda girecek tutar: 1060.0 → "1060", 999.90 → "999.9"."""
    metin = f"{Decimal(fiyat).quantize(Decimal('0.01')):f}"
    return metin.rstrip("0").rstrip(".") if "." in metin else metin


def _paketler(cevap):
    for kategori in (cevap or {}).get("kolayPackCategory") or []:
        yield from kategori.get("kolayPacks") or []


def paketleri_coz(cevap):
    """`getKolayPacks` cevabı → `list[SorguPaketi]`. Ağa çıkmaz; test edilebilir."""
    sayilar = Counter(str(p.get("reasonCode") or "").strip() for p in _paketler(cevap))
    paketler = []
    for paket in _paketler(cevap):
        kod = str(paket.get("reasonCode") or "").strip()
        if not kod:
            continue
        ad = str(paket.get("description") or "").strip()
        ucret = paket.get("usageFee") or {}
        try:
            fiyat = Decimal(str(ucret.get("value"))) if ucret.get("value") is not None else None
        except InvalidOperation:
            fiyat = None
        if (sayilar[kod] > 1 or kod in PAYLASILAN_KODLAR) and ad:
            kod = f"{kod}-{turkce_slug(ad)}" + (f"-{tutar_metni(fiyat)}" if fiyat is not None else "")
            kod = kod[:60]
        paketler.append(
            SorguPaketi(
                kod=kod,
                ad=ad,
                aciklama=str(paket.get("detail") or "").strip(),
                fiyat=fiyat,
            )
        )
    return paketler


# İstek bayinin sayfa isteği içinde çalışır; gunicorn işçisi o sürede başka
# kimseye hizmet edemez (üç işçi var). İki adım × 8 sn = en kötü 16 sn:
# Vodafone yavaşlarsa bayi sebebini görür, site kilitlenmez.
ZAMAN_ASIMI = 8

# Proxy'ye bağlanılamazsa bu kadar farklı proxy denenir. Yalnızca proxy
# bağlantı hatasında (hızlı düşer); zaman aşımında yeniden denenmez, bayi
# 8 sn'yi birkaç kez beklemesin.
PROXY_DENEMESI = 2


def istemci_ac(*, haric=()):
    """Vodafone istemcisi; Genel Ayarlar'da proxy anahtarı varsa rastgele bir proxy'yle.

    İstemcinin kendi koduna dokunulmaz (yönetimin yazdığı kod): proxy
    oturumun `proxies` alanına verilir. Dönüş: (istemci, proxy adresi | None).
    """
    from apps.kontor.sorgu.proxy import ProxyAlinamadi, rastgele_proxy
    from apps.kontor.sorgu.vodafone_istemci import VodafoneSorgu

    istemci = VodafoneSorgu(timeout=ZAMAN_ASIMI)
    try:
        proxy = rastgele_proxy(haric=haric)
    except ProxyAlinamadi as hata:
        raise SorguHatasi(str(hata))
    if proxy:
        istemci.session.proxies = {"http": proxy, "https": proxy}
    return istemci, proxy


@kaynak("vodafone", "Vodafone Kolay Paket sorgusu")
def sorgula(numara, *, sahip=False):
    import requests

    denenen = []
    for deneme in range(PROXY_DENEMESI):
        istemci, proxy = istemci_ac(haric=denenen)
        try:
            token = (istemci.get_public_token(numara) or {}).get("publicToken")
            if not token:
                raise SorguHatasi("Vodafone bu numara için sorgu anahtarı vermedi; numara Vodafone'da olmayabilir.")
            paketler = paketleri_coz(istemci.get_kolay_packs(token))
            return SorguSonucu(paketler, sahip=_sahip(istemci, numara) if sahip else "")
        except requests.exceptions.ProxyError:
            # Proxy'nin adresi mesajda görünmesin: kimlik bilgisi taşır.
            if proxy is None or deneme == PROXY_DENEMESI - 1:
                if proxy is not None:
                    # Art arda bağlanılamadı: liste eskimiş olabilir, sonraki sorgu tazesini çeksin.
                    from apps.kontor.sorgu.proxy import listeyi_unut

                    listeyi_unut()
                raise SorguHatasi("Sorgu bağlantısı kurulamadı; biraz sonra yeniden deneyin.")
            denenen.append(proxy)
        except requests.RequestException as hata:
            if proxy:
                raise SorguHatasi(f"Vodafone'a ulaşılamadı ({type(hata).__name__}).")
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
