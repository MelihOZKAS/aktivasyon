# Aktivasyon — çalışma kuralları

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
- Form girdileri 16px+ (iOS'ta yakınlaştırma yapmasın), dosya alanları kamerayı açıyor

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
değiştirirken `static/src/app.css` içindeki `--color-vurgu` ile
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
- **Formda sabit alan listesi yoktur.** Hangi alanların sorulacağına
  `KategoriAlani` kayıtları karar verir — İsim, TC No gibi çekirdek alanlar
  dahil. `cekirdek_alan` doluysa değer başvurunun kendi kolonuna yazılır
  (aranabilir olur), boşsa `ek_bilgiler` JSON'una girer. Forma yeni bir sabit
  alan ekleme; kategori tanımından geçir.
- **Roller birbirini dışlamaz.** Bir firma hem bayi hem tedarikçi olabilir
  (`BayiProfili.bayi_mi` / `tedarikci_mi`). Bayi başvuru getirir ve hakediş
  alır; tedarikçi işlemi satın alır, bedeli hesabından düşer.
- **Rol ekranları karışmaz.** Bayi görünümleri `@bayi_gerekli`, tedarikçi
  görünümleri `@tedarikci_gerekli` ile korunur (`apps/bayi/yetki.py`).
  Yeni bir ekran eklerken hangi role ait olduğunu belirt; profili olmayan
  eski kullanıcılar bayi sayılır. Giriş sonrası yönlendirme tek yerde:
  `baslangic_sayfasi()`.
- **Cüzdan yoksa açılır, çökmez.** Elle oluşturulmuş kullanıcının cüzdanı
  olmayabilir; para işlenirken `_cuzdani_getir` sıfır bakiyeli cüzdan açar.
- **Aynı kapsamda iki ücret kuralı varsa son eklenen kazanır.** Sonuç
  rastgele olmamalı; sıralama `(özgüllük, öncelik, pk)` üçlüsüne dayanır.
- **Kâr = tedarikçi geliri + bayiden tahsilat − bayiye hakediş.**
  `Basvuru.kar` bunu hesaplar. Tedarikçi fiyatı tedarikçiden tedarikçiye
  değişir; `UcretKurali.tedarikci` kapsamıyla tanımlanır. Tedarikçi işlem
  aktifleştikten sonra da atanabildiği için bedeli kendi tekillik anahtarıyla
  ayrı işlenir (`tedarikci_bedelini_isle`).
- **Bayi hakedişini şeffaf görür.** `/hakedisler/` sayfası hangi tarifeden ne
  kazanacağını, kesintisini ve elde kalan neti gösterir. Yeni bir para kalemi
  eklerken bu sayfayı da güncelle.
- **SIM kartlar bayiye zimmetlidir.** Bayi yalnızca kendisine atanmış ve
  "Bayiye Atandı" durumundaki kartlarla başvuru girebilir. Başvuru olumsuz
  sonuçlanınca kart otomatik olarak stoğa döner; kart fiziksel olarak bayide
  durduğu için çöp edilmemeli.
- **URL'ler okunur olmalı: slug'lı, sorgu dizesiz.** `?kategori=4` değil
  `/basvuru/yeni/adsl-internet/`. Kayıtlara referans numarasıyla erişilir,
  id ile değil (sayaç taranmasın). Slug üretiminde
  `apps.katalog.utils.turkce_slug` kullan — Django'nun `slugify`'ı Türkçe
  harfleri düşürür ("Faturalı" → "fatural").
- **Bayiye içerik gösteren alanlar admin'den girilir.** Tarife ve kampanya
  açıklaması ile görseli `/tarifeler/` sayfasında görünür; şablona sabit
  metin yazma.
- Şablon değişikliğinden sonra CSS'i derle:
  `./.tools/tailwindcss -i static/src/app.css -o static/app.css --minify`
- Testler: `.venv/bin/python manage.py test`

## Bildirimler

- **Bildirim asla işin önüne geçmez.** Telegram mesajı transaction
  tamamlandıktan sonra, ayrı bir iş parçacığında gider ve her tür hatası
  yutulur. Yeni bir bildirim eklerken `apps/bildirim/telegram.py` içindeki
  `mesaj_gonder` üzerinden geç; doğrudan istek atma. Eski sistemde
  `requests.get()` view içindeydi ve Telegram çöktüğünde başvuru kaydedilmiş
  olmasına rağmen bayi hata sayfası görüyordu.
- Mesaja giren kullanıcı verisi HTML olarak kaçışlanır.
- Hangi durumların bildireceğini admin seçer (`BasvuruDurumu.bildirim_gonder`).

## Yönetim paneli

- **django-unfold Türkçe çeviriyle gelmiyor.** İngilizce bir metin görürsen
  `locale/tr/LC_MESSAGES/django.po` dosyasına ekleyip `compilemessages`
  çalıştır. Şablonu kopyalayıp metni sabitleme.
- Ekleme düğmesi `templates/unfold/helpers/add_link.html` ile ezilmiştir:
  unfold'un ikon-only yuvarlak düğmesi ne yaptığını anlatmıyordu. unfold
  yükseltmelerinde bu şablonu gözden geçir.

## Güvenlik

- **Yüklenen dosyaları asla doğrulamadan kabul etme.** Belgeleri personel açar;
  tarayıcıda çalışabilen bir dosya (HTML, SVG) yüklenirse personelin oturumunda
  betik çalışır. `apps/basvurular/validators.py` uzantı + imza denetimi yapar;
  yeni bir dosya alanı eklerken bu doğrulayıcıyı bağla. HTML'deki `accept`
  özniteliği güvenlik değildir.
- **Belgeler yalnızca izin kontrollü görünümden sunulur.** Doğrudan
  `dosya.url` kullanma; `belge.get_absolute_url()` kullan.
- **Kimlik görüntüleri işi bitince hemen silinir.** Bekleme ya da cron yok:
  `BasvuruDurumu.belgeleri_sil` işaretli bir duruma geçildiğinde
  `apps/basvurular/services.belgeleri_sil` çalışır. Aktif ve İptal siler;
  Hatalı ve Eksik Evrak silmez, çünkü o başvurular düzeltilip yeniden
  denenebilir. Başvuru kaydı ve para geçmişi her hâlükârda kalır.
- **Yüklenen görseller küçültülüp WebP'ye çevrilir** (`apps/basvurular/gorsel.py`).
  Uzun kenar 1000px, kalite 85 — kimlik kartı kadrajın çoğunu kapladığı için
  karttaki yazı ~18px kalıyor ve okunuyor. Tasarruf %95'in üzerinde. Yeni bir
  görsel alanı eklerken `gorseli_kucult`'tan geçir. EXIF döndürmesi uygulanıp
  veri temizlenir; konum bilgisi kimlik görüntüsünde tutulmaz.
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
