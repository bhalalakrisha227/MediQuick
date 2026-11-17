"""
Orders: checkout, payment (mock for now), cancellation and reservation expiry.
No Django / MongoDB imports (tested with in-memory fakes).

Safety design:
 * The cart is CLAIMED atomically at checkout, so a double click cannot make two orders.
 * Stock is reserved all-or-nothing, earliest expiry first. Any failure restores the cart
   and releases every reservation made so far.
 * Every status change is an atomic compare-and-set (orders.transition), so an order is
   paid, cancelled or expired exactly once and reservations are released exactly once.
 * Units leave stock only when payment succeeds (commit), batch by batch, with a ledger row.
"""
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from apps.accounts.errors import DuplicateError, ServiceError
from apps.inventory.reservations import InsufficientStock

from . import rules, validators

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def all_allocations(order: dict) -> list[dict]:
    return [a for line in order["lines"] for a in line["allocations"]]


def payment_status(o: dict) -> str:
    """Display status: 'paid' becomes partially_refunded / refunded from the atomic refunded_paise counter."""
    payment = o["payment"]
    refunded = payment.get("refunded_paise", 0)
    if payment["status"] == "paid" and refunded > 0:
        return "refunded" if refunded >= o["total_paise"] else "partially_refunded"
    return payment["status"]


def public_order(o: dict) -> dict:
    payment = o["payment"]
    return {
        "id": o["_id"], "order_number": o["order_number"], "status": o["status"],
        "lines": [{**{k: l[k] for k in ("product_id", "name", "pack_size", "unit_price_paise", "quantity", "line_total_paise")},
                   "prescription_id": (l.get("rx") or {}).get("prescription_id")}
                  for l in o["lines"]],
        "address": o["address"],
        "subtotal_paise": o["subtotal_paise"], "delivery_fee_paise": o["delivery_fee_paise"], "total_paise": o["total_paise"],
        "payment": {"status": payment_status(o), "provider": payment["provider"], "reference": payment["reference"],
                    "is_mock": payment["provider"] == "mock", "refunded_paise": payment.get("refunded_paise", 0)},
        "delivery": {"partner_id": (o.get("delivery") or {}).get("partner_id"),
                     "failed_count": (o.get("delivery") or {}).get("failed_count", 0),
                     "attempts": [{"reason": a["reason"], "at": a["at"].isoformat()} for a in (o.get("delivery") or {}).get("attempts", [])]},
        "delivered_at": o["delivered_at"].isoformat() if o.get("delivered_at") else None,
        "reservation_expires_at": o["reservation_expires_at"].isoformat() if o["status"] == rules.PENDING else None,
        "created_at": o["created_at"].isoformat(),
    }


