"""Catalogue business logic. No Django or MongoDB imports (testable with fakes)."""
import uuid
from datetime import datetime, timezone

from . import rules, validators
from .errors import DuplicateError, ServiceError


def _now():
    return datetime.now(timezone.utc)


def public_category(c: dict) -> dict:
    return {"id": c["_id"], "slug": c["slug"], "name": c["name"],
            "description": c.get("description", ""), "sort_order": c.get("sort_order", 0)}


def public_product(p: dict, availability: dict | None = None) -> dict:
    price, mrp = p["price_paise"], p["mrp_paise"]
    return {
        "id": p["_id"], "slug": p["slug"], "name": p["name"],
        "generic_name": p.get("generic_name", ""), "brand": p.get("brand", ""),
        "manufacturer": p.get("manufacturer", ""), "category": p["category"],
        "description": p.get("description", ""), "pack_size": p.get("pack_size", ""),
        "storage_info": p.get("storage_info", ""), "tags": p.get("tags", []),
        "price_paise": price, "mrp_paise": mrp,
        "discount_percent": round((mrp - price) * 100 / mrp) if mrp > price else 0,
        "schedule": p["schedule"],
        "requires_prescription": p["requires_prescription"],
        "purchasable_online": rules.purchasable_online(p["schedule"]),
        "is_demo": bool(p.get("is_demo")),
        # {"status": in_stock|low_stock|out_of_stock, "earliest_expiry": date|None} from
        # inventory batches. null means no inventory provider is connected (never a guess).
        "availability": availability,
    }


class CatalogueService:
    def __init__(self, categories, products, clock=_now, availability=None):
        self.categories, self.products, self.clock = categories, products, clock
        self.availability = availability  # object with for_products(ids) -> {id: {...}}, or None

    def _availability_for(self, products: list[dict]) -> dict:
        if self.availability is None or not products:
            return {}
        return self.availability.for_products([p["_id"] for p in products])  # one batched lookup

    # -- public reads ----------------------------------------------------------
    def list_categories(self) -> list[dict]:
        return [public_category(c) for c in self.categories.list_active()]

    def list_products(self, params: dict) -> dict:
        f = validators.validate_listing_params(params)
        skip = (f["page"] - 1) * f["page_size"]
        items, total = self.products.search(f, f["sort"], skip, f["page_size"])
        avail = self._availability_for(items)
        return {
            "results": [public_product(p, avail.get(p["_id"])) for p in items],
            "page": f["page"], "page_size": f["page_size"], "total": total,
            "total_pages": max(1, -(-total // f["page_size"])),
        }

    def get_product(self, slug: str) -> dict:
        product = self.products.get_by_slug(slug) if isinstance(slug, str) else None
        if product is None or not product.get("is_active"):
            raise ServiceError("not_found", "Product not found.", 404)
        return public_product(product, self._availability_for([product]).get(product["_id"]))

    # -- manager/admin writes --------------------------------------------------
    def _unique_slug(self, repo, base: str) -> str:
        slug, n = base or "item", 1
        while repo.get_by_slug(slug) is not None:
            n += 1
            slug = f"{base}-{n}"
            if n > 50:
                raise ServiceError("conflict", "Could not generate a unique slug.", 409)
        return slug

    def create_category(self, data: dict) -> dict:
        cleaned = validators.validate_category(data)
        now = self.clock()
        doc = {"_id": uuid.uuid4().hex, **cleaned, "is_active": True, "created_at": now,
               "slug": self._unique_slug(self.categories, validators.slugify(cleaned["name"]))}
        try:
            self.categories.insert(doc)
        except DuplicateError:
            raise ServiceError("conflict", "A category with this name already exists.", 409)
        return public_category(doc)

    def _require_category(self, slug: str) -> None:
        if self.categories.get_by_slug(slug) is None:
            raise ServiceError("validation_error", "Unknown category.", 400, {"category": "Category does not exist."})

    def create_product(self, data: dict, *, is_demo: bool = False) -> dict:
        cleaned = validators.validate_product(data)
        self._require_category(cleaned["category"])
        now = self.clock()
        doc = {
            "_id": uuid.uuid4().hex, **cleaned,
            "slug": self._unique_slug(self.products, validators.slugify(f"{cleaned['name']} {cleaned['pack_size']}")),
            "name_lower": cleaned["name"].lower(),
            "requires_prescription": rules.requires_prescription(cleaned["schedule"]),
            "is_active": True, "is_demo": is_demo, "created_at": now, "updated_at": now,
        }
        try:
            self.products.insert(doc)
        except DuplicateError:
            raise ServiceError("conflict", "A product with this slug already exists.", 409)
        return public_product(doc)

    def update_product(self, product_id: str, data: dict) -> dict:
        existing = self.products.get(product_id)
        if existing is None:
            raise ServiceError("not_found", "Product not found.", 404)
        cleaned = validators.validate_product(data, partial=True)
        if not cleaned:
            raise ServiceError("validation_error", "Nothing to update.", 400)
        if "category" in cleaned:
            self._require_category(cleaned["category"])
        merged_price = cleaned.get("price_paise", existing["price_paise"])
        merged_mrp = cleaned.get("mrp_paise", existing["mrp_paise"])
        if merged_price > merged_mrp:
            raise ServiceError("validation_error", "Price cannot be higher than MRP.", 400,
                               {"price_paise": "Price cannot be higher than MRP."})
        if "name" in cleaned:
            cleaned["name_lower"] = cleaned["name"].lower()
        if "schedule" in cleaned:
            cleaned["requires_prescription"] = rules.requires_prescription(cleaned["schedule"])
        self.products.update(product_id, {**cleaned, "updated_at": self.clock()})
        return public_product(self.products.get(product_id))

    def deactivate_product(self, product_id: str) -> None:
        if self.products.get(product_id) is None:
            raise ServiceError("not_found", "Product not found.", 404)
        self.products.update(product_id, {"is_active": False, "updated_at": self.clock()})
