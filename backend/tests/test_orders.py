import random
import re
import unittest
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from unittest import mock

from apps.accounts.errors import ServiceError, ValidationFailed
from apps.accounts.services import AddressService
from apps.catalogue.services import CatalogueService
from apps.inventory.reservations import CommitError, InsufficientStock, ReservationService
from apps.inventory.services import InventoryService
from apps.orders import rules
from apps.orders.cart import CartService
from apps.orders.payments import MockPaymentAdapter
from apps.orders.services import OrderService

from .fakes import (FakeAddresses, FakeBatches, FakeCarts, FakeCategories, FakeMovements, FakeOrders, FakeProducts)

TODAY = date(2026, 6, 1)
STAFF = {"id": "staff-1", "role": "inventory_staff"}
MANAGER = {"id": "mgr-1", "role": "pharmacy_manager"}
ADDR = {"recipient_name": "Asha Rao", "phone": "9876543210", "line1": "12 Main Road", "city": "Pune",
        "state": "Maharashtra", "pincode": "411001"}


class Clock:
    def __init__(self):
        self.now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, minutes):
        self.now += timedelta(minutes=minutes)


def d(days):
    return (TODAY + timedelta(days=days)).isoformat()


class Base(unittest.TestCase):
    def setUp(self):
        # Older tests predate the delivery fee and assert exact totals, so they run with a zero fee.
        # The fee itself is tested in tests/test_delivery.py with the real placeholder values.
        patcher = mock.patch("apps.orders.rules.DELIVERY_FEE_PAISE", 0)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.clock = Clock()
        self.products, self.batches, self.movements = FakeProducts(), FakeBatches(), FakeMovements()
        self.catalogue = CatalogueService(FakeCategories(), self.products, self.clock)
        self.catalogue.create_category({"name": "Pain & Fever"})
        self.inv = InventoryService(self.batches, self.movements, self.products, self.clock, lambda: TODAY)
        self.res = ReservationService(self.batches, self.movements, self.clock, lambda: TODAY)
        self.carts, self.order_repo, self.addresses = FakeCarts(), FakeOrders(), FakeAddresses()
        self.cart = CartService(self.carts, self.products, self.res, self.clock)
        self.orders = OrderService(self.carts, self.order_repo, self.products, self.addresses, self.res,
                                   MockPaymentAdapter(), self.clock)
        addr_svc = AddressService(self.addresses, self.clock)
        self.addr = addr_svc.create("u1", ADDR)["id"]
        self.addr2 = addr_svc.create("u2", ADDR)["id"]
        self.para = self.product("Paracetamol", 3000)
        self.cet = self.product("Cetirizine", 2500)
        self.rx = self.product("Amoxicillin", 9500, schedule="H")
        self.restricted = self.product("Restricted", 5000, schedule="X")
        self.stock(self.para, "P1", 400, 20)
        self.stock(self.cet, "C1", 400, 20)
        self.stock(self.rx, "R1", 400, 20)

    def product(self, name, price, schedule="OTC"):
        return self.catalogue.create_product({"name": name, "category": "pain-fever", "pack_size": "Strip",
                                              "price_paise": price, "mrp_paise": price + 500, "schedule": schedule})["id"]

    def stock(self, pid, number, days, qty):
        return self.inv.receive(STAFF, {"product_id": pid, "batch_number": number, "expiry_date": d(days), "quantity": qty})

    def batch(self, number):
        return next(b for b in self.batches.docs.values() if b["batch_number"] == number)

    def place(self, items, user="u1", addr=None):
        for pid, qty in items:
            self.cart.add(user, {"product_id": pid, "quantity": qty})
        return self.orders.create(user, {"address_id": addr or (self.addr if user == "u1" else self.addr2)})

    def sales(self):
        return [m for m in self.movements.docs if m["type"] == "sale"]


