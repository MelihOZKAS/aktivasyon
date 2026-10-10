"""Numara sorgusu: bu numara hangi paketleri alabilir?

Bayi numarayı yazar, bir **sorgu kaynağı** o numaranın alabileceği
paketleri döndürür; ekran bunları kataloğumuzdaki paketlerle kupür
koduna göre eşleştirir. Hangi kategoride hangi kaynağın kullanılacağı
veridir (`Kategori.sorgu_kaynagi`).

Kaynak eklemek: bu klasöre bir dosya koyup fonksiyonu `@kaynak` ile
kaydetmek. Klasördeki bütün dosyalar açılışta kendiliğinden yüklenir,
başka bir yere satır eklemek gerekmez::

    # apps/kontor/sorgu/benim_kaynagim.py
    from apps.kontor.sorgu import SorguHatasi, SorguPaketi, SorguSonucu, kaynak

    @kaynak("benim-kaynagim", "Benim sorgum")
    def sorgula(numara, *, sahip=False):   # numara: "5321234567"
        ...                                # hata olursa: raise SorguHatasi("sebep")
        paketler = [SorguPaketi(kod="17776", ad="Kolay Paket 15", gun=30), ...]
        return SorguSonucu(paketler, sahip="Ah*** Yı***" if sahip else "")

`sahip` yalnızca kategoride "hat sahibini göster" açıkken doğrudur;
kapalıyken kaynak hat sahibinin adını hiç istememeli. Düz liste dönmek de
yeter (sahipsiz sonuç sayılır).

Sonra panelde kategorinin **Numara sorgusu** kutusundan seçilir.

Kurallar (servis uygular, kaynak düşünmez):
  · Sorgu **salt okumadır**; yükleme göndermez, para oynatmaz.
  · Sorgu satışı hiçbir zaman durdurmaz: kaynak hata verirse ya da
    susarsa bayi sebebini görür, paket listesi eskisi gibi seçilebilir.
  · Aynı numara `ONBELLEK_SURESI` içinde ikinci kez sorulmaz.

**Cevabı beklenen kaynak** (robot): sorguyu kuyruğa koyup hemen döner,
cevap henüz yoksa `SorguBekleniyor` yükseltir. Bayi ekranı kendini birkaç
saniyede bir yeniler, gönderim planı işlemi sırada bekletir; ikisi de
kaynağı yeniden çağırır, kaynak hazır sonucu o zaman döndürür. Kimse cevabı
istek içinde beklemez — gunicorn işçisi tarayıcının sorgusunu beklerken
siteye hizmet edemezdi.
"""

import importlib
import pkgutil
from dataclasses import dataclass
from decimal import Decimal


class SorguHatasi(Exception):
    """Kaynak cevap vermedi ya da numarayı sorgulayamadı; sebebi mesajda."""


class SorguBekleniyor(SorguHatasi):
    """Sorgu kuyrukta ya da robotta; birkaç saniye sonra yeniden sorulur.

    `SorguHatasi`'dır: bunu tanımayan bir çağıran sorguyu yapılamamış sayar
    ve satış sürer — bekleyen sorgu yüzünden hiçbir yer kilitlenmez.
    """


@dataclass
class SorguPaketi:
    kod: str
    ad: str = ""
    aciklama: str = ""
    gun: int = 0
    fiyat: Decimal = None
    # İçerik kaynak söylüyorsa dolar; Kataloğa ekle paketi bununla açar
    # (ucuz alternatif hesabı dakika, GB ve güne bakar).
    dakika: int = 0
    internet_mb: int = 0
    sms: int = 0


@dataclass
class SorguSonucu:
    paketler: list
    # Hat sahibinin maskeli adı (Ah*** Yı***). Yalnızca ekranda gösterilir,
    # hiçbir yere yazılmaz; bayi yanlış numarayı yüklemeden önce teyit eder.
    sahip: str = ""


@dataclass
class Kaynak:
    kod: str
    ad: str
    fonksiyon: object


KAYNAKLAR = {}
_yuklendi = False


def kaynak(kod, ad):
    """Sorgu fonksiyonunu kaydeder: `fonksiyon(numara, *, sahip) -> SorguSonucu | list`."""

    def kaydet(fonksiyon):
        KAYNAKLAR[kod] = Kaynak(kod=kod, ad=ad, fonksiyon=fonksiyon)
        return fonksiyon

    return kaydet


def _yukle():
    global _yuklendi
    if _yuklendi:
        return
    _yuklendi = True
    for modul in pkgutil.iter_modules(__path__):
        importlib.import_module(f"{__name__}.{modul.name}")


def kaynak_getir(kod):
    _yukle()
    return KAYNAKLAR.get(kod)


def kaynak_secenekleri():
    _yukle()
    return [(k.kod, k.ad) for k in KAYNAKLAR.values()]
