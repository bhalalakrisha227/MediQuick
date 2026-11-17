import re
import unittest
from pathlib import Path
from types import SimpleNamespace

from common import checks, doctor, errors, security_headers

BACKEND = Path(__file__).resolve().parent.parent
SETTINGS = (BACKEND / "config" / "settings.py").read_text()


def good_settings(**over):
    base = dict(DEBUG=False, SECRET_KEY="s" * 60, JWT_SECRET_KEY="j" * 40, ALLOWED_HOSTS=["shop.example.in"],
                CORS_ALLOWED_ORIGINS=["https://shop.example.in"], FRONTEND_URL="https://shop.example.in",
                MONGODB_URI="mongodb+srv://x", PAYMENT_PROVIDER="razorpay", EMAIL_PROVIDER="smtp",
                RAZORPAY_KEY_ID="rzp_test_abc", RAZORPAY_KEY_SECRET="x", RAZORPAY_WEBHOOK_SECRET="y", PAYMENT_ALLOW_LIVE=False,
                THROTTLE_NUM_PROXIES=1, BEHIND_TLS_PROXY=True, PRIVATE_STORAGE_DIR=Path("/srv/private"), BASE_DIR=Path("/app"),
                DELIVERY_PINCODE_PREFIXES=("5600",), TASK_RUNNER="thread")
    base.update(over)
    return SimpleNamespace(**base)


def ids(s):
    return {i for _, i, _ in checks.collect_issues(s)}


class DeployCheckTests(unittest.TestCase):
    def test_a_sound_configuration_has_no_errors(self):
        errors_ = [i for lvl, i, _ in checks.collect_issues(good_settings()) if lvl == "error"]
        self.assertEqual(errors_, [])

    def test_each_mistake_is_reported(self):
        cases = {
            "mq.E001": dict(DEBUG=True), "mq.E002": dict(SECRET_KEY="short"), "mq.E002b": dict(SECRET_KEY="django-insecure-" + "x" * 60),
            "mq.E003": dict(JWT_SECRET_KEY="s" * 60), "mq.E004": dict(JWT_SECRET_KEY="tiny"),
            "mq.E005": dict(ALLOWED_HOSTS=["*"]), "mq.E005b": dict(ALLOWED_HOSTS=[]), "mq.E005c": dict(ALLOWED_HOSTS=["localhost", "a.in"]),
            "mq.E006": dict(CORS_ALLOWED_ORIGINS=["http://shop.example.in"]), "mq.E006b": dict(CORS_ALLOWED_ORIGINS=["https://localhost:5173"]),
            "mq.E006c": dict(CORS_ALLOWED_ORIGINS=[]), "mq.E007": dict(FRONTEND_URL="http://shop.example.in"),
            "mq.E008": dict(MONGODB_URI=""), "mq.E009": dict(PAYMENT_PROVIDER="mock"), "mq.E010": dict(EMAIL_PROVIDER="console"),
            "mq.E011": dict(RAZORPAY_WEBHOOK_SECRET=""),
        }
        for label, over in cases.items():
            self.assertIn(label[:7], ids(good_settings(**over)), label)

    def test_good_settings_do_not_trip_each_error(self):
        for ident in ("mq.E001", "mq.E002", "mq.E003", "mq.E004", "mq.E005", "mq.E006", "mq.E007", "mq.E008", "mq.E009", "mq.E010", "mq.E011"):
            self.assertNotIn(ident, ids(good_settings()), ident)

    def test_live_money_and_other_warnings(self):
        self.assertIn("mq.W001", ids(good_settings(RAZORPAY_KEY_ID="rzp_live_x")))
        self.assertIn("mq.W001", ids(good_settings(PAYMENT_ALLOW_LIVE=True)))
        self.assertIn("mq.W002", ids(good_settings(EMAIL_PROVIDER="none")))
        self.assertIn("mq.W003", ids(good_settings(THROTTLE_NUM_PROXIES=0, BEHIND_TLS_PROXY=False)))
        self.assertIn("mq.W004", ids(good_settings(PRIVATE_STORAGE_DIR=Path("/app/private_storage"))))
        self.assertIn("mq.W005", ids(good_settings(DELIVERY_PINCODE_PREFIXES=())))
        self.assertIn("mq.W006", ids(good_settings()))
        self.assertNotIn("mq.W003", ids(good_settings()))


