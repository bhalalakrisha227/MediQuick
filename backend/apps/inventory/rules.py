"""
Inventory business rules in one place.

These numbers are engineering defaults, not verified policy. Confirm them with
your pharmacist/pharmacy manager (and, for expiry and recall handling, with
legal advice - see docs/COMPLIANCE_CHECKLIST.md) before real use.
"""
from datetime import date, timedelta

# A batch with less shelf life than this is not offered for sale.
MIN_SELLABLE_SHELF_LIFE_DAYS = 30
# At or below this many sellable units a product shows as "low stock".
LOW_STOCK_THRESHOLD = 10
# Batches expiring within this many days appear in the "expiring soon" alert.
EXPIRY_WARNING_DAYS = 60

BATCH_STATUSES = ("active", "quarantined", "recalled")
# Moving a batch into or out of "recalled" is restricted to these roles.
RECALL_ROLES = frozenset({"pharmacy_manager", "admin"})

# Adjustment reasons -> required sign of the change (None = either direction).
REASONS = {
    "stock_count": None,
    "correction": None,
    "damage": -1,
    "expired_writeoff": -1,
    "returned_to_supplier": -1,
}

MAX_QUANTITY = 100_000


def sellable_cutoff(today: date) -> date:
    """Earliest expiry date a batch may have and still be sold."""
    return today + timedelta(days=MIN_SELLABLE_SHELF_LIFE_DAYS)


def availability_status(sellable_units: int) -> str:
    if sellable_units <= 0:
        return "out_of_stock"
    if sellable_units <= LOW_STOCK_THRESHOLD:
        return "low_stock"
    return "in_stock"
