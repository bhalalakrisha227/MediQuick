"""Pure query builders (no pymongo import) so they are unit-testable anywhere."""
from datetime import datetime, timedelta

BATCH_STATES = ("all", "expired", "expiring", "in_stock")


def build_batch_query(f: dict, today_dt: datetime, warning_days: int) -> dict:
    query: dict = {}
    if f.get("product_id"):
        query["product_id"] = f["product_id"]
    if f.get("status"):
        query["status"] = f["status"]
    state = f.get("state", "all")
    if state == "expired":
        query["expiry_date"] = {"$lt": today_dt}
        query["quantity_on_hand"] = {"$gt": 0}
    elif state == "expiring":
        query["expiry_date"] = {"$gte": today_dt, "$lte": today_dt + timedelta(days=warning_days)}
        query["quantity_on_hand"] = {"$gt": 0}
    elif state == "in_stock":
        query["quantity_on_hand"] = {"$gt": 0}
    return query


def sellable_match(product_ids: list, cutoff_dt: datetime) -> dict:
    """Batches that may be sold: active, enough shelf life, and units not reserved."""
    return {
        "product_id": {"$in": list(product_ids)},
        "status": "active",
        "expiry_date": {"$gte": cutoff_dt},
        "$expr": {"$gt": ["$quantity_on_hand", "$quantity_reserved"]},
    }
