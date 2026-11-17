"""
HTTP-level pharmacist-portal tests (need Django + DRF: run with `python manage.py test`).
MongoDB is replaced by in-memory fakes, storage by a temp folder, OCR by a fake runner.
"""
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from rest_framework.test import APIClient

from apps.catalogue.services import CatalogueService
from apps.prescriptions.allowance import AllowanceService
from apps.prescriptions.ocr.engines.base import OcrResult
from apps.prescriptions.review import ReviewService
from apps.prescriptions.services import PrescriptionService
from apps.prescriptions.storage import FileStorage

from .fakes import FakeCategories, FakePrescriptions, FakeProducts
from .test_accounts_api import make_services
from .test_prescription_files import make_png

REG = "MH-12345"


class ReviewApiTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.accounts = make_services()
        products = FakeProducts()
        cat = CatalogueService(FakeCategories(), products)
        cat.create_category({"name": "Infection Care"})
        self.rx = cat.create_product({"name": "Amoxicillin 500 mg Capsules", "category": "infection-care", "pack_size": "Strip",
                                      "price_paise": 9500, "mrp_paise": 11000, "schedule": "H"})["id"]
        repo = FakePrescriptions()
        self.repo = repo
        presc = PrescriptionService(repo, FileStorage(Path(self._tmp.name) / "p"), products, SimpleNamespace(name="fake"),
                                    ocr_runner=lambda *a, **k: OcrResult("x", [], "fake"))
        self.presc = presc
        self.services = SimpleNamespace(prescriptions=presc, review=ReviewService(repo, products),
                                        allowances=AllowanceService(repo))
        for target, value in (("apps.accounts.deps.get_services", self.accounts),
                              ("apps.prescriptions.deps.get_services", self.services)):
            p = mock.patch(target, return_value=value)
            p.start()
            self.addCleanup(p.stop)
        self.client = APIClient()
        self.n = 0

    def login(self, role="customer"):
        self.n += 1
        res = self.accounts.auth.register({"email": f"u{self.n}@example.com", "full_name": f"User {self.n}", "password": "a-good-long-pass"})
        if role != "customer":
            self.accounts.users.update(res["user"]["id"], {"role": role})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res['access_token']}")
        return res["user"]["id"]

    def customer_submits(self):
        self.login()
        res = self.client.post("/api/v1/prescriptions/", {"file": SimpleUploadedFile("rx.png", make_png(5 + self.n, 3), content_type="image/png"),
                                                          "consent": "true"}, format="multipart")
        pid = res.json()["id"]
        self.presc.process(pid)
        self.assertEqual(self.client.post(f"/api/v1/prescriptions/{pid}/submit/").status_code, 200)
        return pid

    def test_everything_requires_login(self):
        for method, url in (("get", "/api/v1/staff/prescriptions/"), ("get", "/api/v1/staff/prescriptions/x/"),
                            ("post", "/api/v1/staff/prescriptions/x/claim/"), ("post", "/api/v1/staff/prescriptions/x/approve/"),
                            ("get", "/api/v1/prescriptions/allowances/")):
            self.assertEqual(getattr(self.client, method)(url).status_code, 401, url)

    def test_role_matrix(self):
        pid = self.customer_submits()
        for role in ("customer", "inventory_staff", "delivery_partner", "support_agent"):
            self.login(role)
            self.assertEqual(self.client.get("/api/v1/staff/prescriptions/").status_code, 403, role)
            self.assertEqual(self.client.get(f"/api/v1/staff/prescriptions/{pid}/").status_code, 403, role)
            self.assertEqual(self.client.post(f"/api/v1/staff/prescriptions/{pid}/claim/").status_code, 403, role)
        for role in ("pharmacy_manager", "admin"):
            self.login(role)
            self.assertEqual(self.client.get("/api/v1/staff/prescriptions/").status_code, 200, role)
            self.assertEqual(self.client.get(f"/api/v1/staff/prescriptions/{pid}/").status_code, 200, role)
            for action in ("claim", "approve", "reject", "clarify"):
                self.assertEqual(self.client.post(f"/api/v1/staff/prescriptions/{pid}/{action}/", {}, format="json").status_code, 403, f"{role} {action}")
        self.assertEqual(self.repo.docs[pid]["status"], "submitted")

    def test_pharmacist_full_flow_and_customer_sees_outcome(self):
        pid = self.customer_submits()
        customer_token = self.client._credentials["HTTP_AUTHORIZATION"]
        self.login("pharmacist")
        listing = self.client.get("/api/v1/staff/prescriptions/").json()["results"]
        self.assertEqual([r["id"] for r in listing], [pid])
        self.assertEqual(self.client.post(f"/api/v1/staff/prescriptions/{pid}/claim/").status_code, 200)
        early = self.client.post(f"/api/v1/staff/prescriptions/{pid}/approve/", {"items": [{"product_id": self.rx, "max_quantity": 5}],
                                 "registration_number": REG, "attest_original_checked": True}, format="json")
        self.assertEqual((early.status_code, early.json()["error"]["code"]), (409, "open_original_first"))
        self.assertEqual(self.client.get(f"/api/v1/prescriptions/{pid}/file/").status_code, 200)
        ok = self.client.post(f"/api/v1/staff/prescriptions/{pid}/approve/", {"items": [{"product_id": self.rx, "max_quantity": 5}],
                              "registration_number": REG, "attest_original_checked": True, "valid_days": 20}, format="json")
        self.assertEqual((ok.status_code, ok.json()["status"]), (200, "approved"))
        self.client.credentials(HTTP_AUTHORIZATION=customer_token)
        mine = self.client.get(f"/api/v1/prescriptions/{pid}/").json()
        self.assertEqual(mine["review"]["approval"]["items"][0]["remaining"], 5)
        self.assertNotIn(REG, str(mine))
        allowances = self.client.get("/api/v1/prescriptions/allowances/").json()["results"]
        self.assertEqual(allowances[0]["items"][0]["remaining"], 5)

    def test_pharmacist_cannot_review_own_prescription(self):
        pharmacist_id = self.login("pharmacist")
        res = self.client.post("/api/v1/prescriptions/", {"file": SimpleUploadedFile("rx.png", make_png(9, 9), content_type="image/png"),
                                                          "consent": "true"}, format="multipart")
        pid = res.json()["id"]
        self.presc.process(pid)
        self.client.post(f"/api/v1/prescriptions/{pid}/submit/")
        claim = self.client.post(f"/api/v1/staff/prescriptions/{pid}/claim/")
        self.assertEqual((claim.status_code, claim.json()["error"]["code"]), (403, "own_prescription"))
        self.assertEqual(self.repo.docs[pid]["user_id"], pharmacist_id)

    def test_other_customer_cannot_see_allowances_or_prescription(self):
        pid = self.customer_submits()
        self.login()
        self.assertEqual(self.client.get(f"/api/v1/prescriptions/{pid}/").status_code, 404)
        self.assertEqual(self.client.get("/api/v1/prescriptions/allowances/").json(), {"results": []})
