"""
Adds DEMO stock batches for the demo catalogue (run seed_demo_catalogue first).

Batches are flagged is_demo=True with a fictional supplier. Dates are relative to
today so the demo always shows a mix: healthy stock, low stock, out of stock, and
batches that are near expiry or already expired (which are NOT sellable).
Safe to run repeatedly (existing batch numbers are skipped).
"""
from datetime import datetime, timedelta, timezone

from django.core.management.base import BaseCommand

from apps.accounts.errors import ServiceError
from apps.inventory import deps

SYSTEM = {"id": "system:seed", "role": "admin"}

# (product name prefix, batch_number, days_until_expiry, quantity)
PLAN = [
    ("Paracetamol 500 mg", "DEMO-PCM-01", 540, 120),
    ("Paracetamol 500 mg", "DEMO-PCM-00", 20, 40),       # too close to expiry: not sellable
    ("Cetirizine 10 mg", "DEMO-CET-01", 400, 6),          # low stock
    ("Oral Rehydration Salts", "DEMO-ORS-01", 300, 80),
    ("Antacid Oral Gel", "DEMO-ANT-01", 365, 35),
    ("Vitamin C 500 mg", "DEMO-VTC-01", 45, 50),          # sellable but expiring soon
    ("Cough Lozenges", "DEMO-LOZ-01", 500, 200),
    ("Antiseptic Liquid", "DEMO-ASL-01", 700, 60),
    ("Amoxicillin 500 mg", "DEMO-AMX-01", 420, 90),
    ("Azithromycin 500 mg", "DEMO-AZI-01", 380, 25),
    ("Metformin 500 mg", "DEMO-MET-01", 600, 150),
    ("Amlodipine 5 mg", "DEMO-AML-01", 450, 70),
    # Digital Thermometer and Pantoprazole intentionally get no batch: they show as out of stock.
]


class Command(BaseCommand):
    help = "Load demo stock batches (idempotent)."

    def handle(self, *args, **options):
        service = deps.get_service()
        products = {p["name"]: p for p in service.products.list_active(500)}
        today = datetime.now(timezone.utc).date()
        made = skipped = 0
        for prefix, number, days, qty in PLAN:
            product = next((p for n, p in products.items() if n.startswith(prefix)), None)
            if product is None:
                self.stderr.write(f"Skipping {number}: product '{prefix}' not found (seed the catalogue first).")
                continue
            try:
                result = service.receive(SYSTEM, {
                    "product_id": product["_id"], "batch_number": number,
                    "expiry_date": (today + timedelta(days=days)).isoformat(),
                    "quantity": qty, "supplier": "Demo supplier (fictional)",
                })
                service.batches.col.update_one({"_id": result["id"]}, {"$set": {"is_demo": True}})
                made += 1
            except ServiceError as exc:
                if exc.status == 409:
                    skipped += 1
                else:
                    raise
        self.stdout.write(self.style.SUCCESS(f"Demo inventory ready: {made} batches added, {skipped} already existed."))
