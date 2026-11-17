"""
Order lifecycle after payment: cancel, manual fulfilment status, returns. No Django / MongoDB imports.

Safety design:
 * Cancelling a PAID order is an atomic confirmed -> cancelled change. Only the caller that wins it
   restocks, restores prescription units and refunds, so each happens exactly once. After dispatch
   a customer can no longer cancel (they can request a return after delivery).
 * Restocking is allowed ONLY here (units never left the pharmacy). Returned medicines are NEVER
   put back on sale: an approved return refunds the money and leaves stock and prescription units alone.
 * Returns: delivered orders only, inside a short window, from a fixed list of reasons (no "changed
   my mind"), at most one open request per order, quantities capped by what was delivered. Only
   staff roles decide, once (atomic), and a refund follows via RefundService.
 * "Dispatched" and "delivered" are set BY HAND by pharmacy staff. There is no delivery partner
   integration yet (Phase 9), and the screens say so.
"""
import logging
import uuid
from datetime import timedelta

from apps.accounts.errors import DuplicateError, ServiceError

from . import rules
from .refunds import public_refund
from .services import all_allocations, public_order

logger = logging.getLogger(__name__)


def public_return(r: dict, refunds=()) -> dict:
    refund = next((x for x in refunds if x["source_id"] == r["_id"]), None)
    decision = r.get("decision")
    return {"id": r["_id"], "order_id": r["order_id"], "order_number": r["order_number"], "status": r["status"],
            "reason": r["reason"], "details": r["details"], "items": r["items"], "amount_paise": r["amount_paise"],
            "decision_note": decision["note"] if decision else "", "restocked": False,
            "refund": public_refund(refund) if refund else None, "created_at": r["created_at"].isoformat()}


def _forbidden():
    return ServiceError("forbidden", "You do not have permission to perform this action.", 403)


