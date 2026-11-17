"""
Payment adapters. Phase 4 ships ONLY a mock. No real money is ever charged.

A real gateway adapter (Phase 8) implements the same charge() interface.
"""
import base64
import hashlib
import hmac
import json
import logging
import re
import urllib.error
import urllib.request
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PaymentResult:
    success: bool
    reference: str = ""
    message: str = ""


class GatewayError(Exception):
    """The payment gateway could not be reached or refused a request (message is safe to show)."""


class PaymentAdapter(ABC):
    provider: str
    is_gateway = False   # True for adapters where the customer pays on the gateway's page (needs start/verify/webhook)

    @abstractmethod
    def charge(self, order: dict, options: dict) -> PaymentResult:
        """Attempt to collect order['total_paise']."""

    @abstractmethod
    def refund(self, order: dict, amount_paise: int, idempotency_key: str, options: dict) -> PaymentResult:
        """Send amount_paise back. Must be idempotent for the same idempotency_key."""


class MockPaymentAdapter(PaymentAdapter):
    """Pretends to charge. Succeeds unless options['simulate'] == 'fail' (for testing the failure path)."""

    provider = "mock"

    def charge(self, order: dict, options: dict) -> PaymentResult:
        if options.get("simulate") == "fail":
            return PaymentResult(False, message="Simulated payment failure (mock).")
        return PaymentResult(True, reference=f"MOCK-{uuid.uuid4().hex[:12].upper()}")

    def refund(self, order: dict, amount_paise: int, idempotency_key: str, options: dict) -> PaymentResult:
        if options.get("simulate") == "fail":
            return PaymentResult(False, message="Simulated refund failure (mock).")
        return PaymentResult(True, reference=f"MOCK-REF-{uuid.uuid4().hex[:12].upper()}")


def default_http(method: str, url: str, *, auth: tuple, body=None, headers=None, timeout: int = 15):
    """Tiny stdlib HTTP client: returns (status_code, parsed_json). Network errors raise GatewayError."""
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
    request.add_header("Authorization", f"Basic {token}")
    request.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        request.add_header(k, v)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:      # noqa: S310 (fixed https base URL)
            raw, status = response.read(), response.status
    except urllib.error.HTTPError as exc:
        raw, status = exc.read(), exc.code
    except Exception as exc:
        raise GatewayError("The payment service could not be reached.") from exc
    try:
        return status, json.loads(raw or b"{}")
    except ValueError:
        return status, {}


_IDEMPOTENCY_SAFE = re.compile(r"[^A-Za-z0-9_-]")


class RazorpayAdapter(PaymentAdapter):
    """
    Razorpay Standard Checkout (server side). Written from Razorpay's public documentation and tested ONLY
    against a fake gateway in this project's test-suite: it has never talked to the real Razorpay.

    The secret key never leaves the server. The browser only receives the public key id and a gateway order id.
    Amounts are integer paise. Every state-changing decision uses data fetched from Razorpay's API (not what the
    browser or webhook body claims), after a constant-time signature check.
    """

    provider = "razorpay"
    is_gateway = True
    BASE = "https://api.razorpay.com/v1"

    def __init__(self, key_id: str, key_secret: str, webhook_secret: str, http=default_http):
        if not (key_id and key_secret and webhook_secret):
            raise ValueError("Razorpay key id, key secret and webhook secret are all required.")
        self.key_id, self._secret, self._webhook_secret, self._http = key_id, key_secret, webhook_secret, http

    @property
    def mode(self) -> str:
        return "test" if self.key_id.startswith("rzp_test_") else "live"

    # -- low level ---------------------------------------------------------------
    def _call(self, method, path, body=None, headers=None):
        status, data = self._http(method, f"{self.BASE}{path}", auth=(self.key_id, self._secret), body=body, headers=headers)
        if status >= 400 or not isinstance(data, dict):
            detail = (data.get("error") or {}).get("description", "") if isinstance(data, dict) else ""
            logger.warning("Razorpay %s %s -> HTTP %s %s", method, path.split("?")[0], status, detail[:200])
            raise GatewayError(f"The payment service refused the request (HTTP {status}).")
        return data

    @staticmethod
    def _payment(d: dict) -> dict:
        return {"id": d.get("id"), "order_id": d.get("order_id"), "amount": d.get("amount"),
                "currency": d.get("currency"), "status": d.get("status")}

    # -- checkout ----------------------------------------------------------------
    def create_gateway_order(self, order: dict) -> str:
        data = self._call("POST", "/orders", {"amount": order["total_paise"], "currency": "INR",
                                              "receipt": order["order_number"][:40],
                                              "notes": {"order_number": order["order_number"]}})
        if not data.get("id") or data.get("amount") != order["total_paise"]:
            raise GatewayError("The payment service returned an unexpected order.")
        return data["id"]

    def verify_payment_signature(self, gateway_order_id: str, payment_id: str, signature: str) -> bool:
        if not all(isinstance(v, str) and v for v in (gateway_order_id, payment_id, signature)):
            return False
        expected = hmac.new(self._secret.encode(), f"{gateway_order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def verify_webhook(self, raw_body: bytes, signature) -> bool:
        if not isinstance(signature, str) or not signature or not isinstance(raw_body, (bytes, bytearray)):
            return False
        expected = hmac.new(self._webhook_secret.encode(), bytes(raw_body), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def fetch_payment(self, payment_id: str) -> dict:
        if not isinstance(payment_id, str) or not re.fullmatch(r"pay_[A-Za-z0-9]{6,40}", payment_id):
            raise GatewayError("Invalid payment id.")
        return self._payment(self._call("GET", f"/payments/{payment_id}"))

    def order_payments(self, gateway_order_id: str) -> list:
        data = self._call("GET", f"/orders/{gateway_order_id}/payments")
        return [self._payment(p) for p in data.get("items", []) if isinstance(p, dict)]

    def capture(self, payment: dict) -> dict:
        return self._payment(self._call("POST", f"/payments/{payment['id']}/capture",
                                        {"amount": payment["amount"], "currency": payment["currency"]}))

    # -- not used for gateway checkout --------------------------------------------
    def charge(self, order: dict, options: dict) -> PaymentResult:
        return PaymentResult(False, message="Pay through the payment page.")

    # -- refunds -----------------------------------------------------------------
    def refund(self, order: dict, amount_paise: int, idempotency_key: str, options: dict) -> PaymentResult:
        payment_id = options.get("payment_id") or (order.get("payment") or {}).get("reference")
        if not payment_id:
            return PaymentResult(False, message="No payment to refund.")
        key = _IDEMPOTENCY_SAFE.sub("-", idempotency_key)[:80].ljust(10, "0")
        try:
            data = self._call("POST", f"/payments/{payment_id}/refund",
                              {"amount": amount_paise, "speed": "normal", "receipt": key[:40],
                               "notes": {"order_number": order.get("order_number", "")}},
                              {"X-Refund-Idempotency": key})
        except GatewayError as exc:
            return PaymentResult(False, message=str(exc))
        if data.get("status") in ("pending", "processed") and data.get("id"):
            return PaymentResult(True, reference=data["id"])
        return PaymentResult(False, message="The payment service did not accept the refund.")
