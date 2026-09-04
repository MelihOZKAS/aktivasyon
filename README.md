# Aktivasyon

Telekom bayileri için başvuru toplama, evrak takibi, bakiye ve otomatik hakediş
sistemi. Django 5.2 + Tailwind + HTMX.

## Temel fikir

Başvuru tipleri, tarifeler, kampanyalar, durumlar ve para kuralları **veridir, kod değil**.
Yeni bir başvuru tipi eklemek için yönetim panelinden kategori açıp form alanlarını
tanımlamak yeterlidir; yazılım güncellemesi gerekmez.

| Katman | Uygulama | Ne yapar |
|---|---|---|
| Katalog | `apps/katalog` | Operatör, kategori, tarife, kampanya, dinamik form alanları |
| Başvuru | `apps/basvurular` | Tek `Basvuru` modeli, belgeler, durum geçmişi |
| Finans | `apps/finans` | Cüzdan, değişmez defter, ücret/hakediş kuralları |
| Bayi | `apps/bayi` | Bayi profili, SIM stoğu, duyurular, panel |

## Para akışı

Para **yalnızca** `apps/finans/services.py` içindeki atomik fonksiyonlar üzerinden hareket eder.

1. Başvuru girilir → hiçbir para hareketi olmaz
2. Durum, `hakedis_tetikler` işaretli bir duruma geçer (varsayılan: "Aktif")
3. Uyan `UcretKurali` kayıtları bulunur — en dar kapsamlı olan kazanır
4. Tahsilat bakiyeden düşer; bayinin borçlanma izni varsa kalanı borç limitine yazılır
5. Hakediş cüzdana eklenir
6. Durum `olumsuz_sonuc` bir duruma dönerse hareketler ters kayıtla iptal edilir

Her hareketin `idempotency_anahtari` alanı benzersizdir: aynı olay iki kez işlenemez.

### Borçlanma

**Borç için üst sınır yoktur.** Bakiye yetmezse tahsilat borç hanesine yazılır
ve işlem tamamlanır; bayi tezgâh başında bakiye bitti diye durmaz. Bir bayiyi
tamamen durdurmak gerekirse cüzdanındaki **İşlem Yapabilir** kapatılır.

Bayi panelinde "borç limiti" ya da "kullanılabilir tutar" **gösterilmez**;
böyle bir kavram yoktur. Bayi yalnızca bakiyesini görür, "Borç" satırı da
yalnızca gerçekten borcu varsa görünür. Bu kural `apps/bayi/tests.py` içinde
testlerle sabitlenmiştir.

Sonraki bakiye yüklemesi önce borcu kapatır, artan bakiyeye geçer.

## Kurulum sırası

Sistem bir kez kurulur, sonra kendi kendine çalışır. Sıra önemli — her adım
öncekine dayanır:

1. **Operatörler** — marka rengiyle
2. **Başvuru durumları** — hangisi başlangıç, hangisi parayı tetikliyor,
   hangisi olumsuz, hangisi belgeleri siliyor, hangisi bildirim gönderiyor
3. **Kategoriler** — geçerli operatörler, tarife zorunlu mu, SIM karşılığı
   takip edilecek mi
4. **Form alanları** — her kategoride hangi bilgiler sorulacak
5. **Tarifeler ve kampanyalar** — bayiye gösterilecek açıklama ve görselle
6. **Bayi grupları** — fiyat kademesi
7. **Ücret ve hakediş kuralları** — bayiye hakediş, bayiden tahsilat, ana
   hakediş (operatör ya da tedarikçi bazlı)
8. **Kullanıcılar** — rolleri ve cüzdanlarıyla

Bundan sonra günlük işte elle yapılan tek şey **başvuru durumunu
değiştirmek**. Para hareketi, SIM stoğu, belge silme ve bildirimler
kendiliğinden işler. Tedarikçi ataması bilinçli olarak elle yapılır.

### Tek komutla kurulum

`manage.py kurulum` bu sekiz adımı sırasıyla yürütür:

```bash
manage.py kurulum                     # migration + 1-4. adımlar (üretim)
manage.py kurulum --yonetici fadil --parola "..."     # yönetici hesabı açar
manage.py kurulum --ornek             # 5-8. adımları da örnek verilerle doldurur
manage.py kurulum --sifirla --ornek   # önce her şeyi siler, sıfırdan kurar
```