class ReservationTests(Base):
    def test_fefo_allocation_across_batches_and_merge(self):
        a = self.stock(self.rx, "EARLY", 100, 10)
        self.stock(self.rx, "LATE", 200, 10)
        held = self.res.reserve_many([(self.rx, 15)])[self.rx]
        got = {x["batch_number"]: x["quantity"] for x in held}
        self.assertEqual(got, {"EARLY": 10, "LATE": 5})
        self.assertEqual((self.batch("EARLY")["quantity_reserved"], self.batch("LATE")["quantity_reserved"]), (10, 5))
        self.assertEqual(a["quantity_on_hand"], 10)

    def test_skips_unsellable_batches(self):
        self.stock(self.cet, "NEAR", 10, 50)                       # under the 30-day minimum
        q = self.stock(self.cet, "QUAR", 100, 50)
        self.inv.set_status(STAFF, q["id"], {"status": "quarantined", "note": "qc hold"})
        held = self.res.reserve_many([(self.cet, 20)])[self.cet]
        self.assertEqual([x["batch_number"] for x in held], ["C1"])
        with self.assertRaises(InsufficientStock):
            self.res.reserve_many([(self.cet, 1)])  # only the 20 in C1 were sellable, all now held

    def test_all_or_nothing_across_products(self):
        with self.assertRaises(InsufficientStock) as cm:
            self.res.reserve_many([(self.para, 5), (self.cet, 21)])
        self.assertEqual((cm.exception.product_id, cm.exception.requested, cm.exception.available), (self.cet, 21, 20))
        self.assertEqual(self.batch("P1")["quantity_reserved"], 0)  # the earlier product was rolled back

    def test_release_and_commit(self):
        held = self.res.reserve_many([(self.para, 4)])[self.para]
        self.res.release(held)
        self.assertEqual(self.batch("P1")["quantity_reserved"], 0)
        held = self.res.reserve_many([(self.para, 4)])[self.para]
        self.res.commit(held, "MQ-TEST", "u1")
        b = self.batch("P1")
        self.assertEqual((b["quantity_on_hand"], b["quantity_reserved"]), (16, 0))
        sale = self.sales()[0]
        self.assertEqual((sale["delta"], sale["quantity_after"], sale["reason"], sale["product_id"]), (-4, 16, "MQ-TEST", self.para))
        with self.assertRaises(CommitError):
            self.res.commit(held, "MQ-TEST", "u1")  # reservation already consumed

    def test_allocation_validity_and_exact_units(self):
        held = self.res.reserve_many([(self.para, 2)])[self.para]
        self.assertTrue(self.res.allocations_still_valid(held))
        self.inv.set_status(STAFF, self.batch("P1")["_id"], {"status": "quarantined", "note": "hold"})
        self.assertFalse(self.res.allocations_still_valid(held))
        self.assertEqual(self.res.sellable_units([self.cet, "nope"]), {self.cet: 20, "nope": 0})


