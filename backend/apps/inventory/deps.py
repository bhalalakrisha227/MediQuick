from functools import lru_cache

from apps.catalogue.repository import ProductRepository
from common.mongo import get_db

from .repository import BatchRepository, MovementRepository
from .services import AvailabilityService, InventoryService


@lru_cache(maxsize=1)
def get_service() -> InventoryService:
    db = get_db()
    return InventoryService(BatchRepository(db), MovementRepository(db), ProductRepository(db))


@lru_cache(maxsize=1)
def get_availability() -> AvailabilityService:
    return AvailabilityService(BatchRepository(get_db()))
