# Sunucuya sıfırdan kurulum — adım adım

Eski veritabanını komple silip yeni yapıyı kurmak için yapılacaklar.
Sırayla, satır satır. Her bloğu olduğu gibi kopyalayabilirsin.

> Bu işlem `fadil_db` içindeki **her şeyi siler**. Aynı sunucudaki diğer
> projelerin veritabanlarına dokunmaz.

---

## 0 · Kendi bilgisayarında (push etmeden önce)

Sunucu Tailwind derlemez; CSS depodan geldiği gibi kullanılır. Derlemeyi
unutursan tasarım üretimde eksik çıkar.

```bash
cd ~/Desktop/Code/aktivasyon
```

```bash
./.tools/tailwindcss -i assets/app.css -o static/app.css --minify
```

```bash
git diff --stat static/app.css      # bir şey çıktıysa CSS bayatmış, commit'le
```

```bash
.venv/bin/python manage.py test     # hepsi geçmeli
```

```bash
git add -A && git commit -m "sunucu kurulumu öncesi" && git push
```

---

## 1 · Sunucuya bağlan

```bash
ssh kullanici@sunucu-adresin
```

```bash
cd /home/aktivasyon
```

---

## 2 · Neyin bu projeye ait olduğunu doğrula

Silmeden önce bir kez bak. Aşağıdakiler dışında hiçbir şeye dokunmuyoruz.

```bash
docker ps --filter name=fadil
```

```bash
docker volume ls | grep fadil
```

| Kaynak | Bu projeye ait |
|---|---|
| Container | `postgresfadil`, `app_fadil` |
| Volume | `aktivasyon_postgresql-data-fadil`, `aktivasyon_static-data-fadil` |
| Network | `main_fadil` (bir de paylaşılan `nginx_network`) |
| Veritabanı | `fadil_db`, port 5434 |

Listede başka projelerin adı çıkıyorsa onlara dokunma.

---

## 3 · Ayar dosyasını kontrol et

`aktivasyon/docker.env` git'te **değil**; `git pull` onu silmez, üzerine
yazmaz. Ama yeni yapı iki Telegram anahtarını farklı adla okuyor.

```bash
cut -d= -f1 aktivasyon/docker.env
```

Çıktıda `Telegram_Token` ve `Telegram_Chat_id` görüyorsan adlarını değiştir —
yoksa bildirimler sessizce çalışmaz (hata vermez, sadece gitmez):

```bash
sed -i 's/^Telegram_Token=/TELEGRAM_BOT_TOKEN=/; s/^Telegram_Chat_id=/TELEGRAM_SOHBET_ID=/' aktivasyon/docker.env
```

```bash
cut -d= -f1 aktivasyon/docker.env   # tekrar bak, yeni adlar görünmeli
```

Beklenen anahtarlar:

```
DEBUG                 False olmalı
SECRET_KEY            uzun ve rastgele
ALLOWED_HOSTS         aktivasyoncu.com,www.aktivasyoncu.com
CSRF_TRUSTED_ORIGINS  https://aktivasyoncu.com,https://www.aktivasyoncu.com
DATABASE_URL          postgres://...@postgresfadil:5434/fadil_db
POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB
TELEGRAM_BOT_TOKEN    (opsiyonel)
TELEGRAM_SOHBET_ID    (opsiyonel)
```

---

## 4 · Kodu çek ve container'ı yenile

```bash
git pull
```

```bash
docker compose up -d --build
```

Container açılırken `entrypoint.sh` şunları kendiliğinden yapar:
veritabanını bekler → `manage.py kurulum` (migration + başlangıç verisi) →
`collectstatic --noinput --clear` (eski tasarımın dosyaları silinir).

---

## 5 · Veritabanını sıfırla ve yeniden kur

Parolayı önce değişkene al — böylece `~/.bash_history` dosyasına düşmez.
Komutu çalıştır, parolayı yaz, Enter'a bas (ekranda görünmez):

```bash
read -rs PAROLA
```

Sonra:

```bash
docker exec -it app_fadil python manage.py kurulum --sifirla \
  --yonetici fadil --parola "$PAROLA"
```

Komut sana bağlı olduğu veritabanını gösterip **adını yazmanı** ister.
`fadil_db` yaz, Enter. Ardından sırayla:

1. Şemayı düşürür (eski yapının tabloları da gider)
2. Migration'ları sıfırdan uygular
3. Başvuru durumlarını, operatörleri, kategorileri ve form alanlarını açar
4. `fadil` yönetici hesabını oluşturur

Bitince değişkeni temizle:

```bash
unset PAROLA
```

---

## 6 · Eski kimlik görüntülerini diskten sil

**Veritabanını silmek diskteki dosyaları silmez.** Eski sistemin
`media/evrak/` altındaki kimlik ve pasaport fotoğrafları, onlara işaret eden
kayıt gittiği hâlde sunucuda durmaya devam eder.

Önce ne sileceğine bak:

```bash
docker exec -it app_fadil python manage.py sahipsiz_belgeler
```

Doğru görünüyorsa sil:

```bash
docker exec -it app_fadil python manage.py sahipsiz_belgeler --sil
```

