from django.core.management.base import BaseCommand

from apps.orders import deps


class Command(BaseCommand):
    help = "Expire unpaid orders whose stock reservation has run out and free their stock."

    def handle(self, *args, **options):
        count = deps.get_services().orders.release_expired(limit=1000)
        self.stdout.write(self.style.SUCCESS(f"Released {count} expired reservation(s)."))