class HeaderTests(unittest.TestCase):
    def test_api_responses_are_never_cached_and_cannot_load_anything(self):
        h = {}
        security_headers.apply_headers(h, "/api/v1/orders/")
        self.assertEqual(h["Cache-Control"], "no-store")
        self.assertIn("default-src 'none'", h["Content-Security-Policy"])
        self.assertIn("frame-ancestors 'none'", h["Content-Security-Policy"])
        self.assertEqual((h["X-Frame-Options"], h["X-Content-Type-Options"], h["Referrer-Policy"]), ("DENY", "nosniff", "no-referrer"))
        self.assertIn("camera=()", h["Permissions-Policy"])

    def test_a_views_own_stricter_header_wins(self):
        h = {"Cache-Control": "private, no-store"}
        security_headers.apply_headers(h, "/api/v1/prescriptions/1/file/")
        self.assertEqual(h["Cache-Control"], "private, no-store")

    def test_non_api_paths_get_security_headers_but_no_cache_rule(self):
        h = {}
        security_headers.apply_headers(h, "/robots.txt")
        self.assertIn("X-Frame-Options", h)
        self.assertNotIn("Cache-Control", h)

    def test_middleware_wraps_the_response(self):
        resp = SimpleNamespace(headers={})
        out = security_headers.SecurityHeadersMiddleware(lambda request: resp)(SimpleNamespace(path="/api/v1/x/"))
        self.assertIs(out, resp)
        self.assertEqual(resp.headers["Cache-Control"], "no-store")


class ErrorShapeTests(unittest.TestCase):
    def test_shape_and_reference(self):
        self.assertEqual(errors.error_body("server_error", "x", "abc"), {"error": {"code": "server_error", "message": "x", "reference": "abc"}})
        self.assertEqual(errors.error_body("not_found", "x"), {"error": {"code": "not_found", "message": "x"}})
        self.assertNotEqual(errors.new_reference(), errors.new_reference())

    def test_handler_never_puts_exception_text_in_the_body(self):
        src = (BACKEND / "common" / "errors.py").read_text()
        self.assertNotIn("str(exc)", src)
        self.assertNotIn("repr(exc)", src)


