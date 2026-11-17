import unittest
from datetime import datetime, timedelta, timezone

from apps.catalogue import queries, rules, validators
from apps.catalogue.errors import ServiceError, ValidationFailed
from apps.catalogue.services import CatalogueService, public_product

from .fakes import FakeCategories, FakeProducts

PRODUCT = {"name": "Paracetamol 500 mg", "category": "pain-fever", "pack_size": "Strip of 15",
           "price_paise": 3000, "mrp_paise": 3500, "schedule": "OTC"}


class TickingClock:
    def __init__(self):
        self.now = datetime.now(timezone.utc)

    def __call__(self):
        self.now += timedelta(seconds=1)
        return self.now


class QueryTests(unittest.TestCase):
    def test_only_active_by_default(self):
        self.assertEqual(queries.build_query({}), {"is_active": True})

    def test_filters(self):
        q = queries.build_query({"category": "c", "rx": "otc", "min_price": 10, "max_price": 20})
        self.assertEqual(q["category"], "c")
        self.assertIs(q["requires_prescription"], False)
        self.assertEqual(q["price_paise"], {"$gte": 10, "$lte": 20})
        self.assertIs(queries.build_query({"rx": "prescription"})["requires_prescription"], True)

    def test_search_text_is_escaped_never_a_regex(self):
        q = queries.build_query({"q": ".*(a|b)+$"})
        pattern = q["$or"][0]["name"]["$regex"]
        self.assertEqual(pattern, r"\.\*\(a\|b\)\+\$")