class CartTests(Base):
    def test_add_merge_totals_set_remove_clear(self):
        self.cart.add("u1", {"product_id": self.para, "quantity": 2})
        v = self.cart.add("u1", {"product_id": self.para, "quantity": 3})
        self.assertEqual((v["items"][0]["quantity"], v["subtotal_paise"], v["item_count"], v["can_checkout"]), (5, 15000, 5, True))
        v = self.cart.add("u1", {"product_id": self.cet, "quantity": 1})
        self.assertEqual((v["subtotal_paise"], v["total_paise"]), (17500, 17500))
        self.assertEqual(self.cart.set_quantity("u1", self.para, {"quantity": 1})["subtotal_paise"], 5500)
        self.assertEqual(len(self.cart.set_quantity("u1", self.para, {"quantity": 0})["items"]), 1)
        self.assertEqual(len(self.cart.remove("u1", self.cet)["items"]), 0)
        self.cart.add("u1", {"product_id": self.cet, "quantity": 1})
        self.assertEqual(self.cart.clear("u1")["items"], [])
        self.assertFalse(self.cart.view("u1")["can_checkout"])

    def test_prescription_and_restricted_and_unknown_products_rejected(self):
        for pid, code in ((self.rx, "prescription_required"), (self.restricted, "not_purchasable"), ("nope", "not_found")):
            with self.assertRaises(ServiceError) as cm:
                self.cart.add("u1", {"product_id": pid, "quantity": 1})
            self.assertEqual(cm.exception.code, code)
        self.catalogue.deactivate_product(self.cet)
        with self.assertRaises(ServiceError) as cm:
            self.cart.add("u1", {"product_id": self.cet, "quantity": 1})
        self.assertEqual(cm.exception.code, "not_found")
        self.assertEqual(self.carts.docs, {})

    def test_quantity_validation(self):
        for bad in (0, -1, 11, 1.5, True, "2", None):
            with self.assertRaises(ValidationFailed, msg=str(bad)):
                self.cart.add("u1", {"product_id": self.para, "quantity": bad})
        self.cart.add("u1", {"product_id": self.para, "quantity": 10})
        with self.assertRaises(ServiceError):
            self.cart.add("u1", {"product_id": self.para, "quantity": 1})  # 11 total
        with self.assertRaises(ServiceError):
            self.cart.set_quantity("u1", "not-in-cart", {"quantity": 1})

    def test_line_limit(self):
        with mock.patch.object(rules, "MAX_CART_LINES", 1):
            self.cart.add("u1", {"product_id": self.para, "quantity": 1})
            with self.assertRaises(ServiceError) as cm:
                self.cart.add("u1", {"product_id": self.cet, "quantity": 1})
            self.assertEqual(cm.exception.code, "cart_full")
            self.cart.add("u1", {"product_id": self.para, "quantity": 1})  # existing line still fine

    def test_cannot_add_more_than_available(self):
        scarce = self.product("Scarce", 1000)
        self.stock(scarce, "S1", 400, 3)
        with self.assertRaises(ServiceError) as cm:
            self.cart.add("u1", {"product_id": scarce, "quantity": 4})
        self.assertEqual(cm.exception.status, 409)
        self.assertEqual(cm.exception.fields, {"quantity": "Only 3 available."})
        none = self.product("NoStock", 1000)
        with self.assertRaises(ServiceError) as cm:
            self.cart.add("u1", {"product_id": none, "quantity": 1})
        self.assertEqual(cm.exception.message, "Currently out of stock.")

    def test_view_flags_problems_that_appear_after_adding(self):
        self.cart.add("u1", {"product_id": self.para, "quantity": 5})
        self.cart.add("u1", {"product_id": self.cet, "quantity": 2})
        self.inv.adjust(STAFF, self.batch("P1")["_id"], {"delta": -18, "reason": "damage"})   # 2 left
        v = self.cart.view("u1")
        para = next(i for i in v["items"] if i["product_id"] == self.para)
        self.assertEqual((para["problem"], para["available_units"], v["can_checkout"]), ("insufficient_stock", 2, False))
        self.assertEqual(v["subtotal_paise"], 5000)  # only valid lines are totalled
        self.products.update(self.cet, {"schedule": "H", "requires_prescription": True})
        self.assertEqual(next(i for i in self.cart.view("u1")["items"] if i["product_id"] == self.cet)["problem"], "prescription_required")
        self.catalogue.deactivate_product(self.cet)
        self.assertEqual(next(i for i in self.cart.view("u1")["items"] if i["product_id"] == self.cet)["problem"], "unavailable")

    def test_carts_are_per_user(self):
        self.cart.add("u1", {"product_id": self.para, "quantity": 1})
        self.assertEqual(self.cart.view("u2")["items"], [])


