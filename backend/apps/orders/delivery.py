"""
Delivery by our own delivery partners (staff accounts with the delivery_partner role). No Django / MongoDB imports.

There is NO third-party courier or tracking integration. The partner uses this app to pick up, hand over and report
failures. Nothing here is live GPS tracking.

Safety design:
 * Handover code: when the partner picks the parcel up, the customer sees a 6-digit code on their order page. The
   partner must type it to mark the order delivered. The code is never stored: it is derived from the order id, a
   per-pickup random salt and a server secret (HMAC), so a database leak does not reveal it. Wrong tries are counted
   by one atomic update and lock the order after MAX_CODE_TRIES; staff then resolve it by hand.
 * A partner can only act on orders assigned to them (anything else looks like "not found"). Every status change
   is an atomic compare-and-set, so two requests can never both win.
 * Partners see only what they need: recipient, phone, address and item COUNT. No medicine names, no prices, no
   payment details, no prescription details. No cash on delivery exists, so partners never handle money.
 * After MAX_FAILED_ATTEMPTS failed attempts the order becomes delivery_failed. Staff then choose: redeliver
   (back to confirmed) or refund (full amount via RefundService, never restocked).
 * Staff can still mark dispatched/delivered by hand (Phase 7). That path skips the code, so it is recorded as manual.
"""
import hashlib
import hmac
import logging
import secrets

from apps.accounts.errors import ServiceError

from . import rules
from .refunds import public_refund
from .services import public_order

logger = logging.getLogger(__name__)


def _forbidden():
    return ServiceError("forbidden", "You do not have permission to perform this action.", 403)


def _not_found():
    return ServiceError("not_found", "Order not found.", 404)


def handover_code(secret: str, order_id: str, salt: str) -> str:
    digest = hmac.new(secret.encode(), f"handover:{order_id}:{salt}".encode(), hashlib.sha256).digest()
    return f"{int.from_bytes(digest[:8], 'big') % 1_000_000:06d}"


def partner_view(o: dict) -> dict:
    """The ONLY order shape a delivery partner receives."""
    d = o.get("delivery") or {}
    a = o["address"]
    return {"id": o["_id"], "order_number": o["order_number"], "status": o["status"],
            "item_count": sum(l["quantity"] for l in o["lines"]),
            "recipient_name": a["recipient_name"], "phone": a["phone"],
            "address": ", ".join(x for x in (a["line1"], a.get("line2"), a.get("landmark"), a["city"], a["state"], a["pincode"]) if x),
            "failed_count": d.get("failed_count", 0), "max_failed": rules.MAX_FAILED_ATTEMPTS,
            "code_tries_left": max(0, rules.MAX_CODE_TRIES - d.get("code_tries", 0)),
            "last_failure": (d.get("attempts") or [{}])[-1].get("reason")}


