"""
Pharmacist review of submitted prescriptions. No Django / MongoDB imports.

Safety design:
 * Only a pharmacist (role "pharmacist") can claim, approve, reject or ask a question. Managers and
   admins can view and release stuck claims but cannot approve. Roles are re-checked here as well as
   in the HTTP layer.
 * Approval is an explicit decision: the pharmacist names every product and quantity (nothing is copied
   from OCR or from the customer's list), enters their registration number, and attests they checked the
   original. No substitution logic exists anywhere.
 * A decision is an atomic compare-and-set on (status == in_review AND assigned pharmacist == actor),
   so two pharmacists can never both decide, and nobody can decide someone else's claim.
 * Every staff action is written to an append-only audit log, with a snapshot of what the customer listed.
 * The registration number is only checked for format. It is NOT verified against any pharmacy council register.
"""
import re
import uuid
from datetime import datetime, timedelta, timezone

from apps.accounts.errors import ServiceError
from apps.catalogue import rules as catalogue_rules

from . import rules
from .services import public_prescription, review_block

_REG = re.compile(r"^[A-Za-z0-9/ .-]{3,30}$")
MAX_CLAIMS = 5
SCOPES = ("queue", "mine", "clarification", "approved", "rejected")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def staff_row(p: dict) -> dict:
    a = p.get("assigned_to")
    return {"id": p["_id"], "status": p["status"], "submitted_at": p.get("submitted_at"), "updated_at": p["updated_at"],
            "assigned_to": a["name"] if a else None, "assigned_to_id": a["id"] if a else None,
            "item_count": len(p.get("items", [])), "ocr_status": (p.get("ocr") or {}).get("status"),
            "file_name": p["file"]["original_name"], "file_type": p["file"]["content_type"]}


def staff_view(p: dict, audit=None) -> dict:
    base = public_prescription(p)
    base.update({
        "customer_id": p["user_id"],
        "assigned_to": p.get("assigned_to"),
        "review": review_block(p, for_staff=True),
        "audit": [{"action": a["action"], "actor_name": a["actor_name"], "actor_role": a["actor_role"], "at": a["at"],
                   "details": a.get("details", {})} for a in (audit or [])],
        "notice": ("Items below were typed or confirmed by the customer, and the OCR text is automatic. "
                   "Neither is verified. Decide from the original file."),
    })
    return base