class CheckoutTests(Base):
    def test_happy_path(self):
        o = self.place([(self.para, 3), (self.cet, 2)])
        self.assertEqual((o["status"], o["subtotal_paise"], o["total_paise"]), ("pending_payment", 14000, 14000))
        self.assertRegex(o["order_number"], r"^MQ-\d{6}-[0-9A-F]{6}$")
        self.assertEqual(o["reservation_expires_at"], (self.clock.now + timedelta(minutes=15)).isoformat())
        self.assertEqual(o["address"]["pincode"], "411001")
        self.assertEqual(o["payment"]["status"], "unpaid")
        self.assertEqual(self.carts.docs, {})
        b = self.batch("P1")
        self.assertEqual((b["quantity_on_hand"], b["quantity_reserved"]), (20, 3))  # held, not yet sold

    def test_empty_cart_and_bad_address(self):
        with self.assertRaises(ServiceError) as cm:
            self.orders.create("u1", {"address_id": self.addr})
        self.assertEqual(cm.exception.code, "cart_empty")
        self.cart.add("u1", {"product_id": self.para, "quantity": 1})
        for bad in ("nope", self.addr2):  # unknown, and another user's address
            with self.assertRaises(ServiceError) as cm:
                self.orders.create("u1", {"address_id": bad})
            self.assertEqual(cm.exception.status, 400)
        with self.assertRaises(ValidationFailed):
            self.orders.create("u1", {})
        self.assertEqual(len(self.carts.docs["u1"]["items"]), 1)  # the cart was never touched
        self.assertEqual(self.order_repo.docs, {})

    def test_prescription_item_blocks_checkout_and_cart_is_restored(self):
        self.cart.add("u1", {"product_id": self.cet, "quantity": 1})
        self.products.update(self.cet, {"schedule": "H", "requires_prescription": True})  # became Rx after adding
        with self.assertRaises(ServiceError) as cm:
            self.orders.create("u1", {"address_id": self.addr})
        self.assertEqual((cm.exception.code, cm.exception.fields), ("cart_invalid", {self.cet: "prescription_required"}))
        self.assertEqual(len(self.carts.docs["u1"]["items"]), 1)
        self.assertEqual(self.batch("C1")["quantity_reserved"], 0)
        self.assertEqual(self.order_repo.docs, {})

    def test_direct_cart_tampering_cannot_order_rx_or_restricted(self):
        for pid, code in ((self.rx, "prescription_required"), (self.restricted, "not_purchasable")):
            self.carts.save("u1", [{"product_id": pid, "quantity": 1}], self.clock.now)
            with self.assertRaises(ServiceError) as cm:
                self.orders.create("u1", {"address_id": self.addr})
            self.assertEqual(cm.exception.fields, {pid: code})
        self.assertEqual(self.order_repo.docs, {})

    def test_insufficient_stock_rolls_back_everything(self):
        self.cart.add("u1", {"product_id": self.para, "quantity": 5})
        self.cart.add("u1", {"product_id": self.cet, "quantity": 3})
        self.inv.adjust(STAFF, self.batch("C1")["_id"], {"delta": -18, "reason": "damage"})  # 2 left, cart wants 3
        with self.assertRaises(ServiceError) as cm:
            self.orders.create("u1", {"address_id": self.addr})
        self.assertEqual((cm.exception.code, cm.exception.status), ("insufficient_stock", 409))
        self.assertEqual(cm.exception.fields, {self.cet: {"requested": 3, "available": 2}})
        self.assertEqual(self.batch("P1")["quantity_reserved"], 0)   # paracetamol hold was undone
        self.assertEqual(self.batch("C1")["quantity_reserved"], 0)
        self.assertEqual(len(self.carts.docs["u1"]["items"]), 2)
        self.assertEqual(self.order_repo.docs, {})

    def test_double_checkout_creates_one_order(self):
        self.cart.add("u1", {"product_id": self.para, "quantity": 3})
        self.orders.create("u1", {"address_id": self.addr})
        with self.assertRaises(ServiceError) as cm:
            self.orders.create("u1", {"address_id": self.addr})
        self.assertEqual(cm.exception.code, "cart_empty")
        self.assertEqual((len(self.order_repo.docs), self.batch("P1")["quantity_reserved"]), (1, 3))

    def test_crash_after_reservation_releases_stock_and_restores_cart(self):
        self.cart.add("u1", {"product_id": self.para, "quantity": 3})
        with mock.patch.object(self.order_repo, "insert", side_effect=RuntimeError("db down")):
            with self.assertRaises(RuntimeError):
                self.orders.create("u1", {"address_id": self.addr})
        self.assertEqual(self.batch("P1")["quantity_reserved"], 0)
        self.assertEqual(self.carts.docs["u1"]["items"], [{"product_id": self.para, "quantity": 3}])

    def test_restore_never_overwrites_a_newer_cart(self):
        self.cart.add("u1", {"product_id": self.para, "quantity": 3})
        def rebuild_cart_then_fail(lines):
            self.cart.add("u1", {"product_id": self.cet, "quantity": 1})   # shopper rebuilt a cart meanwhile
            raise InsufficientStock(self.para, 3, 0)

        with mock.patch.object(self.res, "reserve_many", side_effect=rebuild_cart_then_fail):
            with self.assertRaises(ServiceError):
                self.orders.create("u1", {"address_id": self.addr})
        self.assertEqual([i["product_id"] for i in self.carts.docs["u1"]["items"]], [self.cet])

    def test_price_snapshot_survives_later_price_change(self):
        o = self.place([(self.para, 2)])
        self.products.update(self.para, {"price_paise": 9000, "mrp_paise": 9500})
        again = self.orders.get("u1", o["id"])
        self.assertEqual((again["lines"][0]["unit_price_paise"], again["total_paise"]), (3000, 6000))

    def test_fefo_allocation_recorded_and_committed_per_batch(self):
        self.stock(self.para, "EARLY", 100, 5)   # earlier expiry than P1 (400 days)
        o = self.place([(self.para, 8)])
        stored = self.order_repo.docs[o["id"]]["lines"][0]["allocations"]
        self.assertEqual({a["batch_number"]: a["quantity"] for a in stored}, {"EARLY": 5, "P1": 3})
        self.orders.pay("u1", o["id"], {})
        self.assertEqual((self.batch("EARLY")["quantity_on_hand"], self.batch("P1")["quantity_on_hand"]), (0, 17))
        self.assertEqual(sorted(-m["delta"] for m in self.sales()), [3, 5])


