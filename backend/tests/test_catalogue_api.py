"""
HTTP-level catalogue tests (need Django + DRF: run with `python manage.py test`).
MongoDB is replaced by in-memory fakes.
"""
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase
from rest_framework.test import APIClient

from apps.catalogue.services import CatalogueService

from .fakes import FakeCategories, FakeProducts
from .test_accounts_api import make_services

PRODUCT = {"name": "Paracetamol 500 mg", "category": "pain-fever", "pack_size": "Strip of 15",
           "price_paise": 3000, "mrp_paise": 3500, "schedule": "OTC"}


class CatalogueApiTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.accounts = make_services()
        self.catalogue = CatalogueService(FakeCategories(), FakeProducts())
        self.catalogue.create_category({"name": "Pain & Fever"})
        for target, value in (("apps.accounts.deps.get_services", self.accounts),
                              ("apps.catalogue.deps.get_service", self.catalogue)):
            p = mock.patch(target, return_value=value)
            p.start()
            self.addCleanup(p.stop)
        self.client = APIClient()

    def _login_as(self, role, email):
        res = self.accounts.auth.register({"email": email, "full_name": "Test User", "password": "a-good-long-pass"})
        if role != "customer":
            self.accounts.users.update(res["user"]["id"], {"role": role})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res['access_token']}")

    def test_browsing_is_public(self):
        self.catalogue.create_product(PRODUCT)
        self.assertEqual(self.client.get("/api/v1/categories/").status_code, 200)
        listing = self.client.get("/api/v1/products/?rx=otc&sort=price_asc")
        self.assertEqual(listing.status_code, 200)
        slug = listing.json()["results"][0]["slug"]
        self.assertEqual(self.client.get(f"/api/v1/products/{slug}/").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/products/nope/").status_code, 404)

    def test_bad_query_params_give_400_with_fields(self):
        res = self.client.get("/api/v1/products/?sort=hack&page_size=9999")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(set(res.json()["error"]["fields"]), {"sort", "page_size"})

    def test_manage_endpoints_enforce_roles(self):
        self.assertEqual(self.client.post("/api/v1/manage/products/", PRODUCT, format="json").status_code, 401)
        self._login_as("customer", "cust@example.com")
        self.assertEqual(self.client.post("/api/v1/manage/products/", PRODUCT, format="json").status_code, 403)
        self._login_as("pharmacist", "ph@example.com")
        self.assertEqual(self.client.post("/api/v1/manage/products/", PRODUCT, format="json").status_code, 403)
        self._login_as("pharmacy_manager", "mgr@example.com")
        created = self.client.post("/api/v1/manage/products/", PRODUCT, format="json")
        self.assertEqual(created.status_code, 201)
        pid = created.json()["id"]
        self.assertEqual(self.client.patch(f"/api/v1/manage/products/{pid}/", {"schedule": "H"}, format="json").json()["requires_prescription"], True)
        self.assertEqual(self.client.delete(f"/api/v1/manage/products/{pid}/").status_code, 204)
        self.assertEqual(self.client.get("/api/v1/products/").json()["total"], 0)
