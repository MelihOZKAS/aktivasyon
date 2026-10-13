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
    maliyet: Decimal = None  # faturada sağlayıcının kendi bedeli (alış = fatura + bu + faiz)


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


@dataclass
class SaglayiciKurumu:
    """Sağlayıcının fatura kurum listesindeki bir satır (`kurum_listesi.php`)."""

    kod: str  # KURUM ID: fatura bununla gönderilir
    ad: str
    sorgu_kodu: str = ""  # tekil değil; aynı kurumun birden çok kaydında aynı gelir
    maliyet: Decimal = None  # sağlayıcının fatura başına bedeli


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

    # -- Oyun / e-pin -----------------------------------------------------
    #
    # Ayrı bir pin servisi olan yazılım (Znet: `pin_ekle.php`) bunları ezer.
    # Olmayanda oyun da kontörün kapısından gider: kategori ve paket kodları
    # o sağlayıcının kontör protokolüne göre yazılır.

    def oyun_gonder(self, *, ref, hedef, uzak_kod, uzak_operator, uzak_tip):
        return self.gonder(ref=ref, hedef=hedef, uzak_kod=uzak_kod, uzak_operator=uzak_operator, uzak_tip=uzak_tip)

    def oyun_sorgula(self, *, ref, uzak_ref):
        return self.sorgula(ref=ref, uzak_ref=uzak_ref)

    # -- Fatura -----------------------------------------------------------
    #
    # Faturayı sağlayıcı öder; biz kurum numarasıyla gönderir, sonucunu
    # sorarız (`apps.fatura.services`). Kontördeki üç sonuç burada da
    # geçerlidir: kabul (`alis` = sağlayıcıdan düşen toplam), ret (orada
    # açılmadı), belirsiz (açılmış olabilir — yönetim karar verir).

    fatura_var = False

    def fatura_gonder(self, *, ref, kurum_id, abone_adi, son_odeme_tarihi, tesisat_no, fatura_no, tutar):
        """Tek faturayı ödemeye gönderir: `GonderimSonucu`."""
        raise SaglayiciHatasi(f"{self.ad} fatura ödemesi almıyor.", kesin_gitmedi=True)

    def fatura_sorgula(self, refler):
        """{ref: SorguSonucu}. Listede olmayan ref sürüyor demektir (toplu
        sorguda sağlayıcı bekleyenleri yazmıyor)."""
        raise SaglayiciHatasi(f"{self.ad} fatura sonucu vermiyor.")

    def fatura_kurumlari(self):
        """Sağlayıcının fatura kurumları: `list[SaglayiciKurumu]`."""
        raise SaglayiciHatasi(f"{self.ad} fatura kurum listesi vermiyor.")


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
