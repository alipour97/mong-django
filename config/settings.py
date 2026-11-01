"""
Django settings for mong_samian project.
"""
from pathlib import Path
from urllib.parse import unquote, urlsplit
import os
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env file
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]

DEBUG = os.getenv("DJANGO_DEBUG", "False").lower() in ("true", "1", "yes")

# The one address of the site (backend, panel and storefront behind one domain).
# Moving to a new domain or VPS means changing SITE_URL in the root .env only;
# the frontend reads the same file (mong_front/next.config.ts).
SITE_URL = os.getenv("SITE_URL", "http://localhost:8800").rstrip("/")
SITE_HOST = urlsplit(SITE_URL).hostname or "localhost"

ALLOWED_HOSTS = [h.strip() for h in os.getenv("DJANGO_ALLOWED_HOSTS", "").split(",") if h.strip()]
for host in (SITE_HOST, "localhost", "127.0.0.1", "0.0.0.0", "testserver"):
    if host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(host)

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
    "apps.erp",
    "apps.samian",
    "apps.storefront",
    "apps.legacy",
    "apps.website",
    "apps.adminapi",
    "apps.payhub",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
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

# PostgreSQL when DATABASE_URL is set (Runflare); SQLite otherwise.
DATABASE_URL = os.getenv("DATABASE_URL", "")
if DATABASE_URL:
    _db = urlsplit(DATABASE_URL)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": _db.path.lstrip("/"),
            "USER": unquote(_db.username or ""),
            "PASSWORD": unquote(_db.password or ""),
            "HOST": _db.hostname or "",
            "PORT": _db.port or 5432,
            "CONN_MAX_AGE": 60,
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
            # WAL lets the site read while a sync writes; timeout waits for locks instead of failing.
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

# Public site address, used to turn local media paths into absolute URLs when
# answering. The database keeps only relative paths (/media/..., /img/...).
# Where this service answers; differs from SITE_URL when the API has its own address.
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/") or SITE_URL
# Where /media/, /img/ and /cdn/ are served from; set to a CDN address to move them there.
PUBLIC_MEDIA_BASE_URL = os.getenv("PUBLIC_MEDIA_BASE_URL", "").rstrip("/") or PUBLIC_BASE_URL
for _url in (PUBLIC_BASE_URL, PUBLIC_MEDIA_BASE_URL):
    if (_host := urlsplit(_url).hostname) and _host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(_host)
# Hosts whose URLs are ours: stored as relative paths. Old domains go in OLD_SITE_HOSTS
# so URLs saved under them are recognised (strip_hardcoded_domains, uploads, panel saves).
OWN_HOSTS = {
    h.strip().lower() for h in [SITE_HOST, urlsplit(PUBLIC_MEDIA_BASE_URL).hostname or "",
                                *os.getenv("OLD_SITE_HOSTS", "samian.mong.ir,us.mong.ir").split(",")]
    if h.strip()
}
# URL path of the pre-built images. nginx serves /img/ statically (deploy/nginx/);
# until that block is installed use /api/img, which nginx already passes to Django.
PUBLIC_IMG_PATH = os.getenv("PUBLIC_IMG_PATH", "/img").rstrip("/")
# Local mirror of the legacy cdn.mong.ir files
LEGACY_CDN_ROOT = os.getenv("LEGACY_CDN_ROOT", "/mnt/sda2/cdn.samian.mong.ir/public_html/wwwroot")

# Static files (CSS, JavaScript, Images)
# Matching Nginx config: location /static-backend/ -> /mnt/sda2/mong_samian/static/
STATIC_URL = "/static-backend/"
STATIC_ROOT = BASE_DIR / "static"
# The Django admin's files come straight from the packages, so no collectstatic after an upload.
WHITENOISE_USE_FINDERS = True

# Media files
# Matching Nginx config: location /media/ -> /mnt/sda2/mong_samian/media/
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", BASE_DIR / "media"))  # the persistent disk on Runflare

# Logs directory
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# CORS Configuration
CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOWED_ORIGINS = list(dict.fromkeys([
    "http://localhost:3000",
    "http://localhost:3300",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3300",
    SITE_URL,
    f"https://{SITE_HOST}",
    f"http://{SITE_HOST}",
]))
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = list(dict.fromkeys([SITE_URL, f"https://{SITE_HOST}", PUBLIC_BASE_URL]))
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
    "auth",  # the site sends "auth: true" on signed-in requests
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

# Runflare's proxy ends TLS in front of the service.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

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
SAMIAN_USERNAME = os.getenv("SAMIAN_USERNAME", "")
SAMIAN_PASSWORD = os.getenv("SAMIAN_PASSWORD", "")
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