Tarife görsellerine dokunmaz; onun kendi kaydı var.

---

## 7 · Çalışıyor mu, kontrol et

```bash
docker compose ps
```

```bash
docker compose logs --tail=50 app_fadil
```

```bash
curl -sI https://aktivasyoncu.com/ | head -1     # HTTP/2 200 beklenir
```

Sonra tarayıcıdan:

1. `https://aktivasyoncu.com/` → tanıtım sayfası açılıyor mu, tasarım yerinde mi
2. `https://aktivasyoncu.com/giris-yap/` → `fadil` ile gir
3. Giriş sonrası `/yonetim/` paneline düşmelisin
4. Telefondan da aç — her ekran mobil uyumlu olmalı

Telegram kurduysan dene:

```bash
docker exec -it app_fadil python manage.py telegram_dene
```

---

## 8 · Yönetim panelinde yapılacaklar

Kurulum 1-4. adımları hazır getirdi. Sistemin kendi kendine çalışması için
kalan dördü panelden girilir — **sıra önemli**, her adım öncekine dayanır:

| # | Nerede | Ne girilecek |
|---|---|---|
| 5 | Tarifeler | Her kategori + operatör için tarife; açıklama ve görselle |
| 6 | Bayi Grupları | Fiyat kademeleri (ör. Standart, Anlaşmalı) |
| 7 | Tarifeler → *Bu tarifenin parası* | Her tarifede üç rakam: operatörden alışın, tedarikçiden alışın, bayiye ödeyeceğin. Aradaki fark kârın; tablonun üstünde hesaplanmış durur |
| 8 | Kullanıcılar | Her bayi için hesap; cüzdan ve profil satır içi doldurulur |
| + | Banka Hesapları | Bayiler bakiye yüklerken görecek |
| + | SIM Stoğu | Kartları tek tek gir, bayilere zimmetle |

Bunlar bitince günlük işte elle yapılan tek şey **başvuru durumunu
değiştirmek** kalır. Para hareketi, SIM stoğu, belge silme ve bildirimler
kendiliğinden işler. Tedarikçi ataması bilinçli olarak elle yapılır.

Nasıl görüneceğini merak edersen kendi bilgisayarında dene — sunucuda
çalıştırma, deneme fiyatları ve parolaları girer:

```bash
.venv/bin/python manage.py kurulum --sifirla --ornek
```

---

## 9 · Bir şey ters giderse

Container ayağa kalkmıyorsa önce loglara bak:

```bash
docker compose logs --tail=100 app_fadil
```

**`InconsistentMigrationHistory` görüyorsan** veritabanı eski kurulumdan
kalmıştır. Container açılışta buna çarpıp ölür, ölü container'a `docker exec`
ile girilemez. Açılış betiğini atlayarak sıfırla:

```bash
read -rs PAROLA
docker compose run --rm --entrypoint python app_fadil \
  manage.py kurulum --sifirla --evet --yonetici fadil --parola "$PAROLA"
unset PAROLA
```

```bash
docker compose up -d
```

Volume silmene gerek yok; `--sifirla` yalnızca `fadil_db` şemasını düşürür.

Kurulumu tekrar çalıştırmak zararsızdır; var olan kayıtları bozmaz:

```bash
docker exec -it app_fadil python manage.py kurulum
```

Tasarım eski görünüyorsa statikleri yeniden topla:

```bash
docker exec -it app_fadil python manage.py collectstatic --noinput --clear
```

**Tarife görseli 404 veriyorsa** önce dosya sunucuda duruyor mu
bak — `media/` git'e girmez, container'a host klasöründen bağlanır:

```bash
docker exec -it app_fadil ls -R media/tarife | head
```

Dosya yerindeyse eksik olan koddur: `/media/` altındaki açık görselleri
`apps/medya.py` sunar, daha eski sürümlerde bu yol hiç yoktu.

```bash
git pull && docker compose up -d --build
```

Kimlik görüntüleri bu yoldan **açılmaz**; onlar başvuru sayfasındaki izin
kontrollü bağlantıdan gelir, doğrudan `/media/basvuru/...` istemek 404 verir.

Yönetici parolasını değiştirmek istersen:

```bash
read -rs PAROLA
docker exec -it app_fadil python manage.py kurulum \
  --yonetici fadil --parola "$PAROLA" --parolayi-yenile
unset PAROLA
```

Container'ı komple silip baştan kurmak gerekirse:

```bash
docker compose down
docker volume rm aktivasyon_postgresql-data-fadil
docker compose up -d --build      # kurulum otomatik çalışır
```

---

## 10 · Asla yapma

- **`docker volume prune`** — sunucudaki diğer 50-60 projenin volume'larını da
  siler. Volume silmen gerekirse adını tek tek yaz.
- **`docker system prune -a`** — aynı sebeple.
- **`aktivasyon/docker.env` dosyasını git'e ekleme** — veritabanı parolası içinde.
- **Migration dosyalarını elle silme** — eski projeyi bozan alışkanlık buydu.
- **`ornek_veri` / `ornek_kullanicilar` komutlarını sunucuda çalıştırma** —
  deneme parolası ve uydurma fiyat girer. Zaten `--zorla` olmadan reddeder.
