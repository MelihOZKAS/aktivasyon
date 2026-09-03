from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("yonetim/", admin.site.urls),
    path("", include("apps.bayi.urls", namespace="bayi")),
    path("basvuru/", include("apps.basvurular.urls", namespace="basvurular")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
