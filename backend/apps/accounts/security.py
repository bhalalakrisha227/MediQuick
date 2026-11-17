"""
Password hashing and token helpers. No Django imports, so this is unit-testable
on its own.

Passwords use scrypt (standard library, memory-hard) with a per-password random
salt. Access tokens are short-lived HS256 JWTs. Refresh tokens are random opaque
strings; only their SHA-256 hash is stored in the database.
"""
import base64
import hashlib
import hmac
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt

_N, _R, _P = 2**14, 8, 1


class TokenError(Exception):
    pass


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


# Verified against when an email is unknown, so response time does not reveal
# whether an account exists.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def create_access_token(user_id: str, role: str, secret: str, minutes: int, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "role": role,
        "type": "access",
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + timedelta(minutes=minutes),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_access_token(token: str, secret: str) -> dict:
    try:
        payload = jwt.decode(
            token, secret, algorithms=["HS256"], options={"require": ["exp", "iat", "sub"]}
        )
    except jwt.PyJWTError as exc:
        raise TokenError("Invalid or expired token.") from exc
    if payload.get("type") != "access":
        raise TokenError("Wrong token type.")
    return payload