class OrderService:
    def __init__(self, carts, orders, products, addresses, reservations, payments, clock=_now, allowances=None,
                 pincode_prefixes=()):
        self.pincode_prefixes = tuple(pincode_prefixes)
        self.carts, self.orders, self.products, self.addresses = carts, orders, products, addresses
        self.reservations, self.payments, self.clock = reservations, payments, clock
        self.allowances = allowances   # approved-prescription allowances; None = prescription medicines stay blocked

    # -- helpers ---------------------------------------------------------------
    def _close(self, order: dict, new_status: str, note: str, from_status: str = rules.PENDING) -> bool:
        """Move a still-unpaid order to cancelled/expired and free its stock. True only for the winner of the race."""
        if self.orders.transition(order["_id"], from_status, new_status, {}, note, self.clock()):
            self.reservations.release(all_allocations(order))
            if self.allowances:   # give the prescription units back, exactly once (we won the transition)
                self.allowances.restore([l["rx"] for l in order["lines"] if l.get("rx")])
            return True
        return False

    def release_expired(self, limit: int = 100) -> int:
        count = 0
        for order in self.orders.find_expired_pending(self.clock(), limit):
            if self._close(order, rules.EXPIRED, "reservation expired"):
                count += 1
        return count

    def _price_lines(self, user_id: str, items: list[dict]) -> list[dict]:
        products = self.products.get_many([i["product_id"] for i in items])
        rx_ids = [pid for pid, p in products.items() if p.get("requires_prescription")]
        rx = self.allowances.remaining(user_id, rx_ids) if (self.allowances and rx_ids) else {}
        lines, problems = [], {}
        for item in items:
            p = products.get(item["product_id"])
            problem = rules.line_problem(p, rx.get(item["product_id"], 0), item["quantity"])
            if problem:
                problems[item["product_id"]] = problem
                continue
            lines.append({
                "product_id": p["_id"], "name": p["name"], "pack_size": p.get("pack_size", ""), "schedule": p["schedule"],
                "requires_prescription": bool(p["requires_prescription"]),
                "unit_price_paise": p["price_paise"], "mrp_paise": p["mrp_paise"], "quantity": item["quantity"],
                "line_total_paise": p["price_paise"] * item["quantity"],
            })
        if problems:
            raise ServiceError("cart_invalid", "Some items in your cart cannot be ordered. Please review your cart.", 409, problems)
        return lines

    def _insert_with_number(self, order: dict) -> None:
        for _ in range(5):
            order["order_number"] = f"MQ-{order['created_at']:%y%m%d}-{secrets.token_hex(3).upper()}"
            try:
                self.orders.insert(order)
                return
            except DuplicateError:
                continue
        raise ServiceError("conflict", "Could not allocate an order number. Please try again.", 409)

    def _own(self, user_id: str, order_id) -> dict:
        order = self.orders.get_for_user(user_id, order_id) if isinstance(order_id, str) else None
        if order is None:
            raise ServiceError("not_found", "Order not found.", 404)
        return order

    # -- checkout --------------------------------------------------------------
    def create(self, user_id: str, data: dict) -> dict:
        cleaned = validators.validate_checkout(data)
        self.release_expired()
        address = self.addresses.get(user_id, cleaned["address_id"])
        if address is None:
            raise ServiceError("validation_error", "Choose one of your saved addresses.", 400,
                               {"address_id": "Address not found."})
        if not rules.serviceable(address.get("pincode", ""), self.pincode_prefixes):
            raise ServiceError("not_serviceable", "Sorry, we do not deliver to this PIN code yet.", 409,
                               {"address_id": "We do not deliver to this PIN code."})
        cart = self.carts.claim(user_id)  # atomic: a second simultaneous checkout finds nothing
        if not cart or not cart["items"]:
            raise ServiceError("cart_empty", "Your cart is empty.", 400)
        items, held, consumed = cart["items"], {}, []
        try:
            lines = self._price_lines(user_id, items)
            try:
                held = self.reservations.reserve_many([(l["product_id"], l["quantity"]) for l in lines])
            except InsufficientStock as exc:
                raise ServiceError("insufficient_stock", "Some items are no longer available in the quantity you chose.", 409,
                                   {exc.product_id: {"requested": exc.requested, "available": exc.available}})
            now = self.clock()
            for line in lines:
                line["allocations"] = held[line["product_id"]]
                if line["requires_prescription"]:
                    # Atomic: takes the units from ONE approved prescription, or fails. Restored below on any error.
                    taken = self.allowances.consume(user_id, line["product_id"], line["quantity"]) if self.allowances else None
                    if not taken:
                        raise ServiceError("cart_invalid", "Some items in your cart cannot be ordered. Please review your cart.",
                                           409, {line["product_id"]: "prescription_required"})
                    consumed.append(taken)
                    line["rx"] = taken
            subtotal = sum(l["line_total_paise"] for l in lines)
            fee = rules.delivery_fee(subtotal)
            order = {
                "_id": uuid.uuid4().hex, "order_number": None, "user_id": user_id, "status": rules.PENDING,
                "lines": lines,
                "address": {k: address.get(k, "") for k in ("recipient_name", "phone", "line1", "line2", "landmark",
                                                           "city", "state", "pincode")},
                "subtotal_paise": subtotal, "delivery_fee_paise": fee,
                "total_paise": subtotal + fee,
                "delivery": {"partner_id": None, "salt": None, "failed_count": 0, "code_tries": 0, "attempts": []},
                "payment": {"provider": None, "status": "unpaid", "reference": None, "refunded_paise": 0},
                "reservation_expires_at": now + timedelta(minutes=rules.RESERVATION_MINUTES),
                "created_at": now, "updated_at": now,
                "status_history": [{"status": rules.PENDING, "at": now, "note": "order created"}],
            }
            self._insert_with_number(order)
        except BaseException:
            if consumed and self.allowances:
                self.allowances.restore(consumed)
            if held:
                self.reservations.release([a for allocs in held.values() for a in allocs])
            self.carts.restore_if_empty(user_id, items, self.clock())  # the shopper keeps their cart
            raise
        return public_order(order)

    # -- payment (mock) --------------------------------------------------------
    def pay(self, user_id: str, order_id: str, data: dict) -> dict:
        if getattr(self.payments, "is_gateway", False):
            raise ServiceError("use_gateway", "Please pay through the payment page.", 400)
        cleaned = validators.validate_pay(data)
        order = self._own(user_id, order_id)
        if order["status"] == rules.CONFIRMED:
            return public_order(order)  # idempotent: paying twice never charges or deducts twice
        if order["status"] != rules.PENDING:
            raise ServiceError("invalid_state", f"This order is {order['status'].replace('_', ' ')}.", 409)
        if order["reservation_expires_at"] <= self.clock():
            self._close(order, rules.EXPIRED, "reservation expired before payment")
            raise ServiceError("reservation_expired", "Your stock reservation expired. Please place the order again.", 409)
        allocations = all_allocations(order)
        if not self.reservations.allocations_still_valid(allocations):
            self._close(order, rules.CANCELLED, "stock changed before payment")
            raise ServiceError("stock_changed",
                               "Some items are no longer available. You were not charged. Please order again.", 409)
        if not self.orders.transition(order["_id"], rules.PENDING, rules.PROCESSING, {}, "payment started", self.clock()):
            raise ServiceError("conflict", "This order is already being processed.", 409)

        result = self.payments.charge(order, {"simulate": cleaned["simulate"]})
        provider = self.payments.provider
        if not result.success:
            self.orders.transition(order["_id"], rules.PROCESSING, rules.PENDING,
                                   {"payment": {"provider": provider, "status": "failed", "reference": None, "refunded_paise": 0}},
                                   "payment failed", self.clock())
            raise ServiceError("payment_failed", result.message or "Payment failed. You were not charged.", 402)
        try:
            self.reservations.commit(allocations, order["order_number"], user_id)
        except Exception:
            logger.exception("Stock commit failed after payment for order %s", order["order_number"])
            self.orders.transition(order["_id"], rules.PROCESSING, rules.PAYMENT_REVIEW,
                                   {"payment": {"provider": provider, "status": "paid", "reference": result.reference, "refunded_paise": 0}},
                                   "stock commit failed after payment", self.clock())
            raise ServiceError("payment_review",
                               "Your payment was received but we could not finalise the order. Support will contact you.", 500)
        self.orders.transition(order["_id"], rules.PROCESSING, rules.CONFIRMED,
                               {"payment": {"provider": provider, "status": "paid", "reference": result.reference, "refunded_paise": 0}},
                               "payment confirmed", self.clock())
        return public_order(self.orders.get(order["_id"]))

    # -- customer actions / reads ---------------------------------------------
    def cancel(self, user_id: str, order_id: str) -> dict:
        order = self._own(user_id, order_id)
        if order["status"] != rules.PENDING:
            raise ServiceError("invalid_state", "Only unpaid orders can be cancelled here.", 409)
        if not self._close(order, rules.CANCELLED, "cancelled by customer"):
            raise ServiceError("conflict", "This order is already being processed.", 409)
        return public_order(self.orders.get(order["_id"]))

    def get(self, user_id: str, order_id: str) -> dict:
        self.release_expired()
        return public_order(self._own(user_id, order_id))

    def list(self, user_id: str, page: int = 1, page_size: int = 20) -> dict:
        self.release_expired()
        items, total = self.orders.list_for_user(user_id, (page - 1) * page_size, page_size)
        return {"results": [public_order(o) for o in items], "page": page, "page_size": page_size, "total": total}