class LifecycleService:
    def __init__(self, order_service, orders, returns, refunds, reservations, allowances, clock):
        self.order_service, self.orders, self.returns, self.refunds = order_service, orders, returns, refunds
        self.reservations, self.allowances, self.clock = reservations, allowances, clock

    # ---- cancel --------------------------------------------------------------
    def cancel(self, user_id: str, order_id: str) -> dict:
        order = self.order_service._own(user_id, order_id)
        if order["status"] == rules.PENDING:
            return {"order": self.order_service.cancel(user_id, order_id), "refund": None}
        if order["status"] == rules.PROCESSING and order["payment"].get("gateway_order_id"):
            # Gateway checkout opened but not completed. A payment that still lands later is refunded automatically.
            if not self.order_service._close(order, rules.CANCELLED, "cancelled by customer before payment completed", rules.PROCESSING):
                raise ServiceError("conflict", "This order has just changed. Please refresh.", 409)
            return {"order": public_order(self.orders.get(order["_id"])), "refund": None}
        if order["status"] != rules.CONFIRMED:
            raise ServiceError("invalid_state", "This order can no longer be cancelled. If it was delivered, request a return.", 409)
        if not self.orders.transition(order["_id"], rules.CONFIRMED, rules.CANCELLED, {},
                                      "cancelled by customer after payment", self.clock()):
            raise ServiceError("conflict", "This order has just changed and can no longer be cancelled.", 409)
        try:
            self.reservations.restock(all_allocations(order), order["order_number"], user_id)
        except Exception:
            logger.exception("Restock failed for cancelled order %s", order["order_number"])
            self.orders.set_fields(order["_id"], {"needs_attention": "restock_failed"})
        if self.allowances:
            self.allowances.restore([l["rx"] for l in order["lines"] if l.get("rx")])
        refund = self.refunds.issue(order, order["total_paise"], rules.REFUND_CANCELLATION, order["_id"],
                                    "cancelled by customer")
        return {"order": public_order(self.orders.get(order["_id"])), "refund": public_refund(refund)}

    # ---- manual fulfilment (staff) ------------------------------------------
    def fulfil(self, actor_id: str, role: str, order_id: str, action: str) -> dict:
        if role not in rules.FULFILMENT_ROLES:
            raise _forbidden()
        if action not in ("dispatch", "deliver"):
            raise ServiceError("validation_error", "Unknown action.", 400)
        order = self.orders.get(order_id) if isinstance(order_id, str) else None
        if not order:
            raise ServiceError("not_found", "Order not found.", 404)
        now = self.clock()
        if action == "dispatch":
            ok = self.orders.transition(order["_id"], rules.CONFIRMED, rules.DISPATCHED, {"dispatched_at": now},
                                        f"manually marked dispatched by {actor_id}", now)
        else:
            ok = self.orders.transition(order["_id"], rules.DISPATCHED, rules.DELIVERED, {"delivered_at": now},
                                        f"manually marked delivered by {actor_id}", now)
        if not ok:
            raise ServiceError("invalid_state", f"This order is {order['status'].replace('_', ' ')} and cannot be moved that way.", 409)
        return public_order(self.orders.get(order["_id"]))

    def staff_orders(self, role: str, status=None) -> dict:
        if role not in rules.FULFILMENT_ROLES:
            raise _forbidden()
        statuses = (status,) if status in (rules.CONFIRMED, rules.DISPATCHED, rules.DELIVERY_FAILED) else (rules.CONFIRMED, rules.DISPATCHED, rules.DELIVERY_FAILED)
        return {"results": [public_order(o) for o in self.orders.list_by_status(statuses, 100)]}

    # ---- returns (customer) --------------------------------------------------
    def request_return(self, user_id: str, order_id: str, data: dict) -> dict:
        order = self.order_service._own(user_id, order_id)
        if order["status"] != rules.DELIVERED or not order.get("delivered_at"):
            raise ServiceError("not_delivered", "A return can only be requested after the order is delivered.", 409)
        if order["delivered_at"] + timedelta(days=rules.RETURN_WINDOW_DAYS) < self.clock():
            raise ServiceError("return_window_closed",
                               f"Returns must be requested within {rules.RETURN_WINDOW_DAYS} days of delivery.", 409)
        fields = {}
        reason, details = data.get("reason"), data.get("details", "")
        if reason not in rules.RETURN_REASONS:
            fields["reason"] = "Choose one of: " + ", ".join(rules.RETURN_REASONS) + "."
        if details is None:
            details = ""
        if not isinstance(details, str) or len(details.strip()) > rules.MAX_RETURN_DETAILS:
            fields["details"] = f"Must be text of at most {rules.MAX_RETURN_DETAILS} characters."
        raw = data.get("items")
        lines = {l["product_id"]: l for l in order["lines"]}
        already = {}
        for r in self.returns.list_for_order(order["_id"]):
            if r["status"] == "requested":
                raise ServiceError("return_open", "You already have a return request waiting for review on this order.", 409)
            if r["status"] == "approved":
                for i in r["items"]:
                    already[i["product_id"]] = already.get(i["product_id"], 0) + i["quantity"]
        items, seen = [], set()
        if not isinstance(raw, list) or not raw or len(raw) > len(lines):
            fields["items"] = "Choose at least one item from this order."
        else:
            for n, it in enumerate(raw):
                pid, qty = (it.get("product_id"), it.get("quantity")) if isinstance(it, dict) else (None, None)
                line = lines.get(pid) if isinstance(pid, str) else None
                if line is None or pid in seen:
                    fields[f"items.{n}"] = "Choose each item from this order only once."
                    continue
                seen.add(pid)
                room = line["quantity"] - already.get(pid, 0)
                if isinstance(qty, bool) or not isinstance(qty, int) or not (1 <= qty <= room):
                    fields[f"items.{n}"] = f"You can return at most {room} of this item."
                    continue
                items.append({"product_id": pid, "name": line["name"], "quantity": qty,
                              "unit_price_paise": line["unit_price_paise"], "line_amount_paise": line["unit_price_paise"] * qty})
        if fields:
            raise ServiceError("validation_error", "Some fields are invalid.", 400, fields)
        now = self.clock()
        doc = {"_id": uuid.uuid4().hex, "order_id": order["_id"], "order_number": order["order_number"], "user_id": user_id,
               "status": "requested", "reason": reason, "details": details.strip(), "items": items,
               "amount_paise": sum(i["line_amount_paise"] for i in items), "created_at": now, "updated_at": now}
        try:
            self.returns.insert(doc)
        except DuplicateError as exc:
            raise ServiceError("return_open", "You already have a return request waiting for review on this order.", 409) from exc
        return public_return(doc)

    def customer_returns(self, user_id: str, order_id: str) -> dict:
        order = self.order_service._own(user_id, order_id)
        refunds = self.refunds.refunds.list_for_order(order["_id"])
        return {"returns": [public_return(r, refunds) for r in self.returns.list_for_order(order["_id"])],
                "refunds": [public_refund(r) for r in refunds]}

    # ---- returns (staff) -----------------------------------------------------
    def staff_returns(self, role: str, status="requested") -> dict:
        if role not in rules.RETURN_DECISION_ROLES:
            raise _forbidden()
        status = status if status in ("requested", "approved", "rejected") else "requested"
        rows = self.returns.list_by_status(status, 100)
        return {"results": [public_return(r, self.refunds.refunds.list_for_order(r["order_id"])) for r in rows]}

    def decide_return(self, actor_id: str, role: str, return_id: str, data: dict) -> dict:
        if role not in rules.RETURN_DECISION_ROLES:
            raise _forbidden()
        decision, note = data.get("decision"), data.get("note", "")
        note = note.strip() if isinstance(note, str) else None
        errors = {}
        if decision not in ("approve", "reject"):
            errors["decision"] = "Must be approve or reject."
        if note is None or len(note) > rules.MAX_RETURN_DETAILS or (decision == "reject" and len(note) < 5):
            errors["note"] = "Give a reason of 5 to 500 characters." if decision == "reject" else "Note is too long."
        if errors:
            raise ServiceError("validation_error", "Some fields are invalid.", 400, errors)
        ret = self.returns.get(return_id) if isinstance(return_id, str) else None
        if not ret:
            raise ServiceError("not_found", "Return not found.", 404)
        now = self.clock()
        to = "approved" if decision == "approve" else "rejected"
        if not self.returns.decide(ret["_id"], to, {"decision": {"by": actor_id, "role": role, "note": note, "at": now}}, now):
            raise ServiceError("already_decided", "This return was already decided.", 409)
        refunds = []
        if to == "approved":
            order = self.orders.get(ret["order_id"])
            # Money only. The returned medicine is NOT restocked and prescription units are NOT restored.
            refunds = [self.refunds.issue(order, ret["amount_paise"], rules.REFUND_RETURN, ret["_id"], "approved return")]
        return public_return(self.returns.get(ret["_id"]), refunds)

    # ---- refunds (staff) -----------------------------------------------------
    def failed_refunds(self, role: str) -> dict:
        if role not in rules.FULFILMENT_ROLES:
            raise _forbidden()
        return {"results": [public_refund(r) for r in self.refunds.refunds.list_by_status("failed", 100)]}

    def retry_refund(self, role: str, refund_id: str) -> dict:
        if role not in rules.FULFILMENT_ROLES:
            raise _forbidden()
        return public_refund(self.refunds.retry(refund_id))
