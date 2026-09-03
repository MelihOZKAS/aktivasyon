from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from apps.bayi import views as bayi_views

urlpatterns = [
    # Admin'in kendi giriş formu yerine tek giriş kapısı kullanılır.
    # admin.site.urls'ten ÖNCE gelmeli.
    path("yonetim/login/", bayi_views.yonetim_girisi, name="yonetim-giris"),
    path("yonetim/", admin.site.urls),
    path("", include("apps.bayi.urls", namespace="bayi")),
    path("basvuru/", include("apps.basvurular.urls", namespace="basvurular")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
