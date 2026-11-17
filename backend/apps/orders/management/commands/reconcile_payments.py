from django.core.management.base import BaseCommand

from apps.orders import deps


class Command(BaseCommand):
    help = ("Gateway payments only: free abandoned payment pages, settle payments whose callback never arrived, "
            "and flag orders stuck while confirming. Run every few minutes.")

    def handle(self, *args, **options):
        result = deps.get_services().gateway.reconcile()
        self.stdout.write(self.style.SUCCESS(
            f"confirmed={result['confirmed']} expired={result['expired']} flagged={result['flagged']}"))
