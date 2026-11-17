"""
Prescription upload, OCR, customer review and submission. No Django / MongoDB imports.

Safety design:
 * OCR output is only ever a SUGGESTION. No code path here approves a prescription, chooses a
   medicine, or substitutes one. The most this module does is hand a customer-reviewed
   submission to the pharmacist queue (status "submitted"). Approval belongs to Phase 6.
 * The file is validated by content before it is stored; stored privately under a random name.
 * Every read is scoped to the owner (someone else's id looks like "not found").
   Staff may fetch the original only once it is submitted (never drafts), and each fetch is logged.
 * OCR is claimed atomically so a job cannot run twice, and a failed/unavailable OCR still
   leaves the prescription reviewable (the pharmacist can read the original by eye).
"""
import hashlib
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

from apps.accounts.errors import DuplicateError, ServiceError

from . import rules
from .filetypes import UploadRejected, validate_upload
from .ocr import matcher, parser
from .ocr.errors import OcrError, OcrUnavailable
from .ocr.pipeline import run_ocr
from .storage import StorageError

logger = logging.getLogger(__name__)

_FILENAME_SAFE = re.compile(r"[^A-Za-z0-9._ -]")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def safe_filename(name) -> str:
    base = str(name or "").replace("\\", "/").split("/")[-1]
    base = _FILENAME_SAFE.sub("", base).strip(" .")[:80]
    return base or "prescription"


def public_prescription(p: dict) -> dict:
    ocr = p.get("ocr") or {}
    return {
        "id": p["_id"], "status": p["status"],
        "created_at": p["created_at"], "updated_at": p["updated_at"], "submitted_at": p.get("submitted_at"),
        "file": {"original_name": p["file"]["original_name"], "content_type": p["file"]["content_type"], "size": p["file"]["size"]},
        "ocr": {"status": ocr.get("status", "pending"), "engine": ocr.get("engine"), "text": ocr.get("text", ""),
                "candidates": ocr.get("candidates", [])},
        "items": p.get("items", []), "notes": p.get("notes", ""),
        "consent_accepted": bool(p.get("consent")),
        "editable": p["status"] in rules.CUSTOMER_EDITABLE,
        "review": review_block(p),
        "disclaimer": "Automatic text reading can be wrong. A pharmacist checks your original prescription before anything is approved.",
    }


def review_block(p: dict, for_staff: bool = False) -> dict:
    """What the pharmacist decided, shown to the customer (and staff). Never includes registration numbers for customers."""
    out = {}
    if p["status"] == rules.CLARIFICATION and p.get("clarification"):
        c = p["clarification"]
        out["clarification"] = {"message": c["message"], "at": c["at"]}
    if p.get("rejection") and (p["status"] == rules.REJECTED or for_staff):
        r = p["rejection"]
        out["rejection"] = {"reason": r["reason"], "at": r["at"]}
    if p.get("approval") and p["status"] == rules.APPROVED:
        a = p["approval"]
        out["approval"] = {"approved_at": a["approved_at"], "valid_until": a["valid_until"], "note": a.get("note", ""),
                           "pharmacist_name": a["pharmacist"]["name"],
                           "items": [{"product_id": i["product_id"], "name": i["name"], "max_quantity": i["max_quantity"],
                                      "remaining": i["remaining"]} for i in a["items"]]}
        if for_staff:
            out["approval"]["registration_number"] = a["pharmacist"]["registration_number"]
    return out


def summary(p: dict) -> dict:
    return {"id": p["_id"], "status": p["status"], "created_at": p["created_at"], "submitted_at": p.get("submitted_at"),
            "original_name": p["file"]["original_name"], "item_count": len(p.get("items", []))}


