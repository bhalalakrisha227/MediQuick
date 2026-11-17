from functools import lru_cache
from types import SimpleNamespace

from django.conf import settings

from apps.catalogue.repository import ProductRepository
from common.mongo import get_db
from common.tasks import get_task_runner

from apps.notifications import deps as notify_deps
from apps.notifications.observers import NotifyingPrescriptions

from .allowance import AllowanceService
from .ocr.engines import get_engine
from .repository import PrescriptionRepository
from .review import ReviewService
from .services import PrescriptionService
from .storage import FileStorage


@lru_cache(maxsize=1)
def get_services() -> SimpleNamespace:
    db = get_db()
    holder = {}

    def schedule(prescription_id):
        get_task_runner().submit(holder["svc"].process, prescription_id)

    repo = PrescriptionRepository(db)
    svc = PrescriptionService(
        repo, FileStorage(settings.PRIVATE_STORAGE_DIR), ProductRepository(db),
        get_engine(settings.OCR_ENGINE, cmd=settings.TESSERACT_CMD, lang=settings.OCR_LANG, timeout=settings.OCR_TIMEOUT_SECONDS),
        schedule=schedule,
        max_bytes=settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024,
        max_pixels=settings.MAX_IMAGE_MEGAPIXELS * 1_000_000,
        max_pages=settings.MAX_PDF_PAGES,
    )
    holder["svc"] = svc
    review = ReviewService(NotifyingPrescriptions(repo, notify_deps.get_notifications()), ProductRepository(db), max_valid_days=settings.PRESCRIPTION_VALIDITY_DAYS)
    return SimpleNamespace(prescriptions=svc, review=review, allowances=AllowanceService(repo))
