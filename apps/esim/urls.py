from django.urls import path

from . import views

app_name = "esim"

# Sabit adresler ülke kodundan önce gelir; aksi hâlde `<kod>` deseni
# "siparisler"i ülke sanır.
urlpatterns = [
    path("esim/", views.ulkeler, name="ulkeler"),
    path("esim/bolgesel/", views.bolgesel, name="bolgesel"),
    path("esim/siparisler/", views.siparisler, name="siparisler"),
    path("esim/siparis/<str:referans>/", views.siparis, name="siparis"),
    path("esim/siparis/<str:referans>/durum/", views.siparis_durum, name="siparis-durum"),
    path("esim/siparis/<str:referans>/etiket/", views.etiket, name="etiket"),
    path("esim/siparis/<str:referans>/yukle/", views.yukle, name="yukle"),
    path("esim/<str:kod>/", views.ulke, name="ulke"),
    path("esim/<str:kod>/<int:pk>/", views.paket, name="paket"),
    path("esim/<str:kod>/<int:pk>/satin-al/", views.satin_al, name="satin-al"),
]
