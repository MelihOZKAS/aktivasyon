# Aktivasyon — çalışma kuralları

## Sistem nedir

Telekom bayileri için başvuru toplama, evrak takibi, bakiye ve otomatik
hakediş sistemi. Üç taraf var:

| Taraf | Ne yapar | Para yönü |
|---|---|---|
| **Bayi** | Müşteriyi getirir, başvuruyu girer | Hakediş alır, hat ücreti öder |
| **Tedarikçi** | Kendisine satılan işlemi üstlenir, aktivasyonu yapar | Ana hakedişi bize öder |
| **Operatör** | Tedarikçi yoksa aktivasyon doğrudan onda yapılır | Ana hakedişi bize öder |

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
  bulundurmadan başvuru **giremez**. Kapı üç yerde durur: kategori ekranı
  karşılanamayan kategoriyi kapalı gösterir ve sebebini yazar (gizlemez —
  bayi kategori kaybolmuş sanmasın), form açılışı geri çevirir,
  `BasvuruFormu.clean` seçilen operatör/tarifenin gerçek tutarıyla son kez
  denetler. Tutarı `apps.finans.services.basvuru_bedeli` verir; kategori
  ekranı en ucuz seçeneğe bakar (`en_dusuk_basvuru_bedeli`), çünkü orada
  operatör/tarife henüz belli değil.
  Bu, **borç kuralıyla çelişmez**: borcun üst sınırı yok, ama borç işlenmiş
  bir işlemin sonucudur — parası olmadan yeni bir işlem *başlatmak* ayrı
  şeydir. Tahsilat kuralı yoksa hiçbir kategori engellenmez.
- **Bayiye giren her kuruş önce borcu kapatır.** Hakediş de elle yapılan
  bakiye yüklemesi de aynı sırayı izler: borç varsa oradan düşülür (`BORC_TAHSIL`),
  kalanı bakiyeye yazılır. 100 borcu olan bayi 250 hakediş alınca cüzdanında
  150 durur; hem 250 çekilebilir bakiye hem 100 borç aynı anda durmaz.
  Başvurudaki `hakedis` alanı yine 250'dir — mahsup cüzdan tarafındadır,
  bayinin hakedişi kısılmaz. Bayiye para giren yeni bir kalem eklersen
  aynı sırayı uygula.
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
- **Bayi başvurusunda fiyat kademesi de seçilir.** `BayiBasvurusu.bayi_grubu`
  onay ekranında durur ve hesap açılırken cüzdana yazılır
  (`bayi_hesabi_ac`); yönetici onaydan sonra bir de cüzdan ekranına gitmiyor.
  Boş bırakılırsa hesap yine açılır ama panel uyarır: bayi grubuna bağlı
  hakediş kuralları kademesiz cüzdanda işlemez, bayi işlem yapar karşılığında
  hiçbir şey almaz. Kademe başvurana sorulmaz — kamuya açık formun alan
  listesi sabittir (`fields`), yönetimin fiyat kararı oraya sızmaz.
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
- **Roller birbirini dışlamaz.** Bir firma hem bayi hem tedarikçi olabilir
  (`BayiProfili.bayi_mi` / `tedarikci_mi`). Bayi başvuru getirir ve hakediş
  alır; tedarikçi işlemi satın alır, bedeli hesabından düşer.
