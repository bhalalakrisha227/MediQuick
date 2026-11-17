"""
HTTP-level notification tests (need Django + DRF: run with `python manage.py test`). NOT run in the build sandbox.
MongoDB is replaced by in-memory fakes.
"""
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase
from rest_framework.test import APIClient

from apps.notifications.service import NotificationService

from .fakes import FakeNotifications
from .test_accounts_api import make_services

API = "/api/v1/notifications"


class NotificationsApiTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.accounts = make_services()
        self.svc = NotificationService(FakeNotifications(), self.accounts.users, None, "http://app.test",
                                       lambda: __import__("datetime").datetime.now(__import__("datetime").timezone.utc))
        for target, value in (("apps.accounts.deps.get_services", self.accounts), ("apps.notifications.deps.get_notifications", self.svc)):
            p = mock.patch(target, return_value=value)
            p.start()
            self.addCleanup(p.stop)
        self.client, self.n = APIClient(), 0

    def login(self):
        self.n += 1
        res = self.accounts.auth.register({"email": f"u{self.n}@example.com", "full_name": "T U", "password": "a-good-long-pass"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res['access_token']}")
        return res["user"]["id"]

    def test_requires_login(self):
        for url in ("/", "/unread-count/", "/settings/"):
            self.assertEqual(self.client.get(API + url).status_code, 401)

    def test_list_read_and_isolation(self):
        a = self.login()
        self.svc.emit("order_delivered", a, "o1", "/orders/o1", 1, "MQ-1")
        res = self.client.get(API + "/").json()
        self.assertEqual((res["total"], res["unread"]), (1, 1))
        nid = res["results"][0]["id"]
        self.login()                                           # a different customer
        self.assertEqual(self.client.post(f"{API}/{nid}/read/").status_code, 404)
        self.assertEqual(self.client.get(API + "/").json()["total"], 0)
        self.login()
        self.assertEqual(self.client.get(API + "/unread-count/").json(), {"unread": 0})

    def test_settings_toggle_and_validation(self):
        self.login()
        self.assertEqual(self.client.get(API + "/settings/").json()["sms"], False)
        self.assertEqual(self.client.patch(API + "/settings/", {"email": "yes"}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(API + "/settings/", {"email": False}, format="json").json()["email"], False)
