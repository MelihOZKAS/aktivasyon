from .base import *  # noqa: F403

DEBUG = True
ALLOWED_HOSTS = ["*"]

# Yerelde robot anahtarı ekranı açıldığı adresi yazsın (canlı alan adını değil).
FATURA_ROBOT_ADRESI = ""

# Geliştirmede statik dosya manifesti aranmasın
STORAGES["staticfiles"] = {  # noqa: F405
    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
}
