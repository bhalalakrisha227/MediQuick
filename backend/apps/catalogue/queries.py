"""Pure query helpers (no pymongo import) so they can be unit tested anywhere."""
import re

SORTS = {
    "name": [("name_lower", 1)],
    "price_asc": [("price_paise", 1), ("name_lower", 1)],
    "price_desc": [("price_paise", -1), ("name_lower", 1)],
    "newest": [("created_at", -1), ("name_lower", 1)],
}
SEARCH_FIELDS = ("name", "generic_name", "brand")


def build_query(f: dict) -> dict:
    """f is the already-validated filter dict from CatalogueService."""
    query: dict = {"is_active": True}
    if f.get("category"):
        query["category"] = f["category"]
    if f.get("rx") == "otc":
        query["requires_prescription"] = False
    elif f.get("rx") == "prescription":
        query["requires_prescription"] = True
    price = {}
    if f.get("min_price") is not None:
        price["$gte"] = f["min_price"]
    if f.get("max_price") is not None:
        price["$lte"] = f["max_price"]
    if price:
        query["price_paise"] = price
    if f.get("q"):
        pattern = re.escape(f["q"])  # user text is never treated as a regex
        query["$or"] = [{field: {"$regex": pattern, "$options": "i"}} for field in SEARCH_FIELDS]
    return query