# The sales software this site sells through, and what is needed to reach it (apps/erp)
ERP_CONNECTOR = os.getenv("ERP_CONNECTOR", "dadehfa")
ERP_CONNECTORS = {"samian": "apps.erp.samian.SamianConnector", "dadehfa": "apps.erp.dadehfa.DadehfaConnector"}
# Off until the writing code is reviewed and a real test order is agreed: paid orders wait in the site.
ERP_WRITES_ENABLED = os.getenv("ERP_WRITES_ENABLED", "false").lower() in ("1", "true", "yes")
LEBAZAI_API_URL = os.getenv("LEBAZAI_API_URL", "https://office.lebazacenter.com/api").rstrip("/")
LEBAZAI_API_KEY = os.getenv("LEBAZAI_API_KEY", "")
LEBAZAI_IMAGE_BRAND = os.getenv("LEBAZAI_IMAGE_BRAND", "mong")
# A login of its own for the invoice write, limited to the tables it needs. Never the reading one.
DADEHFA_WRITE_DB_USER = os.getenv("DADEHFA_WRITE_DB_USER", "")
DADEHFA_WRITE_DB_PASSWORD = os.getenv("DADEHFA_WRITE_DB_PASSWORD", "")

# Admin panel API (apps/adminapi)
ADMIN_TOKEN_MINUTES = int(os.getenv("ADMIN_TOKEN_MINUTES", "600"))

# sms.ir (apps/smsir.py): sign-in codes through the approved verify template
SMSIR_API_KEY = os.getenv("SMS_KEY", "")
SMSIR_OTP_TEMPLATE_ID = int(os.getenv("SMSIR_OTP_TEMPLATE_ID", "214177"))
SMSIR_OTP_PARAM = os.getenv("SMSIR_OTP_PARAM", "TOKEN")
SMSIR_INVOICE_TEMPLATE_ID = int(os.getenv("SMSIR_INVOICE_TEMPLATE_ID", "725839"))
SMSIR_INVOICE_PARAM = os.getenv("SMSIR_INVOICE_PARAM", "INVOICE")

# Online payment. SITE_URL is the storefront the customer returns to after paying.
# (SITE_URL, defined at the top, is also the storefront the customer returns to after paying.)
ZARINPAL_MERCHANT_ID = os.getenv("ZARINPAL_KEY", "")
ZARINPAL_SANDBOX = os.getenv("ZARINPAL_SANDBOX", "false").lower() in ("1", "true", "yes")
# The branded payment page (pay.mong.ir is a CNAME to Zarinpal). Empty: Zarinpal's own address.
ZARINPAL_STARTPAY_BASE_URL = os.getenv("ZARINPAL_STARTPAY_BASE_URL", "https://pay.mong.ir/pg/StartPay").rstrip("/")
# SnappPay is offered only once its address is set: SNAPPAY_BASE_URL in production, SNAPPAY_STAGE_URL until then.
SNAPPAY_BASE_URL = (os.getenv("SNAPPAY_BASE_URL") or os.getenv("SNAPPAY_STAGE_URL", "")).rstrip("/")
SNAPPAY_IS_STAGE = not os.getenv("SNAPPAY_BASE_URL")
SNAPPAY_CLIENT_ID = os.getenv("SNAPPAY_CLIENT_ID", "")
SNAPPAY_CLIENT_SECRET = os.getenv("SNAPPAY_CLIENT_SECRET", "")
SNAPPAY_USERNAME = os.getenv("SNAPPAY_USERNAME", "")
SNAPPAY_PASSWORD = os.getenv("SNAPPAY_PASSWORD", "")
SNAPPAY_COMMISSION_TYPE = int(os.getenv("SNAPPAY_COMMISSION_TYPE", "100"))  # the document's default, one category
SNAPPAY_TRANSACTION_ID_START = int(os.getenv("SNAPPAY_TRANSACTION_ID_START", "50000000"))  # 5-10 digits, unique

# The payment hub (apps.payhub): one service for both sites. PAYHUB_PUBLIC_URL is the address both gateways
# send the customer back to, so its domain must be the one registered with SnappPay and Zarinpal.
PAYHUB_PUBLIC_URL = os.getenv("PAYHUB_PUBLIC_URL", SITE_URL).rstrip("/")
if (_hub_host := urlsplit(PAYHUB_PUBLIC_URL).hostname) and _hub_host not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(_hub_host)
PAYHUB_ALLOWED_API_IPS = [h.strip() for h in os.getenv("PAYHUB_ALLOWED_API_IPS", "").split(",") if h.strip()]
PAYHUB_ACCEPT_KEY = os.getenv("PAYHUB_ACCEPT_KEY", "")  # SnappPayForward.Key on Mong.Pay
PAYHUB_ALLOWED_CALLBACK_HOSTS = [h.strip().lower() for h in os.getenv("PAYHUB_ALLOWED_CALLBACK_HOSTS", "api.mong.ir,api.mongnew.ir").split(",") if h.strip()]
PAYHUB_OLD_HUB_URL = os.getenv("PAYHUB_OLD_HUB_URL", "").rstrip("/")  # while moving: Mong.Pay, for the tokens it made
