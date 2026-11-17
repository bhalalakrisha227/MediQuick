from django.core.management.base import BaseCommand

from apps.prescriptions import deps


class Command(BaseCommand):
    help = "Run OCR for prescriptions whose job was lost (for example after a server restart)."

    def handle(self, *args, **options):
        count = deps.get_services().prescriptions.recover_pending(limit=100)
        self.stdout.write(self.style.SUCCESS(f"Processed {count} prescription(s)."))
