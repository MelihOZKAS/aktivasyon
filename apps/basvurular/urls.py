from django.urls import path, register_converter

from . import views
from .converters import ReferansDonusturucu

register_converter(ReferansDonusturucu, "referans")

app_name = "basvurular"

urlpatterns = [
    path("", views.liste, name="liste"),
    path("yeni/", views.kategori_sec, name="kategori-sec"),
    path("yeni/<slug:kategori>/", views.yeni, name="yeni"),
    path("tarifeler/", views.tarife_secenekleri, name="tarifeler"),
    path("kampanyalar/", views.kampanya_secenekleri, name="kampanyalar"),
    path("<referans:referans>/", views.detay, name="detay"),
    path("<referans:referans>/belge/<slug:alan_kodu>/", views.belge, name="belge"),
    path(
        "<referans:referans>/gorunum/",
        views.detay_gorunumu_ayarla,
        name="detay-gorunum",
    ),
]
