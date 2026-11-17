import random
import unittest
from datetime import date, datetime, timedelta, timezone

from apps.accounts.errors import ServiceError, ValidationFailed
from apps.catalogue.services import CatalogueService
from apps.inventory import queries, rules, validators
from apps.inventory.services import AvailabilityService, InventoryService

from .fakes import FakeBatches, FakeCategories, FakeMovements, FakeProducts

TODAY = date(2026, 6, 1)
STAFF = {"id": "staff-1", "role": "inventory_staff"}
MANAGER = {"id": "mgr-1", "role": "pharmacy_manager"}


class TickingClock:
    def __init__(self):
        self.now = datetime(2026, 6, 1, tzinfo=timezone.utc)

    def __call__(self):
        self.now += timedelta(seconds=1)
        return self.now


def d(days):
    return (TODAY + timedelta(days=days)).isoformat()


class Base(unittest.TestCase):
    def setUp(self):
        self.products, self.batches, self.movements = FakeProducts(), FakeBatches(), FakeMovements()
        self.catalogue = CatalogueService(FakeCategories(), self.products, TickingClock())
        self.catalogue.create_category({"name": "Pain & Fever"})
        self.p1 = self.make_product("Paracetamol")
        self.p2 = self.make_product("Cetirizine")
        self.svc = InventoryService(self.batches, self.movements, self.products, TickingClock(), lambda: TODAY)
        self.avail = AvailabilityService(self.batches, lambda: TODAY)

    def make_product(self, name):
        return self.catalogue.create_product({"name": name, "category": "pain-fever", "pack_size": "Strip",
                                              "price_paise": 3000, "mrp_paise": 3500, "schedule": "OTC"})["id"]

    def receive(self, product=None, number="B1", days=400, qty=100, **extra):
        return self.svc.receive(STAFF, {"product_id": product or self.p1, "batch_number": number,
                                        "expiry_date": d(days), "quantity": qty, **extra})

    def status_of(self, pid):
        return self.avail.for_products([pid])[pid]


class RulesAndQueryTests(unittest.TestCase):
    def test_cutoff_and_status_thresholds(self):
        self.assertEqual(rules.sellable_cutoff(TODAY), TODAY + timedelta(days=30))
        self.assertEqual([rules.availability_status(n) for n in (-3, 0, 1, 10, 11)],
                         ["out_of_stock", "out_of_stock", "low_stock", "low_stock", "in_stock"])

    def test_batch_query_shapes(self):
        now = datetime(2026, 6, 1, tzinfo=timezone.utc)
        self.assertEqual(queries.build_batch_query({}, now, 60), {})
        q = queries.build_batch_query({"state": "expired", "product_id": "p"}, now, 60)
        self.assertEqual((q["product_id"], q["expiry_date"], q["quantity_on_hand"]), ("p", {"$lt": now}, {"$gt": 0}))
        self.assertEqual(queries.build_batch_query({"state": "expiring"}, now, 60)["expiry_date"],
                         {"$gte": now, "$lte": now + timedelta(days=60)})

    def test_sellable_match_requires_active_unexpired_unreserved(self):
        m = queries.sellable_match(["a"], datetime(2026, 7, 1, tzinfo=timezone.utc))
        self.assertEqual((m["status"], m["product_id"]), ("active", {"$in": ["a"]}))
        self.assertIn("$expr", m)


