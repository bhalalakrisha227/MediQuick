"""
Django settings for MediQuick (Phase 0).

All configuration comes from environment variables (loaded from backend/.env
in development). No secrets are stored in this file.

MongoDB note: Django's ORM, migrations, admin and django.contrib.auth are built
for relational databases, so they are intentionally NOT used. Data access goes
through PyMongo (see common/mongo.py). DATABASES is a dummy backend only so
Django itself starts.
"""
import logging
import secrets
from pathlib import Path

import os
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

logger = logging.getLogger(__name__)


def env_str(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    value = env_str(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be an integer, got {value!r}") from exc


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in env_str(name, default).split(",") if item.strip()]


# --- Core -------------------------------------------------------------------
DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = env_str("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        # Throwaway key so local tooling works; changes on every restart.
        SECRET_KEY = secrets.token_urlsafe(50)
        logger.warning("DJANGO_SECRET_KEY is not set; using a temporary development key.")
    else:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is not True.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

INSTALLED_APPS = [
    "corsheaders",
    "rest_framework",
    "apps.core",
    "apps.accounts",
    "apps.catalogue",
    "apps.inventory",
    "apps.orders",
    "apps.prescriptions",
    "apps.notifications",
    "apps.adminpanel",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "common.security_headers.SecurityHeadersMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# No relational database. MongoDB is accessed via PyMongo (common/mongo.py).
DATABASES = {"default": {"ENGINE": "django.db.backends.dummy"}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_TZ = True

# --- Django REST Framework --------------------------------------------------
# Secure by default: until real JWT auth is added (Phase 1), every endpoint is
# denied unless a view explicitly opts in (e.g. the health check uses AllowAny).
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["apps.accounts.authentication.JWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    # Login/register/refresh are limited per client IP. The default cache is
    # per-process memory; use a shared cache (not Redis-dependent now) in production.
    # Every endpoint has a limit; the scoped ones below are stricter. In-memory per process: with several server
    # processes each keeps its own count, so the real limit is higher. Set THROTTLE_NUM_PROXIES behind a proxy.
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle", "rest_framework.throttling.UserRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"anon": "120/min", "user": "300/min", "auth": "20/min", "checkout": "30/min", "upload": "10/min"},
    # 0 = trust only the connecting address. (None would make DRF believe the client-supplied X-Forwarded-For
    # header, which lets anyone dodge every rate limit by sending a random value.)
    "NUM_PROXIES": env_int("THROTTLE_NUM_PROXIES", 0),
    "EXCEPTION_HANDLER": "common.errors.api_exception_handler",
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
    ],
}

# --- JWT / accounts -----------------------------------------------------------
# Falls back to DJANGO_SECRET_KEY; set a separate JWT_SECRET_KEY in production.
JWT_SECRET_KEY = env_str("JWT_SECRET_KEY") or SECRET_KEY
JWT_ACCESS_MINUTES = env_int("JWT_ACCESS_MINUTES", 15)
JWT_REFRESH_DAYS = env_int("JWT_REFRESH_DAYS", 14)
MAX_FAILED_LOGINS = env_int("MAX_FAILED_LOGINS", 5)
LOGIN_LOCK_MINUTES = env_int("LOGIN_LOCK_MINUTES", 15)

# --- Payments ---------------------------------------------------------------
# Only "mock" exists (no real money moves) and it refuses to run unless DEBUG is True.
# --- Notifications ----------------------------------------------------------
# "none" = in-app only. "console" = print emails to the log (DEBUG only). "smtp" = a real SMTP server (use a TEST inbox first).
# There is NO SMS provider.
EMAIL_PROVIDER = env_str("EMAIL_PROVIDER", "none")
EMAIL_FROM = env_str("EMAIL_FROM", "")
SMTP_HOST = env_str("SMTP_HOST", "")
SMTP_PORT = env_int("SMTP_PORT", 587)
SMTP_USER = env_str("SMTP_USER", "")
SMTP_PASSWORD = env_str("SMTP_PASSWORD", "")
SMTP_USE_TLS = env_bool("SMTP_USE_TLS", True)
FRONTEND_URL = env_str("FRONTEND_URL", "http://localhost:5173")    # used for links inside emails

# --- Delivery ---------------------------------------------------------------
# PIN code prefixes we deliver to, e.g. "5600,5601,4000". EMPTY = no restriction (fine for demos, not a real service area).
DELIVERY_PINCODE_PREFIXES = tuple(env_list("DELIVERY_PINCODE_PREFIXES", ""))

PAYMENT_PROVIDER = env_str("PAYMENT_PROVIDER", "mock")          # "mock" or "razorpay" (test keys only)
RAZORPAY_KEY_ID = env_str("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = env_str("RAZORPAY_KEY_SECRET")            # server only: never sent to the browser
RAZORPAY_WEBHOOK_SECRET = env_str("RAZORPAY_WEBHOOK_SECRET")
PAYMENT_ALLOW_LIVE = env_bool("PAYMENT_ALLOW_LIVE", False)      # live keys are refused unless this is set on purpose

# --- CORS -------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env_list(
    "CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
)

# --- MongoDB ----------------------------------------------------------------
# MONGODB_URI is optional at startup so `manage.py check` works before Atlas is
# configured; common.mongo raises a clear error when a connection is attempted.
MONGODB_URI = env_str("MONGODB_URI")
MONGODB_DB_NAME = env_str("MONGODB_DB_NAME", "mediquick")
MONGODB_TIMEOUT_MS = env_int("MONGODB_TIMEOUT_MS", 5000)

# --- Uploads (used in Phase 5) ----------------------------------------------
MAX_UPLOAD_SIZE_MB = env_int("MAX_UPLOAD_SIZE_MB", 5)
PRIVATE_STORAGE_DIR = Path(env_str("PRIVATE_STORAGE_DIR") or BASE_DIR / "private_storage")
# Limits non-file request data held in memory. File uploads are checked separately in the
# prescription upload view (Content-Length first, then the real size and content).
DATA_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_SIZE_MB * 1024 * 1024

# --- Prescription OCR (Phase 5) ----------------------------------------------
# OCR output is only a suggestion for the customer and pharmacist; it never approves anything.
OCR_ENGINE = env_str("OCR_ENGINE", "tesseract")
OCR_LANG = env_str("OCR_LANG", "eng")
OCR_TIMEOUT_SECONDS = env_int("OCR_TIMEOUT_SECONDS", 60)
TESSERACT_CMD = env_str("TESSERACT_CMD")          # full path to tesseract.exe if it is not on PATH
MAX_PDF_PAGES = env_int("MAX_PDF_PAGES", 3)
# Longest time an approved prescription stays usable. PLACEHOLDER, not legal advice: needs review.
PRESCRIPTION_VALIDITY_DAYS = env_int("PRESCRIPTION_VALIDITY_DAYS", 30)
MAX_IMAGE_MEGAPIXELS = env_int("MAX_IMAGE_MEGAPIXELS", 25)

# --- Background tasks -------------------------------------------------------
TASK_RUNNER = env_str("TASK_RUNNER", "thread")
TASK_MAX_WORKERS = env_int("TASK_MAX_WORKERS", 2)

# --- Security hardening for non-debug runs ----------------------------------
# Set when a proxy / load balancer in front of Django ends HTTPS (otherwise the redirect below loops forever).
BEHIND_TLS_PROXY = env_bool("BEHIND_TLS_PROXY", False)
THROTTLE_NUM_PROXIES = env_int("THROTTLE_NUM_PROXIES", 0)
if BEHIND_TLS_PROXY:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_CONTENT_TYPE_NOSNIFF = True

# --- Logging ----------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
