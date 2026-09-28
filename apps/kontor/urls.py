from django.urls import path

from . import api, views

app_name = "kontor"

# Sabit adresler kategori slug'ından önce gelir; aksi hâlde `<slug>` deseni
# "islemler"i kategori sanır.
urlpatterns = [
    path("kontor/", views.kategoriler, name="kategoriler"),
    path("kontor/islemler/", views.islemler, name="islemler"),
    path("kontor/islem/<str:referans>/", views.islem, name="islem"),
    path("kontor/islem/<str:referans>/durum/", views.islem_durum, name="islem-durum"),
    path("kontor/<slug:slug>/", views.kategori, name="kategori"),
    path("kontor/<slug:slug>/sorgu/", views.sorgu, name="sorgu"),
    path("kontor/<slug:slug>/<str:kod>/", views.paket, name="paket"),
    path("kontor/<slug:slug>/<str:kod>/yukle/", views.yukle, name="yukle"),
    # Oyun & Pin: aynı görünümler, ayrı vitrin ve adres.
    path("oyun/", views.kategoriler, {"oyun": True}, name="oyunlar"),
    path("oyun/<slug:slug>/", views.kategori, {"oyun": True}, name="oyun"),
    path("oyun/<slug:slug>/sorgu/", views.sorgu, {"oyun": True}, name="oyun-sorgu"),
    path("oyun/<slug:slug>/<str:kod>/", views.paket, {"oyun": True}, name="oyun-paket"),
    path("oyun/<slug:slug>/<str:kod>/yukle/", views.yukle, {"oyun": True}, name="oyun-yukle"),
    # Bayi programlarının kapısı (Znet protokolü). Adresler protokolün
    # kendisidir; programlar bunları değiştirilemez biçimde arıyor.
    path("servis/tl_servis.php", api.tl_servis, name="api-servis"),
    path("servis/tl_kontrol.php", api.tl_kontrol, name="api-kontrol"),
]