class ReceiveValidationTests(Base):
    def test_receive_creates_batch_and_ledger_entry(self):
        b = self.receive(qty=50, mfg_date=d(-30), supplier="Acme")
        self.assertEqual((b["quantity_on_hand"], b["status"], b["product_name"]), (50, "active", "Paracetamol"))
        [m] = self.movements.docs
        self.assertEqual((m["type"], m["delta"], m["quantity_after"], m["actor_id"]), ("receipt", 50, 50, "staff-1"))

    def test_rejects_bad_input(self):
        base = {"product_id": self.p1, "batch_number": "B9", "expiry_date": d(300), "quantity": 5}
        cases = [
            {"expiry_date": d(0)}, {"expiry_date": d(-5)}, {"expiry_date": "2027-13-01"},
            {"expiry_date": "01/02/2027"}, {"expiry_date": 20270101}, {"expiry_date": None},
            {"quantity": 0}, {"quantity": -1}, {"quantity": 1.5}, {"quantity": True}, {"quantity": "5"},
            {"quantity": 100_001}, {"batch_number": "bad batch!"}, {"batch_number": "x" * 41},
            {"batch_number": ""}, {"mfg_date": d(5)}, {"mfg_date": d(400)}, {"supplier": "s" * 81},
        ]
        for over in cases:
            with self.assertRaises(ValidationFailed, msg=str(over)):
                self.svc.receive(STAFF, {**base, **over})
        for missing in ("product_id", "batch_number", "expiry_date", "quantity"):
            with self.assertRaises(ValidationFailed, msg=missing):
                self.svc.receive(STAFF, {k: v for k, v in base.items() if k != missing})
        self.assertEqual(self.batches.docs, {})  # nothing was stored by any rejected call

    def test_unknown_product_and_duplicate_batch(self):
        with self.assertRaises(ServiceError) as cm:
            self.svc.receive(STAFF, {"product_id": "nope", "batch_number": "B", "expiry_date": d(300), "quantity": 1})
        self.assertIn("product_id", cm.exception.fields)
        self.receive()
        with self.assertRaises(ServiceError) as cm:
            self.receive()
        self.assertEqual(cm.exception.status, 409)
        self.receive(product=self.p2)  # same batch number on another product is fine


class AdjustmentTests(Base):
    def test_adjust_updates_stock_and_ledger(self):
        b = self.receive(qty=100)
        out = self.svc.adjust(STAFF, b["id"], {"delta": -30, "reason": "damage", "note": "dropped carton"})
        self.assertEqual(out["quantity_on_hand"], 70)
        last = self.movements.docs[-1]
        self.assertEqual((last["delta"], last["quantity_after"], last["reason"], last["note"]), (-30, 70, "damage", "dropped carton"))

    def test_cannot_go_below_zero_and_nothing_is_recorded(self):
        b = self.receive(qty=5)
        with self.assertRaises(ServiceError) as cm:
            self.svc.adjust(STAFF, b["id"], {"delta": -6, "reason": "stock_count"})
        self.assertEqual((cm.exception.code, cm.exception.status), ("insufficient_stock", 409))
        self.assertEqual(self.batches.get(b["id"])["quantity_on_hand"], 5)
        self.assertEqual(len(self.movements.docs), 1)  # only the receipt

    def test_cannot_go_below_reserved(self):
        b = self.receive(qty=15)
        self.batches.docs[b["id"]]["quantity_reserved"] = 10
        with self.assertRaises(ServiceError):
            self.svc.adjust(STAFF, b["id"], {"delta": -6, "reason": "stock_count"})
        self.assertEqual(self.svc.adjust(STAFF, b["id"], {"delta": -5, "reason": "stock_count"})["quantity_available"], 0)

    def test_validation_rules(self):
        b = self.receive()
        bad = [{"delta": 0, "reason": "stock_count"}, {"delta": 5, "reason": "damage"},
               {"delta": 5, "reason": "expired_writeoff"}, {"delta": -1, "reason": "bogus"},
               {"delta": True, "reason": "stock_count"}, {"delta": 1.5, "reason": "stock_count"},
               {"delta": -1, "reason": "correction"},  # correction needs a note
               {"reason": "stock_count"}, {"delta": 200_000, "reason": "stock_count"}]
        for data in bad:
            with self.assertRaises(ValidationFailed, msg=str(data)):
                self.svc.adjust(STAFF, b["id"], data)
        self.svc.adjust(STAFF, b["id"], {"delta": 3, "reason": "correction", "note": "miscounted at receipt"})

    def test_unknown_batch(self):
        for bad in ("nope", None, 5):
            with self.assertRaises(ServiceError) as cm:
                self.svc.adjust(STAFF, bad, {"delta": -1, "reason": "damage"})
            self.assertEqual(cm.exception.status, 404)

    def test_ledger_always_matches_stock_under_random_operations(self):
        rng = random.Random(7)
        b = self.receive(qty=50)
        self.batches.docs[b["id"]]["quantity_reserved"] = 5
        refused = 0
        for _ in range(300):
            delta = rng.choice([-1, 1]) * rng.randint(1, 40)
            reason = "stock_count"
            try:
                self.svc.adjust(STAFF, b["id"], {"delta": delta, "reason": reason})
            except ServiceError:
                refused += 1
            doc = self.batches.get(b["id"])
            self.assertGreaterEqual(doc["quantity_on_hand"], 0)
            self.assertGreaterEqual(doc["quantity_on_hand"], doc["quantity_reserved"])
            self.assertEqual(doc["quantity_on_hand"], sum(m["delta"] for m in self.movements.docs))
        self.assertGreater(refused, 0)  # the test really exercised refusals
        self.assertEqual(self.movements.docs[-1]["quantity_after"], self.batches.get(b["id"])["quantity_on_hand"])


