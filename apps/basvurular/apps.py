from django.apps import AppConfig


class BasvurularConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.basvurular"
    verbose_name = "Başvurular"

    def ready(self):
        from apps.dosya import dosyalari_temizle

        from . import signals  # noqa: F401
        from .models import BasvuruBelgesi

        dosyalari_temizle(BasvuruBelgesi, "dosya")
