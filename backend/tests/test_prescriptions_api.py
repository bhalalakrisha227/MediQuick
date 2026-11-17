"""
HTTP-level prescription tests (need Django + DRF: run with `python manage.py test`).
MongoDB is replaced by in-memory fakes, storage by a temp folder, OCR by a fake runner.
"""
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIClient

from apps.catalogue.services import CatalogueService
from apps.prescriptions.ocr.engines.base import OcrResult
from apps.prescriptions.services import PrescriptionService
from apps.prescriptions.storage import FileStorage

from .fakes import FakeCategories, FakePrescriptions, FakeProducts
from .test_accounts_api import make_services
from .test_prescription_files import make_png

LINES = [{"text": "Tab Paracetamol 500mg 1-0-1 x 5 days", "confidence": 90.0}]


class PrescriptionApiTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.accounts = make_services()
        products = FakeProducts()
        cat = CatalogueService(FakeCategories(), products)
        cat.create_category({"name": "Pain & Fever"})
        self.para = cat.create_product({"name": "Paracetamol 500 mg Tablets", "category": "pain-fever", "pack_size": "Strip",
                                        "price_paise": 3000, "mrp_paise": 3500, "schedule": "OTC"})["id"]
        self.repo = FakePrescriptions()
        self.svc = PrescriptionService(
            self.repo, FileStorage(Path(self._tmp.name) / "p"), products, SimpleNamespace(name="fake"),
            ocr_runner=lambda *a, **k: OcrResult("x", LINES, "fake"), max_bytes=1024 * 1024)
        for target, value in (("apps.accounts.deps.get_services", self.accounts),
                              ("apps.prescriptions.deps.get_services", SimpleNamespace(prescriptions=self.svc))):
            p = mock.patch(target, return_value=value)
            p.start()
            self.addCleanup(p.stop)
        self.client = APIClient()

    def login(self, email, role="customer"):
        res = self.accounts.auth.register({"email": email, "full_name": "Test User", "password": "a-good-long-pass"})
        if role != "customer":
            self.accounts.users.update(res["user"]["id"], {"role": role})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res['access_token']}")
        return res["user"]["id"]

    def upload(self, data=None, consent="true", name="rx.png", **extra):
        payload = {"file": SimpleUploadedFile(name, data or make_png(4, 3), content_type="image/png"), **extra}
        if consent is not None:
            payload["consent"] = consent
        return self.client.post("/api/v1/prescriptions/", payload, format="multipart")

    def test_everything_requires_login(self):
        for method, url in (("get", "/api/v1/prescriptions/"), ("post", "/api/v1/prescriptions/"),
                            ("get", "/api/v1/prescriptions/x/"), ("get", "/api/v1/prescriptions/x/file/"),
                            ("post", "/api/v1/prescriptions/x/submit/")):
            self.assertEqual(getattr(self.client, method)(url).status_code, 401, url)

    def test_upload_review_submit_flow(self):
        self.login("a@example.com")
        res = self.upload()
        self.assertEqual((res.status_code, res.json()["status"]), (201, "processing"))
        pid = res.json()["id"]
        self.svc.process(pid)
        detail = self.client.get(f"/api/v1/prescriptions/{pid}/").json()
        self.assertEqual(detail["status"], "needs_customer_review")
        self.assertEqual(detail["ocr"]["candidates"][0]["suggestions"][0]["product_id"], self.para)
        patched = self.client.patch(f"/api/v1/prescriptions/{pid}/", {"items": [{"name": "Paracetamol", "product_id": self.para}]}, format="json")
        self.assertEqual(patched.status_code, 200)
        done = self.client.post(f"/api/v1/prescriptions/{pid}/submit/")
        self.assertEqual((done.status_code, done.json()["status"]), (200, "submitted"))
        self.assertEqual(self.client.post(f"/api/v1/prescriptions/{pid}/withdraw/").status_code, 409)

    def test_upload_requires_consent_and_file(self):
        self.login("a@example.com")
        self.assertEqual(self.upload(consent=None).json()["error"]["code"], "consent_required")
        self.assertEqual(self.upload(consent="false").status_code, 400)
        self.assertEqual(self.client.post("/api/v1/prescriptions/", {"consent": "true"}, format="multipart").status_code, 400)

    def test_bad_files_rejected_by_content_not_name(self):
        self.login("a@example.com")
        res = self.upload(data=b"MZ" + b"0" * 100, name="rx.png")
        self.assertEqual((res.status_code, res.json()["error"]["code"]), (400, "unsupported_type"))

    def test_too_large_is_413(self):
        self.login("a@example.com")
        with override_settings(MAX_UPLOAD_SIZE_MB=1):
            res = self.upload(data=make_png() + b"0" * (1024 * 1024 + 10))
        self.assertEqual(res.status_code, 413)

    def test_other_customer_gets_404_everywhere(self):
        self.login("a@example.com")
        pid = self.upload().json()["id"]
        self.svc.process(pid)
        self.login("b@example.com")
        for method, url in (("get", f"/api/v1/prescriptions/{pid}/"), ("get", f"/api/v1/prescriptions/{pid}/file/"),
                            ("post", f"/api/v1/prescriptions/{pid}/submit/"), ("post", f"/api/v1/prescriptions/{pid}/withdraw/"),
                            ("post", f"/api/v1/prescriptions/{pid}/retry-ocr/")):
            self.assertEqual(getattr(self.client, method)(url).status_code, 404, url)
        self.assertEqual(self.client.get("/api/v1/prescriptions/").json()["results"], [])

    def test_file_download_headers_and_staff_rule(self):
        self.login("a@example.com")
        data = make_png(9, 9)
        pid = self.upload(data=data).json()["id"]
        self.svc.process(pid)
        own = self.client.get(f"/api/v1/prescriptions/{pid}/file/")
        self.assertEqual(own.status_code, 200)
        self.assertEqual(own.content, data)
        self.assertEqual(own["X-Content-Type-Options"], "nosniff")
        self.assertIn("no-store", own["Cache-Control"])
        self.assertTrue(own["Content-Disposition"].startswith("attachment"))
        self.client.post(f"/api/v1/prescriptions/{pid}/submit/")   # still the customer
        self.login("rph@example.com", role="pharmacist")
        self.assertEqual(self.client.get(f"/api/v1/prescriptions/{pid}/file/").status_code, 200)
        self.assertEqual(len(self.repo.access), 1)
        self.login("inv@example.com", role="inventory_staff")
        self.assertEqual(self.client.get(f"/api/v1/prescriptions/{pid}/file/").status_code, 404)

    def test_pharmacist_cannot_read_unsubmitted_file(self):
        self.login("a@example.com")
        pid = self.upload().json()["id"]
        self.svc.process(pid)
        self.login("rph@example.com", role="pharmacist")
        self.assertEqual(self.client.get(f"/api/v1/prescriptions/{pid}/file/").status_code, 404)

    def test_upload_is_rate_limited(self):
        self.login("a@example.com")
        codes = [self.upload(data=make_png(3 + i, 3)).status_code for i in range(12)]
        self.assertIn(429, codes)
