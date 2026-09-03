from django.urls import path

from . import views

app_name = "bayi"

urlpatterns = [
    path("", views.anasayfa, name="anasayfa"),
    path("giris-yap/", views.GirisView.as_view(), name="giris"),
    path("bayi-basvurusu/", views.bayi_basvurusu, name="bayi-basvurusu"),
    path("cikis/", views.cikis, name="cikis"),
    path("panel/", views.panel, name="panel"),
    path("tarifeler/", views.tarifeler, name="tarifeler"),
    path("cuzdan/", views.cuzdan_gorunumu, name="cuzdan"),
]
