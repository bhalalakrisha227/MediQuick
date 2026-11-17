import unittest
from datetime import datetime, timedelta, timezone

from apps.accounts import roles, security
from apps.accounts.errors import ServiceError, ValidationFailed
from apps.accounts.services import AddressService, AuthConfig, AuthService, ProfileService

from .fakes import FakeAddresses, FakeTokens, FakeUsers

SECRET = "k" * 40
REG = {"email": "asha@example.com", "full_name": "Asha Rao", "phone": "9876543210", "password": "a-good-long-pass"}


class Clock:
    def __init__(self):
        self.now = datetime.now(timezone.utc)

    def __call__(self):
        return self.now


class AuthServiceTests(unittest.TestCase):
    def setUp(self):
        self.users, self.tokens, self.clock = FakeUsers(), FakeTokens(), Clock()
        self.auth = AuthService(self.users, self.tokens, AuthConfig(jwt_secret=SECRET), self.clock)

    def test_register_returns_tokens_and_customer_role(self):
        out = self.auth.register(REG)
        self.assertEqual(out["user"]["role"], roles.CUSTOMER)
        self.assertNotIn("password_hash", out["user"])
        payload = security.decode_access_token(out["access_token"], SECRET)
        self.assertEqual(payload["sub"], out["user"]["id"])

    def test_client_cannot_choose_role(self):
        out = self.auth.register({**REG, "role": "admin"})
        self.assertEqual(out["user"]["role"], roles.CUSTOMER)

    def test_password_is_stored_hashed(self):
        self.auth.register(REG)
        stored = self.users.get_by_email("asha@example.com")["password_hash"]
        self.assertNotIn(REG["password"], stored)

    def test_duplicate_email_case_insensitive(self):
        self.auth.register(REG)
        with self.assertRaises(ServiceError) as cm:
            self.auth.register({**REG, "email": "ASHA@example.com"})
        self.assertEqual(cm.exception.status, 409)

    def test_login_ok_and_wrong_password_same_error_as_unknown_email(self):
        self.auth.register(REG)
        self.assertIn("access_token", self.auth.login({"email": "Asha@Example.com", "password": REG["password"]}))
        with self.assertRaises(ServiceError) as wrong:
            self.auth.login({"email": REG["email"], "password": "nope-nope-nope"})
        with self.assertRaises(ServiceError) as unknown:
            self.auth.login({"email": "nobody@example.com", "password": "nope-nope-nope"})
        self.assertEqual((wrong.exception.code, wrong.exception.message), (unknown.exception.code, unknown.exception.message))

    def test_lockout_after_repeated_failures_then_expires(self):
        self.auth.register(REG)
        for _ in range(5):
            with self.assertRaises(ServiceError):
                self.auth.login({"email": REG["email"], "password": "bad-bad-bad-bad"})
        with self.assertRaises(ServiceError) as cm:
            self.auth.login({"email": REG["email"], "password": REG["password"]})  # right password, still locked
        self.assertEqual(cm.exception.code, "account_locked")
        self.clock.now += timedelta(minutes=16)
        self.assertIn("access_token", self.auth.login({"email": REG["email"], "password": REG["password"]}))

    def test_inactive_user_cannot_log_in(self):
        out = self.auth.register(REG)
        self.users.update(out["user"]["id"], {"is_active": False})
        with self.assertRaises(ServiceError):
            self.auth.login({"email": REG["email"], "password": REG["password"]})

    def test_login_rejects_non_string_input(self):
        with self.assertRaises(ServiceError):
            self.auth.login({"email": {"$ne": ""}, "password": {"$ne": ""}})

    def test_refresh_rotates_and_old_token_triggers_family_revocation(self):
        first = self.auth.register(REG)
        second = self.auth.refresh({"refresh_token": first["refresh_token"]})
        self.assertNotEqual(first["refresh_token"], second["refresh_token"])
        with self.assertRaises(ServiceError):  # replaying the first token = reuse
            self.auth.refresh({"refresh_token": first["refresh_token"]})
        with self.assertRaises(ServiceError):  # the legitimate newest token is now revoked too
            self.auth.refresh({"refresh_token": second["refresh_token"]})

    def test_refresh_expired_and_garbage(self):
        out = self.auth.register(REG)
        for bad in ("garbage", "", None, 5):
            with self.assertRaises(ServiceError):
                self.auth.refresh({"refresh_token": bad})
        self.clock.now += timedelta(days=15)
        with self.assertRaises(ServiceError):
            self.auth.refresh({"refresh_token": out["refresh_token"]})

    def test_logout_revokes_session(self):
        out = self.auth.register(REG)
        self.auth.logout({"refresh_token": out["refresh_token"]})
        with self.assertRaises(ServiceError):
            self.auth.refresh({"refresh_token": out["refresh_token"]})
        self.auth.logout({})  # never errors

    def test_refresh_tokens_stored_only_as_hashes(self):
        out = self.auth.register(REG)
        self.assertNotIn(out["refresh_token"], str(self.tokens.docs))


