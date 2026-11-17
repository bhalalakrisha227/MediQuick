"""Read-only look at the configured MongoDB. It never writes, drops or changes anything."""
from urllib.parse import urlsplit

from django.conf import settings
from django.core.management.base import BaseCommand

from common.mongo import _uses_tls, get_client, get_db


def _safe_target(uri: str) -> str:
    # host and port only: never print a user name or password from the connection string
    parts = urlsplit(uri)
    return f"{parts.scheme}://{parts.hostname}{':' + str(parts.port) if parts.port else ''}"


def _mask(email: str) -> str:
    name, _, domain = (email or "").partition("@")
    return f"{name[:2]}***@{domain}" if domain else "***"


class Command(BaseCommand):
    help = "Show which MongoDB the app uses and what is in it (read-only)."

    def handle(self, *args, **options):
        out = self.stdout.write
        out(f"Connection : {_safe_target(settings.MONGODB_URI)}")
        out(f"TLS used   : {'yes' if _uses_tls(settings.MONGODB_URI) else 'no (plain local connection)'}")
        out(f"Database   : {settings.MONGODB_DB_NAME}")
        client = get_client()
        client.admin.command("ping")
        out(self.style.SUCCESS("Ping       : ok"))

        db = get_db()
        names = sorted(db.list_collection_names())
        out(f"\nCollections in '{settings.MONGODB_DB_NAME}' ({len(names)}):")
        for n in names:
            out(f"  {n:28} {db[n].count_documents({}):>7} document(s)   indexes: {', '.join(sorted(db[n].index_information())) or '-'}")

        if "users" not in names:
            out(self.style.WARNING("\nNo 'users' collection in this database."))
            return
        users = db["users"]
        total = users.count_documents({})
        out(f"\nUsers: {total}")
        for row in users.aggregate([{"$group": {"_id": "$role", "n": {"$sum": 1}}}, {"$sort": {"_id": 1}}]):
            out(f"  role {row['_id']}: {row['n']}")
        first = users.find_one({}, sort=[("_id", 1)])
        if first:
            out(f"  field names on a user record: {', '.join(sorted(first))}")
        out("  most recent accounts (email masked):")
        for u in users.find({}, {"email": 1, "role": 1, "is_active": 1}).sort("_id", -1).limit(5):
            out(f"    {_mask(u.get('email'))}  role={u.get('role')}  active={u.get('is_active')}")
