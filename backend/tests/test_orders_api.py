"""
HTTP-level cart/order tests (need Django + DRF: run with `python manage.py test`).
MongoDB is replaced by in-memory fakes.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIClient

from apps.catalogue.services import CatalogueService
from apps.inventory.reservations import ReservationService
from apps.inventory.services import InventoryService
from apps.orders import deps as orders_deps
from apps.orders.cart import CartService
from apps.orders.lifecycle import LifecycleService
from apps.orders.payments import MockPaymentAdapter
from apps.orders.refunds import RefundService
from apps.orders.services import OrderService

from .fakes import (FakeBatches, FakeCarts, FakeCategories, FakeMovements, FakeOrders, FakeProducts, FakeRefunds,
                    FakeReturns)
from .test_accounts_api import make_services

ADDR = {"recipient_name": "Asha", "phone": "9876543210", "line1": "12 Main Road", "city": "Pune",
        "state": "Maharashtra", "pincode": "411001"}


def future(days):
    return (datetime.now(timezone.utc).date() + timedelta(days=days)).isoformat()


class OrdersApiTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.accounts = make_services()
        products, batches, movements = FakeProducts(), FakeBatches(), FakeMovements()
        catalogue = CatalogueService(FakeCategories(), products)
        catalogue.create_category({"name": "Pain & Fever"})
        make = lambda name, sched="OTC": catalogue.create_product({
            "name": name, "category": "pain-fever", "pack_size": "Strip", "price_paise": 3000,
            "mrp_paise": 3500, "schedule": sched})["id"]
        self.para, self.rx = make("Paracetamol"), make("Amoxicillin", "H")
        InventoryService(batches, movements, products).receive(
            {"id": "staff", "role": "inventory_staff"},
            {"product_id": self.para, "batch_number": "B1", "expiry_date": future(400), "quantity": 20})
        reservations = ReservationService(batches, movements)
        carts = FakeCarts()
        order_repo = FakeOrders()
        orders = OrderService(carts, order_repo, products, self.accounts.addresses.addresses, reservations, MockPaymentAdapter())
        refunds = RefundService(FakeRefunds(), order_repo, MockPaymentAdapter(), orders.clock)
        self.orders_services = SimpleNamespace(
            cart=CartService(carts, products, reservations), orders=orders,
            lifecycle=LifecycleService(orders, order_repo, FakeReturns(), refunds, reservations, None, orders.clock))
        for target, value in (("apps.accounts.deps.get_services", self.accounts),
                              ("apps.orders.deps.get_services", self.orders_services)):
            p = mock.patch(target, return_value=value)
            p.start()
            self.addCleanup(p.stop)
        self.client = APIClient()

    def login(self, email):
        res = self.accounts.auth.register({"email": email, "full_name": "Test User", "password": "a-good-long-pass"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res['access_token']}")
        return res["user"]["id"]

    def test_everything_requires_login(self):
        for url in ("/api/v1/cart/", "/api/v1/orders/"):
            self.assertEqual(self.client.get(url).status_code, 401)

    def test_cart_rules(self):
        self.login("a@example.com")
        ok = self.client.post("/api/v1/cart/items/", {"product_id": self.para, "quantity": 2}, format="json")
        self.assertEqual((ok.status_code, ok.json()["subtotal_paise"]), (201, 6000))
        rx = self.client.post("/api/v1/cart/items/", {"product_id": self.rx, "quantity": 1}, format="json")
        self.assertEqual((rx.status_code, rx.json()["error"]["code"]), (400, "prescription_required"))
        bad = self.client.post("/api/v1/cart/items/", {"product_id": self.para, "quantity": 99}, format="json")
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.client.patch(f"/api/v1/cart/items/{self.para}/", {"quantity": 0}, format="json").json()["items"], [])

    def test_full_order_flow_and_isolation(self):
        self.login("a@example.com")
        addr = self.client.post("/api/v1/me/addresses/", ADDR, format="json").json()["id"]
        self.client.post("/api/v1/cart/items/", {"product_id": self.para, "quantity": 3}, format="json")
        order = self.client.post("/api/v1/orders/", {"address_id": addr}, format="json")
        self.assertEqual((order.status_code, order.json()["status"]), (201, "pending_payment"))
        oid = order.json()["id"]
        failed = self.client.post(f"/api/v1/orders/{oid}/pay/", {"simulate": "fail"}, format="json")
        self.assertEqual(failed.status_code, 402)
        paid = self.client.post(f"/api/v1/orders/{oid}/pay/", {}, format="json")
        self.assertEqual((paid.status_code, paid.json()["status"], paid.json()["payment"]["is_mock"]), (200, "confirmed", True))
        self.assertEqual(self.client.get("/api/v1/orders/").json()["total"], 1)
        self.login("b@example.com")  # another customer
        self.assertEqual(self.client.get(f"/api/v1/orders/{oid}/").status_code, 404)
        self.assertEqual(self.client.post(f"/api/v1/orders/{oid}/cancel/").status_code, 404)
        self.assertEqual(self.client.get("/api/v1/orders/").json()["total"], 0)


class MockPaymentGuardTests(SimpleTestCase):
    @override_settings(DEBUG=True, PAYMENT_PROVIDER="mock")
    def test_mock_allowed_in_debug(self):
        self.assertEqual(orders_deps.build_payment_adapter().provider, "mock")

    @override_settings(DEBUG=False, PAYMENT_PROVIDER="mock")
    def test_mock_refused_when_not_debug(self):
        with self.assertRaises(ImproperlyConfigured):
            orders_deps.build_payment_adapter()

    @override_settings(DEBUG=True, PAYMENT_PROVIDER="stripe")
    def test_unknown_provider_refused(self):
        with self.assertRaises(ImproperlyConfigured):
            orders_deps.build_payment_adapter()
