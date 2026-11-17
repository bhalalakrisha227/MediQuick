"""
The "needs a human" queue and the audit log. No Django / MongoDB imports.

The system flags problems it must not fix by itself (money or stock that may be wrong) and, until now, nobody could see
them. This lists them in one place. The ONLY action here is to record that a person looked and handled it
elsewhere (clearing an order's needs_attention flag, with a note). Nothing here moves money or stock.
"""
import uuid

from apps.accounts.errors import ServiceError

from . import rules

FLAG_TEXT = {
    "restock_failed": "A cancelled order's stock could not be put back automatically. Check the batch quantities by hand.",
    "payment_mismatch": "A payment did not match this order (amount, currency or order). Money may have been taken without the order being confirmed. Check the payment dashboard.",
    "duplicate_payment": "More than one payment arrived for this order. Refund the extra payment in the payment dashboard.",
}
KIND_TEXT = {
    "payment_review": "Payment was received but the order could not be finished automatically. There is no in-app resolution yet: check stock and the payment dashboard, then handle it by hand.",
    "delivery_failed": "Delivery failed repeatedly. Choose redeliver or refund on the Fulfilment page.",
    "failed_refund": "A refund failed. Retry it on the Fulfilment page.",
}


def _forbidden():
    return ServiceError("forbidden", "You do not have permission to perform this action.", 403)


class AuditLog:
    def __init__(self, repo, clock):
        self.repo, self.clock = repo, clock

    def record(self, actor_id, actor_role, action, target_type, target_id, details=None):
        self.repo.insert({"_id": uuid.uuid4().hex, "at": self.clock(), "actor_id": actor_id, "actor_role": actor_role,
                          "action": action, "target_type": target_type, "target_id": target_id, "details": details or {}})

    def recent(self, role: str, page=1) -> dict:
        if role not in rules.USER_ADMIN_ROLES:
            raise _forbidden()
        page = page if isinstance(page, int) and page >= 1 else 1
        rows, total = self.repo.list_recent((page - 1) * rules.AUDIT_PAGE_SIZE, rules.AUDIT_PAGE_SIZE)
        return {"results": [{**{k: r[k] for k in ("action", "actor_id", "actor_role", "target_type", "target_id", "details")},
                             "id": r["_id"], "at": r["at"].isoformat()} for r in rows], "page": page, "total": total}


class AttentionService:
    def __init__(self, orders, refunds, audit: AuditLog, clock):
        self.orders, self.refunds, self.audit, self.clock = orders, refunds, audit, clock

    def _items(self) -> list[dict]:
        items = []
        for o in self.orders.list_needing_attention(100):
            flag = o["needs_attention"]
            reason, _, ref = flag.partition(":")
            items.append({"kind": "needs_attention", "flag": flag, "order_id": o["_id"], "order_number": o["order_number"],
                          "status": o["status"], "reference": ref or None,
                          "detail": FLAG_TEXT.get(reason, "A problem was flagged on this order."), "since": o["updated_at"], "resolvable": True})
        for kind, statuses in (("payment_review", ("payment_review",)), ("delivery_failed", ("delivery_failed",))):
            for o in self.orders.list_by_status(statuses, 100):
                items.append({"kind": kind, "flag": None, "order_id": o["_id"], "order_number": o["order_number"], "status": o["status"],
                              "reference": None, "detail": KIND_TEXT[kind], "since": o["updated_at"], "resolvable": False})
        for r in self.refunds.list_by_status("failed", 100):
            items.append({"kind": "failed_refund", "flag": None, "order_id": r["order_id"], "order_number": None, "status": "failed",
                          "reference": r["_id"], "detail": f"{KIND_TEXT['failed_refund']} ({r.get('message') or 'no message'})",
                          "since": r["updated_at"], "resolvable": False})
        items.sort(key=lambda i: i["since"])
        return items

    def counts(self) -> dict:
        out = {}
        for i in self._items():
            out[i["kind"]] = out.get(i["kind"], 0) + 1
        return out

    def list(self, role: str) -> dict:
        if role not in rules.ATTENTION_ROLES:
            raise _forbidden()
        return {"results": [{**i, "since": i["since"].isoformat()} for i in self._items()]}

    def resolve(self, actor_id: str, role: str, order_id, flag, note) -> dict:
        if role not in rules.ATTENTION_ROLES:
            raise _forbidden()
        note = note.strip() if isinstance(note, str) else ""
        if not rules.MIN_NOTE <= len(note) <= rules.MAX_NOTE:
            raise ServiceError("validation_error", "Write what you checked or did (5 to 500 characters).", 400, {"note": "Required."})
        if not isinstance(flag, str) or not flag:
            raise ServiceError("validation_error", "Missing flag.", 400, {"flag": "Required."})
        order = self.orders.get(order_id) if isinstance(order_id, str) else None
        if not order:
            raise ServiceError("not_found", "Order not found.", 404)
        if not self.orders.clear_attention(order["_id"], flag):
            raise ServiceError("already_resolved", "That flag is no longer on this order.", 409)
        self.audit.record(actor_id, role, "attention_resolved", "order", order["_id"], {"flag": flag, "note": note})
        return {"order_id": order["_id"], "resolved": flag}
