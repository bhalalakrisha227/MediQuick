"""
Loads a small DEMO catalogue so the UI has something to show.

All rows are flagged is_demo=True and shown with a "Demo data" badge. Names are
generic medicine names; prices, pack sizes and descriptions are fictional and
must not be treated as real product information. Safe to run repeatedly.
"""
from django.core.management.base import BaseCommand

from apps.catalogue import deps, validators

CATEGORIES = [
    ("Pain & Fever", "Everyday pain and fever relief"),
    ("Cold & Allergy", "Cold, cough and allergy care"),
    ("Digestive Health", "Stomach and digestion"),
    ("Vitamins & Supplements", "Daily wellness"),
    ("First Aid & Devices", "Antiseptics and basic devices"),
    ("Infection Care", "Prescription anti-infectives"),
    ("Chronic Care", "Long-term condition medicines"),
]

# (name, generic_name, category, pack_size, price_paise, mrp_paise, schedule)
PRODUCTS = [
    ("Paracetamol 500 mg Tablets", "Paracetamol", "Pain & Fever", "Strip of 15", 3000, 3500, "OTC"),
    ("Cetirizine 10 mg Tablets", "Cetirizine", "Cold & Allergy", "Strip of 10", 2500, 3000, "OTC"),
    ("Oral Rehydration Salts Sachet", "ORS", "Digestive Health", "Pack of 5 sachets", 4000, 4500, "OTC"),
    ("Antacid Oral Gel", "Aluminium/Magnesium hydroxide", "Digestive Health", "200 ml bottle", 11000, 12500, "OTC"),
    ("Vitamin C 500 mg Chewable Tablets", "Ascorbic acid", "Vitamins & Supplements", "Bottle of 20", 9000, 10000, "OTC"),
    ("Cough Lozenges Honey-Lemon", "Menthol", "Cold & Allergy", "Pack of 12", 6000, 6000, "OTC"),
    ("Antiseptic Liquid", "Chloroxylenol", "First Aid & Devices", "100 ml bottle", 7500, 8500, "OTC"),
    ("Digital Thermometer", "", "First Aid & Devices", "1 unit", 15000, 19900, "OTC"),
    ("Amoxicillin 500 mg Capsules", "Amoxicillin", "Infection Care", "Strip of 10", 9500, 11000, "H"),
    ("Azithromycin 500 mg Tablets", "Azithromycin", "Infection Care", "Strip of 3", 11500, 13000, "H"),
    ("Metformin 500 mg Tablets", "Metformin", "Chronic Care", "Strip of 20", 3200, 3800, "H"),
    ("Amlodipine 5 mg Tablets", "Amlodipine", "Chronic Care", "Strip of 15", 4200, 5000, "H"),
    ("Pantoprazole 40 mg Tablets", "Pantoprazole", "Digestive Health", "Strip of 10", 8000, 9500, "H"),
]
DESCRIPTION = "Demo listing with fictional details. Always follow a doctor's advice and the product label."


class Command(BaseCommand):
    help = "Load the labelled demo catalogue (idempotent)."

    def handle(self, *args, **options):
        service = deps.get_service()
        made_c = made_p = 0
        for order, (name, desc) in enumerate(CATEGORIES):
            if service.categories.get_by_slug(validators.slugify(name)) is None:
                service.create_category({"name": name, "description": desc, "sort_order": order})
                made_c += 1
        for name, generic, cat, pack, price, mrp, schedule in PRODUCTS:
            if service.products.get_by_slug(validators.slugify(f"{name} {pack}")) is not None:
                continue
            service.create_product({
                "name": name, "generic_name": generic, "brand": "", "manufacturer": "Demo Labs (fictional)",
                "category": validators.slugify(cat), "description": DESCRIPTION, "pack_size": pack,
                "price_paise": price, "mrp_paise": mrp, "schedule": schedule,
                "storage_info": "Store in a cool, dry place.", "tags": [],
            }, is_demo=True)
            made_p += 1
        self.stdout.write(self.style.SUCCESS(f"Demo catalogue ready: {made_c} categories, {made_p} products added."))