class ProfileTests(unittest.TestCase):
    def test_update_profile_only_allowed_fields(self):
        users = FakeUsers()
        auth = AuthService(users, FakeTokens(), AuthConfig(jwt_secret=SECRET))
        uid = auth.register(REG)["user"]["id"]
        profile = ProfileService(users)
        out = profile.update(uid, {"full_name": "Asha R", "role": "admin", "email": "x@y.com"})
        self.assertEqual((out["full_name"], out["role"], out["email"]), ("Asha R", "customer", "asha@example.com"))
        with self.assertRaises(ValidationFailed):
            profile.update(uid, {"role": "admin"})


ADDR = {"recipient_name": "Asha Rao", "phone": "9876543210", "line1": "12 Main Road", "city": "Pune",
        "state": "Maharashtra", "pincode": "411001"}


class AddressTests(unittest.TestCase):
    def setUp(self):
        self.svc = AddressService(FakeAddresses())

    def test_first_address_becomes_default_and_new_default_replaces(self):
        a = self.svc.create("u1", ADDR)
        self.assertTrue(a["is_default"])
        b = self.svc.create("u1", {**ADDR, "is_default": True})
        listing = {x["id"]: x["is_default"] for x in self.svc.list("u1")}
        self.assertEqual(listing, {a["id"]: False, b["id"]: True})

    def test_users_cannot_access_each_others_addresses(self):
        a = self.svc.create("u1", ADDR)
        for call in (lambda: self.svc.update("u2", a["id"], {"city": "Hacked"}),
                     lambda: self.svc.delete("u2", a["id"])):
            with self.assertRaises(ServiceError) as cm:
                call()
            self.assertEqual(cm.exception.status, 404)
        self.assertEqual(self.svc.list("u2"), [])
        self.assertEqual(self.svc.list("u1")[0]["city"], "Pune")

    def test_deleting_default_promotes_another(self):
        a = self.svc.create("u1", ADDR)
        b = self.svc.create("u1", ADDR)
        self.svc.delete("u1", a["id"])
        self.assertEqual([(x["id"], x["is_default"]) for x in self.svc.list("u1")], [(b["id"], True)])

    def test_limit_and_validation(self):
        for _ in range(10):
            self.svc.create("u1", ADDR)
        with self.assertRaises(ServiceError):
            self.svc.create("u1", ADDR)
        with self.assertRaises(ValidationFailed):
            self.svc.create("u2", {**ADDR, "pincode": "123"})

    def test_partial_update(self):
        a = self.svc.create("u1", ADDR)
        out = self.svc.update("u1", a["id"], {"city": "Mumbai"})
        self.assertEqual((out["city"], out["pincode"]), ("Mumbai", "411001"))


if __name__ == "__main__":
    unittest.main()
