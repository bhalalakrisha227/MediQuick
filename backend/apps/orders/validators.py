from apps.accounts.errors import ValidationFailed

from . import rules


def _id(value, errors, key):
    if not isinstance(value, str) or not value.strip() or len(value) > 64:
        errors[key] = "This field is required."
        return ""
    return value.strip()


def _qty(value, errors, key="quantity", minimum=1):
    if isinstance(value, bool) or not isinstance(value, int) or not (minimum <= value <= rules.MAX_LINE_QUANTITY):
        errors[key] = f"Must be a whole number between {minimum} and {rules.MAX_LINE_QUANTITY}."
        return None
    return value


def validate_item(data: dict) -> dict:
    errors: dict = {}
    product_id = _id(data.get("product_id"), errors, "product_id")
    quantity = _qty(data.get("quantity"), errors)
    if errors:
        raise ValidationFailed(errors)
    return {"product_id": product_id, "quantity": quantity}


def validate_quantity_update(data: dict) -> int:
    errors: dict = {}
    quantity = _qty(data.get("quantity"), errors, minimum=0)
    if errors:
        raise ValidationFailed(errors)
    return quantity


def validate_checkout(data: dict) -> dict:
    errors: dict = {}
    address_id = _id(data.get("address_id"), errors, "address_id")
    if errors:
        raise ValidationFailed(errors)
    return {"address_id": address_id}


def validate_pay(data: dict) -> dict:
    simulate = data.get("simulate")
    if simulate is not None and simulate not in ("success", "fail"):
        raise ValidationFailed({"simulate": "Must be 'success' or 'fail'."})
    return {"simulate": simulate}