class ValidatorTests(unittest.TestCase):
    def test_listing_defaults(self):
        f = validators.validate_listing_params({})
        self.assertEqual((f["sort"], f["page"], f["page_size"]), ("name", 1, 12))

    def test_listing_rejects_bad_values(self):
        for bad in ({"sort": "random"}, {"rx": "maybe"}, {"page": "0"}, {"page": "abc"},
                    {"page_size": "500"}, {"min_price": "-5"}, {"max_price": "1.5"},
                    {"min_price": "500", "max_price": "100"}, {"q": "x" * 61}, {"category": "Bad Slug!"}):
            with self.assertRaises(ValidationFailed, msg=str(bad)):
                validators.validate_listing_params(bad)

    def test_product_price_rules(self):
        with self.assertRaises(ValidationFailed):
            validators.validate_product({**PRODUCT, "price_paise": 5000})
        for bad in (0, -1, 1.5, "30", True):
            with self.assertRaises(ValidationFailed, msg=str(bad)):
                validators.validate_product({**PRODUCT, "price_paise": bad})

    def test_unknown_schedule_rejected_and_rx_flag_ignored(self):
        with self.assertRaises(ValidationFailed):
            validators.validate_product({**PRODUCT, "schedule": "Z"})
        cleaned = validators.validate_product({**PRODUCT, "schedule": "H", "requires_prescription": False})
        self.assertNotIn("requires_prescription", cleaned)

    def test_slugify(self):
        self.assertEqual(validators.slugify("Paracetamol 500 mg / Strip of 15!"), "paracetamol-500-mg-strip-of-15")


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.svc = CatalogueService(FakeCategories(), FakeProducts(), TickingClock())
        self.svc.create_category({"name": "Pain & Fever"})
        self.svc.create_category({"name": "Chronic Care"})

    def add(self, **over):
        return self.svc.create_product({**PRODUCT, **over})

    def test_rx_flag_derived_from_schedule(self):
        self.assertFalse(self.add()["requires_prescription"])
        rx = self.add(name="Amoxicillin 500 mg", schedule="H", category="chronic-care")
        self.assertTrue(rx["requires_prescription"])
        self.assertTrue(rx["purchasable_online"])

    def test_schedule_x_is_not_purchasable_online(self):
        x = self.add(name="Restricted Drug", schedule="X")
        self.assertTrue(x["requires_prescription"])
        self.assertFalse(x["purchasable_online"])

    def test_unknown_category_rejected(self):
        with self.assertRaises(ServiceError) as cm:
            self.add(category="nope")
        self.assertIn("category", cm.exception.fields)

    def test_duplicate_names_get_unique_slugs(self):
        a, b = self.add(), self.add()
        self.assertNotEqual(a["slug"], b["slug"])

    def test_availability_is_honestly_unknown(self):
        self.assertIsNone(self.add()["availability"])
        self.assertEqual(public_product(self.svc.products.get(self.add()["id"]))["discount_percent"], 14)

    def seed(self):
        self.add(name="Paracetamol", price_paise=3000, mrp_paise=3500)
        self.add(name="Cetirizine", price_paise=2500, mrp_paise=3000)
        self.add(name="Amoxicillin", schedule="H", category="chronic-care", price_paise=9500, mrp_paise=11000)
        self.add(name="Metformin", generic_name="Biguanide", schedule="H", category="chronic-care",
                 price_paise=3200, mrp_paise=3800)

    def names(self, **params):
        return [p["name"] for p in self.svc.list_products(params)["results"]]

    def test_listing_filters_and_sorting(self):
        self.seed()
        self.assertEqual(self.names(), ["Amoxicillin", "Cetirizine", "Metformin", "Paracetamol"])
        self.assertEqual(self.names(rx="otc"), ["Cetirizine", "Paracetamol"])
        self.assertEqual(self.names(rx="prescription"), ["Amoxicillin", "Metformin"])
        self.assertEqual(self.names(category="chronic-care"), ["Amoxicillin", "Metformin"])
        self.assertEqual(self.names(q="BIGUA"), ["Metformin"])  # case-insensitive, matches generic name
        self.assertEqual(self.names(sort="price_asc")[0], "Cetirizine")
        self.assertEqual(self.names(sort="price_desc")[0], "Amoxicillin")
        self.assertEqual(self.names(min_price="3000", max_price="3200"), ["Metformin", "Paracetamol"])
        self.assertEqual(self.names(sort="newest")[0], "Metformin")

    def test_pagination(self):
        self.seed()
        page = self.svc.list_products({"page_size": "3", "page": "2"})
        self.assertEqual((len(page["results"]), page["total"], page["total_pages"]), (1, 4, 2))

    def test_inactive_products_are_hidden_everywhere(self):
        p = self.add(name="Hidden")
        self.svc.deactivate_product(p["id"])
        self.assertNotIn("Hidden", self.names())
        with self.assertRaises(ServiceError) as cm:
            self.svc.get_product(p["slug"])
        self.assertEqual(cm.exception.status, 404)

    def test_get_product_and_missing(self):
        p = self.add()
        self.assertEqual(self.svc.get_product(p["slug"])["name"], PRODUCT["name"])
        for bad in ("missing", None, 5):
            with self.assertRaises(ServiceError):
                self.svc.get_product(bad)

    def test_update_rederives_prescription_flag_and_checks_price(self):
        p = self.add()
        out = self.svc.update_product(p["id"], {"schedule": "H"})
        self.assertTrue(out["requires_prescription"])
        with self.assertRaises(ServiceError):
            self.svc.update_product(p["id"], {"price_paise": 99999})  # above existing MRP
        with self.assertRaises(ServiceError):
            self.svc.update_product("missing", {"name": "x1"})
        with self.assertRaises(ServiceError):
            self.svc.update_product(p["id"], {})

    def test_category_listing_hides_inactive_and_orders(self):
        self.assertEqual([c["name"] for c in self.svc.list_categories()], ["Chronic Care", "Pain & Fever"])


class RulesTests(unittest.TestCase):
    def test_rules(self):
        self.assertFalse(rules.requires_prescription("OTC"))
        self.assertTrue(all(rules.requires_prescription(s) for s in ("H", "H1", "X")))
        self.assertFalse(rules.purchasable_online("X"))
        self.assertTrue(rules.purchasable_online("H"))


if __name__ == "__main__":
    unittest.main()
