from django.urls import path

from . import views

app_name = "basvurular"

urlpatterns = [
    path("", views.liste, name="liste"),
    path("yeni/", views.yeni, name="yeni"),
    path("secenek/tarife/", views.tarife_secenekleri, name="tarife-secenekleri"),
    path("secenek/kampanya/", views.kampanya_secenekleri, name="kampanya-secenekleri"),
    path("<int:pk>/", views.detay, name="detay"),
]
