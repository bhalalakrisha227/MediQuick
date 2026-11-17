from functools import lru_cache

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from apps.accounts.repository import UserRepository
from common.mongo import get_db

from .email_adapters import ConsoleEmailAdapter, SmtpEmailAdapter
from .repository import NotificationRepository
from .service import NotificationService


def build_email_adapter():
    provider = settings.EMAIL_PROVIDER
    if provider in ("", "none"):
        return None                       # in-app notifications still work; emails are marked skipped
    if provider == "console":
        if not settings.DEBUG:
            raise ImproperlyConfigured("EMAIL_PROVIDER=console only runs when DJANGO_DEBUG=True.")
        return ConsoleEmailAdapter()
    if provider == "smtp":
        if not (settings.SMTP_HOST and settings.EMAIL_FROM):
            raise ImproperlyConfigured("EMAIL_PROVIDER=smtp needs SMTP_HOST and EMAIL_FROM in .env.")
        return SmtpEmailAdapter(settings.SMTP_HOST, settings.SMTP_PORT, settings.SMTP_USER, settings.SMTP_PASSWORD,
                                settings.EMAIL_FROM, settings.SMTP_USE_TLS)
    raise ImproperlyConfigured(f"EMAIL_PROVIDER={provider!r} is not available. Use 'none', 'console' or 'smtp'.")


@lru_cache(maxsize=1)
def get_notifications() -> NotificationService:
    from apps.orders.services import _now
    return NotificationService(NotificationRepository(get_db()), UserRepository(get_db()), build_email_adapter(),
                               settings.FRONTEND_URL, _now)
