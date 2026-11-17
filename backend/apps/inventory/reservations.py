"""
Stock reservation for orders (no Django / MongoDB imports; tested with fakes).

Flow: reserve (hold units, earliest expiry first) -> either commit (payment succeeded:
units leave on-hand stock and a 'sale' ledger row is written) or release (order
cancelled/expired: units become free again).

Every step is an atomic conditional update in the repository, so concurrent orders
cannot hold or sell the same unit twice.
"""
import logging
import uuid
from datetime import date, datetime, timezone

from . import rules

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _dt(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


class InsufficientStock(Exception):
    def __init__(self, product_id: str, requested: int, available: int):
        super().__init__(f"product {product_id}: wanted {requested}, only {available} available")
        self.product_id, self.requested, self.available = product_id, requested, available


class CommitError(Exception):
    pass


class ReservationService:
    def __init__(self, batches, movements, clock=_now, today=_today):
        self.batches, self.movements, self.clock, self.today = batches, movements, clock, today

    def _cutoff(self) -> datetime:
        return _dt(rules.sellable_cutoff(self.today()))

    def sellable_units(self, product_ids: list[str]) -> dict:
        """Exact sellable units per product. Internal use (cart/checkout), never shown publicly."""
        ids = list(set(product_ids))
        if not ids:
            return {}
        summary = self.batches.sellable_summary(ids, self._cutoff())
        return {pid: summary.get(pid, {}).get("sellable", 0) for pid in ids}

    def reserve_many(self, lines: list[tuple[str, int]]) -> dict:
        """All-or-nothing. Returns {product_id: [allocation, ...]}; raises InsufficientStock after rolling back."""
        held: list[dict] = []
        try:
            return {pid: self._reserve_one(pid, qty, held) for pid, qty in lines}
        except BaseException:
            self.release(held)  # undo everything reserved so far, whatever went wrong
            raise

    def _reserve_one(self, product_id: str, quantity: int, held: list) -> list[dict]:
        remaining, mine = quantity, {}
        for _attempt in range(3):  # a competing order may take units between our read and our reserve
            for batch in self.batches.sellable_batches(product_id, self._cutoff()):
                if remaining == 0:
                    break
                take = min(remaining, batch["quantity_on_hand"] - batch["quantity_reserved"])
                if take <= 0 or not self.batches.reserve(batch["_id"], take):
                    continue
                piece = {"product_id": product_id, "batch_id": batch["_id"], "batch_number": batch["batch_number"],
                         "expiry_date": batch["expiry_date"].date().isoformat(), "quantity": take}
                held.append(piece)
                remaining -= take
                if batch["_id"] in mine:
                    mine[batch["_id"]]["quantity"] += take
                else:
                    mine[batch["_id"]] = dict(piece)
            if remaining == 0:
                return list(mine.values())
        raise InsufficientStock(product_id, quantity, quantity - remaining)

    def release(self, allocations: list[dict]) -> None:
        for a in allocations:
            if not self.batches.release(a["batch_id"], a["quantity"]):
                logger.error("Could not release %s units of batch %s (reservation count out of sync)",
                             a["quantity"], a["batch_id"])

    def allocations_still_valid(self, allocations: list[dict]) -> bool:
        """A held batch must still be active and unexpired (it may have been recalled/quarantined since)."""
        today = self.today()
        for a in allocations:
            batch = self.batches.get(a["batch_id"])
            if batch is None or batch["status"] != "active" or batch["expiry_date"].date() < today:
                return False
        return True

    def restock(self, allocations: list[dict], order_number: str, actor_id: str) -> None:
        """Puts units of a PAID but never-dispatched order back on the shelf, with a ledger row each.

        Only for cancellations before dispatch (the units never left the pharmacy). Returned
        medicines are never restocked by this method.
        """
        for a in allocations:
            new_qty = self.batches.adjust_on_hand(a["batch_id"], a["quantity"])
            if new_qty is None:
                raise CommitError(f"Could not restock {a['quantity']} units of batch {a['batch_id']}")
            self.movements.insert({
                "_id": uuid.uuid4().hex, "batch_id": a["batch_id"], "product_id": a["product_id"],
                "type": "order_cancel_restock", "delta": a["quantity"], "quantity_after": new_qty,
                "reason": order_number, "note": "", "actor_id": actor_id, "created_at": self.clock(),
            })

    def commit(self, allocations: list[dict], order_number: str, actor_id: str) -> None:
        for a in allocations:
            new_qty = self.batches.commit(a["batch_id"], a["quantity"])
            if new_qty is None:
                raise CommitError(f"Could not commit {a['quantity']} units of batch {a['batch_id']}")
            self.movements.insert({
                "_id": uuid.uuid4().hex, "batch_id": a["batch_id"], "product_id": a["product_id"],
                "type": "sale", "delta": -a["quantity"], "quantity_after": new_qty,
                "reason": order_number, "note": "", "actor_id": actor_id, "created_at": self.clock(),
            })
