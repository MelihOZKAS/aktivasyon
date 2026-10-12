# Fatura robotu ↔ Django sözleşmesi

> **Django tarafı kuruldu** (`apps/fatura`). Robotu bağlamak için: yönetim
> panelinde **Sorgu Robotu → Robotlar** → robot ekle (ör. `ev-laptop`) →
> **Yeni anahtar**. Ekranda hazır bir `ayar.json` bloğu çıkar (adres
> `https://www.aktivasyoncu.com.tr` — **www'li**: www'siz alan 301 ile
> yönleniyor ve yönlendirmede POST gövdesi düşüyor); olduğu gibi bu
> klasördeki `ayar.json`'a yapıştır, `isci.bat`'ı başlat. Sunucu robotu
> anahtarından tanır; istekteki `robot` alanı yalnızca bilgi amaçlıdır.

Bu dosya, Django tarafının robotla nasıl konuşacağını anlatır. Robot
(`robot.py` / `isci.py`) laptopta ya da Windows sunucuda çalışır, Django
sunucuda. **Robot Django'ya sorar** (pull): robotun makinesi dışarı port
açmaz. Para/ödeme bu sürümde **yoktur** — robot yalnızca sorgu yapar.

Robot iki iş yapar, hangisi gelirse: **fatura sorgusu** (bölüm 2) ve
kontörün **aboneye özel paket sorgusu** (bölüm 2b). Her "iş var mı?"
isteğinde Django **tek iş** verir; robot onu bitirip sonucu yazar, sonra
sıradakini ister.

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
`GET /fatura/robot/is/?robot=ev-laptop&isler=fatura,paket`
Sunucu bekleyen bir talebi **atomik kilitleyip** (SELECT ... FOR UPDATE SKIP
LOCKED) verir. Böylece **aynı numara iki robota gitmez** — 5 robot da aynı anda
sorsa her biri farklı iş kapar.

`isler` robotun yapabildiği işlerdir. `paket` yoksa (eski sürüm) robota
yalnızca fatura verilir ve paket sorgusu için çevrimiçi sayılmaz. İki
kuyrukta da iş varsa **önce açılan** verilir.

Her iş bir **sağlayıcı hesabına** atanır: Django, robotun o türde bugün
hakkı kalan (en az kullanılmış) hesabını seçer ve **gönderim anında o
hesabın hakkını +1 eksiltir** (sonucu beklemeden). Cevaptaki `hesap` robotun
hangi hesabın oturumuyla soracağını söyler (kimlik bilgilerini bölüm 3'teki
nabız cevabından aldı). Robotun hakkı kalan hesabı yoksa o tür iş verilmez.
```json
// fatura işi:
{"var": true, "tur": "fatura", "hesap": {"id": 7, "kullanici_adi": "5309346655"},
 "talep": {"talep_id": 1234, "kurum_id": "vodafone", "kurum_adi": "Vodafone", "numara": "5332590138"}}
// paket işi (bölüm 2b):
{"var": true, "tur": "paket", "hesap": {"id": 7, "kullanici_adi": "5309346655"},
 "talep": {"talep_id": 55, "numara": "5050488485", "operator": "avea"}}
// yoksa:
{"var": false}
```

### b) Robot sonucu yazar
`POST /fatura/robot/sonuc/` — `tur` işin türüdür (`fatura` / `paket`); yoksa
fatura sayılır. Talep numaraları kuyruk başınadır.
```json
{
  "tur": "fatura",
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

## 2b. Aboneye özel paket sorgusu (kontör, Turkcell / Türk Telekom)

Bayi kontörde numarayı yazınca (ya da kategoride "göndermeden önce paket
sorgusu" açıksa yükleme gitmeden önce) Django bir **paket işi** açar. Robot
`https://bayi.kontorbizde.com/Kontor/index.php`'yi açar, numarayı
`#sorgu_input_0`'a rakam rakam yazar (numara 10 haneye varınca sayfa operatörü bir kez arar),
`#paketsorgula` ("ABONEYE ÖZEL PAKETLERİ SORGULA") çıkınca sayfanın bulduğu
operatörü (`#giz_operator`) işin `operator`'üyle karşılaştırır:

- **Eşitse** düğmeye basar, düğmeden sonra gelen ağ cevabındaki paket
  kutularını ayrıştırır.
- **Farklıysa** (numara taşınmış) düğmeye basmaz, bulduğu operatörü boş
  listeyle döndürür. Bayi "Bu numara Turkcell hattı görünüyor" görür.

Bir paket işi sağlayıcıya dört istek atar, tekrarı yoktur (ağ trafiğiyle
sayıldı): sayfa açılışı (`bilgi_api.php?Goster=Guncel`), operatör bulma
(`operatoru=bul`), operatörün kontör listesi (`operatoru=TURKCELL`) ve tek
paket sorgusu (`bilgi_api_paketsor.php`). Django her işi tek robota bir kez
verir; Robot Paket Sorguları listesindeki her satır bir paket sorgusudur.

