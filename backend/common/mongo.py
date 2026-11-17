"""
Single place where MongoDB (Atlas) connections are created.

Every app should obtain its database through get_db() and keep its collection
access inside its own repository class (added in later phases). Nothing else in
the project should build a MongoClient.
"""
import logging
from functools import lru_cache

import certifi
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from pymongo import MongoClient
from pymongo.database import Database

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_client() -> MongoClient:
    """Return the shared MongoClient (it is thread-safe and pools connections)."""
    uri = settings.MONGODB_URI
    if not uri:
        raise ImproperlyConfigured(
            "MONGODB_URI is not set. Add your MongoDB Atlas connection string to backend/.env."
        )
    options = dict(
        serverSelectionTimeoutMS=settings.MONGODB_TIMEOUT_MS,
        appname="mediquick-api",
        tz_aware=True,  # datetimes come back timezone-aware (UTC)
    )
    if _uses_tls(uri):
        # certifi's CA bundle avoids TLS certificate errors on some Windows setups.
        options["tlsCAFile"] = certifi.where()
    return MongoClient(uri, **options)


def _uses_tls(uri: str) -> bool:
    """Atlas (mongodb+srv://) always uses TLS. A plain mongodb:// URI (for example a local
    MongoDB on 127.0.0.1) does not, unless it says tls=true. Passing a TLS option to a
    non-TLS server makes every connection fail with "SSL handshake failed"."""
    u = uri.lower()
    return u.startswith("mongodb+srv://") or "tls=true" in u or "ssl=true" in u


def get_db() -> Database:
    return get_client()[settings.MONGODB_DB_NAME]


def ping() -> bool:
    """Return True if the database answers. Details are logged, never returned."""
    try:
        get_client().admin.command("ping")
        return True
    except ImproperlyConfigured:
        logger.warning("MongoDB ping skipped: MONGODB_URI is not configured.")
        return False
    except Exception:  # noqa: BLE001 - any driver error means "unavailable"
        logger.exception("MongoDB ping failed")
        return False
