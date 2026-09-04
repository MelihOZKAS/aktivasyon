"""Ortak Django ayarları. Ortama özel değerler dev.py / prod.py içinde."""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, []),
    CSRF_TRUSTED_ORIGINS=(list, []),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    # Modern admin teması — django.contrib.admin'den önce gelmeli
    "unfold",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "django_htmx",
    "apps.katalog",
    "apps.basvurular",
    "apps.finans",
    "apps.bayi",
    "apps.bildirim",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.bayi.context_processors.bayi_baglami",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {"default": env.db()}
DATABASES["default"]["ATOMIC_REQUESTS"] = True
DATABASES["default"]["CONN_MAX_AGE"] = 60

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "tr"
# django-unfold Türkçe çeviri ile gelmiyor; eksik metinler burada karşılanır.
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "Europe/Istanbul"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "bayi:giris"
LOGOUT_REDIRECT_URL = "bayi:anasayfa"
LOGIN_REDIRECT_URL = "bayi:panel"


# Yüklenen görseller küçültülüp WebP'ye çevrilir. Kimlik kartı kadrajın
# çoğunu kapladığı için 1000px yeter: kart üzerindeki yazı ~18px kalıyor,
# rahat okunuyor. Düşük çözünürlükte küçük yazı net kalsın diye kalite
# biraz yüksek tutuldu.
GORSEL_MAKS_KENAR = env.int("GORSEL_MAKS_KENAR", default=1000)
GORSEL_WEBP_KALITE = env.int("GORSEL_WEBP_KALITE", default=85)

# Yüklenen evrak boyutu sınırı (10 MB)
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

# Telegram bildirimleri. Anahtarlar tanımlı değilse bildirim sessizce atlanır,
# uygulama etkilenmez.
TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN", default="")
TELEGRAM_SOHBET_ID = env("TELEGRAM_SOHBET_ID", default="")
# Gönderimi eşzamanlı yapmak için False: hata ayıklarken sonucu hemen görürsünüz.
TELEGRAM_ARKA_PLAN = env.bool("TELEGRAM_ARKA_PLAN", default=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "basit": {"format": "{levelname} {asctime} {name} {message}", "style": "{"},
    },
    "handlers": {
        "konsol": {"class": "logging.StreamHandler", "formatter": "basit"},
    },
    "root": {"handlers": ["konsol"], "level": "INFO"},
    "loggers": {
        "apps": {"handlers": ["konsol"], "level": "INFO", "propagate": False},
    },
}

UNFOLD = {
    "SITE_TITLE": "Aktivasyon Yönetim",
    "SITE_HEADER": "Aktivasyon",
    "SITE_SUBHEADER": "Başvuru ve Bayi Yönetim Sistemi",
    "SITE_SYMBOL": "cell_tower",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": False,
    # Ön yüzle aynı petrol tonu. Mor kullanılmıyor.
    "COLORS": {
        "primary": {
            "50": "236 247 246",
            "100": "207 234 232",
            "200": "165 214 211",
            "300": "112 188 184",
            "400": "62 154 150",
            "500": "23 118 114",
            "600": "14 94 91",
            "700": "13 76 74",
            "800": "13 61 60",
            "900": "12 51 50",
            "950": "4 29 29",
        },
    },
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": False,
        "navigation": [
            {
                "title": "Operasyon",
                "separator": False,
                "items": [
                    {
                        "title": "Gösterge Paneli",
                        "icon": "dashboard",
                        "link": "/yonetim/",
                    },
                    {
                        "title": "Başvurular",
                        "icon": "inbox",
                        "link": "/yonetim/basvurular/basvuru/",
                    },
                    {
                        "title": "Başvuru Durumları",
                        "icon": "flag",
                        "link": "/yonetim/basvurular/basvurudurumu/",
                    },
                ],
            },
            {
                "title": "Katalog",
                "separator": True,
                "items": [
                    {
                        "title": "Kategoriler",
                        "icon": "category",
                        "link": "/yonetim/katalog/basvurukategorisi/",
                    },
                    {
                        "title": "Form Alanları",
                        "icon": "list_alt",
                        "link": "/yonetim/katalog/kategorialani/",
                    },
                    {
                        "title": "Operatörler",
                        "icon": "cell_tower",
                        "link": "/yonetim/katalog/operator/",
                    },
                    {"title": "Tarifeler", "icon": "sell", "link": "/yonetim/katalog/tarife/"},
                    {
                        "title": "Kampanyalar",
                        "icon": "campaign",
                        "link": "/yonetim/katalog/kampanya/",
                    },
                ],
            },
            {
                "title": "Finans",
                "separator": True,
                "items": [
                    {
                        "title": "Cüzdanlar",
                        "icon": "account_balance_wallet",
                        "link": "/yonetim/finans/cuzdan/",
                    },
                    {
                        "title": "Cüzdan Hareketleri",
                        "icon": "receipt_long",
                        "link": "/yonetim/finans/cuzdanhareketi/",
                    },
                    {
                        "title": "Ücret ve Hakediş Kuralları",
                        "icon": "rule",
                        "link": "/yonetim/finans/ucretkurali/",
                    },
                    {
                        "title": "Bayi Grupları",
                        "icon": "groups",
                        "link": "/yonetim/finans/bayigrubu/",
                    },
                    {
                        "title": "Banka Hesapları",
                        "icon": "account_balance",
                        "link": "/yonetim/finans/banka/",
                    },
                ],
            },
            {
                "title": "Bayi",
                "separator": True,
                "items": [
                    {
                        "title": "Bayi Başvuruları",
                        "icon": "how_to_reg",
                        "link": "/yonetim/bayi/bayibasvurusu/",
                    },
                    {
                        "title": "Bayi Profilleri",
                        "icon": "storefront",
                        "link": "/yonetim/bayi/bayiprofili/",
                    },
                    {"title": "SIM Stoğu", "icon": "sim_card", "link": "/yonetim/bayi/simkart/"},
                    {"title": "Duyurular", "icon": "notifications", "link": "/yonetim/bayi/duyuru/"},
                    {"title": "Kullanıcılar", "icon": "person", "link": "/yonetim/auth/user/"},
                ],
            },
        ],
    },
}
