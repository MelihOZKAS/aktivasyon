# Aktivasyon — çalışma kuralları

## Sistem nedir

Telekom bayileri için başvuru toplama, evrak takibi, bakiye ve otomatik
hakediş sistemi. Üç taraf var:

| Taraf | Ne yapar | Para yönü |
|---|---|---|
| **Bayi** | Müşteriyi getirir, başvuruyu girer | Hat ücretini bize öder, hakediş alır |
| **Tedarikçi** | Üstlendiği işlemin aktivasyonunu yapar | Maliyeti ona biz öderiz; prim veriyorsa ondan alırız |
| **Operatör** | Tedarikçi yoksa aktivasyon doğrudan onda yapılır | Maliyeti ona biz öderiz; prim veriyorsa ondan alırız |

Karşı tarafla para **iki yönde birden** akabilir: hattı ondan satın alırız
*ve* aynı işlem için bize prim ödeyebilir. Hattı 1000'e alıp 1500 prim alıp
bayiye 200 verdiğimizde kâr 300'dür.

Bir firma hem bayi hem tedarikçi olabilir.

**Temel ilke: başvuru tipleri, tarifeler, kampanyalar, form alanları,
durumlar ve para kuralları veridir — kod değil.** Yeni bir başvuru tipi
eklemek yönetim panelinden kayıt açmaktır; yazılım değişikliği gerekmez.
Bu ilkeyi bozan bir çözüm önerme.

| Katman | Uygulama | İçerik |
|---|---|---|
| Katalog | `apps/katalog` | Operatör, kategori, tarife, kampanya, form alanları |
| Başvuru | `apps/basvurular` | Tek `Basvuru` modeli, belgeler, durum geçmişi |
| Finans | `apps/finans` | Cüzdan, değişmez defter, ücret ve hakediş kuralları |
| Bayi | `apps/bayi` | Profil ve roller, SIM stoğu, duyurular, paneller |
| Bildirim | `apps/bildirim` | Telegram |
| Destek | `apps/destek` | Bayi–yönetim yazışması |
| Mağaza | `apps/magaza` | Bayinin hakedişiyle aldığı ürünler |
| eSIM | `apps/esim` | Sağlayıcı API'lerinden çekilen yurt dışı internet paketleri, kur ve kâr oranıyla satış, QR teslimi |

## Kurulum sırası

Sistem bir kez kurulup sonra kendi kendine çalışacak şekilde tasarlandı.
Kurulumda sıra önemli, çünkü her adım öncekine dayanır:

1. **Operatörler** — marka rengiyle birlikte
2. **Başvuru durumları** — hangisi başlangıç, hangisi parayı tetikliyor,
   hangisi olumsuz, hangisi belgeleri siliyor
3. **Kategoriler** — hangi operatörlerde geçerli, tarife zorunlu mu, SIM
   karşılığı takip edilecek mi
4. **Form alanları** — her kategoride hangi bilgiler sorulacak
5. **Tarifeler** — bayiye gösterilecek açıklama ve görselle; kampanyalar
   tarifenin alt kaydı olarak aynı sayfadan girilir
6. **Bayi grupları** — fiyat kademesi
7. **Fiyatlar** — tarifenin kendi sayfasındaki *Bu tarifenin parası*
   tablosundan: operatörden alış, tedarikçiden alış, bayiye ödenecek
   (bayi grubu başına). Genel kurallar için *Ücret ve Hakediş Kuralları*
8. **Kullanıcılar** — rolleri ve cüzdanlarıyla

Bundan sonra günlük işte tek elle yapılan şey **başvuru durumunu
değiştirmek**; para, SIM stoğu, belge silme ve bildirimler kendiliğinden
işler. Tedarikçi ataması da bilinçli olarak elle yapılır.

**Kurulum tek komuttur: `manage.py kurulum`.** Migration'ları uygular ve
1-4. adımları açar; `--ornek` 5-8'i de örnek verilerle doldurur,
`--yonetici AD --parola X` yönetici hesabı açar, `--sifirla` önce her şeyi siler. Yeni bir kurulum adımı
eklerken bu komuta da ekle — kurulumu belgeye değil komuta yazıyoruz.

`--sifirla` yalnızca `DATABASE_URL`'in gösterdiği veritabanına dokunur
(PostgreSQL'de `DROP SCHEMA public CASCADE`, SQLite'ta dosyayı siler) ve
silmeden önce veritabanı adının yazılmasını ister. Sunucuda `docker volume
prune` **kullanılmaz**; diğer projelerin volume'larını da siler.

**Var olan bir hesabın parolası sessizce ezilmez.** Yeniden kurulum yönetici
yetkisini doğrular ama parolayı değiştirmez; değiştirmek açık istek gerektirir
(`--parolayi-yenile`). Parola depoya yazılmaz, komut satırından geçer.

Örnek veri komutları (`ornek_veri`, `ornek_kullanicilar`) DEBUG kapalıyken
`--zorla` olmadan çalışmaz: üretime deneme parolası ve uydurma fiyat girmesin.

## Tasarım

**1. Her ekran %100 mobil uyumlu olmalı. İstisnasız.**

Bayiler tezgâh başında, çoğunlukla telefondan iş yapıyor. Mobil ikincil bir
hedef değil, birincil kullanım biçimi. Yeni bir ekran yazarken **önce dar
viewport'ta (≈390px) doğrula**, sonra masaüstüne genişlet.

