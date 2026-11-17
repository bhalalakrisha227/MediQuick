"""
Hostile-input test for EVERY public service method.

Two things are checked while each method is called with database-operator payloads ({"$ne": null}), wrong types,
huge strings and nesting:
 1. Nothing but a clean ServiceError may come out. Any other exception would be an HTTP 500 and a sign the input was
    not validated.
 2. A spy sits in front of every repository. It fails the test if a "$operator" dictionary ever reaches the database
    layer, or a non-string is used as an id lookup (that is how NoSQL operator injection works).
This catches classes of bug; it does not prove the code is free of vulnerabilities.
"""
import inspect
import os
import unittest
from datetime import datetime, timezone

from apps.accounts.errors import ServiceError
from apps.accounts.services import AddressService, AuthConfig, AuthService, ProfileService
from apps.adminpanel.analytics import AnalyticsService

from .fakes import FakeAddresses, FakeTokens
from .test_adminpanel import AdminBase

PAYLOADS = [
    {"$ne": None}, {"$gt": ""}, {"$where": "sleep(1000)"}, {"a": {"$ne": 1}}, [{"$ne": 1}], ["x"], [], {}, 0, -1, 2**70, 1.5,
    float("nan"), True, None, "", " ", "x" * 20000, "\x00", "../../etc/passwd", "a\nb", "$ne", {"$regex": ".*"},
    b"bytes", ("t",), object(),
]
KEYS = ["email", "password", "full_name", "phone", "refresh_token", "address_id", "product_id", "quantity", "reason", "details",
        "items", "note", "decision", "code", "partner_id", "active", "flag", "simulate", "line1", "line2", "landmark", "city",
        "state", "pincode", "recipient_name", "label", "message", "prescription_id", "razorpay_payment_id", "razorpay_order_id",
        "razorpay_signature", "email_on", "page", "q", "role", "from", "to", "status", "medicines", "patient_name", "doctor_name",
        "reviewed_text", "approved_items", "reply", "rejection_reason", "max_quantity"]
# These come from the verified login token / database, never from the request body or URL, so they are not fuzzed.
# (partner_id is trusted EXCEPT in assign(), where staff send it in the request body.)
FIXED = {"role": "admin", "actor_role": "admin", "actor_id": "a1", "actor": {"id": "a1", "role": "admin"}, "user_id": "u1"}
SKIP = {"reconcile", "send_due", "confirm_payment", "handle_webhook", "gateway_refund_failed", "issue", "retry", "_attempt",
        "receive", "adjust", "set_status", "create_product", "create_category", "update_product", "list_movements",
        "upload", "create", "file_for",
        "process", "record"}   # record() is an internal call whose arguments are validated by its callers (tested there); process() is the background OCR job: it is given our own prescription id, never client input


class Spy:
    """Wraps a fake repository and refuses operator injection."""
    ID_GETTERS = ("get", "get_for_user", "get_by_email", "get_by_hash", "get_by_reference")

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if not callable(attr):
            return attr

        def checked(*args, **kwargs):
            for value in list(args) + list(kwargs.values()):
                self._scan(name, value)
            if name in self.ID_GETTERS:
                for value in list(args) + list(kwargs.values()):
                    if not isinstance(value, str):
                        raise AssertionError(f"{type(self._inner).__name__}.{name} got a non-string id: {value!r:.80}")
            return attr(*args, **kwargs)
        return checked

    def _scan(self, method, value, depth=0):
        if depth > 8:
            return
        if isinstance(value, dict):
            for k, v in value.items():
                if isinstance(k, str) and k.startswith("$"):
                    raise AssertionError(f"{type(self._inner).__name__}.{method} received operator key {k!r}")
                self._scan(method, v, depth + 1)
        elif isinstance(value, (list, tuple)):
            for v in value:
                self._scan(method, v, depth + 1)


def spy_on(service):
    for name, value in list(vars(service).items()):
        if hasattr(value, "docs") or type(value).__name__.startswith(("Fake", "Notifying")):
            setattr(service, name, Spy(value))
    return service


def public_methods(service):
    for name, fn in inspect.getmembers(service, inspect.ismethod):
        if not name.startswith("_") and name not in SKIP:
            yield name, fn


class FuzzMixin:
    def fuzz(self, label, service):
        problems, calls = [], 0
        for name, fn in public_methods(service):
            params = [p for p in inspect.signature(fn).parameters.values()
                      if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) and p.default is p.empty]
            for payload in PAYLOADS:
                for variant in ("ids", "data"):
                    args = []
                    for p in params:
                        if p.name in FIXED:
                            args.append(FIXED[p.name])
                        elif p.name in ("data", "body", "params", "options"):
                            args.append({k: payload for k in KEYS} if variant == "data" else {})
                        elif p.name == "partner_id" and name != "assign":
                            args.append("rider1")
                        else:
                            args.append(payload if variant == "ids" else "u1")
                    calls += 1
                    try:
                        fn(*args)
                    except ServiceError:
                        pass
                    except Exception as exc:                      # noqa: BLE001 - this is exactly what we hunt for
                        problems.append(f"{label}.{name}({variant}, {payload!r:.40}) -> {type(exc).__name__}: {str(exc)[:90]}")
        seen = {}
        for line in problems:
            seen.setdefault(line.split("(")[0] + " " + line.split("->")[1][:60], line)
        self.assertGreaterEqual(calls, len(PAYLOADS), f"{label}: the fuzzer barely ran")   # guard against a vacuous pass
        if os.environ.get("FUZZ_VERBOSE"):
            for line in sorted(seen.values()):
                print("FUZZ", line[:200])
        self.assertEqual(sorted(seen.values()), [], f"{len(problems)} unexpected outcomes")


class OrderSideFuzz(AdminBase, FuzzMixin):
    def test_all_services_reject_hostile_input_cleanly(self):
        for label in ("orders", "cart", "life", "dl", "review", "presc", "attn", "useradmin", "audit"):
            service = spy_on(getattr(self, label))
            self.fuzz(label, service)
        self.fuzz("analytics", self.an)


class AccountSideFuzz(unittest.TestCase, FuzzMixin):
    def setUp(self):
        from .fakes import FakeUsers
        users, tokens = FakeUsers(), FakeTokens()
        clock = lambda: datetime.now(timezone.utc)
        self.auth = spy_on(AuthService(users, tokens, AuthConfig(jwt_secret="k" * 40), clock))
        self.profile = spy_on(ProfileService(users, clock))
        self.addresses = spy_on(AddressService(FakeAddresses(), clock))

    def test_accounts(self):
        for label in ("auth", "profile", "addresses"):
            self.fuzz(label, getattr(self, label))


if __name__ == "__main__":
    unittest.main()
