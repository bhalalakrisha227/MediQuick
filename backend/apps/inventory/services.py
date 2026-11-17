"""
Inventory business logic (no Django / MongoDB imports; tested with fakes).

Money-critical invariant: for every batch, quantity_on_hand always equals the sum
of that batch's ledger deltas. Stock only changes through repository.adjust_on_hand,
which is a single atomic conditional update, and every change writes a ledger row.
"""
import uuid
from datetime import date, datetime, timezone

from apps.accounts.errors import DuplicateError, ServiceError

from . import rules, validators


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _dt(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def public_batch(b: dict, today: date, product: dict | None = None) -> dict:
    expiry = b["expiry_date"].date()
    available = b["quantity_on_hand"] - b["quantity_reserved"]
    return {
        "id": b["_id"], "product_id": b["product_id"],
        "product_name": product["name"] if product else None,
        "product_slug": product["slug"] if product else None,
        "batch_number": b["batch_number"],
        "expiry_date": expiry.isoformat(),
        "mfg_date": b["mfg_date"].date().isoformat() if b.get("mfg_date") else None,
        "supplier": b.get("supplier", ""),
        "quantity_received": b["quantity_received"],
        "quantity_on_hand": b["quantity_on_hand"],
        "quantity_reserved": b["quantity_reserved"],
        "quantity_available": available,
        "status": b["status"],
        "days_to_expiry": (expiry - today).days,
        "is_expired": expiry < today,
        "is_sellable": b["status"] == "active" and expiry >= rules.sellable_cutoff(today) and available > 0,
        "is_demo": bool(b.get("is_demo")),
    }


def public_movement(m: dict) -> dict:
    return {"id": m["_id"], "type": m["type"], "delta": m["delta"], "quantity_after": m["quantity_after"],
            "reason": m.get("reason", ""), "note": m.get("note", ""), "actor_id": m["actor_id"],
            "created_at": m["created_at"].isoformat()}


class AvailabilityService:
    """Customer-facing availability. Never exposes exact stock counts."""

    def __init__(self, batches, today=_today):
        self.batches, self.today = batches, today

    def for_products(self, product_ids: list[str]) -> dict:
        ids = list({i for i in product_ids})
        if not ids:
            return {}
        summary = self.batches.sellable_summary(ids, _dt(rules.sellable_cutoff(self.today())))
        out = {}
        for pid in ids:
            row = summary.get(pid)
            units = row["sellable"] if row else 0
            out[pid] = {
                "status": rules.availability_status(units),
                "earliest_expiry": row["earliest_expiry"].date().isoformat() if row and units > 0 else None,
            }
        return out


class InventoryService:
    def __init__(self, batches, movements, products, clock=_now, today=_today):
        self.batches, self.movements, self.products = batches, movements, products
        self.clock, self.today = clock, today

    def _batch_or_404(self, batch_id: str) -> dict:
        batch = self.batches.get(batch_id) if isinstance(batch_id, str) else None
        if batch is None:
            raise ServiceError("not_found", "Batch not found.", 404)
        return batch

    def _ledger(self, batch, actor, type_, delta, after, reason="", note=""):
        self.movements.insert({
            "_id": uuid.uuid4().hex, "batch_id": batch["_id"], "product_id": batch["product_id"],
            "type": type_, "delta": delta, "quantity_after": after, "reason": reason, "note": note,
            "actor_id": actor["id"], "created_at": self.clock(),
        })

    # -- writes ----------------------------------------------------------------
    def receive(self, actor: dict, data: dict) -> dict:
        today = self.today()
        cleaned = validators.validate_receive(data, today)
        product = self.products.get(cleaned["product_id"])
        if product is None:
            raise ServiceError("validation_error", "Unknown product.", 400, {"product_id": "Product does not exist."})
        now = self.clock()
        doc = {
            "_id": uuid.uuid4().hex, "product_id": product["_id"], "batch_number": cleaned["batch_number"],
            "expiry_date": _dt(cleaned["expiry_date"]),
            "mfg_date": _dt(cleaned["mfg_date"]) if cleaned["mfg_date"] else None,
            "supplier": cleaned["supplier"], "quantity_received": cleaned["quantity"],
            "quantity_on_hand": cleaned["quantity"], "quantity_reserved": 0,
            "status": "active", "received_by": actor["id"], "created_at": now, "updated_at": now,
        }
        try:
            self.batches.insert(doc)
        except DuplicateError:
            raise ServiceError("conflict", "This batch number already exists for this product.", 409)
        self._ledger(doc, actor, "receipt", cleaned["quantity"], cleaned["quantity"], reason="received")
        return public_batch(doc, today, product)

    def adjust(self, actor: dict, batch_id: str, data: dict) -> dict:
        batch = self._batch_or_404(batch_id)
        cleaned = validators.validate_adjustment(data)
        new_qty = self.batches.adjust_on_hand(batch["_id"], cleaned["delta"])
        if new_qty is None:
            raise ServiceError("insufficient_stock",
                               "This change would take stock below zero or below the reserved quantity.", 409)
        self._ledger(batch, actor, "adjustment", cleaned["delta"], new_qty, cleaned["reason"], cleaned["note"])
        return public_batch(self.batches.get(batch["_id"]), self.today(), self.products.get(batch["product_id"]))

    def set_status(self, actor: dict, batch_id: str, data: dict) -> dict:
        batch = self._batch_or_404(batch_id)
        cleaned = validators.validate_status_change(data)
        new, old = cleaned["status"], batch["status"]
        if new == old:
            raise ServiceError("validation_error", f"Batch is already {old}.", 400)
        if "recalled" in (new, old) and actor["role"] not in rules.RECALL_ROLES:
            raise ServiceError("forbidden", "Only a pharmacy manager or admin can recall or un-recall a batch.", 403)
        self.batches.set_status(batch["_id"], new, self.clock())
        self._ledger(batch, actor, "status_change", 0, batch["quantity_on_hand"], f"{old}->{new}", cleaned["note"])
        return public_batch(self.batches.get(batch["_id"]), self.today(), self.products.get(batch["product_id"]))

    # -- reads -----------------------------------------------------------------
    def list_batches(self, params: dict) -> dict:
        f = validators.validate_batch_listing(params)
        today = self.today()
        items, total = self.batches.list(f, _dt(today), rules.EXPIRY_WARNING_DAYS,
                                         (f["page"] - 1) * f["page_size"], f["page_size"])
        products = self.products.get_many([b["product_id"] for b in items])
        return {"results": [public_batch(b, today, products.get(b["product_id"])) for b in items],
                "page": f["page"], "page_size": f["page_size"], "total": total,
                "total_pages": max(1, -(-total // f["page_size"]))}

    def list_movements(self, batch_id: str) -> list[dict]:
        batch = self._batch_or_404(batch_id)
        return [public_movement(m) for m in self.movements.list_for_batch(batch["_id"], 200)]

    def overview(self) -> dict:
        today = self.today()
        base = {"page": 1, "page_size": 50}
        expired, _ = self.batches.list({**base, "state": "expired"}, _dt(today), rules.EXPIRY_WARNING_DAYS, 0, 50)
        expiring, _ = self.batches.list({**base, "state": "expiring"}, _dt(today), rules.EXPIRY_WARNING_DAYS, 0, 50)
        products = self.products.list_active(500)
        summary = self.batches.sellable_summary([p["_id"] for p in products], _dt(rules.sellable_cutoff(today)))
        low = []
        for p in products:
            units = summary.get(p["_id"], {}).get("sellable", 0)
            if units <= rules.LOW_STOCK_THRESHOLD:
                low.append({"product_id": p["_id"], "name": p["name"], "slug": p["slug"],
                            "sellable_units": units, "status": rules.availability_status(units)})
        low.sort(key=lambda r: (r["sellable_units"], r["name"]))
        lookup = self.products.get_many([b["product_id"] for b in expired + expiring])
        return {
            "thresholds": {"low_stock": rules.LOW_STOCK_THRESHOLD, "expiry_warning_days": rules.EXPIRY_WARNING_DAYS,
                           "min_sellable_shelf_life_days": rules.MIN_SELLABLE_SHELF_LIFE_DAYS},
            "expired_with_stock": [public_batch(b, today, lookup.get(b["product_id"])) for b in expired],
            "expiring_soon": [public_batch(b, today, lookup.get(b["product_id"])) for b in expiring],
            "low_stock": low[:50],
        }