class StatusTests(Base):
    def test_quarantine_by_staff_and_ledger(self):
        b = self.receive()
        out = self.svc.set_status(STAFF, b["id"], {"status": "quarantined", "note": "awaiting QC"})
        self.assertEqual(out["status"], "quarantined")
        self.assertEqual(self.movements.docs[-1]["type"], "status_change")
        self.assertEqual(self.movements.docs[-1]["delta"], 0)

    def test_recall_and_unrecall_need_manager_or_admin(self):
        b = self.receive()
        with self.assertRaises(ServiceError) as cm:
            self.svc.set_status(STAFF, b["id"], {"status": "recalled", "note": "supplier notice"})
        self.assertEqual(cm.exception.status, 403)
        self.assertEqual(self.batches.get(b["id"])["status"], "active")
        self.svc.set_status(MANAGER, b["id"], {"status": "recalled", "note": "supplier notice"})
        with self.assertRaises(ServiceError):
            self.svc.set_status(STAFF, b["id"], {"status": "active", "note": "trying to undo"})
        self.svc.set_status(MANAGER, b["id"], {"status": "active", "note": "cleared by supplier"})

    def test_requires_note_valid_status_and_change(self):
        b = self.receive()
        for data in ({"status": "quarantined"}, {"status": "quarantined", "note": "x"}, {"status": "gone", "note": "abc"},
                     {"status": "active", "note": "already active"}):
            with self.assertRaises((ValidationFailed, ServiceError), msg=str(data)):
                self.svc.set_status(STAFF, b["id"], data)


class AvailabilityTests(Base):
    def test_only_sellable_batches_count(self):
        self.receive(number="OK", days=400, qty=100)
        self.receive(number="NEAR", days=10, qty=50)            # inside the 30-day minimum
        self.receive(number="EDGE", days=30, qty=7)             # exactly at the cutoff: sellable
        q = self.receive(number="QUAR", days=400, qty=60)
        self.svc.set_status(STAFF, q["id"], {"status": "quarantined", "note": "qc hold"})
        r = self.receive(number="RECALL", days=400, qty=60)
        self.svc.set_status(MANAGER, r["id"], {"status": "recalled", "note": "recall"})
        summary = self.batches.sellable_summary([self.p1], datetime(2026, 7, 1, tzinfo=timezone.utc))
        self.assertEqual(summary[self.p1]["sellable"], 107)

    def test_shelf_life_cutoff_applies_through_the_availability_service(self):
        self.receive(product=self.p2, number="NEAR", days=10, qty=50)
        self.assertEqual(self.status_of(self.p2)["status"], "out_of_stock")  # 10 days left < 30-day minimum
        self.receive(product=self.p2, number="EDGE", days=30, qty=7)
        self.assertEqual(self.status_of(self.p2), {"status": "low_stock", "earliest_expiry": d(30)})
        self.receive(product=self.p2, number="EXPIRED-SOON", days=29, qty=500)  # one day short of the minimum
        self.assertEqual(self.status_of(self.p2)["status"], "low_stock")

    def test_status_and_fefo_expiry(self):
        self.assertEqual(self.status_of(self.p1), {"status": "out_of_stock", "earliest_expiry": None})
        self.receive(number="LATE", days=500, qty=5)
        self.receive(number="SOON", days=100, qty=3)
        self.assertEqual(self.status_of(self.p1), {"status": "low_stock", "earliest_expiry": d(100)})
        self.receive(number="BIG", days=300, qty=50)
        self.assertEqual(self.status_of(self.p1)["status"], "in_stock")

    def test_reserved_units_are_not_available(self):
        b = self.receive(qty=20)
        self.batches.docs[b["id"]]["quantity_reserved"] = 20
        self.assertEqual(self.status_of(self.p1)["status"], "out_of_stock")

    def test_public_availability_never_exposes_counts(self):
        self.receive(qty=500)
        self.assertEqual(set(self.status_of(self.p1)), {"status", "earliest_expiry"})

    def test_catalogue_integration_is_one_batched_lookup(self):
        calls = []
        provider = self.avail
        original = provider.for_products
        provider.for_products = lambda ids: (calls.append(list(ids)), original(ids))[1]
        cat = CatalogueService(FakeCategories(), self.products, TickingClock(), availability=provider)
        self.receive(product=self.p1, qty=50)
        page = cat.list_products({})
        by_name = {p["name"]: p["availability"]["status"] for p in page["results"]}
        self.assertEqual(by_name, {"Cetirizine": "out_of_stock", "Paracetamol": "in_stock"})
        self.assertEqual(len(calls), 1)
        slug = self.products.get(self.p1)["slug"]
        self.assertEqual(cat.get_product(slug)["availability"]["status"], "in_stock")

    def test_catalogue_without_provider_reports_null_not_a_guess(self):
        plain = CatalogueService(FakeCategories(), self.products, TickingClock())
        self.assertTrue(all(p["availability"] is None for p in plain.list_products({})["results"]))


