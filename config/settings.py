"""
Django settings for mong_samian project.
"""
from pathlib import Path
import os
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env file
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "mong-secret-key-development-stage-samian-erp-2026")

DEBUG = os.getenv("DJANGO_DEBUG", "True").lower() in ("true", "1", "yes")

ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "samian.mong.ir,localhost,127.0.0.1,0.0.0.0").split(",")
ALLOWED_HOSTS = [h.strip() for h in ALLOWED_HOSTS if h.strip()]
if "testserver" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append("testserver")

# Application definition
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Third party apps
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",

    # Local apps
    "apps.samian",
    "apps.storefront",
    "apps.legacy",
    "apps.website",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
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
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Database: SQLite for development / staging default, easily switched to Postgres
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        # WAL lets the site read while a sync writes; timeout waits for locks instead of failing.
        # Temporary: production should run on PostgreSQL (see TODO.md).
        "OPTIONS": {"timeout": 30, "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;"},
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Internationalization
LANGUAGE_CODE = "fa-ir"
TIME_ZONE = "Asia/Tehran"
USE_I18N = True
USE_TZ = True

# Public site address, used to turn local media paths into absolute URLs
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://samian.mong.ir")
# Where /img/ and /cdn/ are served from; set to a CDN address to move images there.
PUBLIC_MEDIA_BASE_URL = os.getenv("PUBLIC_MEDIA_BASE_URL", PUBLIC_BASE_URL)
# URL path of the pre-built images. nginx serves /img/ statically (deploy/nginx/);
# until that block is installed use /api/img, which nginx already passes to Django.
PUBLIC_IMG_PATH = os.getenv("PUBLIC_IMG_PATH", "/img").rstrip("/")
# Local mirror of the legacy cdn.mong.ir files
LEGACY_CDN_ROOT = os.getenv("LEGACY_CDN_ROOT", "/mnt/sda2/cdn.samian.mong.ir/public_html/wwwroot")

# Static files (CSS, JavaScript, Images)
# Matching Nginx config: location /static-backend/ -> /mnt/sda2/mong_samian/static/
STATIC_URL = "/static-backend/"
STATIC_ROOT = BASE_DIR / "static"

# Media files
# Matching Nginx config: location /media/ -> /mnt/sda2/mong_samian/media/
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Logs directory
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# CORS Configuration
CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:3300",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3300",
    "https://samian.mong.ir",
    "http://samian.mong.ir",
]
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = [
    "accept",
    "accept-encoding",
    "authorization",
    "content-type",
    "dnt",
    "origin",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
    "companyid",
]

# Django REST Framework
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.AllowAny",
    ),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
}

# Cache Configuration
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "mong-samian-cache",
        "TIMEOUT": 86400,
    }
}

# -----------------------------------------------------------------------------
# Samian ERP Integration Settings
# -----------------------------------------------------------------------------
# Development server MUST be 8087 (Port 8086 is strictly reserved for production)
SAMIAN_BASE_URL = os.getenv("SAMIAN_BASE_URL", "http://78.109.198.8:8087").rstrip("/")
SAMIAN_API_URL = os.getenv("SAMIAN_API_URL", SAMIAN_BASE_URL).rstrip("/")
SAMIAN_USERNAME = os.getenv("SAMIAN_USERNAME", "REMOVED")
SAMIAN_PASSWORD = os.getenv("SAMIAN_PASSWORD", "REMOVED")
SAMIAN_TIMEOUT = int(os.getenv("SAMIAN_TIMEOUT", "60"))
SAMIAN_STORE_RAW_DATA = os.getenv("SAMIAN_STORE_RAW_DATA", "False").lower() in ("true", "1")

# -----------------------------------------------------------------------------
# Legacy website database (DadehfaOnlineShop) - READ ONLY, used for data import
# -----------------------------------------------------------------------------
DADEHFA_DB = {
    "HOST": os.getenv("DADEHFA_DB_HOST", ""),
    "PORT": os.getenv("DADEHFA_DB_PORT", "1433"),
    "NAME": os.getenv("DADEHFA_DB_NAME", "DadehfaOnlineShop"),
    "USER": os.getenv("DADEHFA_DB_USER", ""),
    "PASSWORD": os.getenv("DADEHFA_DB_PASSWORD", ""),
}

# Only these Samian brands belong to the Mong website (مانگ, توليد). Syncs skip everything else.
SAMIAN_BRAND_IDS = [int(x) for x in os.getenv("SAMIAN_BRAND_IDS", "140430,14041").split(",") if x.strip()]

# Storefront rules carried over from the legacy site:
# - listing shows only these website brands (website.Brand ids for مانگ, توليد)
# - stock is the sum of the online-sale branches: مرواريد(3) گلسار(2) ستارخان شيراز(26) زيگورات(28) پارك سنتر اهواز(29)
STOREFRONT_BRAND_IDS = [int(x) for x in os.getenv("STOREFRONT_BRAND_IDS", "15,1").split(",") if x.strip()]
# «پرفروش‌ترین»: Mong units sold in this many days, in every branch (Lebaza's included).
BEST_SELLER_DAYS = int(os.getenv("BEST_SELLER_DAYS", "90"))
STOREFRONT_STOCK_WAREHOUSE_IDS = [
    int(x) for x in os.getenv("STOREFRONT_STOCK_WAREHOUSE_IDS", "2,3,26,28,29").split(",") if x.strip()
]