class PrescriptionService:
    def __init__(self, repo, storage, products, engine, *, clock=_now, schedule=None, ocr_runner=run_ocr, pdf_renderer=None,
                 max_bytes=5 * 1024 * 1024, max_pixels=25_000_000, max_pages=3, stale_seconds=600):
        self.repo, self.storage, self.products, self.engine = repo, storage, products, engine
        self.clock, self.schedule, self.ocr_runner = clock, schedule, ocr_runner
        self.max_bytes, self.max_pixels, self.max_pages, self.stale_seconds = max_bytes, max_pixels, max_pages, stale_seconds
        self.pdf_renderer = pdf_renderer

    # ---------- helpers ----------
    def _own(self, user_id, prescription_id):
        p = self.repo.get_for_user(user_id, str(prescription_id))
        if not p:
            raise ServiceError("not_found", "Prescription not found.", 404)
        return p

    def _kick(self, prescription_id):
        if self.schedule:
            try:
                self.schedule(prescription_id)
            except Exception:  # never fail the request because the queue is unavailable
                logger.exception("Could not schedule OCR for %s", prescription_id)

    def _stale_before(self):
        return self.clock() - timedelta(seconds=self.stale_seconds)

    # ---------- upload ----------
    def upload(self, user_id, data: bytes, original_name, fields: dict) -> dict:
        consent = fields.get("consent")
        if consent is not True and str(consent).lower() not in ("true", "1", "on", "yes"):
            raise ServiceError("consent_required", "Please confirm the consent statement to continue.", 400,
                               {"consent": "You must accept to upload a prescription."})
        notes = self._notes(fields.get("notes"))
        try:
            info = validate_upload(data, max_bytes=self.max_bytes, max_pixels=self.max_pixels)
        except UploadRejected as exc:
            raise ServiceError(exc.code, exc.message, 400, {"file": exc.message}) from exc

        digest = hashlib.sha256(data).hexdigest()
        if self.repo.find_active_by_hash(user_id, digest):
            raise ServiceError("duplicate_file", "You have already uploaded this file.", 409)
        if self.repo.count_drafts(user_id) >= rules.MAX_DRAFTS:
            raise ServiceError("too_many_drafts", "You have too many unfinished prescriptions. Submit or withdraw some first.", 409)

        try:
            relative, stored_hash = self.storage.save(user_id, info.ext, data)
        except (StorageError, OSError) as exc:
            logger.exception("Could not store prescription file")
            raise ServiceError("storage_error", "The file could not be saved. Please try again.", 500) from exc

        now = self.clock()
        doc = {
            "_id": uuid.uuid4().hex, "user_id": user_id, "status": rules.PROCESSING,
            "file": {"path": relative, "size": len(data), "content_type": info.content_type, "kind": info.kind,
                     "sha256": stored_hash, "original_name": safe_filename(original_name)},
            "ocr": {"status": "pending"}, "items": [], "notes": notes,
            "consent": {"accepted_at": now, "version": rules.CONSENT_VERSION},
            "status_history": [{"status": rules.PROCESSING, "at": now, "note": "uploaded"}],
            "created_at": now, "updated_at": now,
        }
        try:
            self.repo.insert(doc)
        except DuplicateError as exc:
            self.storage.delete(relative)
            raise ServiceError("duplicate_file", "You have already uploaded this file.", 409) from exc
        except Exception:
            self.storage.delete(relative)
            raise
        self._kick(doc["_id"])
        return public_prescription(doc)

    # ---------- OCR (runs in the background; never decides anything) ----------
    def process(self, prescription_id) -> bool:
        """Runs OCR once. Returns False if another worker already has the job."""
        now = self.clock()
        p = self.repo.claim_ocr(prescription_id, now, self._stale_before())
        if not p:
            return False
        ocr = {"status": "failed", "engine": getattr(self.engine, "name", None)}
        try:
            data = self.storage.read(p["file"]["path"])
            kwargs = {"max_pages": self.max_pages}
            if self.pdf_renderer:
                kwargs["pdf_renderer"] = self.pdf_renderer
            result = self.ocr_runner(data, p["file"]["kind"], self.engine, **kwargs)
            candidates = parser.parse_lines(result.lines)
            candidates = matcher.attach_suggestions(candidates, self.products.list_active(2000))
            ocr = {"status": "done", "engine": result.engine, "text": result.text[:rules.MAX_OCR_TEXT],
                   "lines": [{"text": l["text"][:200], "confidence": l.get("confidence")} for l in result.lines[:rules.MAX_OCR_LINES]],
                   "candidates": candidates}
        except OcrUnavailable:
            ocr["status"] = "unavailable"
        except (OcrError, StorageError):
            ocr["status"] = "failed"
        except Exception:
            logger.exception("Unexpected OCR failure for %s", prescription_id)
            ocr["status"] = "failed"
        # Whatever happened, the prescription moves to customer review - never to submitted/approved.
        self.repo.finish_ocr(prescription_id, ocr, self.clock())
        return True

    def retry_ocr(self, user_id, prescription_id) -> dict:
        p = self._own(user_id, prescription_id)
        if p["status"] == rules.PROCESSING:
            started = (p.get("ocr") or {}).get("started_at")
            if (p.get("ocr") or {}).get("status") == "running" and started and started <= self._stale_before():
                self._kick(p["_id"])
                return public_prescription(p)
            raise ServiceError("still_processing", "This prescription is still being read.", 409)
        if not self.repo.reset_for_retry(user_id, p["_id"], self.clock()):
            raise ServiceError("cannot_retry", "Automatic reading can only be retried after it failed.", 409)
        self._kick(p["_id"])
        return public_prescription(self._own(user_id, prescription_id))

    def recover_pending(self, limit=100) -> int:
        """Re-runs OCR for jobs lost on a restart. Used by the management command."""
        ids = self.repo.find_pending(self.clock(), self._stale_before(), limit)
        return sum(1 for i in ids if self.process(i))

    # ---------- reads ----------
    def get(self, user_id, prescription_id) -> dict:
        return public_prescription(self._own(user_id, prescription_id))

    def list(self, user_id) -> dict:
        return {"results": [summary(p) for p in self.repo.list_for_user(user_id, 50)]}

    # ---------- customer review ----------
    def _notes(self, value) -> str:
        if value is None:
            return ""
        if not isinstance(value, str) or len(value.strip()) > rules.MAX_NOTES:
            raise ServiceError("validation_error", "Some fields are invalid.", 400,
                               {"notes": f"Notes must be text of at most {rules.MAX_NOTES} characters."})
        return value.strip()

    def _items(self, raw) -> list:
        errors = {}
        if not isinstance(raw, list) or len(raw) > rules.MAX_ITEMS:
            raise ServiceError("validation_error", "Some fields are invalid.", 400,
                               {"items": f"Provide a list of at most {rules.MAX_ITEMS} medicines."})
        out = []
        ids = [i.get("product_id") for i in raw if isinstance(i, dict) and i.get("product_id")]
        found = self.products.get_many([i for i in ids if isinstance(i, str)])
        for n, item in enumerate(raw):
            key = f"items.{n}"
            if not isinstance(item, dict):
                errors[key] = "Invalid entry."
                continue
            name = item.get("name")
            if not isinstance(name, str) or not (2 <= len(name.strip()) <= 120):
                errors[f"{key}.name"] = "Enter the medicine name (2-120 characters)."
                continue
            clean = {"name": name.strip()}
            for field, limit in (("strength", 40), ("dosage", 60), ("duration", 40)):
                v = item.get(field)
                if v in (None, ""):
                    clean[field] = ""
                elif isinstance(v, str) and len(v.strip()) <= limit:
                    clean[field] = v.strip()
                else:
                    errors[f"{key}.{field}"] = f"Must be text of at most {limit} characters."
            q = item.get("quantity")
            if q in (None, ""):
                clean["quantity"] = None
            elif isinstance(q, int) and not isinstance(q, bool) and 1 <= q <= 999:
                clean["quantity"] = q
            else:
                errors[f"{key}.quantity"] = "Must be a whole number from 1 to 999."
            pid = item.get("product_id")
            if pid in (None, ""):
                clean["product_id"] = None
            else:
                product = found.get(pid) if isinstance(pid, str) else None
                if not product or not product.get("is_active"):
                    errors[f"{key}.product_id"] = "That product is not available."
                else:
                    clean["product_id"], clean["product_name"] = pid, product["name"]
            out.append(clean)
        if errors:
            raise ServiceError("validation_error", "Some fields are invalid.", 400, errors)
        return out

    def update(self, user_id, prescription_id, data: dict) -> dict:
        p = self._own(user_id, prescription_id)
        fields = {}
        if "items" in data:
            fields["items"] = self._items(data["items"])
        if "notes" in data:
            fields["notes"] = self._notes(data["notes"])
        if not fields:
            raise ServiceError("validation_error", "Nothing to update.", 400)
        if not self.repo.update_review(user_id, p["_id"], fields, self.clock()):
            raise ServiceError("not_editable", "This prescription can no longer be edited.", 409)
        return public_prescription(self._own(user_id, prescription_id))

    def submit(self, user_id, prescription_id) -> dict:
        p = self._own(user_id, prescription_id)
        now = self.clock()
        fields = {"submitted_at": now}
        if not self.repo.transition(p["_id"], user_id, rules.CUSTOMER_EDITABLE, rules.SUBMITTED,
                                    fields, "submitted by customer", now):
            raise ServiceError("cannot_submit", "This prescription cannot be submitted right now.", 409)
        return public_prescription(self._own(user_id, prescription_id))

    def withdraw(self, user_id, prescription_id) -> dict:
        p = self._own(user_id, prescription_id)
        now = self.clock()
        if not self.repo.transition(p["_id"], user_id, rules.CUSTOMER_WITHDRAWABLE, rules.WITHDRAWN,
                                    {"ocr": {"status": "discarded"}, "items": []}, "withdrawn by customer", now):
            raise ServiceError("cannot_withdraw", "A prescription that is with a pharmacist, approved or rejected cannot be withdrawn here.", 409)
        try:
            self.storage.delete(p["file"]["path"])
        except (StorageError, OSError):
            logger.exception("Could not delete withdrawn prescription file %s", p["_id"])
        return public_prescription(self._own(user_id, prescription_id))

    # ---------- original file ----------
    def file_for(self, actor_id, actor_role, prescription_id):
        """Returns (bytes, content_type, download_name). Owner always; staff only once it is submitted (never drafts), and every staff open is logged."""
        p = self.repo.get(str(prescription_id))
        if not p or p["status"] == rules.WITHDRAWN:
            raise ServiceError("not_found", "Prescription not found.", 404)
        is_owner = p["user_id"] == actor_id
        staff_ok = actor_role in rules.STAFF_FILE_ROLES and p["status"] in rules.STAFF_VISIBLE
        if not (is_owner or staff_ok):
            raise ServiceError("not_found", "Prescription not found.", 404)
        try:
            data = self.storage.read(p["file"]["path"])
        except StorageError as exc:
            raise ServiceError("not_found", "Prescription file not found.", 404) from exc
        if not is_owner:
            self.repo.log_access({"_id": uuid.uuid4().hex, "prescription_id": p["_id"], "actor_id": actor_id,
                                  "actor_role": actor_role, "action": "view_file", "at": self.clock()})
        return data, p["file"]["content_type"], p["file"]["original_name"]
