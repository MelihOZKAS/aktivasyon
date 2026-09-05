from django.apps import AppConfig


class KatalogConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.katalog"
    verbose_name = "Katalog"

    def ready(self):
        from apps.dosya import dosyalari_temizle

        from .models import Operator, Tarife

        dosyalari_temizle(Tarife, "gorsel")
        dosyalari_temizle(Operator, "logo")
