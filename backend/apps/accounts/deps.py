"""Builds the service objects once, wired to MongoDB and Django settings."""
from functools import lru_cache
from types import SimpleNamespace

from django.conf import settings

from common.mongo import get_db

from .repository import AddressRepository, RefreshTokenRepository, UserRepository
from .services import AddressService, AuthConfig, AuthService, ProfileService


@lru_cache(maxsize=1)
def get_services() -> SimpleNamespace:
    db = get_db()
    users = UserRepository(db)
    config = AuthConfig(
        jwt_secret=settings.JWT_SECRET_KEY,
        access_minutes=settings.JWT_ACCESS_MINUTES,
        refresh_days=settings.JWT_REFRESH_DAYS,
        max_failed_logins=settings.MAX_FAILED_LOGINS,
        lock_minutes=settings.LOGIN_LOCK_MINUTES,
    )
    return SimpleNamespace(
        users=users,
        auth=AuthService(users, RefreshTokenRepository(db), config),
        profile=ProfileService(users),
        addresses=AddressService(AddressRepository(db)),
        config=config,
    )
