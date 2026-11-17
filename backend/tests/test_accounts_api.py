"""
HTTP-level tests. These need Django + DRF installed (pip install -r requirements.txt)
and run with:  python manage.py test
MongoDB is replaced by in-memory fakes, so Atlas is not needed.
"""
from types import SimpleNamespace
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase
from rest_framework.test import APIClient

from apps.accounts import roles
from apps.accounts.permissions import has_role
from apps.accounts.services import AddressService, AuthConfig, AuthService, ProfileService

from .fakes import FakeAddresses, FakeTokens, FakeUsers

REG = {"email": "asha@example.com", "full_name": "Asha Rao", "password": "a-good-long-pass"}
ADDR = {"recipient_name": "Asha", "phone": "9876543210", "line1": "12 Main Road", "city": "Pune",
        "state": "Maharashtra", "pincode": "411001"}


def make_services():
    users = FakeUsers()
    config = AuthConfig(jwt_secret="k" * 40)
    return SimpleNamespace(
        users=users, config=config,
        auth=AuthService(users, FakeTokens(), config),
        profile=ProfileService(users),
        addresses=AddressService(FakeAddresses()),
    )


class AccountsApiTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.services = make_services()
        patcher = mock.patch("apps.accounts.deps.get_services", return_value=self.services)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = APIClient()

    def _register(self, data=REG):
        return self.client.post("/api/v1/auth/register/", data, format="json")

    def _auth(self, token):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_register_login_me(self):
        res = self._register()
        self.assertEqual(res.status_code, 201)
        self.assertNotIn("password", str(res.json()))
        login = self.client.post("/api/v1/auth/login/", REG, format="json")
        self.assertEqual(login.status_code, 200)
        self._auth(login.json()["access_token"])
        me = self.client.get("/api/v1/me/")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["email"], "asha@example.com")

    def test_protected_routes_require_token(self):
        self.assertEqual(self.client.get("/api/v1/me/").status_code, 401)
        self.assertEqual(self.client.get("/api/v1/me/addresses/").status_code, 401)
        self._auth("not-a-jwt")
        self.assertEqual(self.client.get("/api/v1/me/").status_code, 401)

    def test_validation_error_shape(self):
        res = self._register({"email": "bad", "full_name": "A", "password": "x"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["error"]["code"], "validation_error")
        self.assertIn("email", res.json()["error"]["fields"])

    def test_address_isolation_between_users(self):
        a = self._register().json()
        b = self._register({**REG, "email": "other@example.com"}).json()
        self._auth(a["access_token"])
        addr_id = self.client.post("/api/v1/me/addresses/", ADDR, format="json").json()["id"]
        self._auth(b["access_token"])
        self.assertEqual(self.client.patch(f"/api/v1/me/addresses/{addr_id}/", {"city": "X"}, format="json").status_code, 404)
        self.assertEqual(self.client.delete(f"/api/v1/me/addresses/{addr_id}/").status_code, 404)
        self.assertEqual(self.client.get("/api/v1/me/addresses/").json()["results"], [])

    def test_refresh_and_logout(self):
        tokens = self._register().json()
        new = self.client.post("/api/v1/auth/refresh/", {"refresh_token": tokens["refresh_token"]}, format="json")
        self.assertEqual(new.status_code, 200)
        out = self.client.post("/api/v1/auth/logout/", {"refresh_token": new.json()["refresh_token"]}, format="json")
        self.assertEqual(out.status_code, 204)
        again = self.client.post("/api/v1/auth/refresh/", {"refresh_token": new.json()["refresh_token"]}, format="json")
        self.assertEqual(again.status_code, 401)

    def test_deactivated_user_token_stops_working(self):
        res = self._register().json()
        self._auth(res["access_token"])
        self.services.users.update(res["user"]["id"], {"is_active": False})
        self.assertEqual(self.client.get("/api/v1/me/").status_code, 401)


class RoleGateTests(SimpleTestCase):
    def _check(self, role, allowed):
        user = SimpleNamespace(is_authenticated=True, role=role) if role else None
        return has_role(*allowed)().has_permission(SimpleNamespace(user=user), None)

    def test_role_gate(self):
        self.assertTrue(self._check(roles.PHARMACIST, (roles.PHARMACIST, roles.ADMIN)))
        self.assertFalse(self._check(roles.CUSTOMER, (roles.PHARMACIST, roles.ADMIN)))
        self.assertFalse(self._check(None, (roles.ADMIN,)))
