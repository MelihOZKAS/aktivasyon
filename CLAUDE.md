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

**5. Marka renkleri `okunur_renk` filtresinden geçer.** Operatör renkleri
admin'den giriliyor; Turkcell sarısı gibi açık renkler beyazda okunmaz.

## Kod

- **Migration dosyaları asla elle silinmez, `.gitignore`'a eklenmez.** Eski
  projeyi bozan alışkanlık buydu. Model değişince `makemigrations`, ardından
  `makemigrations --check --dry-run` ile doğrula.
- **Para yalnızca `apps/finans/services.py` üzerinden hareket eder.** Model
  `save()` içinde bakiye değiştirme.
- **Borç limiti ve kullanılabilir tutar bayiye gösterilmez.** Yeni bir ekran
  eklerken bu değerleri şablona taşıma; `apps/bayi/tests.py` bunu kontrol eder.
- Şablon değişikliğinden sonra CSS'i derle:
  `./.tools/tailwindcss -i static/src/app.css -o static/app.css --minify`
- Testler: `.venv/bin/python manage.py test`

## Güvenlik

- **Yüklenen dosyaları asla doğrulamadan kabul etme.** Belgeleri personel açar;
  tarayıcıda çalışabilen bir dosya (HTML, SVG) yüklenirse personelin oturumunda
  betik çalışır. `apps/basvurular/validators.py` uzantı + imza denetimi yapar;
  yeni bir dosya alanı eklerken bu doğrulayıcıyı bağla. HTML'deki `accept`
  özniteliği güvenlik değildir.
- **Belgeler yalnızca izin kontrollü görünümden sunulur.** Doğrudan
  `dosya.url` kullanma; `belge.get_absolute_url()` kullan.
- **`next` gibi dışarıdan gelen yönlendirme hedeflerini doğrula.**
  `url_has_allowed_host_and_scheme` olmadan `redirect()` çağırma.
