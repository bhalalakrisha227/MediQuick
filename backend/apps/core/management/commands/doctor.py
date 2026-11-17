import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from common.checks import ERROR, collect_issues
from common.doctor import Warn, run_checks, summarize

EXPECT_MULTIPLE_INDEXES = ("users", "orders", "notifications", "batches", "prescriptions", "refunds", "admin_audit")


class Command(BaseCommand):
    help = "Checks that this machine can really run MediQuick (database, indexes, OCR, storage, payments, email). Prints no secrets."

    def handle(self, *args, **options):
        from common.mongo import get_db

        def database():
            get_db().command("ping")

        def indexes():
            db = get_db()
            missing = [c for c in EXPECT_MULTIPLE_INDEXES if len(db[c].index_information()) < 2]
            if missing:
                raise RuntimeError("run `python manage.py create_indexes` (missing for: " + ", ".join(missing) + ")")

        def admin_exists():
            from apps.accounts.repository import UserRepository
            if UserRepository(get_db()).count_active_admins() == 0:
                raise Warn("no active admin account yet (create one with create_staff_user --role admin)")

        def tesseract():
            import pytesseract
            if settings.TESSERACT_CMD:
                pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_CMD
            pytesseract.get_tesseract_version()

        def opencv():
            import cv2  # noqa: F401

        def pdf_support():
            try:
                import fitz  # noqa: F401
            except ImportError:
                raise Warn("PyMuPDF is not installed, so PDF prescriptions cannot be read (images still work)")

        def storage():
            root = Path(settings.PRIVATE_STORAGE_DIR)
            root.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=root, delete=True):
                pass

        def payments():
            from apps.orders.deps import build_payment_adapter
            build_payment_adapter()

        def email():
            from apps.notifications.deps import build_email_adapter
            if build_email_adapter() is None:
                raise Warn("email is off (EMAIL_PROVIDER=none); only in-app alerts are sent")

        def deploy_config():
            errors = [i for lvl, i, _ in collect_issues(settings) if lvl == ERROR]
            if errors:
                raise Warn(f"{len(errors)} production-only problems ({', '.join(errors[:4])}...). Fine while developing; run `manage.py check --deploy` before going live")

        text, ok = summarize(run_checks([
            ("MongoDB reachable", database), ("Database indexes created", indexes), ("An admin account exists", admin_exists),
            ("Tesseract OCR found", tesseract), ("OpenCV importable", opencv), ("PDF support (PyMuPDF)", pdf_support),
            ("Private file storage writable", storage), ("Payment adapter builds", payments), ("Email adapter builds", email),
            ("Production settings", deploy_config)]))
        self.stdout.write(text)
        if not ok:
            raise CommandError("Some checks failed.")
