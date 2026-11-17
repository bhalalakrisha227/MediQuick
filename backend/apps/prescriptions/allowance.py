"""
Approved-prescription allowances used by the cart and checkout. No Django / MongoDB imports.

An approved prescription lists exactly which products the pharmacist allowed and how many units
(`remaining`). An Rx line in an order must be covered by ONE prescription. Units are taken
atomically at checkout and given back exactly once if the unpaid order is cancelled or expires.
"""
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AllowanceService:
    def __init__(self, repo, clock=_now):
        self.repo, self.clock = repo, clock

    def remaining(self, user_id: str, product_ids) -> dict:
        """{product_id: most units one single approved prescription can still cover}."""
        wanted = set(product_ids)
        out = {}
        for doc in self.repo.list_approved(user_id, self.clock()):
            for item in doc["approval"]["items"]:
                if item["product_id"] in wanted and item["remaining"] > out.get(item["product_id"], 0):
                    out[item["product_id"]] = item["remaining"]
        return out

    def consume(self, user_id: str, product_id: str, quantity: int):
        """Returns {"prescription_id", "product_id", "quantity"} or None if no prescription covers it."""
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
            return None
        pid = self.repo.consume_allowance(user_id, product_id, quantity, self.clock())
        return {"prescription_id": pid, "product_id": product_id, "quantity": quantity} if pid else None

    def restore(self, consumptions) -> None:
        for c in consumptions or []:
            try:
                self.repo.restore_allowance(c["prescription_id"], c["product_id"], c["quantity"], self.clock())
            except Exception:
                logger.exception("Could not restore prescription allowance %s", c)

    def view(self, user_id: str) -> dict:
        out = []
        for doc in self.repo.list_approved(user_id, self.clock()):
            a = doc["approval"]
            out.append({"prescription_id": doc["_id"], "valid_until": a["valid_until"].isoformat(),
                        "items": [{"product_id": i["product_id"], "name": i["name"], "max_quantity": i["max_quantity"],
                                   "remaining": i["remaining"]} for i in a["items"]]})
        return {"results": out}
