import unittest
from datetime import datetime, timedelta, timezone

import jwt

from apps.accounts import security, validators
from apps.accounts.errors import ValidationFailed


class PasswordTests(unittest.TestCase):
    def test_hash_and_verify(self):
        h = security.hash_password("a-Strong-pass-1")
        self.assertTrue(h.startswith("scrypt$"))
        self.assertNotIn("a-Strong-pass-1", h)
        self.assertTrue(security.verify_password("a-Strong-pass-1", h))
        self.assertFalse(security.verify_password("wrong", h))

    def test_salts_differ(self):
        self.assertNotEqual(security.hash_password("same-password-1"), security.hash_password("same-password-1"))

    def test_garbage_hash_is_rejected_not_crashing(self):
        self.assertFalse(security.verify_password("x", "not-a-hash"))
        self.assertFalse(security.verify_password("x", "md5$1$2$3$4$5"))


class TokenTests(unittest.TestCase):
    SECRET = "s" * 40

    def test_round_trip(self):
        t = security.create_access_token("u1", "customer", self.SECRET, 15)
        p = security.decode_access_token(t, self.SECRET)
        self.assertEqual((p["sub"], p["role"], p["type"]), ("u1", "customer", "access"))

    def test_wrong_secret_rejected(self):
        t = security.create_access_token("u1", "customer", self.SECRET, 15)
        with self.assertRaises(security.TokenError):
            security.decode_access_token(t, "x" * 40)

    def test_expired_rejected(self):
        old = datetime.now(timezone.utc) - timedelta(hours=1)
        t = security.create_access_token("u1", "customer", self.SECRET, 15, now=old)
        with self.assertRaises(security.TokenError):
            security.decode_access_token(t, self.SECRET)

    def test_alg_none_rejected(self):
        forged = jwt.encode({"sub": "u1", "type": "access", "iat": 1, "exp": 9999999999}, None, algorithm="none")
        with self.assertRaises(security.TokenError):
            security.decode_access_token(forged, self.SECRET)

    def test_non_access_type_rejected(self):
        now = datetime.now(timezone.utc)
        t = jwt.encode({"sub": "u1", "type": "refresh", "iat": now, "exp": now + timedelta(minutes=5)},
                       self.SECRET, algorithm="HS256")
        with self.assertRaises(security.TokenError):
            security.decode_access_token(t, self.SECRET)


class ValidatorTests(unittest.TestCase):
    def test_password_rules(self):
        self.assertTrue(validators.password_problems("short"))
        self.assertTrue(validators.password_problems("1234567890123"))
        self.assertTrue(validators.password_problems("password123"))
        self.assertTrue(validators.password_problems("krishna-is-here", "krishna@x.com"))
        self.assertEqual(validators.password_problems("a-good-long-pass", "a@x.com"), [])

    def test_registration_normalises_and_collects_errors(self):
        ok = validators.validate_registration(
            {"email": "  Me@Example.COM ", "full_name": " Asha Rao ", "phone": "98765 43210", "password": "a-good-long-pass"})
        self.assertEqual((ok["email"], ok["full_name"], ok["phone"]), ("me@example.com", "Asha Rao", "9876543210"))
        with self.assertRaises(ValidationFailed) as cm:
            validators.validate_registration({"email": "bad", "full_name": "A", "password": "x"})
        self.assertEqual(set(cm.exception.fields), {"email", "full_name", "password"})

    def test_non_string_input_is_a_validation_error(self):
        with self.assertRaises(ValidationFailed):
            validators.validate_registration({"email": ["a@b.com"], "full_name": 5, "password": {"x": 1}})

    def test_address_pincode(self):
        base = {"recipient_name": "Asha", "phone": "9876543210", "line1": "12 Main Rd", "city": "Pune", "state": "MH"}
        self.assertEqual(validators.validate_address({**base, "pincode": "411001"})["label"], "Home")
        for bad in ("012345", "41100", "abcdef", None):
            with self.assertRaises(ValidationFailed):
                validators.validate_address({**base, "pincode": bad})


if __name__ == "__main__":
    unittest.main()