class PaymentTests(Base):
    def test_pay_success_commits_stock_with_ledger(self):
        o = self.place([(self.para, 3)])
        paid = self.orders.pay("u1", o["id"], {})
        self.assertEqual(paid["status"], "confirmed")
        self.assertEqual((paid["payment"]["status"], paid["payment"]["is_mock"]), ("paid", True))
        self.assertTrue(paid["payment"]["reference"].startswith("MOCK-"))
        self.assertIsNone(paid["reservation_expires_at"])
        b = self.batch("P1")
        self.assertEqual((b["quantity_on_hand"], b["quantity_reserved"]), (17, 0))
        [sale] = self.sales()
        self.assertEqual((sale["delta"], sale["reason"], sale["actor_id"]), (-3, o["order_number"], "u1"))
        history = [h["status"] for h in self.order_repo.docs[o["id"]]["status_history"]]
        self.assertEqual(history, ["pending_payment", "processing_payment", "confirmed"])

    def test_paying_twice_never_deducts_twice(self):
        o = self.place([(self.para, 3)])
        self.orders.pay("u1", o["id"], {})
        again = self.orders.pay("u1", o["id"], {})
        self.assertEqual(again["status"], "confirmed")
        self.assertEqual((self.batch("P1")["quantity_on_hand"], len(self.sales())), (17, 1))

    def test_failed_payment_keeps_reservation_and_allows_retry(self):
        o = self.place([(self.para, 3)])
        with self.assertRaises(ServiceError) as cm:
            self.orders.pay("u1", o["id"], {"simulate": "fail"})
        self.assertEqual(cm.exception.status, 402)
        now = self.orders.get("u1", o["id"])
        self.assertEqual((now["status"], now["payment"]["status"]), ("pending_payment", "failed"))
        self.assertEqual((self.batch("P1")["quantity_on_hand"], self.batch("P1")["quantity_reserved"]), (20, 3))
        self.assertEqual(self.sales(), [])
        self.assertEqual(self.orders.pay("u1", o["id"], {})["status"], "confirmed")

    def test_invalid_simulate_value(self):
        o = self.place([(self.para, 1)])
        with self.assertRaises(ValidationFailed):
            self.orders.pay("u1", o["id"], {"simulate": "yes please"})

    def test_expired_reservation_cannot_be_paid_and_stock_is_freed(self):
        o = self.place([(self.para, 3)])
        self.clock.advance(16)
        with self.assertRaises(ServiceError) as cm:
            self.orders.pay("u1", o["id"], {})
        self.assertEqual(cm.exception.code, "reservation_expired")
        self.assertEqual(self.order_repo.docs[o["id"]]["status"], "expired")
        self.assertEqual((self.batch("P1")["quantity_reserved"], self.sales()), (0, []))

    def test_sweep_expires_only_unpaid_orders(self):
        paid = self.place([(self.para, 2)])
        self.orders.pay("u1", paid["id"], {})
        self.place([(self.para, 3)])
        self.place([(self.cet, 4)], user="u2")
        self.clock.advance(16)
        self.assertEqual(self.orders.release_expired(), 2)
        self.assertEqual(self.orders.release_expired(), 0)   # nothing left, and never released twice
        self.assertEqual((self.batch("P1")["quantity_reserved"], self.batch("C1")["quantity_reserved"]), (0, 0))
        self.assertEqual(self.batch("P1")["quantity_on_hand"], 18)    # the paid order's units stay sold
        self.assertEqual(self.order_repo.docs[paid["id"]]["status"], "confirmed")

    def test_reading_an_order_shows_expiry(self):
        o = self.place([(self.para, 1)])
        self.clock.advance(20)
        self.assertEqual(self.orders.get("u1", o["id"])["status"], "expired")

    def test_recalled_batch_before_payment_cancels_order_without_charging(self):
        o = self.place([(self.para, 3)])
        self.inv.set_status(MANAGER, self.batch("P1")["_id"], {"status": "recalled", "note": "supplier recall"})
        with self.assertRaises(ServiceError) as cm:
            self.orders.pay("u1", o["id"], {})
        self.assertEqual(cm.exception.code, "stock_changed")
        stored = self.order_repo.docs[o["id"]]
        self.assertEqual((stored["status"], stored["payment"]["status"]), ("cancelled", "unpaid"))
        self.assertEqual((self.batch("P1")["quantity_reserved"], self.sales()), (0, []))

    def test_commit_failure_after_payment_goes_to_review_not_silently_lost(self):
        o = self.place([(self.para, 3)])
        with mock.patch.object(self.res, "commit", side_effect=CommitError("boom")):
            with self.assertRaises(ServiceError) as cm:
                self.orders.pay("u1", o["id"], {})
        self.assertEqual(cm.exception.code, "payment_review")
        stored = self.order_repo.docs[o["id"]]
        self.assertEqual((stored["status"], stored["payment"]["status"]), ("payment_review", "paid"))

    def test_two_simultaneous_payments_charge_and_deduct_once(self):
        o = self.place([(self.para, 3)])
        real, state = self.res.allocations_still_valid, {"raced": False}

        def other_request_wins_the_race(allocations):
            if not state["raced"]:
                state["raced"] = True
                self.orders.pay("u1", o["id"], {})   # a second request completes while the first is mid-flight
            return real(allocations)

        with mock.patch.object(self.res, "allocations_still_valid", side_effect=other_request_wins_the_race):
            with self.assertRaises(ServiceError) as cm:
                self.orders.pay("u1", o["id"], {})
        self.assertEqual(cm.exception.code, "conflict")
        self.assertEqual((self.batch("P1")["quantity_on_hand"], len(self.sales())), (17, 1))
        self.assertEqual(self.order_repo.docs[o["id"]]["status"], "confirmed")

    def test_mock_adapter_declares_itself(self):
        self.assertEqual(MockPaymentAdapter.provider, "mock")
        self.assertFalse(MockPaymentAdapter().charge({}, {"simulate": "fail"}).success)


