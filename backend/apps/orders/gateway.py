"""
Gateway (hosted checkout) payments. No Django / MongoDB imports.

How a payment flows
  start   : create a gateway order, move the order PENDING -> PROCESSING (stock stays reserved while the
            customer pays; the expiry sweep ignores PROCESSING).
  confirm : ONE shared routine, used by the browser "verify" call, the webhook, and the reconcile sweep.
            It never trusts what the browser or the webhook body says: it fetches the payment from the
            gateway and checks id, order, amount and currency before touching anything.
  The first caller to move PROCESSING -> CONFIRMING wins and commits stock; everyone else sees "already".

Safety design
  * Signatures are checked in constant time (browser signature with the key secret, webhook with its own secret).
  * Money in vs order: wrong amount/currency/order never confirms an order (flagged needs_attention).
  * A payment that arrives for an order that was cancelled or expired (late payment), or whose stock became
    unsellable, is REFUNDED automatically, once (idempotent refund key).
  * A second, different payment for an already paid order is not refunded automatically; it is flagged
    needs_attention="duplicate_payment:<id>" for a human.
  * Webhook events are idempotent (event id), and are recorded only after they were handled, so a failed
    attempt is retried by the gateway instead of being lost.
  * Abandoned checkouts are freed by reconcile(); a payment that lands after that is refunded as a late payment.
"""
import json
import logging
from datetime import timedelta

from apps.accounts.errors import ServiceError

from . import rules
from .payments import GatewayError
from .services import all_allocations, public_order

logger = logging.getLogger(__name__)

STALE_PROCESSING_MINUTES = 20
STALE_CONFIRMING_MINUTES = 10


def _gateway_down(exc):
    return ServiceError("gateway_error", str(exc) or "The payment service is unavailable. Please try again.", 502)


