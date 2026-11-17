from functools import lru_cache

from common.mongo import get_db

from .repository import CategoryRepository, ProductRepository
from .services import CatalogueService


@lru_cache(maxsize=1)
def get_service() -> CatalogueService:
    from apps.inventory.deps import get_availability  # imported here to avoid a module-level cycle

    db = get_db()
    return CatalogueService(CategoryRepository(db), ProductRepository(db), availability=get_availability())
