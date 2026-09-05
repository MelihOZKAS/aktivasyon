from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from apps.bayi import views as bayi_views
from apps.medya import acik_gorsel_yollari
from apps.ozet import stok_ve_alacak

urlpatterns = [
    # Admin'in kendi giriş formu yerine tek giriş kapısı kullanılır.
    # admin.site.urls'ten ÖNCE gelmeli.
    path("yonetim/login/", bayi_views.yonetim_girisi, name="yonetim-giris"),
    # Admin'in kendi adreslerinden ÖNCE: yakalayıcı desenlerine takılmasın.
    path("yonetim/ozet/", stok_ve_alacak, name="stok-ve-alacak"),
    path("yonetim/", admin.site.urls),
    path("", include("apps.bayi.urls", namespace="bayi")),
    path("basvuru/", include("apps.basvurular.urls", namespace="basvurular")),
]

# Tarife, kampanya ve operatör görselleri DEBUG'dan bağımsız sunulur:
# yerelde görünüp üretimde 404 veren fark olmasın. Kimlik görüntüleri buraya
# girmez; onlar izin kontrollü `basvurular:belge` görünümünden gelir.
urlpatterns += acik_gorsel_yollari()

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