class CancelAndIsolationTests(Base):
    def test_cancel_releases_stock_once(self):
        o = self.place([(self.para, 3)])
        self.assertEqual(self.orders.cancel("u1", o["id"])["status"], "cancelled")
        self.assertEqual(self.batch("P1")["quantity_reserved"], 0)
        with self.assertRaises(ServiceError) as cm:
            self.orders.cancel("u1", o["id"])
        self.assertEqual(cm.exception.code, "invalid_state")
        self.assertEqual(self.batch("P1")["quantity_reserved"], 0)
        with self.assertRaises(ServiceError):
            self.orders.pay("u1", o["id"], {})   # a cancelled order cannot be paid

    def test_confirmed_orders_cannot_be_cancelled_here(self):
        o = self.place([(self.para, 3)])
        self.orders.pay("u1", o["id"], {})
        with self.assertRaises(ServiceError):
            self.orders.cancel("u1", o["id"])
        self.assertEqual(self.batch("P1")["quantity_on_hand"], 17)

    def test_users_cannot_see_or_touch_each_others_orders(self):
        o = self.place([(self.para, 3)])
        for call in (lambda: self.orders.get("u2", o["id"]), lambda: self.orders.pay("u2", o["id"], {}),
                     lambda: self.orders.cancel("u2", o["id"])):
            with self.assertRaises(ServiceError) as cm:
                call()
            self.assertEqual(cm.exception.status, 404)
        for bad in ("nope", None, 5):
            with self.assertRaises(ServiceError):
                self.orders.get("u1", bad)
        self.assertEqual(self.orders.list("u2")["results"], [])
        self.assertEqual(self.orders.list("u1")["total"], 1)
        self.assertEqual(self.order_repo.docs[o["id"]]["status"], "pending_payment")
        self.assertEqual(self.batch("P1")["quantity_reserved"], 3)

    def test_public_order_hides_batch_allocations(self):
        o = self.place([(self.para, 1)])
        self.assertNotIn("allocations", str(o))
        self.assertNotIn("user_id", o)


