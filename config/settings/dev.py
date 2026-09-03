from .base import *  # noqa: F403

DEBUG = True
ALLOWED_HOSTS = ["*"]

# Geliştirmede statik dosya manifesti aranmasın
STORAGES["staticfiles"] = {  # noqa: F405
    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
}
