"""Role names. Staff roles can never be self-registered; see create_staff_user."""
CUSTOMER = "customer"
PHARMACIST = "pharmacist"
PHARMACY_MANAGER = "pharmacy_manager"
INVENTORY_STAFF = "inventory_staff"
DELIVERY_PARTNER = "delivery_partner"
SUPPORT_AGENT = "support_agent"
ADMIN = "admin"

ALL_ROLES = (
    CUSTOMER,
    PHARMACIST,
    PHARMACY_MANAGER,
    INVENTORY_STAFF,
    DELIVERY_PARTNER,
    SUPPORT_AGENT,
    ADMIN,
)
STAFF_ROLES = tuple(r for r in ALL_ROLES if r != CUSTOMER)