Liste sağlayıcının kataloğuyla sınırlıdır: sayfa, operatörün teklif ettiği
paketlerden yalnızca sağlayıcının tanımladıklarını gösterir. Başka bir Znet
sitesinde görülen "5G Cepte Fırsat" burada çıkmıyordu; Kontorbizde'nin
Turkcell kataloğunda yok, robot eksik okumuyor.

Her paket kutusu:
```html
<div class="urunlist_dis" data-gun="30" data-gb="60" data-dk="750">
  <div onclick="yukle_onay('5050488485','Avea','Ses','1744.00','AVEA FIRSAT SES',
       'Büyük Fırsat 60GB','','1549.00','1475.00','74.00','30 Gün, Heryöne 750 Dk, …','','');">
```
`yukle_onay` sırası: numara, operatör, tip, **paket kodu**, grup, ad, ?,
**fiyat** (müşterinin ödediği), **alış** (bize), kâr, açıklama.

Sonuç:
```json
{
  "tur": "paket",
  "talep_id": 55,
  "veri": {
    "operator": "avea",
    "durum": "",
    "mesaj": "",
    "paketler": [
      {"kod": "1744", "operator": "Avea", "tip": "Ses", "grup": "AVEA FIRSAT SES",
       "ad": "Büyük Fırsat 60GB", "fiyat": "1549.00", "alis": "1475.00",
       "aciklama": "30 Gün, Heryöne 750 Dk, 60 Gb İnternet, Heryöne 250 Sms",
       "gun": "30", "gb": "60", "dk": "750"}
    ]
  }
}
```
- `kod` kataloğumuzdaki `Paket.kod`'dur ("1744.00" → "1744").
- Dönen **bütün** paketler Operatörde Görülen'e işlenir: katalogda olan geçilir,
  olmayan "Yeni" düşer; Kataloğa ekle içeriğiyle (DK, GB, SMS, gün) açar.
- **Boş liste hata sayılır** ("Bu numaraya özel paket bulunamadı"): robotun
  ayrıştıramadığı bir cevap "paket yok" diye okunsaydı plan her satışı
  sağlayıcıya gitmeden iptal ederdi. Hata olunca plan ana paketi gönderir.
