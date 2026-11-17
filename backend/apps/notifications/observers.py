"""
Repository wrappers that turn state changes into notifications. No Django / MongoDB imports.

Every status change in the system already goes through ONE atomic compare-and-set call on a repository. Wrapping that
call means a notification is created exactly when (and only when) the change really happened, from any code path
(mock payment, gateway webhook, reconcile, delivery partner, staff), without editing each service. A failure here is
logged and swallowed: it can never undo or block the real action.
"""
import logging

from apps.orders import rules as order_rules
from apps.prescriptions import rules as rx_rules

logger = logging.getLogger(__name__)


class _Wrapper:
    def __init__(self, repo, service):
        self._repo, self._svc = repo, service

    def __getattr__(self, name):
        return getattr(self._repo, name)

    def _safe(self, fn, *args):
        try:
            fn(*args)
        except Exception:
            logger.exception("Notification hook failed")


class NotifyingOrders(_Wrapper):
    def transition(self, order_id, from_status, to_status, fields, note, now):
        ok = self._repo.transition(order_id, from_status, to_status, fields, note, now)
        if ok and from_status != to_status:
            self._safe(self._changed, order_id, from_status, to_status)
        return ok

    def _changed(self, order_id, old, new):
        event = None
        if new == order_rules.CONFIRMED and old in (order_rules.PROCESSING, order_rules.CONFIRMING):
            event = "order_confirmed"
        elif new == order_rules.DISPATCHED:
            event = "order_dispatched"
        elif new == order_rules.DELIVERED:
            event = "order_delivered"
        elif new == order_rules.DELIVERY_FAILED:
            event = "order_delivery_failed"
        elif new == order_rules.PAYMENT_REVIEW:
            event = "order_payment_review"
        elif new == order_rules.CANCELLED and old != order_rules.PENDING:   # an unpaid order the customer cancelled themselves needs no message
            event = "order_cancelled"
        if event:
            o = self._repo.get(order_id)
            self._svc.emit(event, o["user_id"], o["_id"], f"/orders/{o['_id']}", len(o["status_history"]), o["order_number"])


class NotifyingRefunds(_Wrapper):
    def __init__(self, repo, service, orders):
        super().__init__(repo, service)
        self._orders = orders

    def finish(self, refund_id, status, fields, now):
        result = self._repo.finish(refund_id, status, fields, now)
        if status == "succeeded":
            self._safe(self._done, refund_id)
        return result

    def _done(self, refund_id):
        r = self._repo.get(refund_id)
        o = self._orders.get(r["order_id"])
        self._svc.emit("refund_succeeded", r["user_id"], r["_id"], f"/orders/{o['_id']}", 0, o["order_number"], r["amount_paise"])


class NotifyingReturns(_Wrapper):
    def decide(self, return_id, to_status, fields, now):
        ok = self._repo.decide(return_id, to_status, fields, now)
        if ok:
            self._safe(self._done, return_id, to_status)
        return ok

    def _done(self, return_id, to_status):
        r = self._repo.get(return_id)
        event = "return_approved" if to_status == "approved" else "return_rejected"
        self._svc.emit(event, r["user_id"], r["_id"], f"/orders/{r['order_id']}", 0, r["order_number"])


class NotifyingPrescriptions(_Wrapper):
    EVENTS = {rx_rules.APPROVED: "prescription_approved", rx_rules.REJECTED: "prescription_rejected",
              rx_rules.CLARIFICATION: "prescription_clarification"}

    def staff_transition(self, prescription_id, from_status, to_status, fields, note, now, assignee_id=None, unset=None):
        ok = self._repo.staff_transition(prescription_id, from_status, to_status, fields, note, now, assignee_id, unset)
        if ok and to_status in self.EVENTS:
            self._safe(self._done, prescription_id, to_status)
        return ok

    def _done(self, prescription_id, to_status):
        p = self._repo.get(prescription_id)
        self._svc.emit(self.EVENTS[to_status], p["user_id"], p["_id"], f"/prescriptions/{p['_id']}", len(p["status_history"]))
