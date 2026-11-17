"""
Business logic for accounts. Depends only on repository interfaces, so it is
tested with in-memory fakes and has no Django or MongoDB imports.
"""
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from . import roles, security, validators
from .errors import DuplicateError, ServiceError


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class AuthConfig:
    jwt_secret: str
    access_minutes: int = 15
    refresh_days: int = 14
    max_failed_logins: int = 5
    lock_minutes: int = 15


def public_user(user: dict) -> dict:
    return {
        "id": user["_id"],
        "email": user["email"],
        "full_name": user["full_name"],
        "phone": user.get("phone", ""),
        "role": user["role"],
        "created_at": user["created_at"].isoformat(),
    }


def public_address(addr: dict) -> dict:
    return {k: addr.get(k, "") for k in (
        "label", "recipient_name", "phone", "line1", "line2", "landmark", "city", "state", "pincode"
    ) } | {"id": addr["_id"], "is_default": bool(addr.get("is_default"))}


INVALID_CREDENTIALS = ServiceError("invalid_credentials", "Incorrect email or password.", 401)
INVALID_REFRESH = ServiceError("invalid_refresh_token", "Session expired. Please log in again.", 401)


class AuthService:
    def __init__(self, users, tokens, config: AuthConfig, clock=_now):
        self.users, self.tokens, self.config, self.clock = users, tokens, config, clock

    # -- registration / login -------------------------------------------------
    def register(self, data: dict) -> dict:
        cleaned = validators.validate_registration(data)
        now = self.clock()
        user = {
            "_id": uuid.uuid4().hex,
            "email": cleaned["email"],
            "password_hash": security.hash_password(cleaned["password"]),
            "full_name": cleaned["full_name"],
            "phone": cleaned["phone"],
            "role": roles.CUSTOMER,  # never taken from client input
            "is_active": True,
            "failed_attempts": 0,
            "locked_until": None,
            "created_at": now,
            "updated_at": now,
        }
        try:
            self.users.insert(user)
        except DuplicateError:
            raise ServiceError("email_taken", "An account with this email already exists.", 409)
        return {"user": public_user(user), **self._issue_tokens(user)}

    def login(self, data: dict) -> dict:
        email = data.get("email")
        password = data.get("password")
        if not isinstance(email, str) or not isinstance(password, str) or not email or not password:
            raise INVALID_CREDENTIALS
        user = self.users.get_by_email(validators.normalize_email(email))
        now = self.clock()
        if user is None:
            security.verify_password(password, security.DUMMY_HASH)  # equalise timing
            raise INVALID_CREDENTIALS
        locked_until = user.get("locked_until")
        if locked_until and locked_until > now:
            raise ServiceError("account_locked", "Too many failed attempts. Try again later.", 429)
        if not security.verify_password(password, user["password_hash"]) or not user.get("is_active"):
            attempts = user.get("failed_attempts", 0) + 1
            fields = {"failed_attempts": attempts}
            if attempts >= self.config.max_failed_logins:
                fields = {"failed_attempts": 0,
                          "locked_until": now + timedelta(minutes=self.config.lock_minutes)}
            self.users.update(user["_id"], fields)
            raise INVALID_CREDENTIALS
        if user.get("failed_attempts") or user.get("locked_until"):
            self.users.update(user["_id"], {"failed_attempts": 0, "locked_until": None})
        return {"user": public_user(user), **self._issue_tokens(user)}

    # -- tokens ----------------------------------------------------------------
    def _issue_tokens(self, user: dict, family_id: str | None = None) -> dict:
        now = self.clock()
        raw = security.new_refresh_token()
        self.tokens.insert({
            "_id": uuid.uuid4().hex,
            "user_id": user["_id"],
            "family_id": family_id or uuid.uuid4().hex,
            "token_hash": security.hash_refresh_token(raw),
            "used": False,
            "revoked": False,
            "created_at": now,
            "expires_at": now + timedelta(days=self.config.refresh_days),
        })
        access = security.create_access_token(
            user["_id"], user["role"], self.config.jwt_secret, self.config.access_minutes, now
        )
        return {
            "access_token": access,
            "refresh_token": raw,
            "token_type": "Bearer",
            "expires_in": self.config.access_minutes * 60,
        }

    def refresh(self, data: dict) -> dict:
        raw = data.get("refresh_token")
        if not isinstance(raw, str) or not raw:
            raise INVALID_REFRESH
        record = self.tokens.get_by_hash(security.hash_refresh_token(raw))
        if record is None or record["revoked"] or record["expires_at"] <= self.clock():
            raise INVALID_REFRESH
        # Rotation: each refresh token works once. Presenting a used token means it
        # was probably stolen, so the whole token family is revoked.
        if record["used"] or not self.tokens.mark_used(record["_id"]):
            self.tokens.revoke_family(record["family_id"])
            raise INVALID_REFRESH
        user = self.users.get(record["user_id"])
        if user is None or not user.get("is_active"):
            self.tokens.revoke_family(record["family_id"])
            raise INVALID_REFRESH
        return {"user": public_user(user), **self._issue_tokens(user, record["family_id"])}

    def logout(self, data: dict) -> None:
        raw = data.get("refresh_token")
        if isinstance(raw, str) and raw:
            record = self.tokens.get_by_hash(security.hash_refresh_token(raw))
            if record:
                self.tokens.revoke_family(record["family_id"])