class ReviewService:
    def __init__(self, repo, products, clock=_now, max_valid_days=rules.MAX_VALID_DAYS):
        self.repo, self.products, self.clock = repo, products, clock
        self.max_valid_days = max_valid_days
        self.default_valid_days = min(rules.DEFAULT_VALID_DAYS, max_valid_days)

    # ---------- helpers ----------
    def _require(self, actor: dict, roles) -> None:
        if not actor or actor.get("role") not in roles or not actor.get("id"):
            raise ServiceError("forbidden", "You do not have permission to do this.", 403)

    def _visible(self, prescription_id) -> dict:
        p = self.repo.get(prescription_id) if isinstance(prescription_id, str) else None
        if not p or p["status"] not in rules.STAFF_VISIBLE:
            raise ServiceError("not_found", "Prescription not found.", 404)
        return p

    def _audit(self, actor, prescription_id, action, details=None):
        self.repo.log_audit({"_id": uuid.uuid4().hex, "prescription_id": prescription_id, "actor_id": actor["id"],
                             "actor_role": actor["role"], "actor_name": actor.get("name", ""), "action": action,
                             "at": self.clock(), "details": details or {}})

    def _text(self, data, key, minimum, maximum, label):
        v = data.get(key)
        if not isinstance(v, str) or not (minimum <= len(v.strip()) <= maximum):
            raise ServiceError("validation_error", "Some fields are invalid.", 400,
                               {key: f"{label} must be {minimum}-{maximum} characters."})
        return v.strip()

    def _not_own(self, actor, p) -> None:
        """A pharmacist can never review a prescription they uploaded themselves."""
        if p["user_id"] == actor["id"]:
            raise ServiceError("own_prescription", "You cannot review your own prescription. Another pharmacist must do it.", 403)

    def _opened_original(self, actor, p) -> None:
        """A decision needs the pharmacist to have opened the original file since they claimed it."""
        if p["status"] != rules.IN_REVIEW or (p.get("assigned_to") or {}).get("id") != actor["id"]:
            raise ServiceError("conflict", "You can only decide a prescription you have claimed.", 409)
        claimed = (p.get("assigned_to") or {}).get("at")
        if not claimed or not self.repo.has_file_view(p["_id"], actor["id"], claimed):
            raise ServiceError("open_original_first", "Open the original prescription file before deciding.", 409)

    def _lost(self, prescription_id):
        """A conditional update did not apply: explain why without leaking anything."""
        self._visible(prescription_id)
        return ServiceError("conflict", "This prescription is no longer in the state this action needs "
                                        "(someone else may have changed it). Reload and check.", 409)

    # ---------- reads ----------
    def queue(self, actor, scope="queue") -> dict:
        self._require(actor, rules.VIEW_ROLES)
        if scope not in SCOPES:
            raise ServiceError("validation_error", "Unknown list.", 400, {"scope": f"Use one of: {', '.join(SCOPES)}."})
        if scope == "queue":
            rows = self.repo.list_for_staff(rules.QUEUE_STATUSES, 50, oldest_first=True)
        elif scope == "mine":
            rows = self.repo.list_for_staff((rules.IN_REVIEW,), 50, assigned_to=actor["id"], oldest_first=True)
        else:
            status = {"clarification": rules.CLARIFICATION, "approved": rules.APPROVED, "rejected": rules.REJECTED}[scope]
            rows = self.repo.list_for_staff((status,), 50, oldest_first=False)
        return {"results": [staff_row(p) for p in rows]}

    def detail(self, actor, prescription_id) -> dict:
        self._require(actor, rules.VIEW_ROLES)
        p = self._visible(prescription_id)
        self.repo.log_access({"_id": uuid.uuid4().hex, "prescription_id": p["_id"], "actor_id": actor["id"],
                              "actor_role": actor["role"], "action": "view_detail", "at": self.clock()})
        return staff_view(p, self.repo.audit_for(p["_id"]))

    # ---------- claim / release ----------
    def claim(self, actor, prescription_id) -> dict:
        self._require(actor, rules.DECIDE_ROLES)
        self._not_own(actor, self._visible(prescription_id))
        if self.repo.count_claims(actor["id"]) >= MAX_CLAIMS:
            raise ServiceError("too_many_claims", f"You already have {MAX_CLAIMS} prescriptions in review. Finish or release one first.", 409)
        now = self.clock()
        if not self.repo.staff_transition(prescription_id, rules.SUBMITTED, rules.IN_REVIEW,
                                          {"assigned_to": {"id": actor["id"], "name": actor.get("name", ""), "at": now}},
                                          f"claimed by {actor.get('name', '')}", now):
            raise self._lost(prescription_id)
        self._audit(actor, prescription_id, "claim")
        return self.detail(actor, prescription_id)

    def release(self, actor, prescription_id) -> dict:
        self._require(actor, rules.RELEASE_ROLES)
        self._visible(prescription_id)
        assignee = actor["id"] if actor["role"] == "pharmacist" else None   # pharmacists release only their own
        now = self.clock()
        if not self.repo.staff_transition(prescription_id, rules.IN_REVIEW, rules.SUBMITTED, {}, f"released by {actor.get('name', '')}",
                                          now, assignee_id=assignee, unset=["assigned_to"]):
            raise self._lost(prescription_id)
        self._audit(actor, prescription_id, "release")
        return self.detail(actor, prescription_id)

    # ---------- decisions ----------
    def _validate_items(self, raw) -> list:
        if not isinstance(raw, list) or not (1 <= len(raw) <= rules.MAX_APPROVED_ITEMS):
            raise ServiceError("validation_error", "Some fields are invalid.", 400,
                               {"items": f"Approve between 1 and {rules.MAX_APPROVED_ITEMS} medicines."})
        errors, ids = {}, [i.get("product_id") for i in raw if isinstance(i, dict) and isinstance(i.get("product_id"), str)]
        found = self.products.get_many(ids)
        out, seen = [], set()
        for n, item in enumerate(raw):
            key = f"items.{n}"
            pid = item.get("product_id") if isinstance(item, dict) else None
            qty = item.get("max_quantity") if isinstance(item, dict) else None
            product = found.get(pid) if isinstance(pid, str) else None
            if isinstance(pid, str) and pid in seen:
                errors[f"{key}.product_id"] = "Each medicine can appear once."
            elif not product or not product.get("is_active"):
                errors[f"{key}.product_id"] = "Choose a product from the catalogue."
            elif not product.get("requires_prescription"):
                errors[f"{key}.product_id"] = "This product does not need a prescription."
            elif not catalogue_rules.purchasable_online(product["schedule"]):
                errors[f"{key}.product_id"] = "This product cannot be sold online."
            elif isinstance(qty, bool) or not isinstance(qty, int) or not (1 <= qty <= rules.MAX_APPROVED_QUANTITY):
                errors[f"{key}.max_quantity"] = f"Whole number from 1 to {rules.MAX_APPROVED_QUANTITY}."
            else:
                out.append({"product_id": pid, "name": product["name"], "max_quantity": qty, "remaining": qty})
            if isinstance(pid, str):
                seen.add(pid)
        if errors:
            raise ServiceError("validation_error", "Some fields are invalid.", 400, errors)
        return out

    def approve(self, actor, prescription_id, data: dict) -> dict:
        self._require(actor, rules.DECIDE_ROLES)
        p = self._visible(prescription_id)
        self._not_own(actor, p)
        self._opened_original(actor, p)
        if data.get("attest_original_checked") is not True:
            raise ServiceError("validation_error", "Some fields are invalid.", 400,
                               {"attest_original_checked": "Confirm that you checked the original prescription."})
        reg = data.get("registration_number")
        if not isinstance(reg, str) or not _REG.match(reg.strip()):
            raise ServiceError("validation_error", "Some fields are invalid.", 400,
                               {"registration_number": "Enter your pharmacist registration number (3-30 letters, digits, / . -)."})
        days = data.get("valid_days", self.default_valid_days)
        if isinstance(days, bool) or not isinstance(days, int) or not (1 <= days <= self.max_valid_days):
            raise ServiceError("validation_error", "Some fields are invalid.", 400,
                               {"valid_days": f"Whole number of days from 1 to {self.max_valid_days}."})
        note = data.get("note")
        if note not in (None, "") and (not isinstance(note, str) or len(note.strip()) > rules.MAX_REASON):
            raise ServiceError("validation_error", "Some fields are invalid.", 400, {"note": f"At most {rules.MAX_REASON} characters."})
        items = self._validate_items(data.get("items"))
        now = self.clock()
        approval = {"pharmacist": {"id": actor["id"], "name": actor.get("name", ""), "registration_number": reg.strip()},
                    "approved_at": now, "valid_until": now + timedelta(days=days), "note": (note or "").strip(),
                    "items": items, "attested_original_checked": True}
        if not self.repo.staff_transition(prescription_id, rules.IN_REVIEW, rules.APPROVED, {"approval": approval},
                                          "approved by pharmacist", now, assignee_id=actor["id"]):
            raise self._lost(prescription_id)
        self._audit(actor, prescription_id, "approve", {
            "approved_items": [{k: i[k] for k in ("product_id", "name", "max_quantity")} for i in items],
            "valid_days": days, "registration_number": reg.strip(),
            "customer_items_snapshot": p.get("items", [])})
        return self.detail(actor, prescription_id)

    def reject(self, actor, prescription_id, data: dict) -> dict:
        self._require(actor, rules.DECIDE_ROLES)
        p = self._visible(prescription_id)
        self._not_own(actor, p)
        self._opened_original(actor, p)
        reason = self._text(data, "reason", 5, rules.MAX_REASON, "The reason")
        now = self.clock()
        fields = {"rejection": {"reason": reason, "by": {"id": actor["id"], "name": actor.get("name", "")}, "at": now}}
        if not self.repo.staff_transition(prescription_id, rules.IN_REVIEW, rules.REJECTED, fields, "rejected by pharmacist",
                                          now, assignee_id=actor["id"]):
            raise self._lost(prescription_id)
        self._audit(actor, prescription_id, "reject", {"reason": reason, "customer_items_snapshot": p.get("items", [])})
        return self.detail(actor, prescription_id)

    def clarify(self, actor, prescription_id, data: dict) -> dict:
        self._require(actor, rules.DECIDE_ROLES)
        p = self._visible(prescription_id)
        self._not_own(actor, p)
        self._opened_original(actor, p)
        message = self._text(data, "message", 5, rules.MAX_REASON, "The question")
        now = self.clock()
        fields = {"clarification": {"message": message, "by": {"id": actor["id"], "name": actor.get("name", "")}, "at": now}}
        if not self.repo.staff_transition(prescription_id, rules.IN_REVIEW, rules.CLARIFICATION, fields,
                                          "clarification requested", now, assignee_id=actor["id"], unset=["assigned_to"]):
            raise self._lost(prescription_id)
        self._audit(actor, prescription_id, "clarify", {"message": message})
        return self.detail(actor, prescription_id)
