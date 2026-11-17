"""
Refunds. No Django / MongoDB imports.

Safety design:
 * One refund per (order, kind, source) - an idempotency key with a unique index - so retrying a
   request can never create a second refund.
 * The amount is first added to the order's refunded_paise counter by ONE atomic conditional
   update that refuses to pass the amount paid. Money can therefore never be refunded twice
   over, even with simultaneous requests.
 * If the payment provider fails, the counter is put back and the refund is marked 'failed'
   (kept, visible to staff, retryable once at a time). A failed refund never silently disappears.
 * The mock adapter moves no real money. Real gateway refunds arrive with Phase 8.
"""
import logging
import uuid

from apps.accounts.errors import DuplicateError, ServiceError

logger = logging.getLogger(__name__)


def public_refund(r: dict) -> dict:
    return {"id": r["_id"], "order_id": r["order_id"], "kind": r["kind"], "amount_paise": r["amount_paise"],
            "status": r["status"], "reference": r.get("reference"), "message": r.get("message", ""),
            "created_at": r["created_at"].isoformat()}


class RefundService:
    def __init__(self, refunds, orders, payments, clock):
        self.refunds, self.orders, self.payments, self.clock = refunds, orders, payments, clock

    def issue(self, order: dict, amount_paise: int, kind: str, source_id: str, reason: str, options=None) -> dict:
        """Creates and attempts a refund. Returns the refund doc (status succeeded / failed)."""
        if isinstance(amount_paise, bool) or not isinstance(amount_paise, int) or amount_paise < 1:
            raise ServiceError("invalid_refund", "Refund amount must be positive.", 400)
        key = f"{order['_id']}:{kind}:{source_id}"
        now = self.clock()
        doc = {"_id": uuid.uuid4().hex, "key": key, "order_id": order["_id"], "user_id": order["user_id"], "kind": kind,
               "source_id": source_id, "amount_paise": amount_paise, "reason": reason, "status": "pending",
               "reference": None, "message": "", "attempts": 1, "created_at": now, "updated_at": now}
        try:
            self.refunds.insert(doc)
        except DuplicateError:
            return self.refunds.get_by_key(key)      # already created: never a second refund
        return self._attempt(order, doc, options or {})

    def retry(self, refund_id: str, options=None) -> dict:
        refund = self.refunds.get(refund_id) if isinstance(refund_id, str) else None
        if not refund:
            raise ServiceError("not_found", "Refund not found.", 404)
        if not self.refunds.claim_retry(refund_id, self.clock()):
            raise ServiceError("not_retryable", "Only a failed refund can be retried.", 409)
        order = self.orders.get(refund["order_id"])
        return self._attempt(order, self.refunds.get(refund_id), options or {})

    def _attempt(self, order: dict, refund: dict, options: dict) -> dict:
        amount = refund["amount_paise"]
        if not self.orders.reserve_refund(order["_id"], amount):
            self.refunds.finish(refund["_id"], "failed", {"message": "Refund would exceed the amount paid."}, self.clock())
            logger.error("Refund %s refused: would exceed amount paid on order %s", refund["_id"], order["_id"])
            return self.refunds.get(refund["_id"])
        try:
            result = self.payments.refund(order, amount, refund["key"], options)
        except Exception:
            logger.exception("Refund provider error for %s", refund["_id"])
            result = None
        if result is not None and result.success:
            self.refunds.finish(refund["_id"], "succeeded", {"reference": result.reference, "message": ""}, self.clock())
        else:
            self.orders.release_refund(order["_id"], amount)
            self.refunds.finish(refund["_id"], "failed",
                                {"message": (result.message if result else "The payment provider could not be reached.")},
                                self.clock())
        return self.refunds.get(refund["_id"])

    def gateway_refund_failed(self, reference: str) -> bool:
        """The gateway said a refund we thought succeeded has failed: reopen it for staff and free the counter."""
        refund = self.refunds.get_by_reference(reference)
        if not refund:
            return False
        if not self.refunds.fail_after_success(refund["_id"], "The gateway reported this refund as failed.", self.clock()):
            return False
        self.orders.release_refund(refund["order_id"], refund["amount_paise"])
        return True
