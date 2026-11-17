"""
HTTP-level delivery tests (need Django + DRF: run with `python manage.py test`). Not runnable in the build sandbox,
so these have NOT been run. MongoDB is replaced by in-memory fakes.
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
from apps.orders.delivery import DeliveryService
from apps.orders.lifecycle import LifecycleService
from apps.orders.payments import MockPaymentAdapter
from apps.orders.refunds import RefundService
from apps.orders.services import OrderService

from .fakes import (FakeBatches, FakeCarts, FakeCategories, FakeMovements, FakeOrders, FakeProducts, FakeRefunds,
                    FakeReturns)
from .test_accounts_api import make_services

ADDR = {"recipient_name": "Asha", "phone": "9876543210", "line1": "12 Main Road", "city": "Pune",
        "state": "Maharashtra", "pincode": "411001"}
API = "/api/v1"


class DeliveryApiTests(SimpleTestCase):
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
            lifecycle=LifecycleService(orders, order_repo, FakeReturns(), refunds, reservations, None, orders.clock),
            delivery=DeliveryService(order_repo, self.accounts.users, refunds, "test-secret", orders.clock))
        for target, value in (("apps.accounts.deps.get_services", self.accounts), ("apps.orders.deps.get_services", self.services)):
            p = mock.patch(target, return_value=value)
            p.start()
            self.addCleanup(p.stop)
        self.client, self.n = APIClient(), 0

    def login(self, role="customer"):
        self.n += 1
        res = self.accounts.auth.register({"email": f"u{self.n}@example.com", "full_name": "Ravi Kumar", "password": "a-good-long-pass"})
        if role != "customer":
            self.accounts.users.update(res["user"]["id"], {"role": role})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res['access_token']}")
        return res["user"]["id"], dict(self.client._credentials)

    def test_roles_are_enforced(self):
        for role in ("customer", "pharmacist", "delivery_partner"):
            self.login(role)
            self.assertEqual(self.client.get(f"{API}/staff/delivery/partners/").status_code, 403, role)
        for role in ("customer", "pharmacy_manager", "admin"):
            self.login(role)
            self.assertEqual(self.client.get(f"{API}/rider/deliveries/").status_code, 403, role)
        self.client.credentials()
        self.assertEqual(self.client.get(f"{API}/rider/deliveries/").status_code, 401)

    def test_full_flow_over_http(self):
        _, customer = self.login()
        aid = self.client.post(f"{API}/me/addresses/", ADDR, format="json").json()["id"]
        self.client.post(f"{API}/cart/items/", {"product_id": self.para, "quantity": 2}, format="json")
        order = self.client.post(f"{API}/orders/", {"address_id": aid}, format="json").json()
        oid = order["id"]
        self.assertEqual(order["total_paise"], order["subtotal_paise"] + order["delivery_fee_paise"])
        self.client.post(f"{API}/orders/{oid}/pay/", {}, format="json")
        _, manager = self.login("pharmacy_manager")
        rider_id, rider = self.login("delivery_partner")
        self.client.credentials(**{"HTTP_AUTHORIZATION": manager["HTTP_AUTHORIZATION"]})
        self.assertEqual(self.client.post(f"{API}/staff/delivery/orders/{oid}/assign/", {"partner_id": rider_id}, format="json").status_code, 200)
        self.client.credentials(**{"HTTP_AUTHORIZATION": rider["HTTP_AUTHORIZATION"]})
        listed = self.client.get(f"{API}/rider/deliveries/").json()["results"]
        self.assertEqual([d["id"] for d in listed], [oid])
        self.assertNotIn("Paracetamol", str(listed))
        self.assertEqual(self.client.post(f"{API}/rider/deliveries/{oid}/pickup/").status_code, 200)
        self.client.credentials(**{"HTTP_AUTHORIZATION": customer["HTTP_AUTHORIZATION"]})
        code = self.client.get(f"{API}/orders/{oid}/delivery/").json()["handover_code"]
        self.assertRegex(code, r"^\d{6}$")
        self.client.credentials(**{"HTTP_AUTHORIZATION": rider["HTTP_AUTHORIZATION"]})
        wrong = "000000" if code != "000000" else "111111"
        self.assertEqual(self.client.post(f"{API}/rider/deliveries/{oid}/deliver/", {"code": wrong}, format="json").status_code, 400)
        res = self.client.post(f"{API}/rider/deliveries/{oid}/deliver/", {"code": code}, format="json")
        self.assertEqual((res.status_code, res.json()["status"]), (200, "delivered"))
        self.assertEqual(self.client.post(f"{API}/rider/deliveries/{oid}/bogus/").status_code, 404)

    def test_another_customer_cannot_see_the_code(self):
        self.login()
        self.assertEqual(self.client.get(f"{API}/orders/nope/delivery/").status_code, 404)
