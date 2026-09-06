from django.urls import path, register_converter

from apps.destek import views
from apps.destek.converters import TalepDonusturucu

register_converter(TalepDonusturucu, "talep")

app_name = "destek"

urlpatterns = [
    path("", views.liste, name="liste"),
    path("yeni/", views.yeni, name="yeni"),
    path("<talep:referans>/", views.detay, name="detay"),
    path("<talep:referans>/kapat/", views.kapat, name="kapat"),
]
