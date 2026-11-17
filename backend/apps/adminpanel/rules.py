"""Admin dashboard rules. No Django / MongoDB imports. All limits are engineering placeholders."""
from datetime import timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))     # reports bucket days in Indian time
ANALYTICS_ROLES = ("admin", "pharmacy_manager")
ATTENTION_ROLES = ("admin", "pharmacy_manager")
USER_ADMIN_ROLES = ("admin",)
MAX_RANGE_DAYS = 366
DEFAULT_RANGE_DAYS = 30
MAX_ROWS_SCANNED = 20000          # a report reads at most this many orders; above it the report says it is truncated
TOP_PRODUCTS = 10
USER_PAGE_SIZE = 25
AUDIT_PAGE_SIZE = 50
MIN_NOTE = 5
MAX_NOTE = 500
SOLD_STATUSES = ("confirmed", "dispatched", "delivered")
