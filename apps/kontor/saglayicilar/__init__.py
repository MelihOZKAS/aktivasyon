"""Kontör sağlayıcı adaptörleri.

Kontörü, paketi ve oyun pinini biz yüklemiyoruz; başka bir bayinin
sistemine (Znet/Gencan, Teknografi, kntryeni…) iletiyoruz. Her sağlayıcı
yazılımı burada bir sınıfla temsil edilir; sistemin geri kalanı yalnızca
`Adaptor` arayüzünü bilir. Yeni bir sağlayıcı yazılımı eklemek bu klasöre
bir dosya yazıp `_kayit()`e bir satır koymaktır — adres, kullanıcı adı ve
şifre panelden girilir (`kontor.Saglayici`).

Adaptör **ağ konuşur, veritabanına dokunmaz.** Sırayı yürütmek, parayı
oynatmak `apps.kontor.services`'in işidir; adaptör sağlayıcının düz metin
cevabını sade veri sınıflarına çevirir.

**Gönderimin üç sonucu vardır, ikisi değil.** Sağlayıcı işlemi kabul eder,
açıkça reddeder ya da cevabı anlaşılmaz. Ret güvenlidir: işlem orada hiç
açılmadı, sıradaki sağlayıcıya geçilir. Anlaşılmayan cevapta (zaman aşımı,
tanımadığımız bir kod) işlem orada açılmış **olabilir**; aynı numarayı
ikinci sağlayıcıya göndermek iki kez yüklemek demekti. O yüzden belirsiz
işlem askıya alınır ve yönetici karar verir.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


class SaglayiciHatasi(Exception):
    """Sağlayıcıya ulaşılamadı ya da cevabı okunamadı.

    `kesin_gitmedi` doğruysa istek sağlayıcıya hiç varmadı (bağlantı
    reddedildi, alan adı çözülmedi, adres yok): gönderim güvenle sıradaki
    sağlayıcıya aktarılabilir. Yanlışsa (zaman aşımı, 5xx) istek varmış
    olabilir.
    """

    def __init__(self, mesaj, *, kesin_gitmedi=False):
        super().__init__(mesaj)
        self.kesin_gitmedi = kesin_gitmedi


def bakiye_yetersiz_mi(metin):
    """Sağlayıcının reddi bizim bakiyemizin bitmesinden mi?

    Protokollerin hiçbiri bunu ayrı bir kodla söylemiyor (Znet'te de `OK|3`,
    "Yetersiz bakiye" metniyle); metinden okunur. Büyük harfli Türkçe
    ("YETERSİZ BAKİYE") ve URL kodlu ham cevap da tanınır.
    """
    from urllib.parse import unquote_plus

    metin = unquote_plus(metin or "").replace("İ", "i").replace("I", "ı").lower()
    return "bakiye" in metin or "bakıye" in metin or "balance" in metin


class Gonderim:
    """Sağlayıcının gönderime verdiği cevap."""

    KABUL = "kabul"
    RED = "red"
    BELIRSIZ = "belirsiz"


@dataclass
class GonderimSonucu:
    durum: str  # Gonderim.KABUL / RED / BELIRSIZ
    mesaj: str = ""
    uzak_ref: str = ""  # sağlayıcının kendi işlem numarası (Grafi, kntryeni)
    alis: Decimal = None  # sağlayıcının bu işlem için düştüğü tutar
    ham: str = ""


class Sorgu:
    """Sağlayıcının "yüklendi mi?" sorusuna cevabı."""

    BASARILI = "basarili"
    ISLEMDE = "islemde"
    IPTAL = "iptal"


@dataclass
class SorguSonucu:
    durum: str  # Sorgu.BASARILI / ISLEMDE / IPTAL
    mesaj: str = ""
    alis: Decimal = None
    ham: str = ""


@dataclass
class SaglayiciPaketVerisi:
    """Sağlayıcının fiyat listesindeki bir satır."""

    kod: str
    ad: str
    fiyat: Decimal
    operator: str = ""
    tip: str = ""


def tutar_coz(metin):
    """"12,50" / "12.50" / "{12.50}" → Decimal; okunamıyorsa None."""
    if metin is None:
        return None
    temiz = str(metin).strip().strip("{}[]").replace(" ", "")
    if not temiz:
        return None
    # "1.250,50" gibi binlik ayraçlı biçim: noktalar binlik, virgül kuruş.
    if "," in temiz and "." in temiz:
        temiz = temiz.replace(".", "")
    temiz = temiz.replace(",", ".")
    try:
        tutar = Decimal(temiz)
    except InvalidOperation:
        return None
    return tutar if tutar.is_finite() and tutar >= 0 else None


class Adaptor:
    """Bir sağlayıcı yazılımının yapması gereken işler.

    `saglayici` panelden girilmiş `kontor.Saglayici` kaydıdır; adres ve
    kimlik bilgileri oradan okunur.

    `denenmedi` işaretli adaptör canlı hesapla henüz doğrulanmamıştır:
    protokol eski sistemden aktarıldı ama ilk gönderim göz önünde yapılmalı,
    panel bunu yöneticiye söyler.
    """

    kod = ""
    ad = ""
    denenmedi = True
    varsayilan_sema = "https"
    # Sağlayıcıdan fiyat listesi çekilebiliyor mu? Çekilemiyorsa alış
    # fiyatları rotaya elle yazılır.
    paket_listesi_var = False

    def __init__(self, saglayici):
        self.saglayici = saglayici

    def taban(self):
        """Panelde girilen adres; şema yazılmamışsa adaptörün varsayılanı."""
        adres = (self.saglayici.adres or "").strip().rstrip("/")
        if "://" not in adres:
            adres = f"{self.varsayilan_sema}://{adres}"
        return adres

    def gonder(self, *, ref, hedef, uzak_kod, uzak_operator, uzak_tip):
        """İşlemi sağlayıcıya iletir: `GonderimSonucu`.

        `ref` bizim ürettiğimiz tekil numaradır (`Saglayici.ref_sayaci`);
        sağlayıcı aynı numarayla ikinci isteği reddeder.
        """
        raise NotImplementedError

    def sorgula(self, *, ref, uzak_ref):
        """Kabul edilmiş işlemin sonucu: `SorguSonucu`.

        Ağ hatası `SaglayiciHatasi` yükseltir; servis işlemi olduğu gibi
        bırakır, bir sonraki turda yeniden sorar.
        """
        raise NotImplementedError

    def paketleri_getir(self):
        """Sağlayıcının fiyat listesi: `list[SaglayiciPaketVerisi]`."""
        raise SaglayiciHatasi(f"{self.ad} fiyat listesi vermiyor; alış fiyatları elle girilir.")


def _kayit():
    from apps.kontor.saglayicilar.grafi import Grafi
    from apps.kontor.saglayicilar.kntryeni import KontorYeni
    from apps.kontor.saglayicilar.znet import Znet

    return {s.kod: s for s in (Znet, Grafi, KontorYeni)}


SAGLAYICILAR = {}


def saglayici_sinifi(kod):
    if not SAGLAYICILAR:
        SAGLAYICILAR.update(_kayit())
    try:
        return SAGLAYICILAR[kod]
    except KeyError:
        raise SaglayiciHatasi(f"Tanımsız sağlayıcı türü: {kod}")


def saglayici_secenekleri():
    if not SAGLAYICILAR:
        SAGLAYICILAR.update(_kayit())
    return [(kod, sinif.ad) for kod, sinif in SAGLAYICILAR.items()]
