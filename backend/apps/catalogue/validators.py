import re

from . import rules
from .errors import ValidationFailed
from .queries import SORTS

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_PAGE_SIZE = 50
DEFAULT_PAGE_SIZE = 12
MAX_PRICE_PAISE = 10_000_000  # Rs 1,00,000


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80]


def _text(data, key, errors, *, required=True, min_len=0, max_len=200):
    value = data.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            errors[key] = "This field is required."
        return ""
    if not isinstance(value, str):
        errors[key] = "Must be text."
        return ""
    value = value.strip()
    if not (min_len <= len(value) <= max_len):
        errors[key] = f"Must be between {min_len} and {max_len} characters."
    return value


def _int(data, key, errors, *, required=True, minimum=0, maximum=MAX_PRICE_PAISE):
    value = data.get(key)
    if value is None:
        if required:
            errors[key] = "This field is required."
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not (minimum <= value <= maximum):
        errors[key] = f"Must be a whole number between {minimum} and {maximum}."
        return None
    return value


def validate_category(data: dict, partial: bool = False) -> dict:
    errors, out = {}, {}
    if not partial or "name" in data:
        out["name"] = _text(data, "name", errors, min_len=2, max_len=60)
    if not partial or "description" in data:
        out["description"] = _text(data, "description", errors, required=False, max_len=200)
    if not partial or "sort_order" in data:
        out["sort_order"] = _int(data, "sort_order", errors, required=False, minimum=0, maximum=10_000) or 0
    if "is_active" in data:
        if not isinstance(data["is_active"], bool):
            errors["is_active"] = "Must be true or false."
        out["is_active"] = data["is_active"] is True
    if errors:
        raise ValidationFailed(errors)
    return out


def validate_product(data: dict, partial: bool = False) -> dict:
    """Returns cleaned fields. 'category' is a slug (existence is checked by the service).

    requires_prescription is NEVER accepted from the client; it is derived from the schedule.
    """
    errors, out = {}, {}

    def want(key):
        return not partial or key in data

    for key, opts in {
        "name": dict(min_len=2, max_len=120),
        "generic_name": dict(required=False, max_len=120),
        "brand": dict(required=False, max_len=60),
        "manufacturer": dict(required=False, max_len=80),
        "description": dict(required=False, max_len=2000),
        "pack_size": dict(required=False, max_len=40),
        "storage_info": dict(required=False, max_len=200),
    }.items():
        if want(key):
            out[key] = _text(data, key, errors, **opts)
    if want("category"):
        cat = _text(data, "category", errors, max_len=80)
        if cat and not SLUG_RE.match(cat):
            errors["category"] = "Must be a category slug."
        out["category"] = cat
    if want("price_paise"):
        out["price_paise"] = _int(data, "price_paise", errors, minimum=1)
    if want("mrp_paise"):
        out["mrp_paise"] = _int(data, "mrp_paise", errors, minimum=1)
    if want("schedule"):
        sched = data.get("schedule", rules.OTC if not partial else None)
        if sched not in rules.SCHEDULES:
            errors["schedule"] = f"Must be one of: {', '.join(rules.SCHEDULES)}."
        else:
            out["schedule"] = sched
    if want("tags"):
        tags = data.get("tags", [])
        if not isinstance(tags, list) or len(tags) > 10 or not all(isinstance(t, str) and 1 <= len(t.strip()) <= 30 for t in tags):
            errors["tags"] = "Up to 10 tags, each 1-30 characters."
        else:
            out["tags"] = [t.strip().lower() for t in tags]
    if "is_active" in data:
        if not isinstance(data["is_active"], bool):
            errors["is_active"] = "Must be true or false."
        out["is_active"] = data["is_active"] is True
    if errors:
        raise ValidationFailed(errors)
    if out.get("price_paise") and out.get("mrp_paise") and out["price_paise"] > out["mrp_paise"]:
        raise ValidationFailed({"price_paise": "Price cannot be higher than MRP."})
    return out


def validate_listing_params(params: dict) -> dict:
    """Validates catalogue query-string values (all arrive as strings)."""
    errors, f = {}, {}

    def get(key):
        v = params.get(key)
        return v.strip() if isinstance(v, str) and v.strip() else None

    if (q := get("q")) is not None:
        if len(q) > 60:
            errors["q"] = "Search text is too long (max 60)."
        else:
            f["q"] = q
    if (cat := get("category")) is not None:
        if SLUG_RE.match(cat) and len(cat) <= 80:
            f["category"] = cat
        else:
            errors["category"] = "Invalid category."
    if (rx := get("rx")) is not None:
        if rx in ("otc", "prescription"):
            f["rx"] = rx
        else:
            errors["rx"] = "Must be 'otc' or 'prescription'."
    for key in ("min_price", "max_price"):
        if (raw := get(key)) is not None:
            if raw.isdigit() and int(raw) <= MAX_PRICE_PAISE:
                f[key] = int(raw)
            else:
                errors[key] = "Must be a whole number of paise."
    if f.get("min_price") is not None and f.get("max_price") is not None and f["min_price"] > f["max_price"]:
        errors["min_price"] = "min_price cannot exceed max_price."
    sort = get("sort") or "name"
    if sort in SORTS:
        f["sort"] = sort
    else:
        errors["sort"] = f"Must be one of: {', '.join(SORTS)}."
    page = get("page") or "1"
    size = get("page_size") or str(DEFAULT_PAGE_SIZE)
    if page.isdigit() and 1 <= int(page) <= 10_000:
        f["page"] = int(page)
    else:
        errors["page"] = "Must be a positive whole number."
    if size.isdigit() and 1 <= int(size) <= MAX_PAGE_SIZE:
        f["page_size"] = int(size)
    else:
        errors["page_size"] = f"Must be between 1 and {MAX_PAGE_SIZE}."
    if errors:
        raise ValidationFailed(errors)
    return f
