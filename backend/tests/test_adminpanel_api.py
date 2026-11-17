"""
HTTP-level admin tests (need Django + DRF: run with `python manage.py test`). NOT run in the build sandbox.
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase
from rest_framework.test import APIClient

from apps.adminpanel.analytics import AnalyticsService
from apps.adminpanel.attention import AttentionService, AuditLog
from apps.adminpanel.users import UserAdminService

from .fakes import FakeAudit, FakeOrders, FakePrescriptions, FakeRefunds
from .test_accounts_api import make_services

API = "/api/v1/admin"


class AdminApiTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.accounts = make_services()
        clock = lambda: datetime.now(timezone.utc)
        orders, audit = FakeOrders(), AuditLog(FakeAudit(), clock)
        attention = AttentionService(orders, FakeRefunds(), audit, clock)
        self.services = SimpleNamespace(
            analytics=AnalyticsService(orders, FakePrescriptions(), lambda: {}, attention.counts, clock),
            attention=attention, users=UserAdminService(self.accounts.users, audit, clock), audit=audit)
        for target, value in (("apps.accounts.deps.get_services", self.accounts), ("apps.adminpanel.deps.get_services", self.services)):
            p = mock.patch(target, return_value=value)
            p.start()
            self.addCleanup(p.stop)
        self.client, self.n = APIClient(), 0

    def login(self, role="customer"):
        self.n += 1
        res = self.accounts.auth.register({"email": f"u{self.n}@example.com", "full_name": "T U", "password": "a-good-long-pass"})
        if role != "customer":
            self.accounts.users.update(res["user"]["id"], {"role": role})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res['access_token']}")
        return res["user"]["id"]

    def test_roles(self):
        for role in ("customer", "pharmacist", "support_agent", "delivery_partner"):
            self.login(role)
            for url in ("/overview/", "/sales/", "/attention/", "/users/", "/audit/"):
                self.assertEqual(self.client.get(API + url).status_code, 403, (role, url))
        self.login("pharmacy_manager")
        self.assertEqual(self.client.get(API + "/sales/").status_code, 200)
        self.assertEqual(self.client.get(API + "/users/").status_code, 403)
        self.client.credentials()
        self.assertEqual(self.client.get(API + "/sales/").status_code, 401)

    def test_sales_validation_and_users_flow(self):
        admin = self.login("admin")
        self.assertEqual(self.client.get(API + "/sales/?from=nope").status_code, 400)
        self.assertEqual(self.client.get(API + "/sales/").json()["totals"]["orders"], 0)
        self.accounts.auth.register({"email": "victim@example.com", "full_name": "Victim", "password": "a-good-long-pass"})
        listed = self.client.get(API + "/users/?q=victim").json()["results"]
        self.assertEqual(len(listed), 1)
        res = self.client.post(f"{API}/users/{listed[0]['id']}/active/", {"active": False, "note": "test deactivation"}, format="json")
        self.assertEqual((res.status_code, res.json()["is_active"]), (200, False))
        self.assertEqual(self.client.post(f"{API}/users/{admin}/active/", {"active": False, "note": "myself"}, format="json").status_code, 409)
        self.assertEqual(self.client.get(API + "/audit/").json()["total"], 1)
