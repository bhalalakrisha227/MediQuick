from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError, OperationFailure

from apps.accounts.errors import DuplicateError

from . import rules


class PrescriptionRepository:
    def __init__(self, db):
        self.col = db["prescriptions"]
        self.access = db["prescription_access"]
        self.audit = db["prescription_audit"]

    def insert(self, doc):
        try:
            self.col.insert_one(doc)
        except DuplicateKeyError as exc:
            raise DuplicateError from exc

    def get(self, prescription_id):
        return self.col.find_one({"_id": prescription_id})

    def get_for_user(self, user_id, prescription_id):
        return self.col.find_one({"_id": prescription_id, "user_id": user_id})

    def list_for_user(self, user_id, limit):
        return list(self.col.find({"user_id": user_id, "status": {"$ne": rules.WITHDRAWN}}).sort("created_at", DESCENDING).limit(limit))

    def count_drafts(self, user_id):
        return self.col.count_documents({"user_id": user_id, "status": {"$in": list(rules.DRAFT_STATUSES)}})

    def find_active_by_hash(self, user_id, sha256):
        return self.col.find_one({"user_id": user_id, "file.sha256": sha256, "status": {"$in": list(rules.ACTIVE_STATUSES)}})

    def claim_ocr(self, prescription_id, now, stale_before):
        """Atomically take an OCR job. Only one caller gets the document back."""
        return self.col.find_one_and_update(
            {"_id": prescription_id, "status": rules.PROCESSING,
             "$or": [{"ocr.status": "pending"}, {"ocr.status": "running", "ocr.started_at": {"$lte": stale_before}}]},
            {"$set": {"ocr.status": "running", "ocr.started_at": now, "updated_at": now}},
        )

    def finish_ocr(self, prescription_id, ocr, now):
        """Stores OCR output and moves to customer review - only if the job is still 'processing'."""
        result = self.col.update_one(
            {"_id": prescription_id, "status": rules.PROCESSING},
            {"$set": {"ocr": ocr, "status": rules.NEEDS_REVIEW, "updated_at": now},
             "$push": {"status_history": {"status": rules.NEEDS_REVIEW, "at": now, "note": f"ocr {ocr.get('status')}"}}},
        )
        return result.modified_count == 1

    def reset_for_retry(self, user_id, prescription_id, now):
        result = self.col.update_one(
            {"_id": prescription_id, "user_id": user_id, "status": rules.NEEDS_REVIEW, "ocr.status": {"$in": ["failed", "unavailable"]}},
            {"$set": {"status": rules.PROCESSING, "ocr": {"status": "pending"}, "updated_at": now},
             "$push": {"status_history": {"status": rules.PROCESSING, "at": now, "note": "ocr retry"}}},
        )
        return result.modified_count == 1

    def update_review(self, user_id, prescription_id, fields, now):
        result = self.col.update_one(
            {"_id": prescription_id, "user_id": user_id, "status": {"$in": list(rules.CUSTOMER_EDITABLE)}},
            {"$set": {**fields, "updated_at": now}},
        )
        return result.matched_count == 1

    def transition(self, prescription_id, user_id, from_statuses, to_status, fields, note, now):
        result = self.col.update_one(
            {"_id": prescription_id, "user_id": user_id, "status": {"$in": list(from_statuses)}},
            {"$set": {**fields, "status": to_status, "updated_at": now},
             "$push": {"status_history": {"status": to_status, "at": now, "note": note}}},
        )
        return result.modified_count == 1

    def find_pending(self, now, stale_before, limit):
        query = {"status": rules.PROCESSING,
                 "$or": [{"ocr.status": "pending"}, {"ocr.status": "running", "ocr.started_at": {"$lte": stale_before}}]}
        return [d["_id"] for d in self.col.find(query, {"_id": 1}).limit(limit)]

    def log_access(self, doc):
        self.access.insert_one(doc)

    # ---------- pharmacist review ----------
    def list_for_staff(self, statuses, limit, assigned_to=None, oldest_first=True):
        query = {"status": {"$in": list(statuses)}}
        if assigned_to:
            query["assigned_to.id"] = assigned_to
        sort = [("submitted_at", ASCENDING)] if oldest_first else [("updated_at", DESCENDING)]
        return list(self.col.find(query).sort(sort).limit(limit))

    def staff_transition(self, prescription_id, from_status, to_status, fields, note, now, assignee_id=None, unset=None):
        """Atomic compare-and-set on status (and on the assigned pharmacist when given)."""
        query = {"_id": prescription_id, "status": from_status}
        if assignee_id:
            query["assigned_to.id"] = assignee_id
        update = {"$set": {**fields, "status": to_status, "updated_at": now},
                  "$push": {"status_history": {"status": to_status, "at": now, "note": note}}}
        if unset:
            update["$unset"] = {k: "" for k in unset}
        return self.col.update_one(query, update).modified_count == 1

    def count_by_status(self):
        return {r["_id"]: r["n"] for r in self.col.aggregate([{"$group": {"_id": "$status", "n": {"$sum": 1}}}])}

    def count_claims(self, user_id):
        return self.col.count_documents({"status": rules.IN_REVIEW, "assigned_to.id": user_id})

    def log_audit(self, doc):
        self.audit.insert_one(doc)

    def audit_for(self, prescription_id, limit=100):
        return list(self.audit.find({"prescription_id": prescription_id}).sort("at", ASCENDING).limit(limit))

    # ---------- approved allowances (used by cart/checkout) ----------
    def list_approved(self, user_id, now):
        return list(self.col.find({"user_id": user_id, "status": rules.APPROVED, "approval.valid_until": {"$gt": now}})
                    .sort("approval.valid_until", ASCENDING))

    def consume_allowance(self, user_id, product_id, quantity, now):
        """Atomically take `quantity` units from the earliest-expiring approved prescription that still has them."""
        doc = self.col.find_one_and_update(
            {"user_id": user_id, "status": rules.APPROVED, "approval.valid_until": {"$gt": now},
             "approval.items": {"$elemMatch": {"product_id": product_id, "remaining": {"$gte": quantity}}}},
            {"$inc": {"approval.items.$.remaining": -quantity}, "$set": {"updated_at": now}},
            sort=[("approval.valid_until", ASCENDING)], projection={"_id": 1})
        return doc["_id"] if doc else None

    def restore_allowance(self, prescription_id, product_id, quantity, now):
        result = self.col.update_one(
            {"_id": prescription_id},
            {"$inc": {"approval.items.$[e].remaining": quantity}, "$set": {"updated_at": now}},
            array_filters=[{"e.product_id": product_id}])
        return result.modified_count == 1

    def has_file_view(self, prescription_id, actor_id, since):
        """True if this staff member opened the original file at or after `since` (the claim time)."""
        return self.access.count_documents({"prescription_id": prescription_id, "actor_id": actor_id,
                                            "action": "view_file", "at": {"$gte": since}}, limit=1) > 0


def ensure_indexes(db):
    active = list(rules.ACTIVE_STATUSES)
    col = db["prescriptions"]
    col.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)], name="by_user")
    unique = dict(unique=True, name="uniq_active_file_per_user", partialFilterExpression={"status": {"$in": active}})
    try:
        col.create_index([("user_id", ASCENDING), ("file.sha256", ASCENDING)], **unique)
    except OperationFailure:
        # Phase 5 created this index with a shorter status list; replace it with the current definition.
        col.drop_index("uniq_active_file_per_user")
        col.create_index([("user_id", ASCENDING), ("file.sha256", ASCENDING)], **unique)
    col.create_index([("status", ASCENDING), ("ocr.status", ASCENDING)], name="ocr_queue")
    col.create_index([("status", ASCENDING), ("submitted_at", ASCENDING)], name="review_queue")
    col.create_index([("user_id", ASCENDING), ("status", ASCENDING), ("approval.valid_until", ASCENDING)], name="approved_by_user")
    db["prescription_access"].create_index([("prescription_id", ASCENDING), ("at", DESCENDING)], name="by_prescription")
    db["prescription_audit"].create_index([("prescription_id", ASCENDING), ("at", ASCENDING)], name="audit_by_prescription")
