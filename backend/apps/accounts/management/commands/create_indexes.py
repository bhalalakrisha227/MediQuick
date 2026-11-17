from django.core.management.base import BaseCommand

from apps.accounts.repository import ensure_indexes as accounts_indexes
from apps.catalogue.repository import ensure_indexes as catalogue_indexes
from apps.inventory.repository import ensure_indexes as inventory_indexes
from apps.adminpanel.repository import ensure_indexes as adminpanel_indexes
from apps.notifications.repository import ensure_indexes as notifications_indexes
from apps.orders.repository import ensure_indexes as orders_indexes
from apps.prescriptions.repository import ensure_indexes as prescriptions_indexes
from common.mongo import get_db


class Command(BaseCommand):
    help = "Create MongoDB indexes for all collections (safe to run repeatedly)."

    def handle(self, *args, **options):
        db = get_db()
        accounts_indexes(db)
        catalogue_indexes(db)
        inventory_indexes(db)
        orders_indexes(db)
        prescriptions_indexes(db)
        notifications_indexes(db)
        adminpanel_indexes(db)
        self.stdout.write(self.style.SUCCESS("Indexes are in place."))
