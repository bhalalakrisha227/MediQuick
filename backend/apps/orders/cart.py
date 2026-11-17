"""Server-side cart. No Django / MongoDB imports. A cart never reserves stock; checkout does."""
from datetime import datetime, timezone

from apps.accounts.errors import ServiceError

from . import rules, validators


def _now() -> datetime:
    return datetime.now(timezone.utc)


PROBLEM_MESSAGES = {
    "unavailable": ("not_found", "This product is no longer available.", 404),
    "prescription_required": ("prescription_required",
                              "This medicine needs a pharmacist-approved prescription. Upload your prescription first.", 400),
    "exceeds_prescription": ("exceeds_prescription",
                             "Your approved prescription covers fewer units of this medicine than you chose.", 400),
    "not_purchasable": ("not_purchasable", "This product is not available for online ordering.", 400),
}


class CartService:
    def __init__(self, carts, products, stock, clock=_now, allowances=None):
        self.carts, self.products, self.stock, self.clock = carts, products, stock, clock
        self.allowances = allowances   # approved-prescription allowances; None = prescription medicines stay blocked

    def _rx_remaining(self, user_id: str, products) -> dict:
        ids = [p["_id"] for p in products if p and p.get("requires_prescription")]
        return self.allowances.remaining(user_id, ids) if (self.allowances and ids) else {}

    def _items(self, user_id: str) -> list[dict]:
        doc = self.carts.get(user_id)
        return [dict(i) for i in doc["items"]] if doc else []

    def _save(self, user_id: str, items: list[dict]) -> None:
        self.carts.save(user_id, items, self.clock())

    # -- reading ---------------------------------------------------------------
    def view(self, user_id: str) -> dict:
        items = self._items(user_id)
        products = self.products.get_many([i["product_id"] for i in items])
        units = self.stock.sellable_units(list(products))
        rx = self._rx_remaining(user_id, products.values())
        lines, subtotal = [], 0
        for item in items:
            p = products.get(item["product_id"])
            problem = rules.line_problem(p, rx.get(item["product_id"], 0), item["quantity"])
            if p is None:
                lines.append({"product_id": item["product_id"], "name": "Unavailable item", "slug": "", "pack_size": "",
                              "unit_price_paise": 0, "mrp_paise": 0, "quantity": item["quantity"],
                              "line_total_paise": 0, "problem": problem, "available_units": None})
                continue
            available = units.get(p["_id"], 0)
            if problem is None and item["quantity"] > available:
                problem = "insufficient_stock"
            total = p["price_paise"] * item["quantity"]
            if problem is None:
                subtotal += total
            lines.append({
                "product_id": p["_id"], "slug": p["slug"], "name": p["name"], "pack_size": p.get("pack_size", ""),
                "unit_price_paise": p["price_paise"], "mrp_paise": p["mrp_paise"], "quantity": item["quantity"],
                "line_total_paise": total, "problem": problem,
                "available_units": available if problem == "insufficient_stock" else None,
            })
        return {
            "items": lines, "item_count": sum(i["quantity"] for i in items),
            "subtotal_paise": subtotal, "delivery_fee_paise": rules.delivery_fee(subtotal),
            "total_paise": subtotal + rules.delivery_fee(subtotal),
            "can_checkout": bool(lines) and all(l["problem"] is None for l in lines),
        }

    # -- changing --------------------------------------------------------------
    def _check_product(self, user_id: str, product_id: str, quantity: int) -> dict:
        product = self.products.get(product_id)
        rx = self._rx_remaining(user_id, [product]) if product else {}
        problem = rules.line_problem(product, rx.get(product_id, 0), quantity)
        if problem:
            code, message, status = PROBLEM_MESSAGES[problem]
            raise ServiceError(code, message, status)
        return product

    def _check_stock(self, product_id: str, quantity: int) -> None:
        available = self.stock.sellable_units([product_id]).get(product_id, 0)
        if quantity > available:
            raise ServiceError("insufficient_stock",
                               f"Only {available} available." if available else "Currently out of stock.", 409,
                               {"quantity": f"Only {available} available." if available else "Out of stock."})

    def add(self, user_id: str, data: dict) -> dict:
        cleaned = validators.validate_item(data)
        pid = cleaned["product_id"]
        items = self._items(user_id)
        existing = next((i for i in items if i["product_id"] == pid), None)
        new_qty = (existing["quantity"] if existing else 0) + cleaned["quantity"]
        self._check_product(user_id, pid, new_qty)
        if new_qty > rules.MAX_LINE_QUANTITY:
            raise ServiceError("validation_error", f"You can order at most {rules.MAX_LINE_QUANTITY} of one product.", 400,
                               {"quantity": f"At most {rules.MAX_LINE_QUANTITY} per product."})
        if not existing and len(items) >= rules.MAX_CART_LINES:
            raise ServiceError("cart_full", f"Your cart can hold at most {rules.MAX_CART_LINES} different products.", 400)
        self._check_stock(pid, new_qty)
        if existing:
            existing["quantity"] = new_qty
        else:
            items.append({"product_id": pid, "quantity": new_qty})
        self._save(user_id, items)
        return self.view(user_id)

    def set_quantity(self, user_id: str, product_id: str, data: dict) -> dict:
        quantity = validators.validate_quantity_update(data)
        items = self._items(user_id)
        line = next((i for i in items if i["product_id"] == product_id), None)
        if line is None:
            raise ServiceError("not_found", "That product is not in your cart.", 404)
        if quantity == 0:
            items.remove(line)
        else:
            self._check_product(user_id, product_id, quantity)
            self._check_stock(product_id, quantity)
            line["quantity"] = quantity
        self._save(user_id, items)
        return self.view(user_id)

    def remove(self, user_id: str, product_id: str) -> dict:
        items = [i for i in self._items(user_id) if i["product_id"] != product_id]
        self._save(user_id, items)
        return self.view(user_id)

    def clear(self, user_id: str) -> dict:
        self._save(user_id, [])
        return self.view(user_id)