class StockInvariantTests(Base):
    def assert_books_balance(self):
        held = defaultdict(int)
        for o in self.order_repo.docs.values():
            if o["status"] in ("pending_payment", "processing_payment"):
                for line in o["lines"]:
                    for a in line["allocations"]:
                        held[a["batch_id"]] += a["quantity"]
        for bid, b in self.batches.docs.items():
            self.assertEqual(b["quantity_reserved"], held[bid], "reserved must equal open-order allocations")
            self.assertGreaterEqual(b["quantity_on_hand"], 0)
            self.assertLessEqual(b["quantity_reserved"], b["quantity_on_hand"])
            self.assertEqual(b["quantity_on_hand"], sum(m["delta"] for m in self.movements.docs if m["batch_id"] == bid),
                             "on-hand must equal the sum of ledger changes")
        sold, confirmed = defaultdict(int), defaultdict(int)
        for m in self.sales():
            sold[m["product_id"]] -= m["delta"]
        for o in self.order_repo.docs.values():
            if o["status"] == "confirmed":
                for line in o["lines"]:
                    confirmed[line["product_id"]] += line["quantity"]
        self.assertEqual(dict(sold), dict(confirmed), "units sold must equal units on confirmed orders")

    def test_random_activity_never_oversells_or_leaks_reservations(self):
        rng = random.Random(11)
        users = {"u1": self.addr, "u2": self.addr2}
        placed = {u: [] for u in users}
        refusals = 0
        for _ in range(600):
            user = rng.choice(list(users))
            action = rng.choice(["add", "add", "checkout", "pay", "pay", "cancel", "time", "adjust"])
            try:
                if action == "add":
                    self.cart.add(user, {"product_id": rng.choice([self.para, self.cet]), "quantity": rng.randint(1, 6)})
                elif action == "checkout":
                    placed[user].append(self.orders.create(user, {"address_id": users[user]})["id"])
                elif action == "pay" and placed[user]:
                    self.orders.pay(user, rng.choice(placed[user]), {"simulate": rng.choice([None, "fail", "success"])})
                elif action == "cancel" and placed[user]:
                    self.orders.cancel(user, rng.choice(placed[user]))
                elif action == "time":
                    self.clock.advance(rng.choice([1, 5, 20]))
                elif action == "adjust":
                    self.inv.adjust(STAFF, rng.choice(list(self.batches.docs)),
                                    {"delta": rng.choice([-3, -1, 2, 5]), "reason": "stock_count"})
            except ServiceError:
                refusals += 1
            self.assert_books_balance()
        statuses = {o["status"] for o in self.order_repo.docs.values()}
        self.assertIn("confirmed", statuses)
        self.assertTrue(statuses & {"expired", "cancelled"})
        self.assertGreater(refusals, 0)


if __name__ == "__main__":
    unittest.main()
