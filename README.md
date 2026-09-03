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
4. Tahsilat bakiyeden düşer; bakiye yetmezse kalanı borç limitine yazılır
5. Hakediş cüzdana eklenir
6. Durum `olumsuz_sonuc` bir duruma dönerse hareketler ters kayıtla iptal edilir

Her hareketin `idempotency_anahtari` alanı benzersizdir: aynı olay iki kez işlenemez.

## Geliştirme

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.ornek .env            # SECRET_KEY'i değiştir
.venv/bin/python manage.py migrate
.venv/bin/python manage.py baslangic_verisi
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py runserver
```

Bayi paneli `/`, yönetim `/yonetim/`.

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

# 1) Önce yedek al (silmeden önce her zaman)
docker exec postgresfadil pg_dump -U nasip_fadil_user -p 5434 fadil_db \
  > ~/fadil_db_yedek_$(date +%F_%H%M).sql

# 2) Yalnızca bu projenin container'larını durdur
docker compose -f docker-compose.yml down

# 3) Yalnızca bu projenin veri volume'unu sil
#    DİKKAT: 'docker volume prune' KULLANMA — diğer projeleri siler.
docker volume rm aktivasyon_postgresql-data-fadil

# 4) Yeniden ayağa kaldır; migration ve başlangıç verisi otomatik çalışır
docker compose -f docker-compose.yml up -d --build

# 5) Yönetici hesabı aç
docker exec -it app_fadil python manage.py createsuperuser
```

Volume adını doğrulamak için: `docker volume ls | grep fadil`

### Kurulum sonrası

1. `/yonetim/` → Bayi Grupları: en az bir grup aç, borç limitini belirle
2. Operatörler ve tarifeleri gir
3. Ücret Kuralları: hangi kategoride ne kadar tahsilat/hakediş olacağını tanımla
4. Kullanıcılar: her bayi için kullanıcı aç — cüzdan ve profil satır içi doldurulur
