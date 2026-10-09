# Fatura robotu ↔ Django sözleşmesi

> **Django tarafı kuruldu** (`apps/fatura`). Robotu bağlamak için: yönetim
> panelinde **Fatura → Sorgu Robotları** → robot ekle (ör. `ev-laptop`) →
> **Yeni anahtar**. Ekranda hazır bir `ayar.json` bloğu çıkar (adres
> `https://www.aktivasyoncu.com.tr` — **www'li**: www'siz alan 301 ile
> yönleniyor ve yönlendirmede POST gövdesi düşüyor); olduğu gibi bu
> klasördeki `ayar.json`'a yapıştır, `isci.bat`'ı başlat. Sunucu robotu
> anahtarından tanır; istekteki `robot` alanı yalnızca bilgi amaçlıdır.

Bu dosya, Django tarafının (ayrı yazılacak) robotla nasıl konuşacağını anlatır.
Robot (`robot.py` / `isci.py`) laptopta çalışır, Django sunucuda. **Robot
Django'ya sorar** (pull): laptop dışarı port açmaz. Para/ödeme bu sürümde
**yoktur** — robot yalnızca sorgu yapar.

---

## 1. Kurumu nasıl tanırız? (senin sorun)

Bütün kurumlar siteden çekilip **`kurumlar.json`** dosyasına yazıldı (33 kurum,
bu klasörde). Django bu dosyadan kurum tablosunu **seed eder**; başka bir
senkron uğraşı yok. Her kurumun **tekil bir `id`si** var — çünkü sağlayıcının
`api_adi`'si tekil değil (ör. 171 dört "TL Yükle"de tekrar ediyor). Bu yüzden
kurum adından türetilen tekil id kullanıyoruz: `vodafone`, `turkcell`,
`100-tl-yukle-plaka`…

`kurumlar.json` içindeki her kayıt:
```json
{
  "id": "vodafone",
  "kurum_adi": "Vodafone",
  "api_adi": "3",
  "kategori": 17,
  "aktif": true,
  "token": "JmlkPTk...",
  "alan_etiketi": "Telefon Numarası",
  "min_hane": 10,
  "max_hane": 10,
  "sadece_rakam": true,
  "tahmini_sorgusuz": false,
  "aciklama": "Telefon numarasını başında 0 olmadan yazın."
}
```

- **Django `id`'yi saklar ve robota onunla gönderir.** (`kurum_adi` de gider,
  teyit için.)
- `min_hane`/`max_hane` → bayi formunda hane sayısı; `sadece_rakam` → harf
  girilemez. Django bu kurallarla numarayı **talep açmadan önce** doğrular.
- `token` bilgi olarak durur; robot sorgu anında id→token çevirir (aşağıda).
- Yönetici her kuruma **bayi satış fiyatı**, **müşteri tavsiye fiyatı** ekler ve
  **sorgulu/sorgusuz**'u kesinler (`tahmini_sorgusuz` yalnızca ön tahmin:
  "TL Yükle/Plaka/TC İle" olanlar sabit tutarlı, sorgu adımı atlanır).