class DeliveryService:
    def __init__(self, orders, users, refunds, secret, clock):
        self.orders, self.users, self.refunds, self.secret, self.clock = orders, users, refunds, secret, clock

    # ---- staff ---------------------------------------------------------------
    def partners(self, role: str) -> dict:
        if role not in rules.FULFILMENT_ROLES:
            raise _forbidden()
        return {"results": [{"id": u["_id"], "full_name": u["full_name"]} for u in self.users.list_by_role(rules.DELIVERY_PARTNER_ROLE)]}

    def assign(self, actor_id: str, role: str, order_id: str, partner_id) -> dict:
        if role not in rules.FULFILMENT_ROLES:
            raise _forbidden()
        order = self.orders.get(order_id) if isinstance(order_id, str) else None
        if not order:
            raise _not_found()
        partner = self.users.get(partner_id) if isinstance(partner_id, str) else None
        if not partner or partner.get("role") != rules.DELIVERY_PARTNER_ROLE or not partner.get("is_active"):
            raise ServiceError("validation_error", "Choose an active delivery partner.", 400, {"partner_id": "Not a delivery partner."})
        fields = {"delivery.partner_id": partner_id, "delivery.code_tries": 0, "delivery.assigned_by": actor_id}
        # Allowed while waiting for pickup, and after a failed attempt (reassign). Never after delivery.
        for status in (rules.CONFIRMED, rules.DISPATCHED):
            if self.orders.transition(order["_id"], status, status, fields, f"assigned to delivery partner by {actor_id}", self.clock()):
                return public_order(self.orders.get(order["_id"]))
        raise ServiceError("invalid_state", f"This order is {order['status'].replace('_', ' ')} and cannot be assigned.", 409)

    def resolve_failed(self, actor_id: str, role: str, order_id: str, action: str) -> dict:
        if role not in rules.FULFILMENT_ROLES:
            raise _forbidden()
        if action not in ("redeliver", "refund"):
            raise ServiceError("validation_error", "Unknown action.", 400)
        order = self.orders.get(order_id) if isinstance(order_id, str) else None
        if not order:
            raise _not_found()
        now = self.clock()
        if action == "redeliver":
            ok = self.orders.transition(order["_id"], rules.DELIVERY_FAILED, rules.CONFIRMED,
                                        {"delivery.partner_id": None, "delivery.salt": None, "delivery.failed_count": 0,
                                         "delivery.code_tries": 0}, f"staff {actor_id} chose to redeliver", now)
        else:
            ok = self.orders.transition(order["_id"], rules.DELIVERY_FAILED, rules.CANCELLED, {},
                                        f"delivery failed; staff {actor_id} chose a refund", now)
        if not ok:
            raise ServiceError("invalid_state", f"This order is {order['status'].replace('_', ' ')}, not a failed delivery.", 409)
        if action == "refund":
            fresh = self.orders.get(order["_id"])
            owed = fresh["total_paise"] - fresh["payment"].get("refunded_paise", 0)
            if owed > 0 and fresh["payment"]["status"] == "paid":
                # Only the caller that won the transition gets here, so this runs once. Stock is NOT restocked.
                self.refunds.issue(fresh, owed, rules.REFUND_FAILED_DELIVERY, fresh["_id"], "delivery failed after repeated attempts")
        return public_order(self.orders.get(order["_id"]))

    # ---- partner -------------------------------------------------------------
    def _mine(self, partner_id: str, order_id) -> dict:
        order = self.orders.get(order_id) if isinstance(order_id, str) else None
        if not order or (order.get("delivery") or {}).get("partner_id") != partner_id:
            raise _not_found()
        return order

    def my_deliveries(self, partner_id: str) -> dict:
        rows = self.orders.list_for_partner(partner_id, (rules.CONFIRMED, rules.DISPATCHED), 100)
        return {"results": [partner_view(o) for o in rows]}

    def pickup(self, partner_id: str, order_id: str) -> dict:
        order = self._mine(partner_id, order_id)
        ok = self.orders.transition(order["_id"], rules.CONFIRMED, rules.DISPATCHED,
                                    {"dispatched_at": self.clock(), "delivery.salt": secrets.token_hex(8), "delivery.code_tries": 0},
                                    f"picked up by delivery partner {partner_id}", self.clock())
        if not ok:
            raise ServiceError("invalid_state", f"This order is {order['status'].replace('_', ' ')} and cannot be picked up.", 409)
        return partner_view(self.orders.get(order["_id"]))

    def complete(self, partner_id: str, order_id: str, data: dict) -> dict:
        order = self._mine(partner_id, order_id)
        code = data.get("code") if isinstance(data, dict) else None
        if not isinstance(code, str) or not (code.isascii() and code.isdigit() and len(code) == 6):
            raise ServiceError("validation_error", "Enter the 6-digit code from the customer.", 400, {"code": "Must be 6 digits."})
        if order["status"] != rules.DISPATCHED:
            raise ServiceError("invalid_state", f"This order is {order['status'].replace('_', ' ')}.", 409)
        tries = self.orders.bump_code_tries(order["_id"], partner_id, rules.MAX_CODE_TRIES)
        if tries is None:
            raise ServiceError("code_locked", "Too many wrong codes. Ask the pharmacy team to help with this order.", 423)
        salt = (order.get("delivery") or {}).get("salt")
        if not salt or not hmac.compare_digest(code.encode(), handover_code(self.secret, order["_id"], salt).encode()):
            raise ServiceError("wrong_code", "That code is not correct.", 400, {"code_tries_left": rules.MAX_CODE_TRIES - tries})
        now = self.clock()
        if not self.orders.transition(order["_id"], rules.DISPATCHED, rules.DELIVERED,
                                      {"delivered_at": now, "delivered_by": partner_id},
                                      f"delivered by partner {partner_id} with the customer's code", now):
            raise ServiceError("invalid_state", "This order was already updated.", 409)
        return partner_view(self.orders.get(order["_id"]))

    def fail(self, partner_id: str, order_id: str, data: dict) -> dict:
        order = self._mine(partner_id, order_id)
        reason = data.get("reason") if isinstance(data, dict) else None
        if reason not in rules.FAIL_REASONS:
            raise ServiceError("validation_error", "Choose a reason.", 400, {"reason": "Choose one of: " + ", ".join(rules.FAIL_REASONS) + "."})
        now = self.clock()
        count = self.orders.record_failed_attempt(order["_id"], partner_id, reason, now)
        if count is None:
            raise ServiceError("invalid_state", f"This order is {order['status'].replace('_', ' ')} and cannot be marked failed.", 409)
        if count >= rules.MAX_FAILED_ATTEMPTS:
            self.orders.transition(order["_id"], rules.DISPATCHED, rules.DELIVERY_FAILED, {},
                                   f"{count} failed delivery attempts", now)
        return partner_view(self.orders.get(order["_id"]))

    # ---- customer ------------------------------------------------------------
    def customer_status(self, user_id: str, order_id: str) -> dict:
        order = self.orders.get_for_user(user_id, order_id) if isinstance(order_id, str) else None
        if not order:
            raise _not_found()
        d = order.get("delivery") or {}
        out = {"status": order["status"], "failed_count": d.get("failed_count", 0), "handover_code": None, "partner_name": None}
        if d.get("partner_id"):
            partner = self.users.get(d["partner_id"])
            out["partner_name"] = (partner or {}).get("full_name", "").split(" ")[0] or None   # first name only
        if order["status"] == rules.DISPATCHED and d.get("salt") and d.get("partner_id"):
            out["handover_code"] = handover_code(self.secret, order["_id"], d["salt"])
        return out
