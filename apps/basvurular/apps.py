from django.apps import AppConfig


class BasvurularConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.basvurular"
    verbose_name = "Başvurular"

    def ready(self):
        from . import signals  # noqa: F401