> Token: robot `id→token` haritasını kendi klasöründeki `kurumlar.json`'dan
> okur; site sürekli taranmaz. Liste **yalnızca elle** yenilenir:
> `katalog.bat` (siteyi tarar, `kurumlar.json`'u yazar, `ayar.json` varsa
> listeyi `POST /fatura/robot/katalog/` ile Django'ya da yollar). Çalışan
> işçi dosyanın değiştiğini görüp yeni listeyi kendisi okur.

---

## 2. Sorgu kuyruğu (pull)

### a) Robot iş ister
`GET /fatura/robot/is/?robot=ev-laptop`
Sunucu bekleyen bir talebi **atomik kilitleyip** (SELECT ... FOR UPDATE SKIP
LOCKED) verir. Böylece **aynı numara iki robota gitmez** — 5 robot da aynı anda
sorsa her biri farklı iş kapar.
```json
// iş varsa:
{"var": true, "talep": {"talep_id": 1234, "kurum_id": "vodafone", "kurum_adi": "Vodafone", "numara": "5332590138"}}
// yoksa:
{"var": false}
```

### b) Robot sonucu yazar
`POST /fatura/robot/sonuc/`
```json
{
  "talep_id": 1234,
  "robot": "ev-laptop",
  "veri": {
    "durum": "bulundu",
    "mesaj": "",
    "abone_adi": "M***** A*****",
    "tesisat_no": "5332590138",
    "kurum": "Vodafone",
    "odenmesi_gereken": 410.0,
    "faturalar": [
      {
        "fatura_no": "FD60950NCB9D53",
        "son_odeme_tarihi": "14.10.2026",
        "fatura_bedeli": "390,00",
        "fatura_bedeli_tl": 390.0,
        "g_hizmet_bedeli": 0.0,
        "islem_bedeli": 20.0,
        "toplam_tutar": 410.0,
        "odeme_token": "yYbSp7CZ..."
      }
    ]
  }
}
```
Bayinin sayfası Django'yu HTMX ile yoklar (kontördeki "işlemde" gibi) ve sonucu
görür.

### `durum` değerleri
| durum | anlam | bayiye |
|---|---|---|
| `bulundu` | fatura(lar) var | listeyi göster |
| `borc_yok` | abone bulundu, ödenecek fatura yok | "borç yok" |
| `hata` | sağlayıcı reddetti (ör. gece 23:00-06:00 bloğu) | `mesaj`'ı göster |

Robot/altyapı hatası (oturum düştü, zaman aşımı) ayrı gelir:
```json
{"talep_id": 1234, "robot": "ev-laptop", "basarisiz": true, "hata": "Oturum düştü"}
```

---

## 3. Nabız (hangi robot açık, oturum sağlam mı)
Robotun **her** doğrulanmış isteği (5 sn'de bir "iş var mı?") sunucuda nabız
sayılır; çevrimiçi göstergesi ondan beslenir. Ayrı nabız isteği yalnızca
durum değişince (boş/meşgul, oturum düştü) ya da dakikada bir gider:

`POST /fatura/robot/kalp/`
```json
{"robot": "ev-laptop", "durum": "bos", "oturum": "canli", "mesai": "08:00-23:00"}
```
`mesai`: robotun çalışma saatleri (`ayar.json` → `calisma_saatleri`). Robot bu
saatlerin dışında **hiç istek atmaz**, dakikada bir yalnızca kendi saatine
bakar. Django saatleri robotun kaydına yazar; robot susunca bayiye "sistem
bağlı değil" yerine "Fatura sorgusu 08:00–23:00 arasında yapılır" der.
`durum`: `bos|mesgul`. `oturum`: `canli|dustu`. Yönetim panelinde "şu an açık
robotlar" ve "oturumu düşenler" bundan görünür; oturum düşünce yönetici
laptopta yeniden giriş yapar (`giris.bat`).

---

## 4. Güvenlik / notlar
- Bütün uçlar `Authorization: Bearer <API_KEY>` ister (paylaşılan gizli anahtar,
  `ayar.json`'da). İnternete açık bir uç olduğu için anahtarsız istek 401 döner.
- `odeme_token` her faturada gelir ama **ödeme bu sürümde yapılmaz**; Django
  saklar, ödeme ileride (elle ya da ayrı, dikkatli bir adımda) yapılır.
- Robot talebi işlerken `kurum_id`'yi `kurumlar.json`'dan token'a çevirir.
  Kurum dosyada yoksa ya da token eskimişse sorgu hemen `basarisiz` döner
  (bayi zaman aşımını beklemez); robotun terminali "katalog.bat ile yenile"
  der, yönetim sebebi Sorgular listesinde görür.
- `POST /fatura/robot/katalog/` yalnızca `katalog.bat` çalıştırılınca gelir.
