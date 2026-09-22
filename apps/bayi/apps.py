from django.apps import AppConfig


class BayiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.bayi"
    verbose_name = "Bayi"

    def ready(self):
        from django.contrib.auth import get_user_model

        from .etiket import kullanici_etiketi

        # Django'nun hazır User modeli `__str__`de kullanıcı adını, yani
        # telefon numarasını döndürür; seçim kutuları, süzgeçler ve listeler
        # o metni basar. Ad görünsün diye modeli değiştirmek (AUTH_USER_MODEL)
        # canlı veritabanında hesap tablosunu taşımak demekti. Tek satırlık
        # yama yeter: görünen ad tek yerden (`etiket`) gelir.
        get_user_model().__str__ = kullanici_etiketi