- Sağlayıcı `ZNET=n-HATA=…` derse `"durum": "hata"` + `mesaj` (bayi görür).
- **Vergi borcu**: sayfa paketlerin yerine kırmızı satır yazar
  (`<div … style="…color:red;">Müşterinin 212 TL TKU Borcu Bulunmaktadır</div>`).
  Robot `"durum": "borc"`, `"mesaj"` (satırın kendisi) ve `"borc": "212"`
  (kesirliyse `"1250.50"`) gönderir. Django sorguyu "Vergi borcu" yapar; bayi
  "212 TL vergi borcu var, önce en az 212 TL yükle" görür, gönderim planı
  sağlayıcıya gitmeden iptal + iade eder. Borcun tamamı ödenmeden aboneye
  özel paket yüklenmiyor (sağlayıcının duyurusu: "1 TL borcu olsa dahi sorgu
  çıkmıyor").
- Borç dışında bir kırmızı satır gelirse `mesaj` olarak gider, liste boş
  olduğu için hata sayılır ve bayi o satırı görür.
- **`sorgulandi`**: robot sağlayıcıya sorguyu gönderdi mi? Numara başka
  operatöre taşınmışsa robot "aboneye özel paketleri sorgula" düğmesine
  basmaz, sorgu sağlayıcıya hiç gitmez ve günlük hak harcanmaz —
  `"sorgulandi": false` gönderir. Diğer bütün cevaplarda alan yoktur,
  Django onu `true` sayar (düğmeye basıldı). Yalnızca paket sonucunda var;
  fatura hep gönderilir, sayaç her sonuçta artar.

## 2c. Hesaplar, günlük sayaç ve limit

**Robot = laptop/işçi; altında birden çok sağlayıcı hesabı var.** Hesaplar
(kullanıcı adı, şifre, güvenlik resmi, günlük haklar) **panelden** girilir
(Sorgu Robotu → Robotlar → robotun sayfasındaki satır-içi tablo); robot
onları **nabız cevabında** çeker (bölüm 3) ve her biri için kendi
profilinde (ayrı context, `oturum/<kullanıcı>.json`) **otomatik giriş**
yapar: kullanıcı adı + şifre, sonra panelde seçilen güvenlik resmini
(kivi → `E.png`; `robot.GUVENLIK`) işaretler. Yanlış resim oturumu bitirir,
o yüzden ad doğru olmalı.

**Sayım gönderim anında, hesap başına.** Django işi verirken robotun o türde
bugün hakkı kalan, en az kullanılmış hesabını seçer ve **o an +1** yapar
(`RobotHesabi.fatura_sayaci` / `kontor_sayaci`); hangi hesap seçildiği `is_`
cevabındaki `hesap` ile gelir. Sonucun gelmesi beklenmez — sağlayıcıya işi
yolladığımız an hak eksilir. **Fatura ve kontör ayrı sayılır.**

Limit panelden hesap başına girilir ("Günlük Fatura/Kontör Hakkı"; 0 =
sınırsız; robotun varsayılanı yeni hesaplara kopyalanır). Bir hesabın hakkı
dolunca o hesaba iş gitmez; robotun başka açık hesabı varsa oraya gider.
Robotun o türde hiç açık hesabı kalmazsa o tür iş almaz, öbür tür sürer.
Hiçbir robotun açık hesabı kalmazsa bayi "Bugünkü … hakkı doldu; yarın
yeniden açılır" görür.

**Sağlayıcı "Sorgu limitinizi doldurdunuz" derse** (paket ya da fatura
cevabında kırmızı satır) robot `"durum": "limit"` gönderir; Django o
**hesabı** bugünlük kapatır (saydığımız limit 0/sınırsız olsa da), sorguyu
yeniden denenebilir hata yapar (iş başka hesaba/robota düşer).

Sayaç ve "limit doldu" **gece 00:00'da** kendiliğinden sıfırlanır — cron
yok, gün değişince ilk sayımda/okumada tazelenir. Panel bugünün kullanımını
her zaman doğru gösterir ("Hesaplar · bugün" ve satır-içi tabloda renkli).
- Robot hatası (oturum düştü, kutu açılmadı) `"basarisiz": true` ile gelir;
  robot o anki sayfanın görüntüsünü ve HTML'ini `kayitlar/`'a yazar. Giriş
  düşen hesabın context'i bırakılır, sonraki iş o hesaba yeniden giriş yapar.

Django bekleme sınırları: robot 30 sn'de almazsa, aldıktan sonra 60 sn'de
yazmazsa iş kapanır; gönderim planı en çok 60 sn bekler, sonra ana paketi
gönderir.

Elle deneme (Django'suz): `paket.bat turkcell 5321234567`.

---

## 3. Nabız (hangi robot açık, oturum sağlam mı)
Robotun **her** doğrulanmış isteği (5 sn'de bir "iş var mı?") sunucuda nabız
sayılır; çevrimiçi göstergesi ondan beslenir. Ayrı nabız isteği yalnızca
durum değişince (boş/meşgul, oturum düştü) ya da dakikada bir gider:

`POST /fatura/robot/kalp/`
```json
// istek:
{"robot": "ev-laptop", "durum": "bos", "oturum": "canli", "mesai": "08:00-23:00"}
// cevap: robotun gireceği aktif hesaplar (ayrı uç yok, her nabızda taze):
{"ok": true, "hesaplar": [
  {"id": 7, "kullanici_adi": "5309346655", "sifre": "…", "guvenlik_resmi": "kivi"}
]}
```
`mesai`: robotun çalışma saatleri (`ayar.json` → `calisma_saatleri`). Robot bu
saatlerin dışında **hiç istek atmaz**, dakikada bir yalnızca kendi saatine
bakar. Django saatleri robotun kaydına yazar; robot susunca bayiye "sistem
bağlı değil" yerine "Fatura sorgusu 08:00–23:00 arasında yapılır" der.
`durum`: `bos|mesgul`. `oturum`: `canli|dustu`.

**Hesaplar nabız cevabında döner:** robot her nabızda kullanıcı adı, şifre
ve güvenlik resmini alır (yalnızca aktif hesaplar), onlarla otomatik giriş
yapar. Ayrı bir `/hesaplar/` ucu yok — robot zaten anahtarıyla doğrulanıyor,
bilgi o doğrulanmış cevapta gider; panelde hesap eklenince robot yeniden
başlatılmadan görür. **Şifre yalnızca bu cevapta, robotun anahtarına karşı
verilir; panelde maskeli durur.**

---

## 4. Güvenlik / notlar
- Bütün uçlar `Authorization: Bearer <API_KEY>` ister (paylaşılan gizli anahtar,
  `ayar.json`'da). İnternete açık bir uç olduğu için anahtarsız istek 401 döner.
- Robot her isteğe `User-Agent: FaturaRobotu/1.0` koyar. Sitenin önündeki
  Cloudflare Python'un varsayılan kimliğini (`Python-urllib`) bot sayıp
  `error code: 1010` ile **403** veriyor; istek Django'ya hiç ulaşmaz.
  Terminalde 403 görülürse sebep budur, 401 ise anahtar yanlıştır.
- `odeme_token` her faturada gelir ama **ödeme bu sürümde yapılmaz**; Django
  saklar, ödeme ileride (elle ya da ayrı, dikkatli bir adımda) yapılır.
- Robot talebi işlerken `kurum_id`'yi `kurumlar.json`'dan token'a çevirir.
  Kurum dosyada yoksa ya da token eskimişse sorgu hemen `basarisiz` döner
  (bayi zaman aşımını beklemez); robotun terminali "katalog.bat ile yenile"
  der, yönetim sebebi Sorgular listesinde görür.
- `POST /fatura/robot/katalog/` yalnızca `katalog.bat` çalıştırılınca gelir.