- **Kimlik görüntülerini üç taraf görür:** başvuruyu getiren bayi, işlemi
  üstlenen tedarikçi ve personel. Tedarikçi aktivasyonu fiilen kendisi
  yaptığı için bilgileri kimlikten okuyup operatör sistemine giriyor.
  İlgisiz kullanıcı 404 alır. Kural iki yerde: `basvurular.views.belge`
  (dosya erişimi) ve `detay` (`belgeler_gorunur`) — birlikte güncellenir.
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
- **Kâr = ana hakediş + bayiden tahsilat − bayiye hakediş.** `Basvuru.kar`
  bunu hesaplar. **Ana hakediş iki kaynaktan gelir:** işlemi bir tedarikçi
  üstlendiyse ondan (cüzdanından düşer), üstlenilmemişse operatörden
  (operatörün cüzdanı yoktur, hareket yazılmaz; tutar yalnızca başvuruya
  işlenir). Tutar `UcretKurali`'nda `yon=ANA_HAKEDIS` ile tanımlanır ve
  `operator` ya da `tedarikci` kapsamıyla daraltılır. Tedarikçi sonradan da
  atanabildiği için kendi tekillik anahtarıyla ayrı işlenir
  (`ana_hakedisi_isle`).
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
  **Tedarikçi kapsamı bir süre yalnızca motorda vardı**, formda alanı yoktu:
  tedarikçiden alış fiyatı panelden hiç girilemiyordu. Hem kural admin'inde hem
  satır içi tabloda alan artık var; kullanıcı seçen kutuların ekle/düzenle/sil
  düğmeleri `_kullanici_kutusunu_sadelestir` ile kapatılır.
- **SIM kartlar bayiye zimmetlidir.** Bayi yalnızca kendisine atanmış ve
  "Bayiye Atandı" durumundaki kartlarla başvuru girebilir. Başvuru olumsuz
  sonuçlanınca kart otomatik olarak stoğa döner; kart fiziksel olarak bayide
  durduğu için çöp edilmemeli.
  Formda IMEI elle yazılmaz, **seçim kutusundan seçilir**: listeye zaten
  yalnızca girilebilecek kartlar giriyor, 16 haneyi tezgâh başında yazmak
  hataya davetiyeydi (datalist telefonda güvenilir çalışmıyordu). Stok boşsa
  kutu sebebini yazar. Sunucu doğrulaması (`_sim_dogrula`) yerinde durur.
  Yönetim panelindeki SIM listesi kartın hangi bayide olduğunu ünvanıyla
  gösterir — kullanıcı adı telefon numarası olduğu için numara tek başına
  hangi firma olduğunu anlatmıyordu.
- **URL'ler okunur olmalı: slug'lı, sorgu dizesiz.** `?kategori=4` değil
  `/basvuru/yeni/adsl-internet/`. Kayıtlara referans numarasıyla erişilir,
  id ile değil (sayaç taranmasın). Slug üretiminde
  `apps.katalog.utils.turkce_slug` kullan — Django'nun `slugify`'ı Türkçe
  harfleri düşürür ("Faturalı" → "fatural").
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

- **`apps.bildirim` INSTALLED_APPS'te olmalı.** Bir süre değildi: bildirimler
  doğrudan import edildikleri için çalışıyordu ama `telegram_dene` komutu
  bulunamıyordu. Yeni bir uygulama eklerken INSTALLED_APPS'e de ekle.
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
- **Derlenmiş `django.mo` depoya girer** (`.gitignore`'da `!locale/**/*.mo`
  istisnası). Django `.po` değil `.mo` okur; sunucuda gettext yok ve
  `compilemessages` çalışmıyor. `.po`'yu güncelleyip `.mo`'yu commit'lemezsen
  yerelde Türkçe, sunucuda İngilizce görürsün — bir kez öyle oldu.
- **Yan menü rozetleri "bakılacak iş" sayar, toplam kayıt değil.**
  `apps/rozetler.py`: yeni bayi başvuruları ve başlangıç durumundan çıkmamış
  başvurular. Personel durumu değiştirir değiştirmez sayıdan düşer. Hangi
  durumun başlangıç olduğu veridir (`BasvuruDurumu.baslangic_durumu`), koda
  gömülü değil. Yeni bir rozet eklerken aynı ilkeye uy — kuyruk uzunluğunu
  göster, arşivi değil.
- **Rozet şablonu ezilmiştir** (`templates/unfold/helpers/app_list_badge.html`).
  unfold rozeti `badge` anahtarı dolu olduğu sürece çiziyor; geri çağırım boş
  dönünce sayı yerine geri çağırımın nokta yolunu basıyordu. Ezilmiş sürüm
  değeri önce çözer, boşsa hiç çizmez. Rozet sınıfları unfold'un derlenmiş
  CSS'inden gelir — bizim `static/app.css` yönetim panelinde yüklü değildir,
  oraya yeni sınıf uyduramazsın.
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