class SettingsGuardTests(unittest.TestCase):
    """Reads settings.py as text (Django is not needed). These stop a hardening setting being deleted by accident."""

    def test_security_middleware_and_handlers_are_wired(self):
        self.assertIn('"common.security_headers.SecurityHeadersMiddleware"', SETTINGS)
        self.assertIn('"EXCEPTION_HANDLER": "common.errors.api_exception_handler"', SETTINGS)
        urls = (BACKEND / "config" / "urls.py").read_text()
        self.assertIn('handler404 = "common.errors.json_404"', urls)
        self.assertIn('handler500 = "common.errors.json_500"', urls)

    def test_every_endpoint_is_rate_limited_by_default(self):
        self.assertIn("rest_framework.throttling.AnonRateThrottle", SETTINGS)
        self.assertIn("rest_framework.throttling.UserRateThrottle", SETTINGS)
        for scope in ("anon", "user", "auth", "checkout", "upload"):
            self.assertRegex(SETTINGS, rf'"{scope}": "\d+/min"')

    def test_throttle_does_not_trust_client_forwarded_for_header(self):
        m = re.search(r'"NUM_PROXIES":\s*(.+),', SETTINGS)
        self.assertIsNotNone(m)
        self.assertNotIn("None", m.group(1))               # None would make DRF believe the X-Forwarded-For header
        self.assertNotRegex(m.group(1), r"or\s+None")

    def test_default_permission_is_login_required_and_secrets_are_not_hardcoded(self):
        self.assertIn('"rest_framework.permissions.IsAuthenticated"', SETTINGS)
        self.assertNotRegex(SETTINGS, r"(?i)(secret|password)\w*\s*=\s*['\"][^'\"]{6,}['\"]")
        self.assertIn("raise ImproperlyConfigured", SETTINGS)

    def test_production_settings_force_https(self):
        for name in ("SECURE_SSL_REDIRECT = True", "SECURE_HSTS_SECONDS", "SECURE_CONTENT_TYPE_NOSNIFF = True"):
            self.assertIn(name, SETTINGS)

    def test_the_unauthenticated_surface_is_exactly_this_list(self):
        """Anything new that does not require login must be added here on purpose, with a reason."""
        found = {}
        for path in (BACKEND / "apps").rglob("views.py"):
            for m in re.finditer(r"class (\w+)\(([^)]*)\):(.*?)(?=\nclass |\Z)", path.read_text(), re.S):
                name, bases, body = m.groups()
                if "AllowAny" in body:
                    found[name] = sorted(x for x in ("get", "post", "put", "patch", "delete") if f"def {x}(" in body)
        self.assertEqual(found, {
            "PublicAuthView": [],                    # base of register / login / refresh / logout (rate limited, JSON only)
            "CategoryListView": ["get"], "ProductListView": ["get"], "ProductDetailView": ["get"],   # the public catalogue, read only
            "HealthView": ["get"], "DatabaseHealthView": ["get"],
            "PaymentWebhookView": ["post"],          # authenticated only by the payment provider's body signature
        })

    def test_public_account_views_are_scoped_rate_limited(self):
        text = (BACKEND / "apps" / "accounts" / "views.py").read_text()
        m = re.search(r"class PublicAuthView.*?(?=\nclass )", text, re.S)
        self.assertIn("ScopedRateThrottle", m.group(0))
        self.assertIn('"auth"', text)

    def test_webhook_checks_the_signature_before_doing_anything(self):
        text = (BACKEND / "apps" / "orders" / "gateway.py").read_text()
        body = text[text.index("def handle_webhook"):]
        self.assertLess(body.index("verify_webhook"), body.index("json.loads") if "json.loads" in body else len(body))


class DoctorTests(unittest.TestCase):
    def test_ok_warn_fail_and_survival(self):
        def boom():
            raise RuntimeError("db password is hunter2")

        def warn():
            raise doctor.Warn("PDF off")

        results = doctor.run_checks([("a", lambda: None), ("b", warn), ("c", boom), ("d", lambda: "soft problem"), ("e", lambda: 1 / 0)])
        self.assertEqual([r.status for r in results], ["OK", "WARN", "FAIL", "WARN", "FAIL"])
        text, ok = doctor.summarize(results)
        self.assertFalse(ok)
        self.assertIn("1 ok, 2 warnings, 2 failed", text)

    def test_only_ok_and_warnings_pass(self):
        _, ok = doctor.summarize(doctor.run_checks([("a", lambda: None), ("b", lambda: "careful")]))
        self.assertTrue(ok)

    def test_connection_string_passwords_are_removed_from_messages(self):
        def boom():
            raise RuntimeError("cannot connect to mongodb+srv://app:S3cretPass@cluster0.example.net/?x=1")
        r = doctor.run_checks([("db", boom)])[0]
        self.assertNotIn("S3cretPass", r.message)
        self.assertIn("cluster0.example.net", r.message)

    def test_long_messages_are_cut(self):
        r = doctor.run_checks([("x", lambda: (_ for _ in ()).throw(RuntimeError("y" * 5000)))])[0]
        self.assertLessEqual(len(r.message), 200)


if __name__ == "__main__":
    unittest.main()
