import re
from datetime import date, datetime

from apps.accounts.errors import ValidationFailed

from . import rules
from .queries import BATCH_STATES

BATCH_NUMBER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,39}$")


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


def _date(data, key, errors, required=True):
    value = data.get(key)
    if value in (None, ""):
        if required:
            errors[key] = "This field is required."
        return None
    if not isinstance(value, str):
        errors[key] = "Use the format YYYY-MM-DD."
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        errors[key] = "Use a real date in the format YYYY-MM-DD."
        return None


def _int(value, errors, key, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or not (minimum <= value <= maximum):
        errors[key] = f"Must be a whole number between {minimum} and {maximum}."
        return None
    return value


def validate_receive(data: dict, today: date) -> dict:
    errors: dict = {}
    product_id = _text(data, "product_id", errors, max_len=64)
    batch_number = _text(data, "batch_number", errors, max_len=40)
    if batch_number and not BATCH_NUMBER_RE.match(batch_number):
        errors["batch_number"] = "Use letters, digits and . _ / - only (max 40)."
    expiry = _date(data, "expiry_date", errors)
    if expiry and expiry <= today:
        errors["expiry_date"] = "Stock that has already expired cannot be received."
    mfg = _date(data, "mfg_date", errors, required=False)
    if mfg and mfg > today:
        errors["mfg_date"] = "Manufacturing date cannot be in the future."
    elif mfg and expiry and mfg >= expiry:
        errors["mfg_date"] = "Manufacturing date must be before the expiry date."
    quantity = _int(data.get("quantity"), errors, "quantity", 1, rules.MAX_QUANTITY) if "quantity" in data else None
    if "quantity" not in data:
        errors["quantity"] = "This field is required."
    supplier = _text(data, "supplier", errors, required=False, max_len=80)
    if errors:
        raise ValidationFailed(errors)
    return {"product_id": product_id, "batch_number": batch_number, "expiry_date": expiry,
            "mfg_date": mfg, "quantity": quantity, "supplier": supplier}


def validate_adjustment(data: dict) -> dict:
    errors: dict = {}
    delta = _int(data.get("delta"), errors, "delta", -rules.MAX_QUANTITY, rules.MAX_QUANTITY) if "delta" in data else None
    if "delta" not in data:
        errors["delta"] = "This field is required."
    elif delta == 0:
        errors["delta"] = "Change must not be zero."
    reason = data.get("reason")
    if reason not in rules.REASONS:
        errors["reason"] = f"Must be one of: {', '.join(rules.REASONS)}."
    elif delta and rules.REASONS[reason] and (delta > 0) != (rules.REASONS[reason] > 0):
        errors["delta"] = f"'{reason}' must reduce stock."
    note = _text(data, "note", errors, required=reason == "correction", max_len=200)
    if errors:
        raise ValidationFailed(errors)
    return {"delta": delta, "reason": reason, "note": note}


def validate_status_change(data: dict) -> dict:
    errors: dict = {}
    status = data.get("status")
    if status not in rules.BATCH_STATUSES:
        errors["status"] = f"Must be one of: {', '.join(rules.BATCH_STATUSES)}."
    note = _text(data, "note", errors, min_len=3, max_len=200)
    if errors:
        raise ValidationFailed(errors)
    return {"status": status, "note": note}


def validate_batch_listing(params: dict) -> dict:
    errors, f = {}, {}

    def get(key):
        v = params.get(key)
        return v.strip() if isinstance(v, str) and v.strip() else None

    if (pid := get("product_id")) is not None:
        if len(pid) <= 64:
            f["product_id"] = pid
        else:
            errors["product_id"] = "Invalid product id."
    if (status := get("status")) is not None:
        if status in rules.BATCH_STATUSES:
            f["status"] = status
        else:
            errors["status"] = f"Must be one of: {', '.join(rules.BATCH_STATUSES)}."
    state = get("state") or "all"
    if state in BATCH_STATES:
        f["state"] = state
    else:
        errors["state"] = f"Must be one of: {', '.join(BATCH_STATES)}."
    page, size = get("page") or "1", get("page_size") or "20"
    if page.isdigit() and 1 <= int(page) <= 10_000:
        f["page"] = int(page)
    else:
        errors["page"] = "Must be a positive whole number."
    if size.isdigit() and 1 <= int(size) <= 100:
        f["page_size"] = int(size)
    else:
        errors["page_size"] = "Must be between 1 and 100."
    if errors:
        raise ValidationFailed(errors)
    return f
