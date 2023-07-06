from django.urls import path
from . import views
urlpatterns = [
    path("", views.home, name = "home"),
    path("logout/", views.logout, name='logout'),
    path("bayi/", views.basvuru, name = "bayi"),
    path("panel/", views.panel, name = "panel"),
    path("mnt/", views.evrak, name = "mnt"),
    path("kontorlu-yeni-hat/", views.kontorluYeni, name = "kontorlu-yeni-hat"),
    path("faturali-yeni-hat/", views.FaturaliYeni, name = "faturali-yeni-hat"),
    path("sekebe-ici-gecis/", views.sebekeicigecis, name = "sekebe-ici-gecis"),
    path("internet-basvuru/", views.internet, name = "internet-basvuru"),
    path("evrak-gir-pass/", views.evrakpass, name = "evrak-gir-pass"),
    path("kontor-yukle/", views.kontor, name = "kontor-yukle"),
    path("alt-yapi-sorgula/", views.altYapi, name = "alt-yapi-sorgula"),
]
