"""
HTTP-level inventory tests (need Django + DRF: run with `python manage.py test`).
MongoDB is replaced by in-memory fakes.
"""
from datetime import datetime, timedelta, timezone
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase
from rest_framework.test import APIClient

from apps.catalogue.services import CatalogueService
from apps.inventory.services import AvailabilityService, InventoryService

from .fakes import FakeBatches, FakeCategories, FakeMovements, FakeProducts
from .test_accounts_api import make_services


def future(days):
    return (datetime.now(timezone.utc).date() + timedelta(days=days)).isoformat()


class InventoryApiTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.accounts = make_services()
        products, batches = FakeProducts(), FakeBatches()
        self.inventory = InventoryService(batches, FakeMovements(), products)
        self.catalogue = CatalogueService(FakeCategories(), products, availability=AvailabilityService(batches))
        self.catalogue.create_category({"name": "Pain & Fever"})
        self.product = self.catalogue.create_product({
            "name": "Paracetamol", "category": "pain-fever", "pack_size": "Strip",
            "price_paise": 3000, "mrp_paise": 3500, "schedule": "OTC"})
        for target, value in (("apps.accounts.deps.get_services", self.accounts),
                              ("apps.inventory.deps.get_service", self.inventory),
                              ("apps.catalogue.deps.get_service", self.catalogue)):
            p = mock.patch(target, return_value=value)
            p.start()
            self.addCleanup(p.stop)
        self.client = APIClient()
        self.n = 0

    def login_as(self, role):
        self.n += 1
        res = self.accounts.auth.register({"email": f"u{self.n}@example.com", "full_name": "Test User",
                                           "password": "a-good-long-pass"})
        if role != "customer":
            self.accounts.users.update(res["user"]["id"], {"role": role})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res['access_token']}")

    def receive_payload(self, number="B1", qty=40):
        return {"product_id": self.product["id"], "batch_number": number, "expiry_date": future(400), "quantity": qty}

    def test_role_matrix(self):
        url = "/api/v1/inventory/batches/"
        self.assertEqual(self.client.get(url).status_code, 401)
        self.login_as("customer")
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, self.receive_payload(), format="json").status_code, 403)
        self.login_as("pharmacist")  # may look, not change
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.post(url, self.receive_payload(), format="json").status_code, 403)
        self.login_as("inventory_staff")
        self.assertEqual(self.client.post(url, self.receive_payload(), format="json").status_code, 201)

    def test_receive_adjust_and_public_availability(self):
        self.login_as("inventory_staff")
        batch = self.client.post("/api/v1/inventory/batches/", self.receive_payload(qty=40), format="json").json()
        self.assertEqual(batch["quantity_on_hand"], 40)
        out = self.client.post(f"/api/v1/inventory/batches/{batch['id']}/adjust/", {"delta": -35, "reason": "damage"}, format="json")
        self.assertEqual(out.json()["quantity_on_hand"], 5)
        too_much = self.client.post(f"/api/v1/inventory/batches/{batch['id']}/adjust/", {"delta": -6, "reason": "damage"}, format="json")
        self.assertEqual(too_much.status_code, 409)
        moves = self.client.get(f"/api/v1/inventory/batches/{batch['id']}/movements/").json()["results"]
        self.assertEqual([m["delta"] for m in moves], [-35, 40])
        self.client.credentials()  # anonymous shopper sees status only
        product = self.client.get(f"/api/v1/products/{self.product['slug']}/").json()
        self.assertEqual(set(product["availability"]), {"status", "earliest_expiry"})
        self.assertEqual(product["availability"]["status"], "low_stock")

    def test_recall_needs_manager(self):
        self.login_as("inventory_staff")
        batch = self.client.post("/api/v1/inventory/batches/", self.receive_payload(), format="json").json()
        url = f"/api/v1/inventory/batches/{batch['id']}/status/"
        body = {"status": "recalled", "note": "supplier notice"}
        self.assertEqual(self.client.post(url, body, format="json").status_code, 403)
        self.login_as("pharmacy_manager")
        self.assertEqual(self.client.post(url, body, format="json").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/inventory/overview/").status_code, 200)
