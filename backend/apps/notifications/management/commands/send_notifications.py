import time

from django.core.management.base import BaseCommand

from apps.notifications import deps


class Command(BaseCommand):
    help = "Send pending notification emails. Run it all the time (default) or once with --once (e.g. from a scheduler)."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--interval", type=int, default=15, help="Seconds between checks")

    def handle(self, *args, **opts):
        svc = deps.get_notifications()
        while True:
            counts = svc.send_due()
            if any(counts.values()):
                self.stdout.write(f"emails: {counts}")
            if opts["once"]:
                return
            time.sleep(max(1, opts["interval"]))
