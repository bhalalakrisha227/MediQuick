import getpass
import uuid
from datetime import datetime, timezone

from django.core.management.base import BaseCommand, CommandError

from apps.accounts import roles, security, validators
from apps.accounts.errors import DuplicateError, ValidationFailed
from apps.accounts.repository import UserRepository
from common.mongo import get_db


class Command(BaseCommand):
    help = "Create a staff account (pharmacist, admin, ...). Staff cannot self-register."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--name", required=True, help="Full name")
        parser.add_argument("--role", required=True, choices=roles.STAFF_ROLES)

    def handle(self, *args, **opts):
        password = getpass.getpass("Password (hidden): ")
        if password != getpass.getpass("Repeat password: "):
            raise CommandError("Passwords do not match.")
        try:
            cleaned = validators.validate_registration(
                {"email": opts["email"], "full_name": opts["name"], "password": password}
            )
        except ValidationFailed as exc:
            raise CommandError(f"Invalid input: {exc.fields}")
        now = datetime.now(timezone.utc)
        doc = {
            "_id": uuid.uuid4().hex, "email": cleaned["email"],
            "password_hash": security.hash_password(password), "full_name": cleaned["full_name"],
            "phone": "", "role": opts["role"], "is_active": True, "failed_attempts": 0,
            "locked_until": None, "created_at": now, "updated_at": now,
        }
        try:
            UserRepository(get_db()).insert(doc)
        except DuplicateError:
            raise CommandError("An account with that email already exists.")
        self.stdout.write(self.style.SUCCESS(f"Created {opts['role']} {cleaned['email']}"))
