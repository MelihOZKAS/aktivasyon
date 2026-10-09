from django.urls import path

from . import api, views

app_name = "fatura"

# Sabit adresler kurum kodundan önce gelir; aksi hâlde `<slug:kod>` deseni
# "odemeler"i ya da "robot"u kurum sanır.
urlpatterns = [
    path("fatura/", views.index, name="index"),
    path("fatura/odemeler/", views.odemeler, name="odemeler"),
    path("fatura/odeme/<str:referans>/", views.odeme, name="odeme"),
    path("fatura/odeme/<str:referans>/durum/", views.odeme_durum, name="odeme-durum"),
    path("fatura/sorgu/<str:referans>/", views.sorgu, name="sorgu"),
    path("fatura/sorgu/<str:referans>/durum/", views.sorgu_durum, name="sorgu-durum"),
    path("fatura/sorgu/<str:referans>/ode/", views.sorgu_ode, name="sorgu-ode"),
    # Sorgu robotunun kapısı (znetfaturasorgu/DJANGO_API.md).
    path("fatura/robot/is/", api.is_, name="robot-is"),
    path("fatura/robot/sonuc/", api.sonuc, name="robot-sonuc"),
    path("fatura/robot/kalp/", api.kalp, name="robot-kalp"),
    path("fatura/robot/katalog/", api.katalog, name="robot-katalog"),
    path("fatura/<slug:kod>/", views.kurum, name="kurum"),
    path("fatura/<slug:kod>/sorgula/", views.sorgula, name="sorgula"),
    path("fatura/<slug:kod>/ode/", views.ode, name="ode"),
]