class GatewayPaymentService:
    def __init__(self, order_service, orders, adapter, reservations, refunds, events, allowances, clock):
        self.os, self.orders, self.adapter = order_service, orders, adapter
        self.reservations, self.refunds, self.events, self.allowances, self.clock = reservations, refunds, events, allowances, clock

    # ---- public config ---------------------------------------------------------
    def config(self) -> dict:
        if not self.adapter.is_gateway:
            return {"provider": self.adapter.provider, "key_id": None, "mode": None}
        return {"provider": self.adapter.provider, "key_id": self.adapter.key_id, "mode": self.adapter.mode}

    def _require_gateway(self):
        if not self.adapter.is_gateway:
            raise ServiceError("not_gateway", "Gateway payments are not enabled.", 400)

    # ---- start -----------------------------------------------------------------
    def start(self, user_id: str, order_id: str) -> dict:
        self._require_gateway()
        order = self.os._own(user_id, order_id)
        if order["status"] == rules.PROCESSING and order["payment"].get("gateway_order_id"):
            return self._start_info(order)                       # resume: same gateway order
        if order["status"] != rules.PENDING:
            raise ServiceError("invalid_state", f"This order is {order['status'].replace('_', ' ')}.", 409)
        if order["reservation_expires_at"] <= self.clock():
            self.os._close(order, rules.EXPIRED, "reservation expired before payment")
            raise ServiceError("reservation_expired", "Your stock reservation expired. Please place the order again.", 409)
        if not self.os.reservations.allocations_still_valid(all_allocations(order)):
            self.os._close(order, rules.CANCELLED, "stock changed before payment")
            raise ServiceError("stock_changed", "Some items are no longer available. You were not charged. Please order again.", 409)
        try:
            gateway_order_id = self.adapter.create_gateway_order(order)
        except GatewayError as exc:
            raise _gateway_down(exc) from exc
        payment = {"provider": self.adapter.provider, "status": "awaiting_payment", "reference": None,
                   "gateway_order_id": gateway_order_id, "refunded_paise": 0, "started_at": self.clock()}
        if not self.orders.transition(order["_id"], rules.PENDING, rules.PROCESSING, {"payment": payment},
                                      "payment page opened", self.clock()):
            order = self.orders.get(order["_id"])               # a concurrent start won; use its gateway order
            if not (order and order["status"] == rules.PROCESSING and order["payment"].get("gateway_order_id")):
                raise ServiceError("conflict", "This order has just changed. Please refresh.", 409)
            return self._start_info(order)
        return self._start_info(self.orders.get(order["_id"]))

    def _start_info(self, order: dict) -> dict:
        return {"key_id": self.adapter.key_id, "mode": self.adapter.mode, "gateway_order_id": order["payment"]["gateway_order_id"],
                "amount_paise": order["total_paise"], "currency": "INR", "order_number": order["order_number"]}

    # ---- verify (browser callback) -------------------------------------------------
    def verify(self, user_id: str, order_id: str, data: dict) -> dict:
        self._require_gateway()
        order = self.os._own(user_id, order_id)
        stored = order["payment"].get("gateway_order_id")
        payment_id, signature = data.get("razorpay_payment_id"), data.get("razorpay_signature")
        # The gateway order id comes from OUR database, never from the browser.
        if not stored or data.get("razorpay_order_id") != stored or not self.adapter.verify_payment_signature(stored, payment_id, signature):
            raise ServiceError("invalid_signature", "The payment could not be verified.", 400)
        outcome = self.confirm_payment(order["_id"], payment_id)
        if outcome in ("late_refunded", "cancelled_refunded"):
            raise ServiceError("payment_refunded", "Your payment arrived too late or the items became unavailable, so it is being refunded.", 409)
        if outcome == "pending":
            raise ServiceError("payment_not_completed", "The payment has not been completed yet.", 402)
        if outcome in ("mismatch", "duplicate"):
            raise ServiceError("payment_review", "We could not match this payment to your order. Support will contact you.", 409)
        return public_order(self.orders.get(order["_id"]))

    # ---- the one shared confirm routine ------------------------------------------------
    def confirm_payment(self, order_id: str, payment_id: str) -> str:
        """Returns: confirmed | already | pending | mismatch | duplicate | late_refunded | cancelled_refunded | review."""
        try:
            payment = self.adapter.fetch_payment(payment_id)
        except GatewayError as exc:
            raise _gateway_down(exc) from exc
        order = self.orders.get(order_id)
        gw = (order or {}).get("payment", {}).get("gateway_order_id")
        if not order or not gw or payment.get("order_id") != gw or payment.get("id") != payment_id:
            logger.error("Payment %s does not belong to order %s", payment_id, order_id)
            return "mismatch"
        if payment.get("amount") != order["total_paise"] or payment.get("currency") != "INR":
            logger.error("Payment %s amount/currency mismatch for order %s", payment_id, order["order_number"])
            self.orders.set_fields(order["_id"], {"needs_attention": f"payment_mismatch:{payment_id}"})
            return "mismatch"
        try:
            if payment["status"] == "authorized":
                payment = self.adapter.capture(payment)
        except GatewayError as exc:
            raise _gateway_down(exc) from exc
        if payment["status"] != "captured":
            return "pending"

        status, now = order["status"], self.clock()
        paid = {**order["payment"], "provider": self.adapter.provider, "status": "paid", "reference": payment_id,
                "refunded_paise": order["payment"].get("refunded_paise", 0)}
        if status == rules.PROCESSING:
            if not self.orders.transition(order["_id"], rules.PROCESSING, rules.CONFIRMING, {"payment": paid}, "payment captured", now):
                return self._already_or_duplicate(self.orders.get(order["_id"]), payment_id)
            allocations = all_allocations(order)
            if not self.os.reservations.allocations_still_valid(allocations):
                self.orders.transition(order["_id"], rules.CONFIRMING, rules.CANCELLED, {}, "stock changed after payment", self.clock())
                self.os.reservations.release(allocations)
                if self.allowances:
                    self.allowances.restore([l["rx"] for l in order["lines"] if l.get("rx")])
                self.refunds.issue(self.orders.get(order["_id"]), order["total_paise"], rules.REFUND_CANCELLATION, order["_id"],
                                   "stock changed after payment", {"payment_id": payment_id})
                return "cancelled_refunded"
            try:
                self.os.reservations.commit(allocations, order["order_number"], order["user_id"])
            except Exception:
                logger.exception("Stock commit failed after gateway payment for %s", order["order_number"])
                self.orders.transition(order["_id"], rules.CONFIRMING, rules.PAYMENT_REVIEW, {}, "stock commit failed after payment", self.clock())
                return "review"
            self.orders.transition(order["_id"], rules.CONFIRMING, rules.CONFIRMED, {}, "payment confirmed", self.clock())
            return "confirmed"
        if status in (rules.CANCELLED, rules.EXPIRED):
            if order["payment"].get("reference") not in (None, payment_id):
                # An earlier payment on this closed order was already handled; this is an EXTRA one. The per-order
                # refund counter covers one payment only, so a person must settle it.
                return self._already_or_duplicate(order, payment_id)
            # Late payment: the stock was already released, so never fulfil it. Refund once.
            self.orders.set_fields(order["_id"], {"payment": paid})
            self.refunds.issue(self.orders.get(order["_id"]), order["total_paise"], "late_payment", payment_id,
                               "payment arrived after the order was closed", {"payment_id": payment_id})
            return "late_refunded"
        return self._already_or_duplicate(order, payment_id)

    def _already_or_duplicate(self, order: dict, payment_id: str) -> str:
        if order and order["payment"].get("reference") == payment_id:
            return "already"
        if order:
            self.orders.set_fields(order["_id"], {"needs_attention": f"duplicate_payment:{payment_id}"})
        return "duplicate"

    # ---- webhook -------------------------------------------------------------------
    def handle_webhook(self, raw_body: bytes, signature, event_id) -> dict:
        self._require_gateway()
        if not self.adapter.verify_webhook(raw_body, signature):
            raise ServiceError("invalid_signature", "Invalid signature.", 400)
        if not isinstance(event_id, str) or not event_id:
            raise ServiceError("validation_error", "Missing event id.", 400)
        if self.events.seen(event_id):
            return {"status": "duplicate"}
        try:
            event = json.loads(raw_body)
            name = event["event"]
            entity = lambda kind: (((event.get("payload") or {}).get(kind) or {}).get("entity") or {})
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ServiceError("validation_error", "Malformed event.", 400)
        if name in ("payment.captured", "order.paid"):
            payment = entity("payment")
            order = self.orders.find_by_gateway_order(payment.get("order_id")) if payment.get("order_id") else None
            if order and isinstance(payment.get("id"), str):
                self.confirm_payment(order["_id"], payment["id"])      # errors propagate -> 5xx -> gateway retries
            else:
                logger.warning("Webhook %s for an unknown order (event %s)", name, event_id)
        elif name == "refund.failed":
            self.refunds.gateway_refund_failed(entity("refund").get("id"))
        # payment.failed, refund.processed and anything else: nothing to change (recorded below)
        self.events.record(event_id, name, self.clock())
        return {"status": "ok", "event": name}

    # ---- reconcile (management command) ---------------------------------------------------
    def reconcile(self, limit: int = 100) -> dict:
        """Frees abandoned gateway checkouts and settles ones whose browser/webhook callback never arrived."""
        self._require_gateway()
        result = {"confirmed": 0, "expired": 0, "flagged": 0}
        cutoff = self.clock() - timedelta(minutes=STALE_PROCESSING_MINUTES)
        for order in self.orders.find_stale(rules.PROCESSING, cutoff, limit):
            gw = order["payment"].get("gateway_order_id")
            if not gw:
                continue
            try:
                captured = next((p for p in self.adapter.order_payments(gw) if p["status"] in ("captured", "authorized")), None)
                if captured and self.confirm_payment(order["_id"], captured["id"]) == "confirmed":
                    result["confirmed"] += 1
                elif not captured and self.os._close(order, rules.EXPIRED, "payment page abandoned", rules.PROCESSING):
                    result["expired"] += 1
            except (GatewayError, ServiceError):
                logger.exception("Reconcile skipped order %s", order["order_number"])
        stuck = self.clock() - timedelta(minutes=STALE_CONFIRMING_MINUTES)
        for order in self.orders.find_stale(rules.CONFIRMING, stuck, limit):
            if self.orders.transition(order["_id"], rules.CONFIRMING, rules.PAYMENT_REVIEW, {}, "stuck while confirming payment", self.clock()):
                result["flagged"] += 1
        return result