class OverviewAndListingTests(Base):
    def test_overview_alerts(self):
        self.receive(product=self.p1, number="EXPIRING", days=45, qty=100)
        old = self.receive(product=self.p1, number="OLD", days=100, qty=40)
        self.batches.docs[old["id"]]["expiry_date"] = datetime(2026, 5, 1, tzinfo=timezone.utc)  # now expired, has stock
        empty = self.receive(product=self.p1, number="OLD-EMPTY", days=100, qty=1)
        self.batches.docs[empty["id"]]["expiry_date"] = datetime(2026, 5, 1, tzinfo=timezone.utc)
        self.batches.docs[empty["id"]]["quantity_on_hand"] = 0
        ov = self.svc.overview()
        self.assertEqual([b["batch_number"] for b in ov["expired_with_stock"]], ["OLD"])
        self.assertEqual([b["batch_number"] for b in ov["expiring_soon"]], ["EXPIRING"])
        self.assertTrue(ov["expired_with_stock"][0]["is_expired"])
        low = {r["name"]: r["status"] for r in ov["low_stock"]}
        self.assertEqual(low, {"Cetirizine": "out_of_stock"})  # Paracetamol has 100 sellable

    def test_listing_filters_sort_and_pagination(self):
        self.receive(number="C", days=300)
        self.receive(number="A", days=100)
        self.receive(number="B", days=200, product=self.p2)
        names = lambda **p: [b["batch_number"] for b in self.svc.list_batches(p)["results"]]
        self.assertEqual(names(), ["A", "B", "C"])  # earliest expiry first (FEFO)
        self.assertEqual(names(product_id=self.p1), ["A", "C"])
        page = self.svc.list_batches({"page_size": "2", "page": "2"})
        self.assertEqual(([b["batch_number"] for b in page["results"]], page["total"], page["total_pages"]), (["C"], 3, 2))
        for bad in ({"state": "x"}, {"status": "x"}, {"page": "0"}, {"page_size": "101"}):
            with self.assertRaises(ValidationFailed):
                self.svc.list_batches(bad)

    def test_movements_listed_newest_first(self):
        b = self.receive(qty=10)
        self.svc.adjust(STAFF, b["id"], {"delta": -2, "reason": "damage"})
        types = [(m["type"], m["delta"]) for m in self.svc.list_movements(b["id"])]
        self.assertEqual(types, [("adjustment", -2), ("receipt", 10)])


if __name__ == "__main__":
    unittest.main()