| Bayrak | Ne yapar |
|---|---|
| _(yok)_ | Migration'ları uygular, durum/operatör/kategori/form alanlarını açar. Var olan kayıtlara dokunmaz; her açılışta güvenle çalışır. |
| `--ornek` | Tarife, kampanya, bayi grubu, ücret kuralı, banka, duyuru, SIM stoğu ve deneme hesapları ekler. Yalnızca geliştirme için; üretimde `--zorla` ister. |
| `--yonetici AD` | Yönetici hesabı açar. Parolayı `--parola` ile verirsiniz; vermezseniz üretilip bir kez ekrana yazılır. Hesap zaten varsa parolası değiştirilmez — `--parolayi-yenile` ile değiştirilir. |
| `--sifirla` | Bu projenin veritabanındaki her şeyi siler. Silmeden önce hangi veritabanına bağlı olduğunu yazar ve adını yazmanızı ister; `--evet` onayı atlar. |

`--sifirla` yalnızca `DATABASE_URL`'in gösterdiği veritabanına dokunur
(PostgreSQL'de `DROP SCHEMA public CASCADE`, SQLite'ta dosyayı siler).
Aynı sunucudaki diğer projelerin veritabanları ayrıdır, etkilenmez.

## Geliştirme

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.ornek .env            # SECRET_KEY'i değiştir
.venv/bin/python manage.py kurulum --ornek
.venv/bin/python manage.py runserver
```

Deneme hesapları ve parolaları: `kullanicilar.md`.

### URL yapısı

Sorgu dizesi kullanılmaz; adresler okunur olmalı.

| Yol | Ne |
|---|---|
| `/` | Tanıtım sayfası (herkese açık) |
| `/giris-yap/` | **Tek giriş kapısı** — bayi de yönetici de buradan girer |
| `/panel/` | Bayi paneli |
| `/basvuru/` | Başvuru listesi |
| `/basvuru/yeni/` | Kategori seçimi |
| `/basvuru/yeni/<kategori-slug>/` | Başvuru formu |
| `/basvuru/<REFERANS>/` | Başvuru detayı (referans no ile, id ile değil) |
| `/basvuru/<REFERANS>/belge/<alan>/` | Belge (izin kontrollü) |
| `/cuzdan/` | Cüzdan |
| `/yonetim/` | Yönetim paneli (yalnızca yetkili) |

Yeni ekran eklerken aynı biçimi koru: slug'lı, sorgu dizesiz. Slug üretiminde
`apps.katalog.utils.turkce_slug` kullan — Django'nun `slugify`'ı Türkçe harfleri
düşürür ("Faturalı" → "fatural").

### Giriş ve yetki

Giriş tek yerdedir. Girişten sonra yönetici `/yonetim/`'e, bayi `/panel/`'e
düşer. `/yonetim/login/` kendi formunu göstermez, `/giris-yap/`'a yönlendirir.
Yetkisiz bir bayi yönetim adresine giderse açık bir mesajla kendi paneline
gönderilir. Kategori, tarife, ücret kuralı gibi tüm düzenlemeler yalnızca
yetkili kullanıcı tarafından yapılabilir.

### Yüklenen belgeler

Kimlik ve pasaport görüntüleri kişisel veridir; **MEDIA_URL üzerinden doğrudan
sunulmaz**. Erişim `/basvuru/<REFERANS>/belge/<alan>/` üzerinden ve izin
kontrolüyle olur: yalnızca başvuruyu giren bayi ve yetkili personel görebilir.

### Görseller yüklenirken küçültülür

Telefon kameraları 4000×3000 çekiyor; kimlikteki yazıyı okumak için bu
gereksiz. Kimlik kartı kadrajın çoğunu kapladığından uzun kenar
`GORSEL_MAKS_KENAR` (varsayılan **1000px**) olduğunda bile karttaki yazı
~18px kalıyor ve rahat okunuyor. Görseller küçültülüp WebP'ye çevrilir.
Tasarruf **%95'in üzerinde**; bayinin mobil verisi de kazanıyor.

Kimlik yazıları okunmuyor diye şikâyet gelirse `GORSEL_MAKS_KENAR=1400` ya da
`GORSEL_WEBP_KALITE=90` yapmak yeterli.

EXIF verisi temizlenir — telefon fotoğrafları konum bilgisi taşır ve bunun
kimlik görüntüsünde işi yoktur. Silmeden önce EXIF'teki döndürme uygulanır,
yoksa fotoğraf yan yatar.

PDF ve dönüştürülemeyen dosyalar olduğu gibi kalır. Dönüşüm başarısız olursa
yükleme iptal edilmez; özgün dosya kullanılır ve hata günlüğe düşer.

### Neden veritabanında değil, diskte?

Kimlik görüntüleri diskte (`media/`) tutulur, veritabanına konmaz. Bir kimlik
fotoğrafı birkaç MB; bunları satır içinde saklamak veritabanını şişirir,
`pg_dump` yedeklerini gigabaytlara çıkarır ve her görüntüleme isteğinde tüm
veriyi belleğe alır. Diskte akış (streaming) mümkün, yedekleme ayrı yapılabilir.

Asıl mesele "nerede durduğu" değil "ne kadar durduğu": kişisel veri işi
bittikten sonra süresiz saklanmamalı. Bunun için saklama süresi vardır.

### Belgeler ne zaman silinir?

Kimlik ve pasaport görüntüleri, başvurunun **işi bittiği anda** silinir:
bakiye yüklendiğinde (Aktif) ya da iptal edilip para geri alındığında.
Bekleme süresi ve cron yoktur.

Hangi durumun sileceğini siz seçersiniz: **Başvuru Durumları** ekranındaki
"Belgeleri Sil" kutusu. Varsayılan olarak *Aktif* ve *İptal* siler; *Hatalı*
ve *Eksik Evrak* silmez, çünkü o başvurular düzeltilip yeniden denenebilir.

Dosyalar veritabanı değişikliği **commit edildikten sonra** silinir. Aksi
hâlde bir hata yüzünden işlem geri alınsa dosya çoktan gitmiş, kayıt geri
gelmiş olur ve olmayan bir dosyayı işaret ederdi.

Kayıt silindiğinde ve dosya değiştirildiğinde eski dosya diskten otomatik
silinir (`apps/dosya.py`). Django bunu kendiliğinden yapmaz; silinen her
tarife görseli ve değiştirilen her kimlik fotoğrafı aksi hâlde diskte
kalırdı.

Yine de disk hatası sahipsiz dosya bırakabilir; arada bir kontrol edin:

```bash
python manage.py sahipsiz_belgeler        # bulur, listeler
python manage.py sahipsiz_belgeler --sil  # siler
```

Silinen şey yalnızca görüntülerdir. Başvuru kaydı, durum geçmişi, para
hareketleri ve hakediş bilgisi yerinde kalır; bayi detayında "işi tamamlandı,
görüntüler silindi" notu görünür.

Dosyalar diskte durur (`media/`), S3 gibi bir nesne deposu kullanılmaz.
Sunucuda `/home/aktivasyon/media/` altındadır ve bind mount olduğu için
container yeniden kurulunca kaybolmaz — ama Docker volume olmadığı için
yedeklemeye ayrıca dahil edilmelidir.

**Nginx'e `/media/` için location tanımlamayın**; tanımlarsanız izin kontrolü
devre dışı kalır.

Yüklenen dosyalar iki katmanda denetlenir:

1. **Yükleme anında** (`apps/basvurular/validators.py`): uzantı allowlist'i
   (png, jpg, jpeg, webp, gif, pdf), boyut sınırı ve dosyanın gerçek imzası.
   Uzantısı `.png` yapılmış bir HTML dosyası içerik denetiminde takılır.
   Formdaki `accept` özniteliği yalnızca tarayıcı ipucudur, güvenlik sağlamaz.
2. **Servis anında**: yalnızca bilinen güvenli resim türleri gömülü gösterilir;
   PDF dahil diğer her şey indirilir. Yanıta `Content-Security-Policy: sandbox`
   eklenir.

Bu katmanlar birlikte, bayinin yüklediği bir dosyanın belgeyi açan personelin
oturumunda betik çalıştırmasını engeller.

### Tema

Tek tema vardır: beyaz. Arayüz kağıt, mürekkep ve griden ibarettir; ekrandaki
**her renk bir bilgi taşır** — operatör markası, başvuru durumu, para yönü.
Bu yüzden yeni bir arayüz rengi eklemeden önce "bu renk hangi veriyi
anlatıyor?" sorusunu sor.

Marka renkleri admin'den girildiği için açık renkler (Turkcell sarısı gibi)
beyaz üstünde okunmaz. `okunur_renk` şablon filtresi tonu koruyup parlaklığı
güvenli aralığa çeker; rozetlerde ve sinyal çubuklarında hep bu filtre kullanılır.

### Tailwind

Sunucuda Node yoktur; CSS burada derlenip `static/app.css` olarak commit edilir.

```bash
./.tools/tailwindcss -i static/src/app.css -o static/app.css --minify
```

Şablon değiştirdikten sonra bu komutu çalıştırmayı unutma.

### Testler

```bash
.venv/bin/python manage.py test
```

## Migration kuralı

**Migration dosyaları asla elle silinmez ve asla `.gitignore`'a eklenmez.**
Eski sistemde bunlar silindiği için yerel ortam, sunucu ve veritabanı şeması
birbirini tutmaz hale gelmişti.

Model değiştirdikten sonra:

```bash
.venv/bin/python manage.py makemigrations
.venv/bin/python manage.py makemigrations --check --dry-run   # "No changes detected" görmeli
```

## Telegram bildirimleri

Operasyon grubuna yeni başvuru ve durum değişikliği bildirimi gider.
Yapılandırmak için `.env` dosyasına ekleyin:

```
TELEGRAM_BOT_TOKEN=BotFather'dan aldığınız anahtar
TELEGRAM_SOHBET_ID=@grup_kullanici_adi
```

Sınamak için: `python manage.py telegram_dene`

Hangi durumların bildirim göndereceğini yönetim panelinden **Başvuru
Durumları** ekranındaki "Telegram Bildirimi Gönder" kutusuyla siz seçersiniz.
Yeni başvurular ve yeni bayi başvuruları her zaman bildirilir.

Bildirim hiçbir zaman işin önüne geçmez: mesaj transaction tamamlandıktan
sonra ayrı bir iş parçacığında gönderilir ve hatası yutulur. Telegram
erişilemez olsa bile başvuru kaydedilmiş kalır. (Eski sistemde `requests.get`
doğrudan view içindeydi; Telegram çöktüğünde başvuru kaydedilmiş olmasına
rağmen bayi hata sayfası görüyordu.)

## Tarifeler sayfası

`/tarifeler/` bayinin gördüğü tarife kataloğudur: kategori sekmeleri, operatör
başlıkları ve akordiyon olarak açılan tarife ayrıntıları. İçeriği yönetim
panelinden **Tarifeler** ve **Kampanyalar** ekranlarındaki "Bayiye gösterilecek
içerik" bölümünden girersiniz — açıklama ve görsel. Süresi geçmiş kampanyalar
kendiliğinden görünmez olur.

## Yönetim paneli dili

django-unfold Türkçe çeviriyle gelmiyor. Eksik metinler `locale/tr/` altında
karşılanır. Yeni bir İngilizce metin görürseniz `locale/tr/LC_MESSAGES/django.po`
dosyasına ekleyip derleyin:

```bash
python manage.py compilemessages
```

Ekleme düğmesi de `templates/unfold/helpers/add_link.html` ile ezilmiştir:
unfold'un ikon-only yuvarlak düğmesi ne işe yaradığını anlatmıyordu, artık
"Yeni <model> ekle" yazıyor.

## SIM karşılığı takibi

Fiziksel SIM tüketen kategorilerde (**Kategoriler** ekranında "SIM Karşılığı
Takip Edilsin" açık olanlar), tamamlanan her işlem yeni bir SIM alacağı
doğurur.

Alacak kimden?

| Durum | Alacak |
|---|---|
| İşlemi bir tedarikçi üstlendiyse | **O tedarikçiden** |
| Üstlenilmemişse | **Operatörden** |

Başvuru listesinin üstünde kimden kaç kart beklendiği kart kart görünür;
üstüne tıklayınca o tarafın bekleyen işlemleri listelenir. Kartlar geldiğinde
seçip **"SIM karşılığı alındı olarak işaretle"** deyin — işaretlendiği an
damgalanır.

## Tedarikçi

Bir firma hem bayi hem tedarikçi olabilir; roller **Bayi Profilleri**
ekranındaki iki kutuyla açılır.

- **Bayi rolü:** başvuru getirir, tamamlanınca hakediş alır
- **Tedarikçi rolü:** kendisine satılan işlemi üstlenir, bedeli hesabından düşer

İşlem satmak için başvuruları seçip **"Seçili işlemleri bir tedarikçiye sat"**
işlemini kullanın. Zaten aktif olan işlemlerde bedel atama anında düşer.
Bedeli işlenmiş bir işlemin tedarikçisi değiştirilemez.

Fiyat tedarikçiye özeldir: **Ücret ve Hakediş Kuralları**'nda yön olarak
*Tedarikçi Geliri* seçip *Tek Tedarikçi* alanını doldurun. Aynı işlem için
her tedarikçiye farklı fiyat tanımlayabilirsiniz.

### Ana hakediş ve kâr

Kâr = **ana hakediş** + bayiden kesilen − bayiye ödenen.

Ana hakediş, işlemden bize giren tutardır ve iki kaynaktan gelebilir:

| Durum | Kaynak | Cüzdan hareketi |
|---|---|---|
| İşlemi tedarikçi üstlendi | O tedarikçiden | Hesabından düşer |
| Üstlenilmedi | Operatörden | Yok — operatörün cüzdanı yoktur, tutar yalnızca kâra yazılır |

Tanımlamak için **Ücret ve Hakediş Kuralları**'nda yön olarak *Ana Hakediş*
seçin; operatör bazlı tutar için **Operatör** alanını, tedarikçiye özel tutar
için **Tek Tedarikçi** alanını doldurun.

Kâr, başvuru listesinde sütun olarak, detayda kaynağıyla birlikte hesap
tablosu olarak ve listenin üstünde filtreye göre toplam olarak görünür.

Tedarikçi `/tedarikci/` panelinde üstlendiği işlemleri ve hesabını görür.
Aktivasyonu fiilen kendisi yaptığı için **üstlendiği işlemin kimlik
görüntülerini de görebilir**; bilgileri oradan okuyup operatör sistemine
girer. Kendisine atanmamış bir işlemin belgesine erişemez.

## Bayi başvurusu

`/bayi-basvurusu/` kamuya açıktır: isim, soy isim ve telefon alınır.
Talepler yönetim panelinde **Bayi Başvuruları** altında listelenir; hesabı
oradan siz açarsınız. Formda görünmez bir tuzak alan vardır, botların
doldurduğu kayıtlar sessizce atılır.

## Sunucu

Bu proje kendi container ve volume'larında tamamen izoledir. Aşağıdaki komutlar
**yalnızca** bu projeye dokunur; sunucudaki diğer projeler etkilenmez.

| Kaynak | Bu projeye ait |
|---|---|
| Container | `postgresfadil`, `app_fadil` |
| Volume | `postgresql-data-fadil`, `static-data-fadil` |
| Network | `main_fadil` (ek olarak paylaşılan `nginx_network`) |
| Veritabanı | `fadil_db` (port 5434) |

### Güncelleme

```bash
cd /home/aktivasyon
git pull
docker compose -f docker-compose.yml up -d --build app_fadil
```

### Veritabanını sıfırdan kurma

> Bu işlem `fadil_db` içindeki **tüm veriyi siler**. Diğer projelerin
> veritabanlarına dokunmaz.

```bash
cd /home/aktivasyon

