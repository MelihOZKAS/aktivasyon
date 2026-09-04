from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from apps.bayi import views as bayi_views
from apps.medya import acik_gorsel_yollari

urlpatterns = [
    # Admin'in kendi giriş formu yerine tek giriş kapısı kullanılır.
    # admin.site.urls'ten ÖNCE gelmeli.
    path("yonetim/login/", bayi_views.yonetim_girisi, name="yonetim-giris"),
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
