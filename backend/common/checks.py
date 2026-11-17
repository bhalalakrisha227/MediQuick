"""
Production configuration review. `collect_issues` is plain Python (testable without Django); the Django check wrapper
at the bottom exposes it through `python manage.py check --deploy`.

It reports configuration mistakes it can SEE. It cannot tell you the system is secure or ready for real customers.
"""
from urllib.parse import urlparse

ERROR, WARNING = "error", "warning"
LOCAL = ("localhost", "127.0.0.1", "[::1]", "0.0.0.0")


def _is_local(url_or_host: str) -> bool:
    host = urlparse(url_or_host).hostname if "://" in url_or_host else url_or_host
    return (host or "") in LOCAL


def collect_issues(s) -> list[tuple[str, str, str]]:
    """`s` is the settings object. Returns (level, id, message) tuples."""
    out = []

    def add(level, ident, message):
        out.append((level, ident, message))

    if s.DEBUG:
        add(ERROR, "mq.E001", "DJANGO_DEBUG is True. Never run with debug on for real users (it shows stack traces and allows the mock payment provider).")
    if len(s.SECRET_KEY) < 50 or s.SECRET_KEY.startswith("django-insecure"):
        add(ERROR, "mq.E002", "DJANGO_SECRET_KEY should be a random value of at least 50 characters.")
    if s.JWT_SECRET_KEY == s.SECRET_KEY:
        add(ERROR, "mq.E003", "JWT_SECRET_KEY must be set to its own random value, different from DJANGO_SECRET_KEY.")
    elif len(s.JWT_SECRET_KEY) < 32:
        add(ERROR, "mq.E004", "JWT_SECRET_KEY must be at least 32 characters.")
    hosts = list(s.ALLOWED_HOSTS)
    if not hosts or "*" in hosts or any(_is_local(h) for h in hosts):
        add(ERROR, "mq.E005", "DJANGO_ALLOWED_HOSTS must list only your real domain(s), not * or localhost.")
    origins = list(s.CORS_ALLOWED_ORIGINS)
    if not origins or any(not o.startswith("https://") or _is_local(o) for o in origins):
        add(ERROR, "mq.E006", "CORS_ALLOWED_ORIGINS must list only your https:// website address(es).")
    if not s.FRONTEND_URL.startswith("https://"):
        add(ERROR, "mq.E007", "FRONTEND_URL must be an https:// address (it is put in emails).")
    if not s.MONGODB_URI:
        add(ERROR, "mq.E008", "MONGODB_URI is not set.")
    if s.PAYMENT_PROVIDER == "mock":
        add(ERROR, "mq.E009", "PAYMENT_PROVIDER is mock: no real money moves. Use razorpay (test keys first).")
    if s.EMAIL_PROVIDER == "console":
        add(ERROR, "mq.E010", "EMAIL_PROVIDER=console only prints emails to the log.")
    if s.PAYMENT_PROVIDER == "razorpay":
        if not (s.RAZORPAY_KEY_ID and s.RAZORPAY_KEY_SECRET and s.RAZORPAY_WEBHOOK_SECRET):
            add(ERROR, "mq.E011", "Razorpay needs RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET and RAZORPAY_WEBHOOK_SECRET.")
        if s.RAZORPAY_KEY_ID.startswith("rzp_live_") or s.PAYMENT_ALLOW_LIVE:
            add(WARNING, "mq.W001", "LIVE payments are enabled. This project has NOT had a legal, financial or security review for real money.")
    if s.EMAIL_PROVIDER in ("", "none"):
        add(WARNING, "mq.W002", "Email is off (EMAIL_PROVIDER=none): customers only get in-app alerts.")
    if not s.THROTTLE_NUM_PROXIES and not s.BEHIND_TLS_PROXY:
        add(WARNING, "mq.W003", "Rate limits use the connecting IP. Behind a proxy or load balancer set THROTTLE_NUM_PROXIES and BEHIND_TLS_PROXY, otherwise every user shares one limit.")
    if str(s.PRIVATE_STORAGE_DIR).startswith(str(s.BASE_DIR)):
        add(WARNING, "mq.W004", "PRIVATE_STORAGE_DIR is inside the project folder. Use a separate, backed-up, non-web-served path.")
    if not s.DELIVERY_PINCODE_PREFIXES:
        add(WARNING, "mq.W005", "DELIVERY_PINCODE_PREFIXES is empty: orders to ANY PIN code are accepted.")
    if s.TASK_RUNNER == "thread":
        add(WARNING, "mq.W006", "Background OCR runs in the web process (thread pool). Work in progress is lost on restart; recovery depends on the reconcile commands being scheduled.")
    return out


def register_django_checks():
    from django.conf import settings
    from django.core import checks

    @checks.register(checks.Tags.security, deploy=True)
    def mediquick_deploy_checks(app_configs, **kwargs):
        make = {ERROR: checks.Error, WARNING: checks.Warning}
        return [make[level](message, id=ident) for level, ident, message in collect_issues(settings)]