class ProfileService:
    def __init__(self, users, clock=_now):
        self.users, self.clock = users, clock

    def get(self, user_id: str) -> dict:
        user = self.users.get(user_id)
        if user is None:
            raise ServiceError("not_found", "User not found.", 404)
        return public_user(user)

    def update(self, user_id: str, data: dict) -> dict:
        cleaned = validators.validate_profile_update(data)
        self.users.update(user_id, {**cleaned, "updated_at": self.clock()})
        return self.get(user_id)


class AddressService:
    """Every operation is scoped by user_id, so users can only touch their own addresses."""

    def __init__(self, addresses, clock=_now):
        self.addresses, self.clock = addresses, clock

    def list(self, user_id: str) -> list[dict]:
        return [public_address(a) for a in self.addresses.list(user_id)]

    def create(self, user_id: str, data: dict) -> dict:
        cleaned = validators.validate_address(data)
        existing = self.addresses.count(user_id)
        if existing >= validators.MAX_ADDRESSES:
            raise ServiceError("limit_reached", f"You can save at most {validators.MAX_ADDRESSES} addresses.", 400)
        make_default = cleaned.pop("is_default", False) or existing == 0
        if make_default:
            self.addresses.clear_default(user_id)
        now = self.clock()
        doc = {"_id": uuid.uuid4().hex, "user_id": user_id, **cleaned,
               "is_default": make_default, "created_at": now, "updated_at": now}
        self.addresses.insert(doc)
        return public_address(doc)

    def update(self, user_id: str, address_id: str, data: dict) -> dict:
        if not isinstance(address_id, str) or self.addresses.get(user_id, address_id) is None:
            raise ServiceError("not_found", "Address not found.", 404)
        cleaned = validators.validate_address(data, partial=True)
        if not cleaned:
            raise ServiceError("validation_error", "Nothing to update.", 400)
        if cleaned.get("is_default"):
            self.addresses.clear_default(user_id)
        elif cleaned.get("is_default") is False:
            cleaned.pop("is_default")  # a default is changed by choosing another one
        self.addresses.update(user_id, address_id, {**cleaned, "updated_at": self.clock()})
        return public_address(self.addresses.get(user_id, address_id))

    def delete(self, user_id: str, address_id: str) -> None:
        target = self.addresses.get(user_id, address_id) if isinstance(address_id, str) else None
        if target is None:
            raise ServiceError("not_found", "Address not found.", 404)
        self.addresses.delete(user_id, address_id)
        if target.get("is_default"):
            remaining = self.addresses.list(user_id)
            if remaining:
                self.addresses.update(user_id, remaining[0]["_id"], {"is_default": True})