Kontrol listesi:
- Yatay taşma yok (`overflow-x`), gövde asla yana kaymıyor
- Dokunma hedefleri en az 44×44px
- Gezinme telefonda çalışıyor (çekmece açılıyor, kapanıyor, arkası kilitli)
- Tablolar/listeler dar ekranda okunur; taşan içerik kendi kutusunda kayıyor
- Form girdileri 16px+ (iOS'ta yakınlaştırma yapmasın); görsel alanında hem
  galeri hem kamera var — **tek girdiyle ikisi birden olmuyor**: `capture`
  varken telefon doğrudan kamerayı açıp galeriye hiç girmiyor, yokken de
  Android 13+ ve yeni iOS foto seçiciyi açıp kamerayı hiç göstermiyor. Bu
  yüzden kutu galeriyi açar, yanındaki "Fotoğraf çek" düğmesi tıklanınca aynı
  girdiye `capture` ekleyip açar ve hemen geri alır

**2. Mor / violet renk kullanma.** Bu aile tercih edilmiyor.

**3. Arayüz kağıt, mürekkep ve gridir; ekrandaki her renk bir bilgi taşır.**

Operatör markası, başvuru durumu, para yönü. Birincil düğmeler mürekkep siyahı
— operatör renkleriyle yarışmasınlar. Yeni bir arayüz rengi eklemeden önce
"bu renk hangi veriyi anlatıyor?" sorusunu sor.

Tek tema vardır: beyaz. Koyu tema bilinçli olarak yok.

**4. İmza formlar korunur:** SIM kart silüeti (`.sim`, tek köşe pahlı) ve durum
göstergesi olarak sinyal çubuğu (`.sinyal`). Her yere aynı border-radius
uygulanmaz; yüzeyler gölgeyle değil kenarlıkla ayrılır.

`clip-path` elemanı kenarlığıyla birlikte kestiği için pahlı köşede çizgi
kaybolur. `.sim`/`.sim-sol` bu çizgiyi `::after` üzerinde yeniden çizer; rengi
`--sim-kenar` değişkeninden gelir. Kenarlık rengini değiştiren bir hover
yazarken bu değişkeni de güncelle (`.kart-secim`e bak). Dolu zeminlerde
(marka işareti gibi) `.sim-cizgisiz` ekle.

Sinyal çubuğu dekor değil: panelde durum dağılımını da o anlatır ve her sütun
o duruma filtrelenmiş listeye gider. Yeni bir "durum" görselleştirmesi
gerekirse yeni bir dil icat etme, bu motifi kullan.

**5. Marka renkleri `okunur_renk` filtresinden geçer.** Operatör renkleri
admin'den giriliyor; Turkcell sarısı gibi açık renkler beyazda okunmaz.

**6. Yönetim paneli ön yüzle aynı renkte olmalı.** Vurgu rengini
değiştirirken `assets/app.css` içindeki `--color-vurgu` ile
`config/settings/base.py` içindeki `UNFOLD["COLORS"]["primary"]` birlikte
güncellenir. Bir kez yalnızca ön yüz değiştirildi ve yönetim paneli mor kaldı.

## Kod

- **Migration dosyaları asla elle silinmez, `.gitignore`'a eklenmez.** Eski
  projeyi bozan alışkanlık buydu. Model değişince `makemigrations`, ardından
  `makemigrations --check --dry-run` ile doğrula.
- **Para yalnızca `apps/finans/services.py` üzerinden hareket eder.** Model
  `save()` içinde bakiye değiştirme.
- **Borç için üst sınır yoktur.** Bakiye yetmezse kalan tutar borca yazılır.
  Bayiyi tamamen durdurmak gerekirse cüzdandaki `islem_yapabilir` kapatılır.
  Bayi panelinde "borç limiti" ya da "kullanılabilir tutar" gösterilmez;
  `apps/bayi/tests.py` bunu kontrol eder.
- **Bedeli olan işlem parası olmayana verilmez.** Bayiden tahsil edilecek
  bir tutar tanımlıysa (`yon=TAHSILAT`), bayi o parayı cüzdanında
  bulundurmadan başvuru **giremez**. Kapı dört yerde durur: kategori ekranı
  karşılanamayan kategoriyi kapalı gösterir ve sebebini yazar (gizlemez —
  bayi kategori kaybolmuş sanmasın), form açılışı hiçbirini karşılayamıyorsa
  geri çevirir, karşılayamadığı **operatörler** varsa açılışta uyarı kutusu
  çıkar, `BasvuruFormu.clean` seçilen operatör/tarifenin gerçek tutarıyla son
  kez denetler.
- **Fiyat operatöre göre değişir; ekranlar da öyle davranır.** Turkcell 1150,
  Vodafone 1000 iken kategori kartında tek rakam göstermek yanıltıcıydı —
  hangi kuralın kazandığına göre biri görünüyordu. `operator_bedelleri`
  kategorideki her operatör için ayrı tutar verir; kart hepsini listeler,
  karşılanamayanı uyarı renginde gösterir. Bakiye uyarısı da operatör
  kırılımındadır: bakiyesi Vodafone'a yetip Turkcell'e yetmeyen bayi forma
  girer ama hangisini seçemeyeceğini **baştan** öğrenir — bilgileri doldurup
  sonunda reddedilmesin. Hepsine yetiyorsa hiçbir kutu açılmaz.
  `basvuru_bedeli` tam tutarı, `en_dusuk_basvuru_bedeli` en ucuz seçeneği
  verir (kategori ekranında operatör/tarife henüz belli değil).
  Bu, **borç kuralıyla çelişmez**: borcun üst sınırı yok, ama borç işlenmiş
  bir işlemin sonucudur — parası olmadan yeni bir işlem *başlatmak* ayrı
  şeydir. Tahsilat kuralı yoksa hiçbir kategori engellenmez.
- **Cüzdana elle yapılan işlem dört türlüdür** (`CuzdanIslemi`): *hem borç hem
  bakiye ekle* (açık hesap — bayi hemen işlem yapar, bedelini sonra öder),
  *sadece borç arttır* (düzeltme), *tahsilat* (bayiden para alındı; borcu
  varsa önce o kapanır, artan bakiyeye geçer) ve *bakiye düşür* (bayiye para
  ödendi). İade, bayinin bakiyesi **ve havalenin çıktığı bankanın bakiyesi**
  ile birlikte düşer — tek yerde düşseydi kasa ile defter ayrışırdı; banka bu
  yüzden zorunludur. Bakiyeden fazlası düşürülemez (olmayan parayı ödemek eksi
  bakiye demek, borç hanesiyle karışır) ve borca dokunulmaz: bu bir ödeme,
  mahsuplaşma değil. Tek giriş noktası
  `apps.finans.services.cuzdan_islemi`. Ekran hem **Cüzdanlar** hem
  **Kullanıcılar** listesinden açılır — yönetici bayiyi kullanıcı adından
  bulup para işlemi için ikinci kez aramasın; ekranın kendisi tek yerdedir,
  kullanıcı tarafı yalnızca yönlendirir. Her hareket kimin yaptığını taşır
  (`olusturan`) ve hareket listesinde görünür. İşlem anahtarı formda gizli
  alanda taşınır: sayfa yenilenince aynı işlem ikinci kez yazılmaz.
- **Bayi hakedişini mağazadan ürüne çevirir** (`apps/magaza`). Kazandığı
  parayı harcayabileceği tek yer başvuru bedeliydi. Ürünü görür, fiyatını
  bilir, siparişi verir; tutar o anda **bakiyesinden** düşer.
  **Borca yazılmaz** — başvuruda borcun üst sınırı yoktur çünkü borç işlenmiş
  bir işlemin sonucudur; burada ise parası olmayana mal verilmiş olurdu ve
  giden mal geri gelmiyor. Kapı iki yerde durur: ürün sayfası sebebini yazıp
  düğmeyi kapatır (gizlemez), `siparis_odemesini_isle` son kez denetler.
  **Stok tutulmaz.** Ürünler bayiye uğrandığında elden veriliyor; tutulmayan
  bir sayı yanlış olurdu. Satılmayacak ürünün "Aktif"i kapatılır — mağazada
  hiç görünmez, verilmiş siparişler yerinde kalır.
  **Fiyat tektir**, bayi grubuna göre kademe yok: satılan şey bir hizmet
  değil, rafta duran bir ürün. Sipariş anında `urun_adi` ve `birim_fiyat`
  kopyalanır; ürünün fiyatı sonra değişse de ödenen tutar kayıtta doğru kalır.
  **Para siparişin iptal edilmemiş olmasına bağlıdır** — başvurudaki kuralın
  aynısı. İptal'e geçince ters kayıtla iade edilir, İptal'den çıkarılırsa
  yeniden kesilir (bakiye yetmezse kayıt iptalde kalır ve yönetici sebebini
  görür). Tek kapı `finans.services.siparis_durumunu_uygula`; satır düğmesi de
  formdaki durum alanı da (`SiparisAdmin.save_model`) oradan geçer. Defter
  anahtarı `Siparis.para_surumu` içerir. İptal para oynattığı için düğme
  doğrudan çalışmaz, ne olacağını yazan onay ekranını açar ve iş POST ile
  yapılır. Sipariş formundaki gizli `islem_anahtari` sayfa yenilenince aynı
  siparişin ikinci kez açılmasını engeller.
  Durum bilinçli olarak üç tanedir (verildi / teslim / iptal): kargo yok,
  ara durumlar takip edilecek bir şey anlatmıyor.
- **eSIM mağazadan ayrı bir bölümdür** (`apps/esim`, `/esim/…`, menüde
  kendi maddesi). Ürün değil, ülke seçilip anında teslim edilen bir hizmet;
  mağazanın sipariş listesine girmez (`esim__isnull=True`), kendi listesi
  vardır. **Para yine `magaza.Siparis` üzerinden yürür**: eSIM siparişi
  `urun=None`, `urun_adi="eSIM · …"` olan bir sipariştir, cüzdan kuralları
  (bakiyeden düşer, borca yazılmaz, iptalde ters kayıt, `para_surumu`) aynen
  geçerlidir. `esim.Teslimat` o siparişin sağlayıcı tarafını tutar.
  · **Sağlayıcı adaptörü koddur, gerisi veridir.** `apps/esim/saglayicilar/`
  altında her sağlayıcı bir sınıf (`Adaptor`: paketleri getir, bakiye,
  sipariş ver, profil getir, iptal et); anahtarlar, kâr oranı ve açık/kapalı
  hâli panelden (`Saglayici`). eSIM Access canlı anahtarla denendi; eSIM Go
  ve Airalo **belgeden yazıldı** (`denenmedi = True`, panel satırda uyarır) —
  anahtar gelince ilk eşitleme ve ilk sipariş göz önünde yapılır. Yeni
  sağlayıcı = bir adaptör dosyası + `_kayit()`e bir satır.
  · **Sağlayıcı seçimi fiyatla yapılır, elle değil.** Aynı kapsam
  (ülke listesi), hacim ve süredeki paketlerden yalnızca alışı en ucuz olan
  bayiye gösterilir (`services.en_ucuzlar`); sipariş o sağlayıcıya gider.
  · **Satış fiyatı saklanmaz, hesaplanır:** `alış_usd × kur × (1 + kâr%)`,
  **küsurat atılır** (`tam_lira`: 41,53 → 41, yukarı değil aşağı — bayi
  öyle istedi; her eSIM fiyatı aynı kuraldan geçer, iki rakam birbirini
  tutar). Kur `GenelAyarlar.usd_kuru` (TCMB'den; panelde
  **Kuru güncelle** düğmesi, komut `kur_guncelle`); kur sıfırsa satış
  kapalıdır ve bayi sebebini görür. **Cron yok, güncelleme elle**: kur ya da
  katalog bir günden eskiyse paket listesinin başlığı uyarır
  (`PaketAdmin.changelist_view`), yönetici düğmeye basar.
  · **Her bayi aynı fiyatı öder; bayi grubundaki yüzde bayinin kârıdır.**
  `BayiGrubu.esim_kar_orani` tam sayı yüzdedir ve **tavsiye fiyatı** üretir:
  paket 230 ₺ ise %25'lik gruptaki bayi "müşteriye 287 ₺'ye sat" görür,
  cüzdanından yine 230 düşer, 57 ₺ onundur. Boşsa ya da 0'sa tavsiye
  gösterilmez. Grup cüzdanda yaşar (`Cuzdan.grup`), başvuru fiyatlarıyla
  aynı yer; fiyat saklanmadığı için grubu kaydetmek bayi ekranında anında
  geçerlidir. Tek kapı `services.bayi_tavsiye_orani` → `fiyatlandir(...,
  tavsiye)`; bayiye fiyat gösteren her yer oradan geçer.
  **Bu alan iki kez yanlış kuruldu.** Önce alışın üzerine yüzdeydi ("%10
  yazdım, fiyat düştü"), sonra bayinin ödeyeceği fiyatın üzerine kademe
  farkı oldu ve bayinin müşteriye kârı ayrı bir alan olarak Genel Ayarlar'a
  kondu. Yönetici %25'i gruba yazdı, bayi 230 yerine 287 ödedi: "adamın
  kârını da biz kesiyoruz." Ders: yöneticinin kafasında **tek yüzde** var —
  bayinin kârı — ve bayiye göre girilmek isteniyor. İkinci bir yüzde
  (kademe farkı, genel tavsiye oranı) nereye konursa konsun ilkiyle
  karışıyor. Bayinin ödeyeceğini gruba göre değiştirmek gerekirse yeni bir
  alan açma; paket kâr oranı tektir, herkes onu öder. Paket listesindeki
  "Satış" sütunu herkesin ödediği fiyattır; başlık grup kârlarını yazar ki
  yönetici "bayi neden başka rakam görüyor" diye aramasın.
  Kâr oranı paket başına durur ama **günlük iş sağlayıcı düzeyindedir**:
  sağlayıcıya bir oran yazılır, listedeki **Fiyatları güncelle** düğmesi
  (`fiyatlari_guncelle`, POST) bütün paketleri o orana çeker. Oran yalnızca
  eşitlemede yeni paketlere yazılıyor, sonradan değiştirilince paketler eski
  oranda kalıyordu; iki bin paketi tek tek yönetmenin anlamı yok, paket
  başına özel oran istisnadır (Paketler ekranındaki toplu işlem). Eşitleme
  sağlayıcı verisini (ad, hacim, alış)
  günceller, yönetimin kararını (kâr, aktif) **korur**; listeden düşen paket
  silinmez, `saglayicida_var` kapanır.
  · **Sipariş iki adımdır:** önce para düşer ve kayıt açılır (transaction),
  sonra sağlayıcıya gidilir (transaction dışı — HTTP beklerken kilit
  tutulmaz). Sağlayıcı reddederse (`SaglayiciHatasi`) sipariş iptale çekilip
  para **kendiliğinden iade edilir**, sebep `Teslimat.hata`da ve bayinin
  ekranında. Profil eşzamansız gelirse (eSIM Access) bayinin sayfası HTMX ile
  4 sn'de bir sorar (`profili_getir`, sağlayıcıya 3 sn'den sık gidilmez);
  eşzamanlı sağlayıcı (eSIM Go, Airalo) profili siparişle döndürür. Webhook
  bilinçli olarak yok.
  · **İptal önce sağlayıcıda, sonra cüzdanda.** Sağlayıcı reddederse (profil
  kurulmuş) para iade edilmez. Mağaza admin'indeki iptal düğmesi ve durum
  alanı eSIM siparişinde `esim_siparisi_iptal_et`e yönlenir; sağlayıcı
  atlanamaz. Airalo iadeyi elle incelediği için adaptör talebi iletip hata
  yükseltir — otomatik iade olmaz, yönetici cüzdan işlemiyle yapar.
  · **Tavsiye edilen satış fiyatı** bayinin müşteriye ne diyeceğidir:
  bayiye satış × (1 + bayi grubunun `esim_kar_orani`'ı), küsurat
  atılmış. Paket kartında, paket sayfasında ("kazancın 7 ₺" ile) ve sipariş
  sayfasında görünür; oran sıfırsa hiç çizilmez. Sipariş anındaki değer
  `Teslimat.tavsiye_fiyati`nda saklanır — oran sonra değişse de bayinin o
  gün gördüğü rakam kayıtta kalır. Tek hesap `fiyatlandir()`; bayiye fiyat
  yazan her ekran oradan geçer. **Ekran müşteriye dönüktür:** tavsiye oranı
  varsa büyük rakam müşterinin fiyatıdır, bayinin alışı ve kazancı **göz
  düğmesiyle** açılır (`parca_fiyat.html`, `data-goz`/`data-alis`; bir göz
  bütün kartları açar, tercih `sessionStorage`'da oturum boyunca kalır).
  Bayi tezgâhta telefonu müşteriye çeviriyor, kendi alışı görünmesin.
  Tavsiye oranı yoksa saklanacak şey yok, bayinin fiyatı düz yazılır.
  · **Yükleme (top-up) satılmış eSIM'e yeni pakettir** (`esim.Yukleme`).
  Yükleme paketleri kataloğa yazılmaz: hangi paketin hangi eSIM'e uyduğunu
  sağlayıcı bilir, liste her açılışta ondan alınır (`yukleme_paketleri`)
  ve POST'ta kod yeniden doğrulanır — elle gönderilen kod listede yoksa
  reddedilir. Fiyat kuralı satıştaki gibi (asıl paketin oranı, o yoksa
  sağlayıcı varsayılanı; tavsiye grubun kârıyla), para yine `magaza.Siparis` (`urun_adi="eSIM
  yükleme · …"`) ile önce düşer, sağlayıcı reddederse döner. Sağlayıcıda
  yükleme **geri alınamaz**; mağaza admin'inde iptal yönetimin bilinçli
  kararıdır (iade bizden çıkar), teslim düğmesi yoktur. Desteklemeyen
  adaptör `SaglayiciHatasi` yükseltir, ekran sebebini yazar. Yükleme
  siparişleri eSIM listesinde durur, mağazanınkinde değil.
  · **Müşteri etiketi** (`Teslimat.musteri_adi/telefonu`) bayinin kendi
  notudur: müşteri aylar sonra "paketim bitti" diye arayınca bayi eSIM'i
  adla, telefonla ya da ICCID ile bulsun (`/esim/siparisler/?q=`). Telefon
  `apps.bayi.telefon.normalize`den geçer. Sağlayıcıya gitmez.
  · **Kâr iki yerde okunur, saklanmaz** (`apps/esim/rapor.py`). Yönetim:
  Kârlılık Raporu'nda ayrı "eSIM" bölümü — sağlayıcıdan alış (sipariş günkü
  kurla `alis_tl`), bayiye satış, kâr; sağlayıcı ve bayi kırılımı; başvuru
  kalemleriyle karıştırılmaz. Bayi: eSIM sayfasının üstünde bu ayın özeti —
  ödediği, tavsiye fiyatla satış, kazancı. Yalnızca tamamlanmış teslimat ve
  yükleme sayılır, iade edilen girmez. **Bayinin kazancı hakediş değildir**:
  biz ödemiyoruz, bayi müşteriden alıyor; bu yüzden hakediş sayfasına ve
  cüzdana girmez, "tavsiye fiyatla" diye nitelenir.
  · QR bizim ürettiğimiz SVG'dir (`segno`, aktivasyon kodundan); sağlayıcının
  görsel sunucusuna bağımlı değil. Sağlayıcı adı bayiye gösterilmez.
  **Bizim QR ile sağlayıcınınki farklı görünür ama aynı metindir** — ilk
  canlı satışta ikisi de çözülüp karşılaştırıldı (`LPA:1$…`, birebir).
  "QR farklı, kurulum yarım kaldı" şikâyetinde suç QR'da değil: profil
  telefona inmiş, hat ağa bağlanamamıştır (Veri Dolaşımı kapalı, ya da
  paket yalnızca belirli operatörde dolaşıyor — TR paketleri Vodafone —
  ve otomatik ağ seçimi onu bulamamış; elle seçilir). Teslim sayfası ve
  WhatsApp mesajı bu ikisini paketin `operatorler` alanıyla söyler.
  · **Telefondaki durum sağlayıcıdan sorulur** (`durumu_sorgula`;
  `Teslimat.kurulum_durumu/eid/aktivasyon_zamani`). Üç hâl: QR okutulmadı
  (EID boş), kuruldu ama bağlanmadı (EID dolu, ilk bağlantı boş), bağlandı.
  Bayinin sipariş sayfasında ve teslimat listesinde **Durumu sorgula**
  düğmesi; "çalışmıyor" diyen müşteride önce buna bakılır. Profil tek
  kullanımlıktır: kurulmuş profili telefondan silip yeniden okutmak eSIM'i
  yakar, sağlayıcı da artık iptal etmez.
  · Sadece sabit paketler alınır; günlük (dataType 2) paketler kademeli
  indirimle fiyatlandığı için bu sürümde katalogda yok.
- **Karar hangi yoldan verilirse verilsin tek servisten geçer.** Ödeme
  bildiriminin `durum` alanı formda düzenlenebilir; yönetici "Onaylandı"
  seçip kaydedince bildirim onaylanmış **görünüyor** ama para hiç hareket
  etmiyordu — bayi "bakiyem yüklenmedi" diyene kadar kimse fark etmez.
  `OdemeBildirimiAdmin.save_model` durumu bekleyene çevirip servisi çağırır.
  Bayi başvurusundaki onayla aynı kural; durum alanı olan yeni bir onay
  ekranı yazarsan aynısını yap.
- **Satır düğmesi kayda göre değişecekse unfold'un `actions_row`'u
  kullanılmaz.** `get_actions_row` kaydı bilmiyor, düğmeler satır başına
  süzülemiyor: sonuçlanmış bildirimde de "Onayla" duruyor ve basınca "zaten
  sonuçlandırılmış" uyarısı çıkıyordu. Adresler `get_urls` ile tanımlanır,
  düğme `list_display` sütununda koşullu çizilir (`karar_dugmeleri`).
- **Ödeme bildirimi para hareketi değildir.** Bayi havaleyi yapıp hangi
  hesaba ne yatırdığını `OdemeBildirimi` ile bildirir; **onaylanana kadar
  cüzdana dokunulmaz**. Aksi hâlde gelmeyen havale bakiyeye yazılmış olurdu.
  Onay tahsilat gibi işler (borç varsa önce o kapanır, bankanın bakiyesi de
  artar) ve tekillik anahtarı bildirimin kendisine bağlıdır: iki kez
  onaylamak parayı iki kez yazmaz. Red parayı hiç hareket ettirmez; karar
  notu bayinin cüzdan sayfasında görünür. Bekleyenler yan menüde rozetle
  sayılır.
- **Sonuçlanmış bildirimin durumu formdan değiştirilemez; yanlış onay
  parasıyla birlikte geri alınır.** Durum alanı serbestken yönetici
  onayladığı bildirimi "Reddedildi" yapabiliyordu: kayıt reddedilmiş
  görünüyor, yüklenen para bayinin cüzdanında duruyordu — defterle
  karşılaştıran olmadıkça fark edilmez. Alan artık sonuçlanmış kayıtta salt
  okunur (`OdemeBildirimiAdmin.get_readonly_fields`) ve `save_model` elle
  gönderilen isteği de geri çevirir. Düzeltmenin tek yolu satırdaki
  **"Onayı geri al"**: `odeme_bildirimini_geri_al` onayda yazılan her defter
  satırının karşısına ters kaydını yazar (satır silinmez), borcu kapatan
  kısım borca geri döner, bankanın bakiyesi de iner ve bildirim yeniden
  **Bekliyor**'a düşer — yönetici sebebini yazıp reddeder ya da düzeltip
  yeniden onaylar. Başvurudaki "yanlış onayı geri alma" kuralının aynısı.
  `OdemeBildirimi.para_surumu` her geri almada artar ve defter anahtarına
  girer; sürümsüz anahtarla ikinci onayın hareketi `IntegrityError`'a takılıp
  sessizce yutulurdu. Geri alma para oynattığı için düğme doğrudan çalışmaz,
  ne olacağını yazan onay ekranını açar ve iş POST ile yapılır.
- **Bayi yalnızca kendisine açılmış banka hesaplarını görür ve seçebilir**
  (`Banka.aktif` + `bayiye_gorunur`). Kısıt formun `queryset`'inde durur:
  gizli bir hesabın id'si elle gönderilse de bildirim kaydedilmez.
- **Bayiye giren her kuruş önce borcu kapatır.** Hakediş de elle yapılan
  bakiye yüklemesi de aynı sırayı izler: borç varsa oradan düşülür (`BORC_TAHSIL`),
  kalanı bakiyeye yazılır. 100 borcu olan bayi 250 hakediş alınca cüzdanında
  150 durur; hem 250 çekilebilir bakiye hem 100 borç aynı anda durmaz.
  Başvurudaki `hakedis` alanı yine 250'dir — mahsup cüzdan tarafındadır,
  bayinin hakedişi kısılmaz. Bayiye para giren yeni bir kalem eklersen
  aynı sırayı uygula.
- **Giriş bedeli özet rakamlarda tahsilatla birlikte sayılır.** Başvuru
  listesinin üstündeki "Bayilerden kesilen" kartı yalnızca `tahsil_edilen`i
  topluyordu; giriş bedeliyle satılan işlemde kart 0, kâr 150 yazıyor ve aynı
  ekrandaki iki rakam birbirini tutmuyordu. İkisi de bayinin cebinden çıkan
  paradır — satır sütunu (`tutar_ozeti`) zaten birlikte gösteriyordu. Bayiden
  gelen parayı toplayan yeni bir yer eklersen `giris_bedeli`'ni de kat.
- **Giriş bedeli ayrı bir hattır.** Bayi ürünü alırken öder: başvurunun
  **başlangıç durumuna** ("İlk giriş") yazılmış `TAHSILAT` kuralı, başvuru
  oluşturulduğu anda işler (`giris_bedelini_isle`). Aktivasyonda işleyen
  paradan (hakediş, ana hakediş) bilinçli olarak ayrıdır: aynı `para_islendi`
  bayrağını paylaşsalardı biri diğerini bloke eder, giriş bedeli kesilen
  başvuruda aktivasyon hakedişi hiç işlenmezdi. Alan `Basvuru.giris_bedeli`,
  hareket `CuzdanHareketi.giris_bedeli` ile işaretlenir, kâr hesabına girer.
  **Yalnızca olumsuz sonuçta iade edilir** — yanlış onay geri alındığında
  durur, çünkü ürün hâlâ bayinin elindedir. Bu yüzden `basvuru_parasini_geri_al`
  `giris_bedeli_dahil` parametresi alır; olumsuz duruma geçişte `True`,
  tetikleyici durumdan çıkışta `False`.
  Bir uç durum var: başvuru İlk giriş'ten *tetikleyici olmayan* bir duruma
  (İşlemde gibi) çekilirse giriş bedeli yerinde kalır ama İlk giriş'e
  dönülmedikçe ikinci kez de kesilmez. Akış İlk giriş → Aktif / İptal
  olduğu sürece bu yola girilmez.
- **Hiç işlemeyecek ücret kuralı kaydedilemez.** Para, `hakedis_tetikler`
  işaretli duruma geçilince işler; kural başka bir duruma bağlanmışsa
  hiçbir zaman çalışmaz. Alış kuralını "Giriş" durumuna bağlayan yönetici
  maliyeti hiç düşülmeyen bir kâr görüyordu (1000'e alıp 1150'ye satarken
  kâr 1150) ve sistem tek kelime etmiyordu. `UcretKurali.clean` artık bunu
  alan adıyla reddeder; tek istisna **giriş bedelidir** — başlangıç
  durumuna yazılmış `TAHSILAT`, başvuru oluşturulduğu anda kesilir
  (`giris_bedelini_isle`). Kural listesindeki tetikleyici durum sütunu eski
  kayıtları "hiç işlemez" diye işaretler; doğrulama yalnızca yeni kaydı
  tutar, var olanı düzeltmez.
- **Para, tetikleyen durumda *olmaya* bağlıdır.** `hakedis_tetikler` bir
  duruma geçilince işlenir; o durumdan **herhangi bir** duruma çıkılınca ters
  kayıtla geri alınır. Yalnızca `olumsuz_sonuc` durumunda geri almak sessiz
  bir tuzaktı: yanlış başvuruyu onaylayan yönetici durumu "İşlemde"ye çekiyor,
  para bayide kalıyordu. Yanlış onayın düzeltmesi de günlük işin kuralına
  uyar — tek yapılan şey durumu değiştirmektir.
- **Defterin tekillik anahtarı `Basvuru.para_surumu` içerir.** Para her geri
  alındığında sürüm artar. Anahtar sürümsüzken geri alınıp yeniden onaylanan
  başvurunun ikinci hareketi `IntegrityError`'a takılıp sessizce yutuluyordu:
  başvuru "150 hakediş ödendi" derken cüzdanda karşılığı yoktu. Yeni bir para
  hareketi eklerken anahtara sürümü koy.
- **Onaylanan başvurunun kimlik görüntüleri anında silinir** (`belgeleri_sil`).
  Yanlış onay geri alınabilir, para geri döner ama **görüntüler geri gelmez.**
  Bayiden yeniden istemek gerekirse başvuru `bayi_duzenleyebilir` işaretli bir
  duruma (Eksik Evrak) alınır.
- **Formda sabit alan listesi yoktur.** Hangi alanların sorulacağına
  `KategoriAlani` kayıtları karar verir — İsim, TC No gibi çekirdek alanlar
  dahil. `cekirdek_alan` doluysa değer başvurunun kendi kolonuna yazılır
  (aranabilir olur), boşsa `ek_bilgiler` JSON'una girer. Forma yeni bir sabit
  alan ekleme; kategori tanımından geçir.
- **Bir alan yalnızca belirli tarifelerde sorulabilir.** `KategoriAlani.tarifeler`
  boşsa alan kategorideki bütün tarifelerde çıkar; tarife işaretlenirse koşul
  **kategori ve tarife** olarak birlikte aranır ("Faturalı Yeni Hat *ve* Genç
  Tarife"). Boş = hepsi kuralı ücret motorundaki `kapsam()` ile aynı: pozitif
  liste olsaydı her yeni tarifede bütün alanları tek tek işaretlemek
  gerekirdi. Alternatif, aynı işin her tarife bileşimi için ayrı kategori
  açmaktı — form alanları yirmi kez kopyalanırdı.
  Kapı iki yerde durur: kutu tarayıcıda gizlenir (`data-tarifeler`,
  `templates/basvurular/yeni.html`) ve `BasvuruFormu.clean` sorulmamış alanın
  değerini almaz, zorunluluğunu aramaz — gizli girdi elle gönderilse de
  yazılmaz. Gizlerken `required` de kaldırılır: gizli ve zorunlu bir girdi
  tarayıcıyı kilitler, form gönderilmez ama odaklanılamayan alana uyarı da
  basılamaz. Bütün alanları gizlenen **bölüm** başlığıyla birlikte kalkar.
  Yönetimde kutu Kategori satırının yanındaki **"+ Tarife koşulu"** düğmesiyle
  açılır (`templates/admin/katalog/kategorialani/change_form.html`): alanların
  çoğunda koşul yok, her tanım ekranında açık duran bir tarife listesi
  gürültüydü. Koşul girilmiş kayıtta bölüm kendiliğinden açık gelir ve düğme
  vurgu renginde sayıyı yazar. Liste kategorinin tarifeleriyle sınırlıdır;
  başka kategorinin tarifesi seçilirse `KategoriAlaniFormu` reddeder — koşul
  hiçbir zaman sağlanmaz, alan da hiç görünmezdi. Alan listesindeki *Tarife
  koşulu* sütunu bunu kayıt kayıt aramadan gösterir.
- **Yeni hatta verilen numarayı yönetim yazar, bayi görür**
  (`Basvuru.aktif_numara`). Numarayı operatör veriyor, yönetim tabletten
  SIM'le eşleştiriyor; müşteri numarasını öğrenmek için bayiyi, bayi de
  yönetimi arıyordu. Alan bir form alanı değildir — bayi sormaz, sonuçtur —
  bu yüzden `KategoriAlani` değil başvurunun kendi kolonudur (aranabilir).
  Yönetim panelinde **Durum** bölümünde, durum kutusunun hemen altında
  durur: hattı açıp "Aktif" seçen yönetici numarayı aynı yerde yazar.
  `Basvuru.clean` `apps.bayi.telefon.normalize`den geçirir ve 10 hane
  ister. Bayi numarayı başvuru detayının en üst kartında (kopyala ve ara
  bağlantısıyla), Başvurularım listesinde ve panelde görür, numarayla
  arar. Boşsa hiçbir yerde çizilmez. Okunur biçim tek yerden:
  `panel.telefon` süzgeci (`0532 123 45 67`).
- **Çekirdek alan çoğu alanda boş kalır.** Yalnızca başvurunun kendi kolonu
  olan bilgilerde (isim, TC no, telefon) doldurulur; o zaman değer aranabilir
  olur. Bir kategoride aynı çekirdek alan iki kez kullanılamaz, görsel/dosya
  alanları hiç kullanamaz. Bu yüzden **bir kategoriye istenildiği kadar görsel
  alanı eklenebilir** (çocuk kimliği, ebeveyn kimliği…): kod farklı olsun,
  çekirdek alan boş kalsın. Yönetici bunu bilmeyip çekirdek alanı doldurunca
  ham veritabanı kısıtı mesajı görüyordu
  ("kategori_cekirdek_alan_benzersiz ihlal edildi"); `KategoriAlani.clean`
  artık çakışan alanı adıyla söyleyip ne yapılacağını yazar. Yeni bir tekillik
  kısıtı eklersen mesajını da yaz — kısıt adı kullanıcıya bir şey anlatmaz.
- **Yeni kategori boş formla açılmaz; bilinen bütün alanlar açık gelir.**
  Panelden kategori eklemek hiç alanı olmayan bir kategori bırakıyordu: bayi
  boş form görüyor, yönetici yirmi satırı elle giriyordu.
  `apps/katalog/varsayilan_alanlar.TUM_ALANLAR` hepsini açar
  (`BasvuruKategorisiAdmin.save_related`); bu kategoride sorulmayacak olanı
  yönetici "Aktif" kutusundan kapatır. Kapatmak eklemekten kolaydır ve kural
  tek cümlede durur — müşteri tipine göre dallanma **yok**, kimlik de pasaport
  da gelir. Her kategoriye açılan niş alanlar (Taşınacak No, Geçeceği
  Operatör) zorunlu **değildir**: kapatmayı unutan yönetici bayiyi olmayan
  bir bilgiyi doldurmaya mahkûm etmesin. Var olan alana dokunulmaz, kapatılan
  alan geri açılmaz. Ortak alan listesi tek yerde durur; `baslangic_verisi`
  de oradan okur. Yeni bir alan yaygınlaşırsa listeye buradan eklenir.
- **Başvuru tipi bayi bazında kapatılabilir.** Her bayi her işi yapmıyor;
  kimine yalnızca kontörlü hat, kimine numara taşıma da açılıyor.
  `BayiProfili.kapali_kategoriler` **negatif** listedir: boş liste "hepsi
  açık" demektir ve sonradan eklenen yeni bir tip bütün bayilere
  kendiliğinden gelir. Pozitif liste her yeni tipi bayi bayi işaretlemeyi
  gerektirirdi; unutulan bayide tip hiç görünmez, sebebini de kimse bilmezdi
  (kategori alanlarındaki kuralın aynısı: kapatmak eklemekten kolaydır).
  Yönetici kutuyu **kullanıcı sayfasından** açar (`BayiProfiliInline`, ayrıca
  Bayi Profilleri ekranı); onay kutusu listesidir — çoklu seçim kutusunda
  kapatmak Ctrl'e basmayı gerektiriyor, yönetici tek tıkla açtığını
  kapatıyordu. Süzme tek yerden geçer: `apps.bayi.kategoriler`. Kapı beş
  yerde durur: kategori ekranı, panel kartları, tarife kataloğu, hakediş
  sayfası ve form açılışı. Bayiye içerik gösteren yeni bir ekran yazarken
  oradan da geçir. **Kapalı tip gizlenir**, bakiye yetersizliği gibi kapalı
  gösterilmez: bakiye geçicidir (para yatınca açılır, o yüzden sebebiyle
  durur), kapatma ise yönetimin kararıdır ve bayinin yapabileceği bir şey
  yoktur. Adresi elle yazan bayi sessiz bir 404 değil sebebini görür; hepsi
  kapalıysa kategori ekranı "tanımlanmamış" değil "hesabına açık tip yok"
  der. Girilmiş başvurular yerinde kalır — liste ve detay kısıtlanmaz, yarım
  kalan iş tamamlanabilsin. Katalogda bir tarife ancak geçerli olduğu
  **bütün** kategoriler kapalıysa düşer.
- **Bayi parolasını başvuru sırasında kendisi seçer.** Kamuya açık formda
  parola alanı vardır; `BayiBasvurusu.parola_ozeti` yalnızca **özeti** tutar,
  düz metin hiçbir yere yazılmaz — Telegram bildirimine de girmez. Özet
  hesap açılırken doğrudan `User.password`'e taşınır; kimse parolayı görmeden
  bayi kendi seçtiği parolayla girer. **Kullanıcı adı telefon numarasıdır** —
  ayrıca bir ad uydurup telefonla bildirmek gerekmiyor. Hesap açma mantığı tek
  yerde: `apps.bayi.services.bayi_hesabi_ac`.
- **Başvurunun durumunu "Onaylandı" yapmak hesabı açar.** Listedeki "Seçili
  başvurular için bayi hesabı aç" işlemi de aynı işi yapar; ikisi de aynı
  servisi çağırır (`BayiBasvurusuAdmin.save_model`). Onayı yalnızca listedeki
  işleme bağlamak sessiz bir tuzaktı: yönetici durumu değiştirip onayladığını
  sanıyor, bayi giriş ekranında "kullanıcı adı veya parola hatalı" görüyordu.
  Sistemde günlük işte tek elle yapılan şey durumu değiştirmektir; onay da bu
  kurala uyar. Başvuruda parola yoksa hesap girişe kapalı açılır ve yönetici
  bunu açık bir uyarı olarak görür.
- **"Bayi giremiyor" şikâyeti `manage.py bayi_hesap <numara>` ile ayrıştırılır.**
  Başvuru mu düşmemiş, hesap mı açılmamış, parola mı yok, numara mı başka
  biçimde kaydedilmiş — dördü de giriş ekranında aynı hatayı gösterir. Komut
  parolayı göstermez, yalnızca var/yok der.
- **Parola unutulunca yönetici yenisini üretir; e-posta ile sıfırlama yoktur.**
  Kullanıcı listesinin her satırında ve kullanıcı sayfasının üstünde "Yeni
  parola" düğmesi var. `apps.bayi.parola.uret` telefonda okunabilecek bir
  parola verir (`kavun-limon-7431`; Türkçe'ye özgü harf yok, bayi klavyede
  aramasın), parola bir kez gösterilir ve yanında bayiye gönderilecek mesaj
  hazır durur. Üretme **POST ile** olur: düğme düz bağlantı olsaydı
  yöneticinin açtığı herhangi bir sayfa bayinin parolasını sıfırlatabilirdi.
  Parola log'a, mesaja, bildirime girmez — sistem yalnızca özetini saklar,
  bu yüzden "eski parolası neydi" diye bakılamaz.
- **Bayi başvurusunda fiyat kademesi zorunludur.** `BayiBasvurusu.bayi_grubu`
  onay ekranında durur ve hesap açılırken cüzdana yazılır
  (`bayi_hesabi_ac`); yönetici onaydan sonra bir de cüzdan ekranına gitmiyor.
  Bir süre yalnızca uyarı vardı: hesap kademesiz açılıyor, uyarı okunmayınca
  bayi ne fiyat görüyor ne hakediş alıyordu. Kural motoru grup kapsamını
  `bayi_grubu__isnull=True | bayi_grubu=grup_id` diye süzdüğü için kademesiz
  cüzdana **yalnızca gruba bağlı olmayan** kurallar uyar; fiyatlar grup
  başına tanımlıysa bayi kategori ekranında hiçbir rakam görmez ve
  `basvuru_bedeli` sıfır döner. Kapı iki yerde durur: `bayi_hesabi_ac`
  kademesiz başvurudan hesap açmaz (`HesapAcilamadi`) ve
  `BayiBasvurusuAdminFormu` onayı kaydettirmez — servis tarafında durdurmak
  kaydı "Onaylandı" bırakıp hesabı açmamak olurdu. Hesabı zaten açılmış eski
  kayıtlar serbesttir; kademe artık cüzdanda yaşar. Kademe başvurana sorulmaz —
  kamuya açık formun alan listesi sabittir (`fields`), yönetimin fiyat kararı
  oraya sızmaz.
- **Kullanıcı seçtiren kutularda ekle/düzenle/sil düğmeleri kapatılır.**
  Başvurudaki "Açılan Hesap" kutusunun yanındaki kırmızı çöp kutusu seçimi
  değil, seçili kullanıcının kendisini siler; yanlış hesap seçilince ilk
  refleks ona basmak oluyor ve bir kez yönetici hesabı böyle silindi.
  `BayiBasvurusuAdmin.formfield_for_foreignkey` üçünü de kapatır. Kullanıcı
  seçtiren yeni bir alan eklersen aynısını yap.
- **Telefon numarası her yerde tek biçimde durur: `5321234567`.**
  `apps.bayi.telefon.normalize` boşluğu, ayraçları, `+90` ülke kodunu ve
  baştaki sıfırı atar; harf içeren gerçek kullanıcı adlarına dokunmaz. Dört
  yerde çağrılır: başvuru formu, yönetim panelinin kullanıcı ekleme/düzenleme
  formu, `BayiProfili.save`, `BayiBasvurusu.save`. Giriş formu da aynı
  normalleştirmeden geçer — bayi "0532 123 45 67" yazınca da girer. Numara
  tutan yeni bir alan eklersen buradan geçir; aksi hâlde aynı kişi iki ayrı
  hesap olur ve hangisiyle gireceğini bilemez.
- **Kullanıcı her yerde adıyla anılır, numara yanında durur:** "Fadil
  Yiğitdöl · 5304517888". Kullanıcı adı telefon numarası olduğu için seçim
  kutuları, süzgeçler ve listeler yalnızca numara gösteriyordu; yönetici
  bayiyi ezbere bilmek zorundaydı. Görünen ad **tek yerden** gelir:
  `apps.bayi.etiket`. Django'nun hazır User modelinin `__str__`ü oraya
  bağlanır (`BayiConfig.ready`) — modeli değiştirmek (`AUTH_USER_MODEL`)
  canlı veritabanında hesap tablosunu taşımak demekti. Sıra: hesabın kendi
  adı-soyadı (ek sorgu atmaz; `assertNumQueries(0)` ile korunur) → profildeki
  firma ünvanı → yalnızca numara. Liste sütunu `kullanici_etiketi_html`
  (ad üstte, numara altta), operatör adlarının yanında duran yerler
  `kisa_ad` (numarasız), `.values()` ile okuyan raporlar
  `etiket_sutunlari` + `etiket_satirdan`. Kullanıcıyı gösteren yeni bir yer
  yazarken bunlardan birinden geç; `get_username()`i tek başına basma, aynı
  `unvan or username` kalıbını da yeniden yazma (altı yerde kopyalanmıştı).
  Bayi adı aranan admin'lerde `search_fields`e `first_name`, `last_name` ve
  `bayi_profili__unvan` da girer.
- **Roller birbirini dışlamaz.** Bir firma hem bayi hem tedarikçi olabilir
  (`BayiProfili.bayi_mi` / `tedarikci_mi`). Bayi başvuru getirir ve hakediş
  alır; tedarikçi aktivasyonu yapar ve alış bedelini alacak olarak yazar.
- **Kimlik görüntülerini üç taraf görür:** başvuruyu getiren bayi, işlemi
  üstlenen tedarikçi ve personel. Tedarikçi aktivasyonu fiilen kendisi
  yaptığı için bilgileri kimlikten okuyup operatör sistemine giriyor.
  İlgisiz kullanıcı 404 alır. Kural iki yerde: `basvurular.views.belge`
  (dosya erişimi, `_belge_kaydi`) ve `detay` (`belgeler_gorunur`) — birlikte
  güncellenir.
  **Görüntü sitenin içinde açılır, cihaza inmez.** Bağlantılar dosyanın
  kendisine gidiyordu; telefon ve bazı tarayıcılar kimliği indirip
  galeriye/İndirilenler'e koyuyordu. Tıklanan adres
  `BasvuruBelgesi.goruntuleme_url()` → `belge_goster` sayfasıdır (resmi
  `<img>` ile gömer, uzun basma menüsü ve sürükleme kapalı); dosyanın kendisi
  `Content-Disposition: inline` ile, **dosya adı olmadan** sunulur — adı
  gören tarayıcı indiriyordu. Bayi, tedarikçi ve yönetim paneli aynı
  sayfayı açar. Belgeye bağlanan yeni bir yer yazarsan `goruntuleme_url`
  kullan; `get_absolute_url` yalnızca `<img src>` içindir.
- **Tedarikçi işlemin sonucunu kendisi yazar.** Aktivasyonu fiilen o yapıyor;
  hattı açan da operatörden ret yiyen de o. Panelindeki satır başvuru detayına
  gider (bir süre gitmiyordu: müşteri bilgilerini ve kimlik görüntülerini
  göremeden aktivasyon yapılamaz) ve detayda durum kutusu vardır. Hangi
  durumları seçebileceği veridir — `BasvuruDurumu.tedarikci_secebilir` —
  başlangıç durumu dışında hepsi açık gelir; istemediğini yönetici kapatır.
  **Sonuçlanmış başvuruya dokunamaz:** para işlendikten sonra durumu geri
  çekmek ters kayıt demektir, yanlış onayın düzeltmesi yönetim kararıdır ve
  tedarikçi ödediği bedeli tek başına geri alamamalı. Değişiklik `durum_bildir`
  görünümünden geçer, kimin yaptığı ve notu durum geçmişine düşer
  (`Basvuru._degistiren` / `_aciklama`). Detayda herkes kendi hesabını görür:
  bayi kesintisini ve hakedişini, tedarikçi bu işlem için ödediğini — bayinin
  marjı tedarikçiye açılmaz. **Başvuruyu hangi bayinin getirdiği de
  gösterilmez** (`detay_alanlari.BAYIYI_ELE_VEREN`): tedarikçi işlemi üstlenir,
  müşteriyle ilgilenir; aradaki bayiyi tanıması doğrudan temasa kapı açar.
  Satır listeye hiç girmediği için "Görünüm" kutusundan da açılamaz. Tedarikçiye
  bayiyi ele verecek yeni bir alan eklersen bu listeye de yaz.
- **Destek talebi bayi ile yönetim arasındaki yazışmadır** (`apps/destek`).
  Bayi telefonla arıyordu; konuşma hiçbir yerde kalmıyor, kimin ne dediği
  unutuluyordu. Talep bir **konu** ve **mesajlardan** oluşur; isteğe bağlı
  olarak bir başvuruya bağlanır — kutuya yalnızca bayinin kendi başvuruları
  girer. Adres referans numarasıyla kurulur (`/destek/VV6YEHDW/`), sayaçla
  değil.
  **Durum bilinçli olarak iki tanedir:** açık ve kapalı. "Sıra kimde"
  sorusu ayrı bir durum değil, son mesajın kimden geldiğinden okunan bir
  bayraktır (`yanit_bekliyor`); üçüncü bir durum iki kaydı senkron tutmak
  demekti ve senkron kalmayan gün yanlış tarafı bekletirdi.
  **Kapalı talep kapalı kalır; mesaj yazmak durumu değiştirmez.** Bir süre
  kapalı talebe yazılan mesaj onu yeniden açıyordu ("konuşma sürüyorsa kayıt
  kapalı görünmemeli") — sonuç, kapatmanın hiç tutmaması oldu: yönetici
  kapatıyor, bayi yazıyor, talep yeniden açılıyor ve bayi kapalı talebe
  sürekli yazabiliyordu. Kapatmak yazışmayı **bitirir**; devam eden konu
  için bayi yeni talep açar, yeniden açmak yönetimin bilinçli kararıdır
  (durum alanı ya da listedeki "yeniden aç" işlemi). Bayi tarafında kapı iki
  yerde durur: kutu hiç çizilmez ve `detay` görünümü elle gönderilen isteği
  geri çevirir; servis de kapalı talepte bayi mesajını reddeder
  (`TalepKapali`). Yönetim kapalı talebe not düşebilir — talep yine kapalı
  kalır ve panel "bayi bu yanıta cevap yazamaz" diye uyarır.
  Mesaj eklemenin tek yolu `destek.services.mesaj_ekle`: kaydı yazar,
  talebin özet alanlarını günceller, gerekirse yeniden açar. Yönetim
  panelindeki satır içi yanıt kutusu da (`save_formset`) oradan geçer;
  doğrudan kaydedilseydi talep yanıtlandığı hâlde rozette beklemeye devam
  ederdi. Talep Telegram'a **bildirilmez** (aşağıda *Bildirimler*): açık
  talep zaten rozetle sayılıyor.
- **Bayi menüsünün sırası bilinçlidir:** Panel, Tarifeler, Yeni başvuru,
  Başvurularım, Hakedişler, Cüzdan. Bayi müşteriyle önce tarifeye bakıyor,
  sonra başvuruyu giriyor; menü bu sırayı izler.
- **Rol ekranları karışmaz.** Bayi görünümleri `@bayi_gerekli`, tedarikçi
  görünümleri `@tedarikci_gerekli` ile korunur (`apps/bayi/yetki.py`).
  Yeni bir ekran eklerken hangi role ait olduğunu belirt; profili olmayan
  eski kullanıcılar bayi sayılır. Giriş sonrası yönlendirme tek yerde:
  `baslangic_sayfasi()`.
- **Cüzdan yoksa açılır, çökmez.** Elle oluşturulmuş kullanıcının cüzdanı
  olmayabilir; para işlenirken `_cuzdani_getir` sıfır bakiyeli cüzdan açar.
- **Aynı kapsamda iki ücret kuralı varsa son eklenen kazanır.** Sonuç
  rastgele olmamalı; sıralama `(özgüllük, öncelik, pk)` üçlüsüne dayanır.
- **Kâr = bayiden tahsilat + giriş bedeli + alınan prim − bayiye hakediş −
  alış bedeli.** `Basvuru.kar` bunu hesaplar. **Karşı tarafla (operatör ya da
  tedarikçi) para iki yönde birden akar** ve her yön ayrı bir kuraldır:
  `KuralYonu.ALIS` (maliyetim — gider) ve `KuralYonu.PRIM` (aldığım prim —
  gelir). İkisi aynı işlemde birlikte tanımlanabilir; `alis_ve_primi_isle`
  ikisini de kendi bayrağı ve kendi defter anahtarıyla işler, biri boşken
  diğeri çalışır.
  · **Tedarikçi varsa:** maliyet onun **cüzdanına alacak** yazılır (cüzdana
  giren para gibi önce borcunu kapatır), prim ise **hesabından düşer**
  (bakiyesi yetmezse borca yazılır).
  · **Tedarikçi yoksa:** operatörün cüzdanı olmadığı için hareket yazılmaz;
  iki tutar da yalnızca başvuruya işlenir ve kâra girer.
  Tedarikçi sonradan da atanabildiği için bayi tarafındaki paradan ayrı işlenir.
  **Bu alan iki kez yanlış kuruldu.** Önce "ana hakediş" adıyla tek kalemdi ve
  gelir sayılıyordu: 1000'e alıp 1150'ye satan yönetici kârını 2150 görüyordu.
  Yön düzeltilince bu sefer prim alan yönetici primini maliyet hanesine yazmak
  zorunda kaldı, kâr eksiye düştü. Ders: **karşı tarafla olan hesap tek yönlü
  değildir.** Alanlar `Basvuru.alis_bedeli` / `alinan_prim`; veritabanındaki
  kural değeri hâlâ eski adını taşır (`tedarikci_geliri`), kayıtlı kurallar
  bozulmasın diye değiştirilmedi.
- **Özet rakamlar defter satırlarından değil başvurudan okunur.** Panelin
  "Bu ay hakediş" değeri bir süre yalnızca `HAKEDIS` tipli cüzdan
  hareketlerini topluyordu; iki yerde yanlıştı. İptalin ters kaydı (`IPTAL`)
  sayılmadığı için bakiye sıfırlanmışken panelde hakediş duruyordu, borcu
  kapatan hakediş de `BORC_TAHSIL` satırına düştüğü için eksik görünüyordu.
  `Basvuru.hakedis` ikisini de doğru taşır: geri alınan başvuruda sıfırlanır,
  borç mahsubunda tam tutarı korur. Yeni bir özet rakam eklerken başvurunun
  alanlarından topla; defter satırı tek tek doğrudur ama toplamı almak
  hareket tiplerini bilmeyi gerektirir (borç satırının işareti bakiye
  satırıyla aynı anlama gelmez).
- **Kârlılık raporu tarih aralıklıdır ve aralık en fazla 31 gündür**
  (`apps/rapor.py`, `/yonetim/rapor/`). Kâr rakamı başvuru listesinin üstünde
  de duruyor ama orada uygulanan filtreye bağlı ve kırılımı yok; "bu ay hangi
  kategori kazandırdı, hangi bayi ne getirdi" sorusu cevapsız kalıyordu.
  Rapor **sonuçlanma tarihine** göre çalışır: kâr ancak işlem sonuçlanınca
  kesinleşir, yarım işlenmiş başvuru tabloyu yanıltır. Sayfa bunu açıkça
  yazar. Aralık sınırı bilinçlidir — rapor her açılışta başvuruları tarar,
  yıllık bir aralık sunucuyu boşuna yorar; sınır aşılırsa form sebebini
  söyler ve varsayılan aralığa (son 30 gün) düşer. Bitiş günü aralığa
  **dahildir** (`GunAraligiFiltresi` ile aynı gerekçe: alan `DateTimeField`,
  saf tarih gece yarısı demek). Para kalemleri tek yerde durur
  (`rapor.KALEMLER`); toplam da kırılımlar da oradan üretilir, biri
  güncellenip diğeri unutulmaz. Yeni bir para kalemi eklersen o sözlüğe yaz.
- **Stok ve alacak özeti tek ekranda toplanır** (`apps/ozet.py`,
  `/yonetim/ozet/`). SIM stoğu, bayilerdeki kartlar, beklenen SIM
  karşılıkları, tedarikçi borçları ve işlenen ana hakediş ayrı listelerde
  duruyordu; yönetici hepsini ayrı ekranda açıp kafasında topluyordu. Her
  satır kendi filtreli listesine gider — sayı burada, ayrıntı bir tık ötede.
  Rakamlar hesaplanır, **saklanmaz**: kaynak yine başvurular, SIM kartlar ve
  cüzdanlardır; ikinci bir doğruluk kaynağı yaratılmaz. Operatöre ödenen alış
  bedeli sistemde bir borç kaydı doğurmaz (operatörün cüzdanı yok) — sayfa
  bunu açıkça yazar. Tedarikçiye borcumuz onun cüzdanının **bakiyesinde**
  durur.
- **Bayi hakedişini şeffaf görür.** `/hakedisler/` sayfası hangi tarifeden ne
  kazanacağını, kesintisini ve elde kalan neti gösterir. Yeni bir para kalemi
  eklerken bu sayfayı da güncelle.
- **Bir tarife birden çok kategoride geçerli olabilir.** `Tarife.kategoriler`
  çoktan çoğadır; operatör aynı paketi hem numara taşımada hem yeni hatta
  veriyorsa tarife bir kez açılır, kategoriler işaretlenir. Tekil `kategori`
  alanı varken aynı tarife iki kez açılıyor, fiyatı iki yerde güncelleniyordu.
  **Tarifede tekillik kısıtı yoktur.** Eski kısıt (kategori, operatör, ad)
  bir kategoride aynı tarifenin iki kez açılmasını engelliyordu; kategori
  çoğullaşınca veritabanı karşılığı (operatör, ad) olurdu. O kısıt konunca
  migration üretimde patladı: "İlk Turkcellim" iki kategoride ayrı ayrı
  tanımlıydı ve kısıt onların birleştirilmesini şart koşuyordu. Her tarifenin
  kendi para kuralları olduğu için birleştirmek hangi fiyatın kalacağına karar
  vermektir — migration'ın vereceği bir karar değil. Yönetici isterse
  kategorileri tek tarifede işaretleyip diğerini kapatır. Kısıtı geri ekleme. Kategori sayfasındaki satır içi tablo bağlantı tablosu
  üzerinden kurulur (`Tarife.kategoriler.through`) — oradan tarife
  eklenip çıkarılır, ayrıntısı Tarifeler ekranından girilir. Tarife
  sorgularında `kategori=` değil `kategoriler=` kullan.
- **Tarifenin kısa açıklaması seçildiği anda açılır.** `Tarife.kisa_aciklama`
  doluysa bayi başvuruda o tarifeyi seçince `<dialog>` ile karşısına çıkar,
  tek düğmesi "Tamam"dır. Atlanmaması gereken uyarıyı listede küçük yazıyla
  göstermek yetmiyordu. Metin `<option>` üzerinde `data-uyari` ile taşınır;
  seçim değişince sunucuya ikinci tur atılmaz. Kutu ana formun **dışındadır**
  (içindeki kapatma formu iç içe geçseydi HTML geçersiz olurdu) ve olay
  belgeye bağlanır, çünkü tarife kutusu HTMX ile yenileniyor.
- **Tarifenin parası tarifenin sayfasından girilir.** Kural motoru genel
  kalır (kampanya, bayi grubu, tek bayi, tarih aralığı hâlâ mümkün) ama günlük
  iş üç rakamdan ibaret: **operatörden alışım**, **tedarikçiden alışım**,
  **bayiye ödeyeceğim** (bayi grubu = bayinin fiyat listesi). `TarifeAdmin`
  altındaki **Bu tarifenin parası** satır içi tablosu (`TarifeParaKuraliInline`)
  üçünü aynı ekranda toplar; üstündeki özet her alış kaynağı × bayi grubu
  bileşimi için kârı yazar. Kayıtlar yine `UcretKurali` — motorun tek kaynağı
  değişmedi.
  `KuralYonu` etiketleri bilinçli olarak alış/satış diliyle yazıldı: "yön" ve
  "hakediş" soyut kalıyor, "Alışım (operatörden ya da tedarikçiden)" herkesin
  bildiği şey. `UcretKurali.ad` boş bırakılabilir, kapsamdan üretilir; iki
  rakam girmeye gelen yönetici bir de ad uydurmasın.
  **Her kural yalnızca kendi ekranında görünür.** *Ücret ve Hakediş
  Kuralları* bayi tarafını (bayiden tahsilat, bayiye hakediş), *Operatörden
  Alışlarım* tedarikçisi olmayan alış/prim kurallarını, *Tedarikçiden
  Alışlarım* tedarikçili olanları listeler. Üçü tek listede karışıkken
  yönetici "bu satır kimin hesabı" diye her seferinde yön rozetini okumak
  zorunda kalıyor, tedarikçiye ait bir fiyat operatör kurallarının arasında
  görünüyordu. Ayrılan yalnızca **görüntüleme ve giriş yeri**; kayıt yine
  tek tabloda (`UcretKurali`), motor tek kaynaktan okur. Ayrım üç yerde
  birden durur, yoksa kayıt girildiği anda kaybolur: liste süzgeci
  (`get_queryset`), yön kutusunun seçenekleri (`formfield_for_choice_field`)
  ve yön filtresi (`BayiYonuFiltresi`; Django'nun hazır alan filtresi dört
  seçeneği birden yazıp ikisinde boş sonuç veriyordu). Alış kuralının genel
  adresi kendi ekranına yönlendirilir — eski yer imi 404 vermesin. Listeye
  yeni bir sütun ya da uyarı eklerken **iki tarafa da** ekle:
  "hiç işlemez" işareti bir süre yalnızca genel listedeydi, tetiklemeyen
  duruma bağlanmış alış kuralı sessizce hiç çalışmıyordu
  (`TetikleyiciGosterimi`).
  **Operatörle Hesabım / Tedarikçiyle Hesabım** ekranları iki yönü birden
  alır: yön kutusu yalnızca maliyet ve prim seçeneklerini gösterir
  (`formfield_for_choice_field`), bayi tarafındaki yönler oraya karışmaz.
  Yön bu ekranlarda bir süre sabitti; prim alan yönetici primini maliyet
  hanesine yazmak zorunda kalıyordu.
  Kural listesinde **bayi grubu kendi sütunundadır**: aynı fiyatın kademe
  kademe girildiği bir tabloda aranan ilk şey odur, kapsam özetinin içinde
  bir etiket olarak okunması zordu. Kâr satırı **gelir ya da gider kalemi
  eksikken rakam yazmaz**, eksiği adıyla söyler; alış girilmeden hesaplayınca
  kâr şişik, tahsilat girilmeden hesaplayınca eksi görünüyordu — ikisi de
  "kural yarım kalmış" demek.
  **Kural sayfasındaki "Bu kapsamın hesabı" motorla aynı mantıkla eşleşir**
  (`UcretKuraliAdmin._kapsam_tutarlari`). Kardeş kurallar bir süre **tam
  eşitlikle** aranıyordu: operatörden alış fiyatının bayi grubuyla işi yok,
  o kural gruba bağlanmaz — ama bayiye ödenen kurala bir grup seçilince alış
  "girilmedi" görünüyor, kâr hesaplanamıyordu. Yönetici grubu kaldırınca
  hesap düzeliyor, sebebi görünmüyordu. Artık kapsam alanı boş olan kural
  "hepsi" sayılır (motordaki `kapsam()` ile aynı) ve aynı yönde birden çok
  aday varsa (özgüllük, öncelik, pk) kazanır. Daha **dar** kapsamlı kurallar
  sayılmaz: onlar bu kapsamın yalnızca bir kısmına uyar.
  **Kural eklerken kategori çoklu seçilir** (`UcretKuraliEklemeFormu`): aynı
  fiyat çoğu zaman birkaç kategoride birden geçerli, her biri için formu
  baştan doldurmak gerekiyordu. Motor değişmedi — kural yine tek kategoriye
  bağlı tek kayıt; seçilen her kategori için ayrı kural açılır, biri sonradan
  tek başına düzenlenebilir. Düzenleme ekranında alan tekildir. Tarife
  seçiliyse form her kategoride geçerli olduğunu doğrular; modelin kendi
  `clean`'i tekil alana baktığı için eklemede o kontrol devreye girmezdi.
  **Tedarikçi kapsamı bir süre yalnızca motorda vardı**, formda alanı yoktu:
  tedarikçiden alış fiyatı panelden hiç girilemiyordu. Hem kural admin'inde hem
  satır içi tabloda alan artık var; kullanıcı seçen kutuların ekle/düzenle/sil
  düğmeleri `_kullanici_kutusunu_sadelestir` ile kapatılır.
  **Bu tabloda gösterilemeyen hata tarife sayfasını kilitlemez.** Kuralın
  kapsamı satır içi tabloda tam görünmez: kategori ve kampanya alanları orada
  yok, tarife gizli alanda taşınır. Kategorisi tarifeden düşmüş **tek bir eski
  kural** yüzünden model doğrulaması hatayı gizli `tarife` alanına yazıyor,
  unfold da onu hiçbir yerde çizmiyordu: sayfanın üstünde "Lütfen aşağıdaki
  hatayı düzeltin" yazıyor, aşağıda düzeltilecek bir şey görünmüyordu. Tarife
  o günden sonra hiç kaydedilemiyordu — ne ikinci kategori eklenebiliyor ne
  fiyat güncellenebiliyordu. Formda hiç olmayan alana (kampanya) yazılan hata
  ise sayfayı `ValueError` ile çökertiyordu. `TarifeParaKuraliFormu` bu tabloda
  çizilmeyen alanlara düşen hataları eler; kayıttan sonra `kapsami_dusen_kurallar`
  hâlâ duruyorsa kuralı adıyla uyarı olarak yazar. Kilit yerine uyarı, çünkü
  düzeltmenin yeri bu ekran değil kuralın kendi ekranı: düzeltilemeyen bir
  kilit, okunmayan bir uyarıdan beterdir. Bu tabloda **düzeltilebilen** hata
  (tetikleyici durum) blokamaya devam eder. Satır içi tabloya modelin
  `clean`'inin dokunduğu yeni bir alan eklersen ya alanı tabloya koy ya da
  aynı yoldan geçir.
- **SIM kart eklenirken operatör zorunludur.** Operatörsüz kart başvuru
  formundaki stok kutusunda doğru operatöre süzülemez ve SIM alacağının
  kimden beklendiği yazılamaz. Alan modelde `null=True` kalır — operatör
  kaydı silinirse kartlar da silinmesin diye (`SET_NULL`) — ama `blank=False`
  olduğu için form boş bırakmaya izin vermez.
- **SIM kartlar listeyle toplu eklenir.** Kartlar operatörden koli koli
  geliyor; her IMEI için ayrı ekleme ekranı açmak günlük işi kilitliyordu.
  SIM listesinin üstünde "Ekle"nin yanında **Toplu ekle** düğmesi var
  (`SimKartAdmin.toplu_ekle`); operatörden gelen dosya olduğu gibi
  yapıştırılır, satır/virgül/noktalı virgül/boşluk ayraç sayılır — kopyalanan
  biçim her seferinde aynı olmuyor. Bayi seçilirse kartlar zimmetli
  ("Bayiye Atandı"), seçilmezse stoğa ("Beklemede") girer; `bulk_create`
  model `save()`'ini çağırmadığı için bu kural serviste elle yazılır.
  **Zaten kayıtlı numara hata değil, atlanan satırdır:** yönetici çoğu zaman
  bir kolinin devamını yapıştırıyor ve araya önceden girilmiş kartlar
  karışıyor. Bütün listeyi geri çevirmek hangi satırın tekrar olduğunu elle
  aramak demekti — atlananlar (ve listenin kendi içindeki tekrarlar) adıyla
  sayılıp yazılır, kalanı girilir.
- **SIM kartlar bayiye zimmetlidir.** Bayi yalnızca kendisine atanmış ve
  "Bayiye Atandı" durumundaki kartlarla başvuru girebilir. Başvuru olumsuz
  sonuçlanınca kart otomatik olarak stoğa döner; kart fiziksel olarak bayide
  durduğu için çöp edilmemeli.
  **Aynı kart iki başvuruya giremez, çift tıklamada da.** Yavaş bağlantıda
  fotoğraflar yüklenirken bayi düğmeye yeniden basıyordu; iki istek
  doğrulamayı birlikte geçiyor, iki başvuru açılıyor, giriş bedeli iki kez
  kesiliyordu. `BasvuruFormu.kaydet` başvuruyu açmadan önce kartları
  `select_for_update` ile yeniden okur (`_simleri_kilitle`); ikinci istek
  birincinin bitmesini bekler, kartı kullanılmış bulur ve hangi başvuruda
  kullanıldığını yazar. Tarayıcıda da gönder düğmesi kilitlenir, içinde
  sinyal çubuğu dolar ve "Fotoğraflar yükleniyor" notu çıkar
  (`parca_form_js.html`, `.gonderim-sinyali`) — bayi işin sürdüğünü görsün.
  Formda IMEI elle yazılmaz, **seçim kutusundan seçilir**: listeye zaten
  yalnızca girilebilecek kartlar giriyor, 16 haneyi tezgâh başında yazmak
  hataya davetiyeydi (datalist telefonda güvenilir çalışmıyordu). Stok boşsa
  kutu sebebini yazar. Sunucu doğrulaması (`_sim_dogrula`) yerinde durur.
  Yönetim panelindeki SIM listesi kartın hangi bayide olduğunu ünvanıyla
  gösterir — kullanıcı adı telefon numarası olduğu için numara tek başına
  hangi firma olduğunu anlatmıyordu.
- **Bozuk SIM için para hareketi yoktur, kart takası vardır.** Bayi kartın
  parasını (nakit ya da başvuruda) zaten ödedi; ona para değil kart borçluyuz.
  Başvuruyu iptal edip yeniden girmek giriş bedelini iade edip güncel
  fiyattan yeniden keserdi — bayi 100'e aldığı işi 150'ye almış olurdu.
  Bunun yerine kart **aynı başvuruda** değişir, para olduğu yerde kalır.
  Bozuk kart yalnızca ilk aktivasyonda belli olur; hat açıldıktan sonra
  bozulan kart ayrı bir iştir ("SIM Değişimi" kategorisi açılır, veridir).
  · **Bildiren tedarikçi ya da yönetimdir, bayi değil.** Tedarikçi başvuru
  detayındaki "SIM kart bozuk çıktı" kutusundan (`views.sim_bozuk`), yönetim
  başvuru sayfasındaki **SIM bozuk** düğmesinden (`BasvuruAdmin.sim_bozuk`;
  yalnızca sonuçlanmamış ve takılı kartı olan başvuruda çıkar,
  `has_sim_bozuk_permission`). İkisi de `basvurular.services.sim_bozuk_bildir`
  çağırır: kart Arızalı'ya düşer (`ariza_tarihi`, `ariza_bildiren`),
  başvuru bayinin düzenleyebildiği duruma çekilir. Hangi durum olduğu
  veridir — `BasvuruDurumu.bayi_duzenleyebilir`; ilki hazır gelir, yönetim
  onay ekranından değiştirebilir. Öyle bir durum yoksa servis sebebini
  söyler. Sonuçlanmış başvuruda reddedilir.
  · **Bayi yerine yenisini düzeltme ekranından takar** (aşağıdaki Eksik
  Evrak kuralı): bozuk kart SIM kutusuna hiç girmez, bayi stoğundan başka
  kart seçmek zorunda kalır. "Değiştirildi mi" ayrı bayrak değildir:
  arızalı kartın IMEI'si başvuruda artık yazmıyorsa değişmiştir
  (`Basvuru.bozuk_simler`).
  · **Durumu elle değiştiren yöneticiye SIM hatırlatılır**
  (`BasvuruAdmin.save_model`). Günlük işte tek elle yapılan şey durumu
  değiştirmektir; yönetici "Eksik Evrak" deyip nota "SIM bozuk, değiştir"
  yazıyor ve düğmeye hiç basmıyordu. Kart o zaman arızalıya düşmüyor: bayi
  yenisini takınca eskisi **sağlam** sayılıp stoğa dönüyor ve değişim
  takibine hiç girmiyordu ("değişen sim arızalıya düşmedi"). Bayiye açılan
  bir duruma geçen, takılı sağlam kartı olan başvuruda uyarı çıkar ve
  doğrudan **SIM bozuk** ekranına bağlanır. Blok değil hatırlatma: Eksik
  Evrak çoğu zaman evrakla ilgilidir. Kararın tek servisten geçmesi
  kuralının aynısı — yeni bir "düğmeyle yapılan iş" eklersen durum alanından
  gelen yolu da düşün.
  · **Kartın hangi başvuruda kullanıldığı silinmez.** Takasta eski sağlam
  kart stoğa dönerken `basvuru` bağı korunur (iptalde serbest bırakan
  `basvurunun_simlerini_serbest_birak` de aynısını yapar); bağ koparılınca
  kart sonradan arızalı işaretlendiğinde arıza sayfasında "bozulduğu
  başvuru" boş çıkıyordu. Kart yeniden kullanılırsa bağ yeni başvuruyla
  güncellenir.
  · **Arızalı kartın üç adımı** (`SimKart`: `iade_alinma_tarihi`,
  `yerine_verilen`, `degisim_tarihi`) birbirinden bağımsızdır ve
  `bayi.services` ile işler: `sim_bayiden_alindi`, `sim_yerine_ver` (stoktan
  aynı operatörün kartını bayiye zimmetler ve bağlar — OneToOne, aynı kart
  iki bozuğun yerine verilemez), `sim_degisimi_alindi`. Operatörden gelen
  yeni kart burada açılmaz, "Toplu ekle" ile stoğa girer; adım yalnızca
  alacağı kapatır. Günlük iş SIM Stoğu listesindeki **Takip** düğmesinden
  (`ariza_sayfasi`, her adım POST); toplu "bayiden alındı" / "değişimi
  geldi" işlemleri de var. Açık işler `acik_ariza_isleri`; stokta bozulan
  kartta (bayisi yok) bayi adımları hiç sayılmaz. Liste `ArizaFiltresi` ile
  süzülür, Stok ve Alacak Özeti'ndeki **Arızalı kartlar** bloğu o süzgece
  gider. Kapanmış kart sayılmaz.
  · **Arızalı kart stoğa da bayiye de dönmez.** Olumsuz sonuçta kartlar
  bayinin stoğuna döner (`basvurunun_simlerini_serbest_birak`) ama yalnızca
  Kullanıldı olanlar; toplu zimmetleme ve geri alma da arızalıyı atlar.
  Aksi hâlde bozuk kart "sağlam" görünüp yeni başvuruya girerdi.
- **Eksik Evrak'taki başvuruyu bayi tek ekrandan düzeltip yeniden gönderir.**
  "Bayi düzenleyebilir" kutusu uzun süre yalnızca bir etiketti: yönetici
  durumu değiştiriyor, bayi görüyor ama kimliği yeniden yükleyemiyor, alanı
  düzeltemiyor, evrakı WhatsApp'tan gönderiyordu. Şimdi detayda **Düzeltme
  bekleniyor** kutusu yönetimin notunu (`Basvuru.son_yonetim_notu`: başvuruyu
  bu duruma getiren geçmiş kaydının açıklaması — o yüzden Eksik Evrak'a
  alırken **not yaz**) ve "Düzelt ve yeniden gönder" düğmesini gösterir;
  `/basvuru/<ref>/duzelt/` (`views.duzelt`, `BasvuruDuzeltmeFormu`) aynı
  form tanımını dolu değerlerle açar: kategori alanları, belgeler, SIM, not.
  Kapı `Basvuru.bayi_duzeltebilir` (sonuçlanmamış + `durum.bayi_duzenleyebilir`).
  · **Hat bilgileri kilitlidir** (operatör, tarife, kampanya formdan
  çıkarılır): fiyat oradan çıkıyor ve giriş bedeli çoktan kesildi; yanlışsa
  yönetim düzeltir. Gizli `id_operator`/`id_tarife` girdileri durur ki
  tarifeye bağlı alanlar ve SIM daraltması yeni başvurudaki gibi çalışsın.
  · **Bakiye kapısı işlemez, para oynamaz**: iş zaten satın alındı.
  `BasvuruFormu.clean` tarife/operatör seçimini ve bakiye kapısını
  kancalardan okur (`_secili_tarife`, `_secili_operator`, `_bakiye_kapisi`);
  düzeltme formu onları ezer. Yeni başvuruda davranış değişmedi.
  · **Belge yalnızca yoksa zorunludur**; yüklenmezse eskisi kalır, yüklenirse
  eskisi commit sonrasında diskten silinir. Onaydan sonra silinmiş kimlik
  (`belgeler_silindi`) yeniden istenirken alan yine zorunludur — kayıt yok.
  · **SIM kutusuna stok + takılı sağlam kart girer** ("(takılı)" etiketiyle),
  arızalı kart girmez. Sağlam kart değişirse eskisi bayinin stoğuna döner
  (elinde duruyor, kullanılmadı: `ATANDI`, başvuru bağı kalkar); arızalı
  kart arızalı kalır, takibi ayrı.
  · **Gönderince başvuru bildirim öncesi durumuna döner**
  (`services.duzeltmeyi_gonder` → `_onceki_durum`: son geçmiş kaydının
  öncekisi; o kapalıysa ya da yine bayinin düzenlediği bir durumsa başlangıç
  durumu). İş kuyruğa geri girer, Eksik Evrak'ta unutulmaz. Geçmişe "Bayi
  düzeltip yeniden gönderdi: TC No, Kimlik ön yüz" düşer — yönetim alan alan
  karşılaştırmasın; değişmeyen alan yazılmaz. SIM değişiminde not IMEI'leri
  taşır ("SIM Kart (111 → 222)"): yalnızca alan adı yazılınca hangi kartın
  çıktığı görünmüyordu.
  · Form parçaları ortaktır: `parca_form_alanlar.html` (müşteri tipi,
  alanlar, belgeler, not) ve `parca_form_js.html` (tarifeye bağlı alanlar,
  SIM daraltma, kamera, zorunlu alana kaydırma) hem `yeni.html` hem
  `duzelt.html` tarafından çizilir. Forma bir şey eklerken parçaya ekle,
  ikisini ayrı ayrı büyütme. `belge_alanlari` üçlü demet döner
  (tanım, alan, mevcut belge); yeni başvuruda mevcut hep `None`.
- **URL'ler okunur olmalı: slug'lı, sorgu dizesiz.** `?kategori=4` değil
  `/basvuru/yeni/adsl-internet/`. Kayıtlara referans numarasıyla erişilir,
  id ile değil (sayaç taranmasın). Slug üretiminde
  `apps.katalog.utils.turkce_slug` kullan — Django'nun `slugify`'ı Türkçe
  harfleri düşürür ("Faturalı" → "fatural").
- **Sitenin iletişim bilgisi Genel Ayarlar'dan girilir** (`GenelAyarlar`,
  yan menüde Ayarlar → Genel Ayarlar). Telefon ve e-posta şablona gömülü
  olsaydı numarayı değiştirmek yazılım güncellemesi gerektirirdi. Kayıt
  **tekildir**: `pk` her kayıtta 1'e sabitlenir, admin'de ekleme ve silme
  kapalıdır, liste doğrudan düzenleme sayfasına yönlendirir — "hangi ayar
  geçerli" sorusu hiç doğmasın. Ayarları okumanın yolu `GenelAyarlar.getir()`;
  `objects.create()` ikinci kez çağrılırsa tekil anahtara çarpar.
  Bilgiler kamuya açık üç sayfada (giriş, tanıtım, bayi başvurusu) **ve
  panelin kenar menüsünde** görünür — takılan bayi çıkış yapmadan
  ulaşabilsin. Hepsi `parcalar/iletisim.html` ile tek yerden çizilir; bağlam işlemcisi
  `genel_ayarlar` oturum açmamış ziyaretçiye de taşır (`bayi_baglami` girişi
  olmayana boş döner). **Boş bırakılan alan hiç gösterilmez** — yarım bir
  iletişim kutusu göstermektense hiç göstermemek yeğdir. Yeni bir site geneli
  ayar gerekirse bu modele alan eklenir, ikinci bir ayar modeli açılmaz.
- **Bayiye içerik gösteren alanlar admin'den girilir.** Tarife açıklaması
  ile görseli `/tarifeler/` sayfasında görünür; şablona sabit metin yazma.
  Katalogdaki akordiyonlar **kapalı** açılır: ilkini açık getirmek, listeye
  bakmak isteyen bayiye istemediği tarifenin ayrıntısını dayatıyordu.
- **Kampanyanın yalnızca adı vardır.** Görseli ve açıklaması bilinçli olarak
  yok: kampanya bayiye gösterilen bir içerik değil, başvuru girilirken yapılan
  bir seçimdir. Bir süre ikisi de vardı ve hiçbir ekranda görünmüyordu —
  yöneticiye her kampanyada doldurulacak iki boş kutu olarak çıkıyordu.
  Anlatılacak bir şey varsa tarifenin açıklamasına yazılır. `kampanya/` medya
  klasörü de bu yüzden `ACIK_KLASORLER`'de değildir.
- **Tarifede iki ayrı görünürlük anahtarı vardır.** `bayiye_gorunur` kapalı
  tarife `/tarifeler/` kataloğunda listelenmez ama başvuruda **hâlâ
  seçilebilir** — duyurulmayan ama satılabilen tarifeler için (`Banka`'daki
  anahtarın aynısı). Bayinin hiç seçememesi gerekiyorsa `aktif` kapatılır: o
  zaman ne katalogda ne formda çıkar, eski başvurular ve fiyat kuralları
  yerinde kalır.
- **Kampanya katalogda değil, başvuru formundadır.** Kampanya bir süre
  kaldırılmıştı, geri getirildi — ama yeri değişti. `/tarifeler/` sayfası
  bayinin müşteriye anlatırken açtığı katalogdur; kampanya ise başvuru
  girerken yapılan bir **seçimdir**. İkisi aynı yerde durunca bayi kampanyayı
  katalogda görüyor, forma geçince arıyordu. Kampanya kutusu artık yalnızca
  başvuru formundadır ve tarife seçimine bağlı HTMX ile dolar; katalog
  sayfasında hiç görünmez (`apps/bayi/tests.py` bunu kontrol eder).
- **Kampanya kutusuna yalnızca seçili tarifenin geçerli kampanyaları girer.**
  SIM kart kutusundaki kuralın aynısı: listeye yalnızca seçilebilecek olan
  girer. Tarife seçilmeden kutu "Önce tarife seç" der; kategorinin bütün
  kampanyalarını dökmez. Süresi geçmiş kampanya listeye girmez. Sunucu
  doğrulaması (`BasvuruFormu.clean`) yine de yerinde durur: tarifeye ait
  olmayan ya da süresi geçmiş kampanya reddedilir.
- **Şablon değişikliğinden sonra CSS'i derle ve derlenmiş dosyayı commit'le:**
  `./.tools/tailwindcss -i assets/app.css -o static/app.css --minify`
  Kaynak `assets/app.css`, çıktı `static/app.css`. **Kaynak dosya `static/`
  altında durmaz:** orada durduğunda `collectstatic` onu da toplayıp
  `@import "tailwindcss"` satırında çöküyor ve container açılamıyordu.
  Sunucuda Node yok, Docker imajı Tailwind çalıştırmıyor; `static/app.css`
  depodan geldiği gibi kullanılır (`.gitignore`'da `!static/app.css` istisnası
  bu yüzden var). Derlemeyi unutursan yeni sınıflar üretimde çalışmaz ve
  bunu ancak canlıda fark edersin. Kontrol: derledikten sonra
  `git diff --stat static/app.css` boş olmalı.
- Testler: `.venv/bin/python manage.py test`

## Bildirimler

- **Telegram anahtarları eski adlarıyla da okunur.** Sunucudaki
  `docker.env` git'te olmadığı için `git pull` onu güncellemiyor ve orada
  anahtarlar hâlâ `Telegram_Token` / `Telegram_Chat_id` olarak duruyordu.
  Ortam değişkeni adı büyük/küçük harfe duyarlı; ikisi de boş okunuyor,
  `yapilandirilmis_mi()` False dönüyor ve bildirim **hiç gitmiyor, hata da
  vermiyordu** — "ayarlar dolu ama mesaj yok" tablosu buradan çıktı.
  `base.py` yeni adı bulamazsa eskisine bakar. Yeni bir ayar adı
  değiştirirken aynısını yap: sunucudaki dosyayı elle düzeltmek gereken
  her ad değişikliği bir gün unutulur.
- **`manage.py telegram_dene` Telegram'ın kendi hata metnini yazar.**
  "chat not found", "Unauthorized" gibi sebepler yalnızca günlüğe düşüyordu;
  onu görmek container log'unu taramak demekti. `_gonder` sonucu
  `(gitti_mi, açıklama)` olarak döndürür.
- **`apps.bildirim` INSTALLED_APPS'te olmalı.** Bir süre değildi: bildirimler
  doğrudan import edildikleri için çalışıyordu ama `telegram_dene` komutu
  bulunamıyordu. Yeni bir uygulama eklerken INSTALLED_APPS'e de ekle.
- **Telegram yalnızca üç şeyi taşır:** yeni başvuru, ödeme bildirimi, yeni
  bayi başvurusu. Grup her durum değişikliğinde, her mağaza/eSIM
  siparişinde ve her destek talebinde mesajla doluyordu; yönetici kendi
  yaptığı işlemin haberini de alıyordu ve önemli olan kayboluyordu.
  Durum bildirimleri veri olarak kalır (`BasvuruDurumu.bildirim_gonder`) ama
  hepsi kapatıldı (`basvurular` 0016) ve tohum da kapalı açar; yönetici
  isterse durumun sayfasından açar. Sipariş ve destek bildirimleri kodla
  kaldırıldı — bekleyenler zaten yan menüde rozetle sayılıyor. Yeni bir
  bildirim eklemeden önce bu listeyi büyütmek gerektiğini sorgula.
- **Bildirim asla işin önüne geçmez.** Telegram mesajı transaction
  tamamlandıktan sonra, ayrı bir iş parçacığında gider ve her tür hatası
  yutulur. Yeni bir bildirim eklerken `apps/bildirim/telegram.py` içindeki
  `mesaj_gonder` üzerinden geç; doğrudan istek atma. Eski sistemde
  `requests.get()` view içindeydi ve Telegram çöktüğünde başvuru kaydedilmiş
  olmasına rağmen bayi hata sayfası görüyordu.
- Mesaja giren kullanıcı verisi HTML olarak kaçışlanır.
- **Ödeme bildirimi geldiğinde Telegram'a haber gider**
  (`odeme_bildirimi_bildir`). Bildirim para hareketi değil: onaylanana kadar
  cüzdana dokunulmuyor, yani bayi havaleyi yapıp bekliyor ve panele bakan
  olmazsa bakiyesi askıda kalıyordu. Mesaj bayiyi, tutarı, yatırılan hesabı
  ve gönderen adını taşır. **Karar bildirilmez** — bekleyenler yan menüde
  zaten rozetle sayılıyor, onayı veren de yönetimin kendisi.
- Hangi durumların bildireceğini admin seçer (`BasvuruDurumu.bildirim_gonder`);
  varsayılan hiçbiri.

## Yönetim paneli

- **django-unfold Türkçe çeviriyle gelmiyor.** İngilizce bir metin görürsen
  `locale/tr/LC_MESSAGES/django.po` dosyasına ekleyip `compilemessages`
  çalıştır. Şablonu kopyalayıp metni sabitleme.
- **Derlenmiş `django.mo` depoya girer** (`.gitignore`'da `!locale/**/*.mo`
  istisnası). Django `.po` değil `.mo` okur; sunucuda gettext yok ve
  `compilemessages` çalışmıyor. `.po`'yu güncelleyip `.mo`'yu commit'lemezsen
  yerelde Türkçe, sunucuda İngilizce görürsün — bir kez öyle oldu.
- **Başlangıç verisi ikinci bir başlangıç durumu açmaz.** Yönetici başlangıç
  durumunun adını değiştirip ("Giriş") giriş bedelini ona bağlamış olabilir.
  Tohum, slug'ını bulamadığı durumu yeniden açarken onu da başlangıç
  işaretleseydi yeni başvurular oraya düşer ve giriş bedeli hiç kesilmezdi.
  `baslangic_verisi` sistemde başlangıç durumu varsa yenisini başlangıç
  yapmaz. Tohuma başka "yalnızca bir tane olmalı" türü bir bayrak eklersen
  aynı korumayı yaz.
- **Yan menü rozetleri "bakılacak iş" sayar, toplam kayıt değil.**
  `apps/rozetler.py`: yeni bayi başvuruları ve başlangıç durumundan çıkmamış
  başvurular. Personel durumu değiştirir değiştirmez sayıdan düşer. Hangi
  durumun başlangıç olduğu veridir (`BasvuruDurumu.baslangic_durumu`), koda
  gömülü değil. Yeni bir rozet eklerken aynı ilkeye uy — kuyruk uzunluğunu
  göster, arşivi değil.
- **Tarih aralığı filtresinde bitiş günü dahildir** (`apps/filtreler.py`).
  unfold'un hazır `RangeDateFilter`'ı seçilen tarihi olduğu gibi `__lte` ile
  karşılaştırıyor; alan `DateTimeField` olunca "5 Eylül" gece yarısı demek
  oluyor ve o günün hareketleri listeye girmiyordu. `GunAraligiFiltresi`
  bitişi ertesi günün başlangıcından öncesi olarak kurar ve tarihleri zaman
  dilimine bağlar. Yeni bir tarih aralığı filtresi eklerken bunu kullan.
- **Rozet şablonu ezilmiştir** (`templates/unfold/helpers/app_list_badge.html`).
  unfold rozeti `badge` anahtarı dolu olduğu sürece çiziyor; geri çağırım boş
  dönünce sayı yerine geri çağırımın nokta yolunu basıyordu. Ezilmiş sürüm
  değeri önce çözer, boşsa hiç çizmez.
  **Değer tembel bir vekildir** (`lazy(callback)(request)`): sonuç sınıfı
  verilmediği için `bool()` her zaman doğru döner, `{% if deger %}` yetmiyordu
  — bekleyen iş yokken de içi boş kırmızı bir nokta çiziliyordu. Şablon değeri
  `stringformat` ile metne çevirip öyle bakar. Aynı şablon hem yan menüde hem
  gösterge panelinde kullanılıyor. Rozet sınıfları unfold'un derlenmiş
  CSS'inden gelir — bizim `static/app.css` yönetim panelinde yüklü değildir,
  oraya yeni sınıf uyduramazsın.
- **Satır işlemleri açılır menüde saklanmaz**
  (`templates/unfold/helpers/actions_row.html` ezilmiştir). unfold bunları
  "..." düğmesinin arkasına koyuyordu; yönetici her bayi için önce menüyü
  açmak zorundaydı. Günlük iş bu düğmelere basmak — parola vermek, bakiye
  işlemek — ikinci bir tıklama arkasına saklanmamalı. `actions_row` ekleyen
  yeni bir admin yazarsan düğme adını kısa tut, satırda yan yana duruyorlar.
- **Admin form ekranlarında unfold'un kendi bileşenleri kullanılır**
  (`unfold.widgets.UnfoldAdmin*Widget`). Yönetim panelinde bizim
  `static/app.css` yüklü değildir; `form.as_div` çıplak HTML basıyor,
  uydurulan sınıf da çalışmıyor. Sınıf gerekiyorsa unfold'un derlenmiş
  CSS'inde var olduğunu doğrula (`peer-checked` gibi bazıları yok); yoksa
  satır içi stil yaz.
- **Yönetim panelinde sayı kutularının oku ve fare tekerleği kapalıdır**
  (`static/yonetim.css`, `static/yonetim.js`; `UNFOLD["STYLES"/"SCRIPTS"]`).
  Tutar kutusu odaktayken sayfayı kaydıran yönetici bayiye yüklediği tutarı
  fark etmeden kuruş kuruş değiştiriyordu. Bu iki dosya unfold'un derlenmiş
  CSS'ine sınıf eklemeden, yalnızca eleman seçicisiyle çalışır.
- Ekleme düğmesi `templates/unfold/helpers/add_link.html` ile ezilmiştir:
  unfold'un ikon-only yuvarlak düğmesi ne yaptığını anlatmıyordu. unfold
  yükseltmelerinde bu şablonu gözden geçir.

## Sunucu

Adım adım kurulum ve sorun giderme `SUNUCU.md` dosyasındadır. Yeni bir
kurulum adımı çıkarsa oraya da yaz — o dosya çalıştırılmak için var,
buradaki metin ise neden öyle olduğunu anlatır.

**Sunucu hiçbir şey derlemez.** Node, Tailwind ve gettext yok; Docker imajı
yalnızca Python çalıştırır. Bu yüzden üretilmiş üç dosya bilinçli olarak
depoya girer:

| Dosya | Kaynağı | Unutulursa |
|---|---|---|
| `static/app.css` | `assets/app.css` (Tailwind) | Yeni sınıflar üretimde çalışmaz |
| `locale/tr/LC_MESSAGES/django.mo` | `django.po` (`compilemessages`) | Panel sunucuda İngilizce görünür |
| `apps/*/migrations/*.py` | `makemigrations` | Şema uyuşmaz, `migrate` patlar |

İlk ikisi `.gitignore`'da açık istisnadır (`!static/app.css`,
`!locale/**/*.mo`); migration'lar hiç yoksayılmaz. Push etmeden önce ilk
ikisini derle, `git status` temiz olmalı.

**Kurulum başarısız olursa container ölür** (`entrypoint.sh` içinde
`set -e`). Ölü container'a `docker exec` ile girilemediği için çıkış yolu
açılış betiğini atlamaktan geçer:

```
docker compose run --rm --entrypoint python app_fadil manage.py kurulum --sifirla --evet
```

`kurulum` komutu `InconsistentMigrationHistory` ve `IntegrityError`
hatalarını yakalayıp ne yapılacağını ekrana yazar; başka bir açılış hatası
eklersen aynısını yap — traceback değil, çıkış yolu göster.

**Başlangıç verisi kayıtları adından *ve* slug'ından aranır.** İkisi de
tekil olduğu için `get_or_create(ad=...)` yetmiyordu: yönetici panelden bir
kategorinin adını değiştirdiğinde slug eskisi gibi kalıyor, komut kaydı
bulamayıp yeniden açmaya çalışıyor ve tekil slug kısıtına çarpıyordu.
Kurulum her container açılışında çalıştığı için sonuç, tek bir yeniden
adlandırmayla ayağa kalkmayan bir sunucuydu. `_getir_ya_da_ac` ikisine
birden bakar ve bulduğu kayda dokunmaz — panelde yapılan düzenleme
kurulumla geri alınmaz. Başlangıç verisine yeni bir model eklersen aynı
yoldan geçir.

**Statikler her açılışta `--clear` ile toplanır.** Tasarım değiştiğinde eski
dosyalar `STATIC_ROOT`'ta birikmesin diye.

**Bu projeye ait olmayan hiçbir şeye dokunulmaz.** Sunucuda 50-60 başka site
var. `docker volume prune` ve `docker system prune -a` yasak; volume silmek
gerekirse adı tek tek yazılır. `kurulum --sifirla` yalnızca `DATABASE_URL`'in
gösterdiği veritabanının şemasını düşürür.

## Güvenlik

- **Yüklenen dosyaları asla doğrulamadan kabul etme.** Belgeleri personel açar;
  tarayıcıda çalışabilen bir dosya (HTML, SVG) yüklenirse personelin oturumunda
  betik çalışır. `apps/basvurular/validators.py` uzantı + imza denetimi yapar;
  yeni bir dosya alanı eklerken bu doğrulayıcıyı bağla. HTML'deki `accept`
  özniteliği güvenlik değildir.
- **Belgeler yalnızca izin kontrollü görünümden sunulur.** Doğrudan
  `dosya.url` kullanma; `belge.get_absolute_url()` kullan.
- **Açık görseller `/media/` altından Django tarafından sunulur.** Tarife,
  kampanya ve operatör görselleri admin'den yüklenip diske yazılır;
  `static()` yalnızca DEBUG açıkken URL üretir, WhiteNoise ise açılışta
  taradığı `STATIC_ROOT`'u sunar. Sonradan yüklenen dosya ikisine de
  girmediği için görsel yerelde görünüp üretimde 404 veriyordu.
  `apps/medya.py` bu üç klasörü DEBUG'dan bağımsız sunar — yeni bir açık
  görsel klasörü eklersen `ACIK_KLASORLER`'e yaz. Kişisel veri taşıyan
  klasör buraya **girmez** (`basvuru/`, eski sistemin `evrak/`'ı);
  görüntüler veritabanına ya da base64'e taşınmaz, diskte kalır.
- **Kimlik görüntüleri işi bitince hemen silinir.** Bekleme ya da cron yok:
  `BasvuruDurumu.belgeleri_sil` işaretli bir duruma geçildiğinde
  `apps/basvurular/services.belgeleri_sil` çalışır. Aktif ve İptal siler;
  Hatalı ve Eksik Evrak silmez, çünkü o başvurular düzeltilip yeniden
  denenebilir. Başvuru kaydı ve para geçmişi her hâlükârda kalır.
- **Veritabanını silmek diskteki dosyaları silmez.** Sıfırlamadan sonra
  `manage.py sahipsiz_belgeler --sil` çalıştırılır; eski sistemin `evrak/`
  klasörü de taranır, çünkü yeni yapıda oraya yazan bir model yok. Yeni bir
  belge klasörü eklersen komuttaki `KLASORLER` listesine ekle.
- **Dosya alanları otomatik temizlenir.** Django kayıt silinince dosyayı
  diskten silmez; `apps/dosya.py` bunu kapatır — kayıt silinince ve dosya
  değişince eskisi commit sonrasında silinir. Yeni bir dosya/görsel alanı
  eklerken ilgili `AppConfig.ready()` içinde `dosyalari_temizle`'ye kaydet.
- **Başvuru detayında hangi alanların görüneceğini kullanıcı seçer.** Ekran
  uzun; herkes her alanla ilgilenmiyor. Yönetim panelinde detay sayfasının
  üstündeki **Görünüm** düğmesi (`BasvuruAdmin.gorunum_ayarla`), bayi
  tarafında "Başvuru bilgileri" başlığının yanındaki aynı adlı düğme. Tercih
  kullanıcıya özeldir (`DetayGorunumTercihi`), kapatılanlar saklanır — yeni
  eklenen alan kendiliğinden görünür olur.
  Kapatmak yalnızca görünümü etkiler: alan formdan çıkar, **değeri korunur**.
  Ama model doğrulaması hatayı alan adıyla veriyor; alan formda yoksa Django
  `add_error`a hiç varmadan `ValueError` atıp kaydı imkânsız hâle
  getiriyordu. `BasvuruAdminFormu._update_errors` karşılığı olmayan hatayı
  alan adıyla birlikte genel hataya taşır. Alan gizlenebilen yeni bir admin
  ekranı yazarsan aynısını yap. Ekleme ekranında süzme yapılmaz: zorunlu bir
  alan gizli kalırsa yeni kayıt hiç açılamaz.
- **Seçim kutuları geçersiz seçenek göstermemeli.** Başvuru admin'inde
  tarife ve kampanya, başvurunun kategorisine göre daraltılır. Bu yüzden
  ikisi bilinçli olarak `autocomplete_fields` değil: autocomplete kutusu
  hedef admin'in tüm kayıtlarını gösterir, sibling alana göre daraltılamaz.
  Sunucu doğrulaması yine de yerinde durur.
- **Kategoride aktif tarifesi olan operatör forma otomatik girer.** Tarife
  tanımlayıp operatörü kategorinin listesine eklemeyi unutmak sessiz bir
  tuzaktı; `gecerli_operatorler()` ikisini birleştirir.
- **SIM karşılığı takibi kategoriye bağlı.** `sim_karsiligi_gerekir` açık
  kategorilerde tamamlanan her işlem yeni bir SIM alacağı doğurur. Alacak,
  işlemi bir tedarikçi üstlendiyse ondan, üstlenilmemişse operatördendir
  (`Basvuru.sim_karsiligi_kimden`). Kimden kaç kart beklendiği
  `apps/basvurular/raporlar.sim_alacaklari` ile hesaplanır ve başvuru
  listesinin üstünde gösterilir.
- **Şablonda çok satırlı yorum için `{% comment %}` kullan.** Django'nun
  `{# #}` yorumu tek satırlıktır; çok satıra yayılırsa sayfada metin olarak
  basılır.
- **Yüklenen görseller küçültülüp WebP'ye çevrilir** (`apps/basvurular/gorsel.py`).
  Uzun kenar 1000px, kalite 85 — kimlik kartı kadrajın çoğunu kapladığı için
  karttaki yazı ~18px kalıyor ve okunuyor. Tasarruf %95'in üzerinde. Yeni bir
  görsel alanı eklerken `gorseli_kucult`'tan geçir — model `save()`'inde
  `kucult()` ile ya da formda doğrudan. Şu an dört alan geçiyor: başvuru
  belgeleri, tarife görseli, kampanya görseli, operatör logosu. Logo bir süre
  atlanmıştı; yeni alan eklerken bu listeyi de güncelle. EXIF döndürmesi
  uygulanıp veri temizlenir; konum bilgisi kimlik görüntüsünde tutulmaz.
- **Görüntüler diskte tutulur, veritabanında değil.** Veritabanı yalnızca
  dosya yolunu saklar. base64 ile satır içinde saklamak %33 şişme, dev
  `pg_dump` yedekleri ve her görüntülemede tüm veriyi belleğe alma demektir.
- **Dosya silme `transaction.on_commit` içinde yapılır.** İşlem geri alınırsa
  dosya gitmiş, kayıt geri gelmiş olmamalı.
- **Admin'de HTML üretirken `format_html_join` kullan.** `"".join(...)` düz
  `str` döndürür ve dıştaki `format_html` onu kaçışlayıp etiketleri metin
  olarak basar.
- **`next` gibi dışarıdan gelen yönlendirme hedeflerini doğrula.**
  `url_has_allowed_host_and_scheme` olmadan `redirect()` çağırma.
