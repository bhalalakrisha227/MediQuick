"""
Cart and order rules in one place.

These limits are engineering defaults, not verified policy. In particular, the
Rx rule below is deliberately strict: it only passes with a pharmacist-approved
prescription (Phase 6), and legal requirements for selling medicines online must be
confirmed professionally (see docs/COMPLIANCE_CHECKLIST.md).
"""
from apps.catalogue import rules as catalogue_rules

MAX_LINE_QUANTITY = 10          # units of one product per order
MAX_CART_LINES = 30             # different products per order
RESERVATION_MINUTES = 15        # how long stock is held for an unpaid order
DELIVERY_FEE_PAISE = 4900           # PLACEHOLDER flat fee (Rs 49), not a business decision
FREE_DELIVERY_ABOVE_PAISE = 49900   # PLACEHOLDER: no fee when the medicines subtotal is at least this

PENDING = "pending_payment"
PROCESSING = "processing_payment"
CONFIRMED = "confirmed"
CANCELLED = "cancelled"
EXPIRED = "expired"
PAYMENT_REVIEW = "payment_review"   # money taken but stock commit failed: needs a human
CONFIRMING = "confirming_payment"   # gateway says paid; stock is being committed (one worker at a time)
DISPATCHED = "dispatched"           # picked up by the delivery partner (or marked by hand by staff)
DELIVERED = "delivered"             # handed over with the customer's code (or marked by hand by staff)
DELIVERY_FAILED = "delivery_failed" # too many failed attempts: staff decide (redeliver or refund)

# --- Delivery (placeholders) ---
DELIVERY_PARTNER_ROLE = "delivery_partner"
MAX_FAILED_ATTEMPTS = 3
MAX_CODE_TRIES = 5                  # wrong handover codes allowed per order before it locks
FAIL_REASONS = ("customer_unavailable", "wrong_address", "refused_by_customer", "unreachable_phone")
REFUND_FAILED_DELIVERY = "failed_delivery"


def delivery_fee(subtotal_paise: int) -> int:
    if subtotal_paise <= 0 or subtotal_paise >= FREE_DELIVERY_ABOVE_PAISE:
        return 0
    return DELIVERY_FEE_PAISE


def serviceable(pincode: str, prefixes) -> bool:
    """prefixes is a tuple of PIN code prefixes we deliver to. EMPTY means no restriction (demo default)."""
    return not prefixes or any(str(pincode).startswith(p) for p in prefixes)

# --- Returns (placeholders: medicine return rules are legally restricted and must be reviewed) ---
RETURN_WINDOW_DAYS = 2
RETURN_REASONS = ("wrong_item", "damaged", "expired_item", "missing_item")   # no "changed my mind"
MAX_RETURN_DETAILS = 500
FULFILMENT_ROLES = ("pharmacy_manager", "admin")                 # dispatch / deliver / retry refunds
RETURN_DECISION_ROLES = ("support_agent", "pharmacy_manager", "admin")

# Refund kinds
REFUND_CANCELLATION = "cancellation"
REFUND_RETURN = "return"


def line_problem(product: dict | None, rx_remaining: int = 0, quantity: int = 1) -> str | None:
    """Why this product cannot be ordered right now (None = it can).

    rx_remaining: units a single pharmacist-approved prescription of this customer still covers.
    """
    if product is None or not product.get("is_active"):
        return "unavailable"
    # Checked first so restricted products get the more accurate "not available online" message.
    if not catalogue_rules.purchasable_online(product["schedule"]):
        return "not_purchasable"
    # Prescription medicines need a pharmacist-approved prescription that still covers the quantity.
    if product["requires_prescription"]:
        if rx_remaining <= 0:
            return "prescription_required"
        if quantity > rx_remaining:
            return "exceeds_prescription"
    return None
