"""eSIM sağlayıcı adaptörleri.

Her sağlayıcı (eSIM Access, ileride başkaları) burada bir sınıfla temsil
edilir; sistemin geri kalanı yalnızca `Adaptor` arayüzünü bilir. Yeni bir
sağlayıcı eklemek bu klasöre bir dosya yazıp `SAGLAYICILAR` sözlüğüne kaydı
koymaktır — anahtarlar, kâr oranı ve açık/kapalı hâli panelden girilir
(`esim.Saglayici`). Fiyat karşılaştırması, sipariş ve iade sağlayıcıdan
bağımsızdır: hangisi ucuzsa ondan alınır.

Adaptör **ağ konuşur, veritabanına dokunmaz.** Paket listesini `Paket`
kayıtlarına çevirmek, parayı oynatmak `apps.esim.services`'in işidir; adaptör
yalnızca sağlayıcının cevabını sade veri sınıflarına çevirir ve hatayı
`SaglayiciHatasi` olarak yükseltir.
"""

from dataclasses import dataclass, field
from decimal import Decimal


class SaglayiciHatasi(Exception):
    """Sağlayıcı isteği reddetti ya da ulaşılamadı; sebebi mesajda."""

    def __init__(self, mesaj, kod=""):
        super().__init__(mesaj)
        self.kod = kod


@dataclass
class PaketVerisi:
    """Sağlayıcının kataloğundaki bir paket, sağlayıcıdan bağımsız biçimde."""

    kod: str
    ad: str
    ulkeler: list  # Alpha-2 ISO kodları
    hacim_bayt: int
    sure_gun: int
    alis_usd: Decimal
    slug: str = ""
    hiz: str = ""
    operatorler: str = ""
    aciklama: str = ""
    ulke_adlari: dict = field(default_factory=dict)  # kod → sağlayıcının verdiği ad


@dataclass
class ProfilVerisi:
    """Sipariş sonrası tahsis edilen eSIM profili."""

    esim_no: str
    iccid: str
    ac: str  # LPA:1$smdp$aktivasyon-kodu
    qr_url: str = ""
    kisa_url: str = ""
    apn: str = ""
    durum: str = ""  # sağlayıcının paket durumu (GOT_RESOURCE, IN_USE, USED_UP…)
    kurulum_durumu: str = ""  # SM-DP+ profil durumu (RELEASED, ENABLED, DELETED…)
    eid: str = ""  # profilin indirildiği cihazın eSIM çipi; boşsa hiç okutulmamış
    aktivasyon_zamani: str = ""  # ilk ağ bağlantısı; boşsa hat hiç bağlanmamış


@dataclass
class YuklemeVerisi:
    """Var olan eSIM'e paket yüklemenin sonucu."""

    yukleme_no: str = ""
    toplam_hacim_bayt: int = 0
    toplam_sure_gun: int = 0
    son_kullanma: str = ""


class Adaptor:
    """Bir sağlayıcının yapması gereken işler.

    `saglayici` panelden girilmiş `esim.Saglayici` kaydıdır; anahtarlar
    oradan okunur.

    `denenmedi` işaretli adaptör sağlayıcının belgesinden yazılmış, canlı
    anahtarla henüz doğrulanmamıştır: ilk eşitleme ve ilk sipariş göz
    önünde yapılmalı, panel bunu yöneticiye söyler.
    """

    kod = ""
    ad = ""
    denenmedi = False

    def __init__(self, saglayici):
        self.saglayici = saglayici

    def paketleri_getir(self):
        """Satılabilir bütün paketler: `list[PaketVerisi]`."""
        raise NotImplementedError

    def bakiye(self):
        """Sağlayıcıdaki ön ödemeli bakiye, USD `Decimal`."""
        raise NotImplementedError

    def siparis_ver(self, paket_kodu, islem_no, alis_usd):
        """Bir profil sipariş eder: `(sağlayıcı sipariş no, profil | None)`.

        Profili siparişle birlikte veren sağlayıcı (eSIM Go, Airalo) onu
        hemen döndürür; eşzamansız çalışan (eSIM Access) `None` verir ve
        profil sonra `profil_getir` ile sorulur.

        `islem_no` bizim ürettiğimiz tekil anahtardır: destekleyen sağlayıcıda
        aynı anahtarla ikinci istek yeni sipariş açmamalı.
        """
        raise NotImplementedError

    def profil_getir(self, saglayici_siparis_no):
        """Profil hazırsa `ProfilVerisi`, hâlâ hazırlanıyorsa `None`."""
        raise NotImplementedError

    def iptal_et(self, esim_no, *, iccid="", paket_kodu=""):
        """Kullanılmamış profili iptal eder; sağlayıcı reddederse hata yükseltir.

        Hangi kimliğin gerektiği sağlayıcıya göre değişir: eSIM Access kendi
        eSIM numarasını, eSIM Go ICCID ile paket kodunu, Airalo ICCID'yi ister.
        """
        raise NotImplementedError

    # Yükleme (top-up): satılmış eSIM'e yeni paket. Desteklemeyen sağlayıcı
    # `SaglayiciHatasi` yükseltir; bayi ekranında düğme sebebiyle kapanır.

    def yukleme_paketleri(self, esim_no, *, iccid="", paket_kodu=""):
        """Bu eSIM'e yüklenebilecek paketler: `list[PaketVerisi]`."""
        raise SaglayiciHatasi(f"{self.ad} bu sistemde yükleme desteklemiyor.")

    def yukle(self, esim_no, yukleme_kodu, islem_no, alis_usd, *, iccid=""):
        """Paketi eSIM'e yükler; `YuklemeVerisi` döndürür."""
        raise SaglayiciHatasi(f"{self.ad} bu sistemde yükleme desteklemiyor.")


def _kayit():
    from apps.esim.saglayicilar.airalo import Airalo
    from apps.esim.saglayicilar.esimaccess import EsimAccess
    from apps.esim.saglayicilar.esimgo import EsimGo

    return {s.kod: s for s in (EsimAccess, EsimGo, Airalo)}


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
