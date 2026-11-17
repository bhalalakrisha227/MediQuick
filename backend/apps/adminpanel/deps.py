from functools import lru_cache
from types import SimpleNamespace

from apps.accounts.repository import UserRepository
from apps.catalogue.repository import ProductRepository
from apps.inventory.repository import BatchRepository, MovementRepository
from apps.inventory.services import InventoryService
from apps.orders.repository import OrderRepository, RefundRepository
from apps.orders.services import _now
from apps.prescriptions.repository import PrescriptionRepository
from common.mongo import get_db

from .analytics import AnalyticsService
from .attention import AttentionService, AuditLog
from .repository import AuditRepository
from .users import UserAdminService


@lru_cache(maxsize=1)
def get_services() -> SimpleNamespace:
    db = get_db()
    orders, users = OrderRepository(db), UserRepository(db)
    audit = AuditLog(AuditRepository(db), _now)
    attention = AttentionService(orders, RefundRepository(db), audit, _now)
    inventory = InventoryService(BatchRepository(db), MovementRepository(db), ProductRepository(db))
    analytics = AnalyticsService(orders, PrescriptionRepository(db), inventory.overview, attention.counts, _now)
    return SimpleNamespace(analytics=analytics, attention=attention, users=UserAdminService(users, audit, _now), audit=audit)
