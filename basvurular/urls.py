from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("logout/", views.logout, name='logout'),
    path("bayi/", views.basvuru, name="bayi"),
    path("panel/", views.panel, name="panel"),
    path("mnt/", views.evrak, name="mnt"),
    path("kontorlu-yeni-hat/", views.kontorluYeni, name="kontorlu-yeni-hat"),
    path("faturali-yeni-hat/", views.FaturaliYeni, name="faturali-yeni-hat"),
    path("sekebe-ici-gecis/", views.sebekeicigecis, name="sekebe-ici-gecis"),
    path("internet-basvuru/", views.internetBasvuru, name="internet-basvuru"),
    path("evrak-gir-pass/", views.evrakpass, name="evrak-gir-pass"),
    path("kontor-yukle/", views.kontor, name="kontor-yukle"),
    path("alt-yapi-sorgula/", views.altYapi, name="alt-yapi-sorgula"),
    path('get-tariffs', views.get_tariffs, name='get-tariffs'),
    path('takip/', views.evrak_list, name='takip'),
    path('bakiyetakip/', views.bakiye_hareketleri, name='bakiyetakip'),
    path('banka/', views.bankalar, name='banka'),
    path('mntm/', views.mntmutabakat, name='mntm'),

]
