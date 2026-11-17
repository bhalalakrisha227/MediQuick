"""
HTTP-level cancel / fulfilment / return / refund tests (need Django + DRF: run with `python manage.py test`).
MongoDB is replaced by in-memory fakes.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase
from rest_framework.test import APIClient

from apps.catalogue.services import CatalogueService
from apps.inventory.reservations import ReservationService
from apps.inventory.services import InventoryService
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


class LifecycleApiTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.accounts = make_services()
        products, batches, movements = FakeProducts(), FakeBatches(), FakeMovements()
        catalogue = CatalogueService(FakeCategories(), products)
        catalogue.create_category({"name": "Pain & Fever"})
        self.para = catalogue.create_product({"name": "Paracetamol", "category": "pain-fever", "pack_size": "Strip",
                                              "price_paise": 3000, "mrp_paise": 3500, "schedule": "OTC"})["id"]
        InventoryService(batches, movements, products).receive(
            {"id": "staff", "role": "inventory_staff"},
            {"product_id": self.para, "batch_number": "B1", "expiry_date": (datetime.now(timezone.utc).date() + timedelta(days=400)).isoformat(),
             "quantity": 50})
        reservations, carts, order_repo = ReservationService(batches, movements), FakeCarts(), FakeOrders()
        orders = OrderService(carts, order_repo, products, self.accounts.addresses.addresses, reservations, MockPaymentAdapter())
        refunds = RefundService(FakeRefunds(), order_repo, MockPaymentAdapter(), orders.clock)
        self.services = SimpleNamespace(
            cart=CartService(carts, products, reservations), orders=orders,
            lifecycle=LifecycleService(orders, order_repo, FakeReturns(), refunds, reservations, None, orders.clock))
        for target, value in (("apps.accounts.deps.get_services", self.accounts), ("apps.orders.deps.get_services", self.services)):
            p = mock.patch(target, return_value=value)
            p.start()
            self.addCleanup(p.stop)
        self.client, self.n = APIClient(), 0

    def login(self, role="customer"):
        self.n += 1
        res = self.accounts.auth.register({"email": f"u{self.n}@example.com", "full_name": "Test User", "password": "a-good-long-pass"})
        if role != "customer":
            self.accounts.users.update(res["user"]["id"], {"role": role})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res['access_token']}")
        return res["user"]["id"]

    def paid_order(self):
        self.login()
        address_id = self.client.post("/api/v1/me/addresses/", ADDR, format="json").json()["id"]
        self.client.post("/api/v1/cart/items/", {"product_id": self.para, "quantity": 2}, format="json")
        oid = self.client.post("/api/v1/orders/", {"address_id": address_id}, format="json").json()["id"]
        self.client.post(f"/api/v1/orders/{oid}/pay/", {}, format="json")
        return oid

    def test_staff_endpoints_need_the_right_role(self):
        for role in ("customer", "pharmacist", "inventory_staff"):
            self.login(role)
            for method, url in (("get", "/api/v1/staff/orders/"), ("get", "/api/v1/staff/refunds/"), ("get", "/api/v1/staff/returns/")):
                self.assertEqual(getattr(self.client, method)(url).status_code, 403, (role, url))
        self.client.credentials()
        self.assertEqual(self.client.get("/api/v1/staff/orders/").status_code, 401)

    def test_cancel_paid_order_refunds(self):
        oid = self.paid_order()
        res = self.client.post(f"/api/v1/orders/{oid}/cancel/")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual((body["status"], body["refund"]["status"], body["payment"]["status"]), ("cancelled", "succeeded", "refunded"))
        self.assertEqual(self.client.post(f"/api/v1/orders/{oid}/cancel/").status_code, 409)

    def test_full_delivery_and_return_flow(self):
        oid = self.paid_order()
        customer_auth = dict(self.client._credentials)
        self.login("pharmacy_manager")
        self.assertEqual(self.client.post(f"/api/v1/staff/orders/{oid}/dispatch/").json()["status"], "dispatched")
        self.assertEqual(self.client.post(f"/api/v1/staff/orders/{oid}/deliver/").json()["status"], "delivered")
        self.client.credentials(**customer_auth)
        ret = self.client.post(f"/api/v1/orders/{oid}/returns/", {"reason": "damaged", "items": [{"product_id": self.para, "quantity": 1}]},
                               format="json")
        self.assertEqual((ret.status_code, ret.json()["amount_paise"]), (201, 3000))
        self.login("support_agent")
        self.assertEqual(len(self.client.get("/api/v1/staff/returns/").json()["results"]), 1)
        done = self.client.post(f"/api/v1/staff/returns/{ret.json()['id']}/decision/", {"decision": "approve"}, format="json")
        self.assertEqual((done.status_code, done.json()["refund"]["status"]), (200, "succeeded"))
        self.client.credentials(**customer_auth)
        shown = self.client.get(f"/api/v1/orders/{oid}/returns/").json()
        self.assertEqual((shown["returns"][0]["status"], shown["refunds"][0]["amount_paise"]), ("approved", 3000))
        self.assertEqual(self.client.get(f"/api/v1/orders/{oid}/").json()["payment"]["status"], "partially_refunded")

    def test_customer_cannot_use_staff_actions_or_see_others_returns(self):
        oid = self.paid_order()
        self.assertEqual(self.client.post(f"/api/v1/staff/orders/{oid}/dispatch/").status_code, 403)
        self.login()
        self.assertEqual(self.client.get(f"/api/v1/orders/{oid}/returns/").status_code, 404)
        self.assertEqual(self.client.post(f"/api/v1/orders/{oid}/cancel/").status_code, 404)
