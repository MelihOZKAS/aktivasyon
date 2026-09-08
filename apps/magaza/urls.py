from django.urls import path

from . import views

app_name = "magaza"

# "siparislerim" ürün slug'ından önce gelmeli; aksi hâlde slug deseni yutar.
urlpatterns = [
    path("magaza/", views.magaza, name="liste"),
    path("magaza/siparislerim/", views.siparislerim, name="siparislerim"),
    path("magaza/<slug:slug>/", views.urun, name="urun"),
    path("magaza/<slug:slug>/satin-al/", views.satin_al, name="satin-al"),
]
