"""Numarayı sesli okumak için kayıtlı ses birimleri.

Tarayıcının kendi konuşma sesi cihaza bağlıydı: Mac'te sıkıştırılmış "Yelda",
Windows Chrome'da "Tolga" geliyor, "kırk dört" sonunda tıslıyordu. Numara
3-3-2-2 gruplarla okunur ve her grup bu birimlerden kurulur: "532" =
"beş yüz" + "otuz iki", "45" = "kırk beş", "07" = "sıfır" + "yedi".
Birimler bir kez doğal bir sesle üretilip tek MP3'te durur (`static/ses/`),
tarayıcı onları dizer (`parca_numara_betik.html`).

Önce 20 tek kelime vardı ("kırk" + "beş"). Her kelime cümle sonu gibi
düşen tonla ve hırıltıyla bitiyordu, ek yerleri "zırt" diye duyuluyordu.
Birim büyüyünce iki haneli grupta hiç, üç haneli grupta tek ek yeri kalır.

Birimler parti parti tek kayıtta okutulur ki ton ve seviye aynı kalsın.
Kayıt sessiz yerlerinden bölünür. Burası saf hesaptır (ağa çıkmaz),
üretimi `manage.py rakam_sesleri` yapar.
"""

from array import array
import sys

BIRLER = ["", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"]
ONLAR = ["", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan"]


def iki_hane(sayi):
    """1..99 → "kırk beş"."""
    return " ".join(s for s in (ONLAR[sayi // 10], BIRLER[sayi % 10]) if s)


YUZLER = ["yüz"] + [f"{BIRLER[i]} yüz" for i in range(2, 10)]
SOZLER = ["sıfır"] + [iki_hane(i) for i in range(1, 100)] + YUZLER


PENCERE_MS = 10
# Kelimenin önünde ve arkasında bırakılan gerçek sessizlik. MP3 kodlayıcısı
# başa birkaç ms ekliyor; tarayıcı pencere içinde sesin başladığı yeri
# kendisi bulur, kayma bu payın içinde kalır.
DOLGU_MS = 80
KENAR_MS = 30
YUMUSATMA_MS = 8
HEDEF_RMS = 4500
TEPE_SINIRI = 30000


def ses_coz(veri, mime):
    """Gemini'nin gönderdiği sesi `(pcm, oran)`'a çevirir.

    Bazen ham PCM ("audio/L16;rate=24000"), bazen başlıklı WAV ("audio/wav")
    geliyor. WAV ham diye okunursa başlık baytları kaydın başında yüksek bir
    tık olarak duyuluyordu.
    """
    import io
    import re
    import wave

    if "wav" in (mime or "").lower():
        with wave.open(io.BytesIO(veri)) as dosya:
            if dosya.getsampwidth() != 2 or dosya.getnchannels() != 1:
                raise ValueError(f"Beklenmeyen WAV: {dosya.getnchannels()} kanal, {dosya.getsampwidth() * 8} bit")
            return dosya.readframes(dosya.getnframes()), dosya.getframerate()
    eslesme = re.search(r"rate=(\d+)", mime or "")
    return veri, int(eslesme.group(1)) if eslesme else 24000


def ornekler(pcm):
    """16 bit, little-endian tek kanal PCM → `array('h')`."""
    dizi = array("h")
    dizi.frombytes(pcm)
    if sys.byteorder == "big":
        dizi.byteswap()
    return dizi


def baytlar(dizi):
    """`array('h')` → 16 bit little-endian PCM baytları."""
    if sys.byteorder == "big":
        dizi = array("h", dizi)
        dizi.byteswap()
    return dizi.tobytes()


def _rms(dizi, bas, bit):
    if bit <= bas:
        return 0.0
    toplam = 0
    for i in range(bas, bit):
        toplam += dizi[i] * dizi[i]
    return (toplam / (bit - bas)) ** 0.5


def parcalara_bol(dizi, oran, bosluk_ms=300):
    """Konuşulan bölümleri `[(baslangic, bitis), ...]` örnek indisleriyle döndürür.

    Kelime içindeki kısa duraklar ("altmış"taki t, "sekiz"deki k) bölmesin
    diye `bosluk_ms`'den kısa sessizlik birleştirilir. Kaç parça çıkacağına
    güvenilmez: model fazladan bir şey söyleyebilir, sonda tık olabilir.
    Hangi parçanın hangi kelime olduğunu `eslestir` bulur.
    """
    pencere = oran * PENCERE_MS // 1000
    enerjiler = [_rms(dizi, i, min(i + pencere, len(dizi))) for i in range(0, len(dizi), pencere)]
    sirali = sorted(enerjiler)
    # Tepe yerine %99'luk dilim: tek bir tık eşiği yukarı itmesin.
    tepe = sirali[int(len(sirali) * 0.99)] if sirali else 0
    if not tepe:
        raise ValueError("Kayıt boş.")
    esik = tepe * 0.05
    bosluk = max(1, bosluk_ms // PENCERE_MS)

    parcalar, bas, sessiz, son = [], None, 0, 0
    for i, enerji in enumerate(enerjiler):
        if enerji > esik:
            if bas is None:
                bas = i
            sessiz, son = 0, i
        elif bas is not None:
            sessiz += 1
            if sessiz >= bosluk:
                parcalar.append((bas, son + 1))
                bas = None
    if bas is not None:
        parcalar.append((bas, son + 1))
    # Nefes ve tık kelime sayılmaz.
    parcalar = [p for p in parcalar if p[1] - p[0] >= 8]
    return [(b * pencere, min(s * pencere, len(dizi))) for b, s in parcalar]


def eslestir(duyulanlar, beklenen=SOZLER, sade=lambda m: m):
    """Parçaların yazıya dökümünde beklenen kelimeleri sırayla arar.

    `duyulanlar[i]` i. parçada duyulan metindir. Her beklenen kelime için
    sıradaki eşleşen parçanın indisi döner, eşleşmeyen parçalar (fazladan
    söz, tık) atlanır. Bir kelime bulunamazsa `ValueError`.
    """
    indisler, j = [], 0
    for soz in beklenen:
        while j < len(duyulanlar) and sade(duyulanlar[j]) != sade(soz):
            j += 1
        if j == len(duyulanlar):
            raise ValueError(f"\"{soz}\" kayıtta bulunamadı. Duyulanlar: {duyulanlar}")
        indisler.append(j)
        j += 1
    return indisler


def kelime_sesi(dizi, bas, bit, oran):
    """Parçayı kenar payıyla keser, seviyesini eşitler, uçlarını yumuşatır."""
    kenar = oran * KENAR_MS // 1000
    bas, bit = max(0, bas - kenar), min(len(dizi), bit + kenar)
    parca = [float(x) for x in dizi[bas:bit]]
    rms = (sum(x * x for x in parca) / len(parca)) ** 0.5 or 1.0
    carpan = HEDEF_RMS / rms
    tepe = max(abs(x) for x in parca) * carpan
    if tepe > TEPE_SINIRI:
        carpan *= TEPE_SINIRI / tepe
    yumusatma = min(oran * YUMUSATMA_MS // 1000, len(parca) // 2)
    for i in range(yumusatma):
        k = i / yumusatma
        parca[i] *= k
        parca[-1 - i] *= k
    return array("h", (int(round(x * carpan)) for x in parca))


def birlestir(kelimeler, oran):
    """Kelimeleri sessizlik dolgusuyla tek kayıtta toplar.

    `(pcm_bytes, {kelime: [baslangic_sn, bitis_sn]})` döner; aralık dolguyu
    da kapsayan penceredir.
    """
    dolgu = array("h", [0] * (oran * DOLGU_MS // 1000))
    tum = array("h")
    konumlar = {}
    for soz, ses in kelimeler:
        bas = len(tum)
        tum.extend(dolgu)
        tum.extend(ses)
        tum.extend(dolgu)
        konumlar[soz] = [round(bas / oran, 3), round(len(tum) / oran, 3)]
    return baytlar(tum), konumlar


def wav(pcm, oran):
    """Ham PCM'i WAV başlığıyla sarar (doğrulama için Gemini'ye gider)."""
    import io
    import wave

    tampon = io.BytesIO()
    with wave.open(tampon, "wb") as dosya:
        dosya.setnchannels(1)
        dosya.setsampwidth(2)
        dosya.setframerate(oran)
        dosya.writeframes(pcm)
    return tampon.getvalue()
