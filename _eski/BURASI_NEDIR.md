# Eski sistem (2023) — referans amaçlı

Bu klasör, yeni yapıya geçilirken **silinmeyen** eski kod tabanıdır. Çalışmıyor,
hiçbir yerden çağrılmıyor. Yalnızca henüz taşınmamış iş mantığına bakmak için duruyor.

## Neden duruyor?

Eski `basvurular/views.py` ve `admin.py` içinde yeni sisteme henüz taşınmamış
bazı akışlar var:

- `mntmutabakat`, `faturalimutabakat`, `sebekemutabakat`, `internetmutabakat`,
  `Passmutabakat` — dönemsel mutabakat/ödeme raporları
- `admin.py` içindeki toplu işlem ve filtre mantığı
- SIM kart dağıtım / hesaplama akışı (`SimCard.dist_status`)

Bu akışlar yeni yapıya taşındıktan sonra bu klasör tamamen silinebilir.

## Bilinen hatalar (yeni sisteme taşınmadı)

- `Bayi_Listesi.save()` içinde transaction'sız para hareketi — aynı kaydı iki kez
  kaydetmek bakiyeyi iki kez işliyordu
- `Duyuru` modelinde çift `class Meta` — ikincisi birincisini eziyor, sıralama çalışmıyor
- `Urun.__str__` — `fiyat_kategorisi` boşsa AttributeError
- `urls.py` — `passm` ve `internetm` route'larının ikisi de `name='internetm'`
- `views.home` — `request.POST["numara"]` doğrudan indeksleniyor, boş POST'ta 500

Not: `aktivasyon/.env` ve `aktivasyon/docker.env` yerlerinde bırakıldı, çünkü
`docker-compose.yml` hâlâ o yolu kullanıyor.
