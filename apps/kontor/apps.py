from django.apps import AppConfig


class KontorConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.kontor"
    verbose_name = "Kontör"

    def ready(self):
        from apps.dosya import dosyalari_temizle
        from apps.kontor.models import Kategori

        # Oyun logosu değişince ya da kategori silinince eski dosya diskte kalmasın.
        dosyalari_temizle(Kategori, "gorsel")
