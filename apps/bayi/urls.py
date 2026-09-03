from django.urls import path

from . import views

app_name = "bayi"

urlpatterns = [
    path("", views.anasayfa, name="anasayfa"),
    path("giris-yap/", views.GirisView.as_view(), name="giris"),
    path("cikis/", views.cikis, name="cikis"),
    path("panel/", views.panel, name="panel"),
    path("cuzdan/", views.cuzdan_gorunumu, name="cuzdan"),
]
