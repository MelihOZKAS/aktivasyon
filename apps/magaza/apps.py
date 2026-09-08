from django.apps import AppConfig


class MagazaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.magaza"
    verbose_name = "Mağaza"

    def ready(self):
        from apps.dosya import dosyalari_temizle
        from apps.magaza.models import Urun

        # Kayıt silinince ve görsel değişince eski dosya diskten silinir.
        dosyalari_temizle(Urun, "gorsel")