# 1) Önce yedek al — silmeden önce her zaman
docker exec postgresfadil pg_dump -U nasip_fadil_user -p 5434 fadil_db \
  > ~/fadil_db_yedek_$(date +%F_%H%M).sql

# 2) Son sürümü çek ve container'ı yenile
git pull
docker compose -f docker-compose.yml up -d --build

# 3) Sıfırla ve yeniden kur (veritabanı adını yazarak onaylarsınız)
docker exec -it app_fadil python manage.py kurulum --sifirla \
  --yonetici fadil --parola 'PAROLANIZ'
```

Üçüncü adım yalnızca `fadil_db` şemasını düşürür; aynı PostgreSQL sunucusundaki
diğer veritabanlarına dokunmaz. `--parola` vermezseniz güçlü bir parola üretilir
ve bir kez ekrana yazılır.

Komut satırına yazılan parola kabuk geçmişine (`~/.bash_history`) düşer.
Sonradan değiştirmek için: `/yonetim/` → Kullanıcılar, ya da
`manage.py kurulum --yonetici fadil --parola 'YENİ' --parolayi-yenile`.

Container'ı da komple silmek isterseniz volume'u elle kaldırabilirsiniz:

```bash
docker compose -f docker-compose.yml down
docker volume rm aktivasyon_postgresql-data-fadil   # yalnızca bu proje
docker compose -f docker-compose.yml up -d --build  # kurulum otomatik çalışır
```

> **`docker volume prune` KULLANMAYIN** — sunucudaki diğer projelerin
> volume'larını da siler. Volume adını doğrulamak için: `docker volume ls | grep fadil`

### Kurulum sonrası

`kurulum` komutu 1-4. adımları (durumlar, operatörler, kategoriler, form
alanları) hazır getirir. Geriye yönetim panelinden girilecekler kalır:

1. **Tarifeler ve kampanyalar** — her kategori/operatör için, açıklama ve görselle
2. **Bayi grupları** — fiyat kademeleri
3. **Ücret ve hakediş kuralları** — üç yön: bayiye hakediş, bayiden tahsilat,
   ana hakediş (operatör ya da tedarikçi bazlı). Aradaki fark kârdır.
4. **Kullanıcılar** — her bayi için hesap; cüzdan ve profil satır içi doldurulur
5. **Banka hesapları** — bayiler bakiye yüklerken görecek

Nasıl görüneceğini denemek için geliştirme makinenizde
`manage.py kurulum --ornek` çalıştırıp örnek kurgusuna bakabilirsiniz.
