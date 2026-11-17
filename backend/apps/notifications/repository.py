from datetime import timedelta

from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError

from apps.accounts.errors import DuplicateError

from . import rules


class NotificationRepository:
    def __init__(self, db):
        self.col = db["notifications"]

    def insert(self, doc):
        try:
            self.col.insert_one(doc)
        except DuplicateKeyError as exc:
            raise DuplicateError from exc

    def get(self, notification_id):
        return self.col.find_one({"_id": notification_id})

    def list_for_user(self, user_id, unread_only, skip, limit):
        query = {"user_id": user_id, **({"read_at": None} if unread_only else {})}
        rows = list(self.col.find(query).sort("created_at", DESCENDING).skip(skip).limit(limit))
        return rows, self.col.count_documents(query)

    def unread_count(self, user_id):
        return self.col.count_documents({"user_id": user_id, "read_at": None})

    def mark_read(self, user_id, notification_id, now):
        return self.col.update_one({"_id": notification_id, "user_id": user_id, "read_at": None},
                                   {"$set": {"read_at": now}}).modified_count == 1

    def mark_all_read(self, user_id, now):
        self.col.update_many({"user_id": user_id, "read_at": None}, {"$set": {"read_at": now}})

    def claim_due(self, now, lease_until):
        """Atomically takes ONE email that is due (or whose earlier worker vanished). Two workers never get the same one."""
        return self.col.find_one_and_update(
            {"$or": [{"email.status": "pending", "email.next_attempt_at": {"$lte": now}},
                     {"email.status": "sending", "email.lease_until": {"$lte": now}}]},
            {"$set": {"email.status": "sending", "email.lease_until": lease_until}},
            sort=[("email.next_attempt_at", ASCENDING)], return_document=ReturnDocument.BEFORE)

    def finish_email(self, notification_id, fields):
        self.col.update_one({"_id": notification_id}, {"$set": {**{f"email.{k}": v for k, v in fields.items()}, "email.lease_until": None}})


def ensure_indexes(db):
    db["notifications"].create_index([("key", ASCENDING)], unique=True, name="uniq_notification_key")
    db["notifications"].create_index([("user_id", ASCENDING), ("created_at", DESCENDING)], name="by_user")
    db["notifications"].create_index([("user_id", ASCENDING), ("read_at", ASCENDING)], name="by_user_unread")
    db["notifications"].create_index([("email.status", ASCENDING), ("email.next_attempt_at", ASCENDING)], name="email_outbox",
                                     partialFilterExpression={"email.status": {"$in": ["pending", "sending"]}})
    db["notifications"].create_index([("created_at", ASCENDING)], name="notifications_ttl",
                                     expireAfterSeconds=rules.RETENTION_DAYS * 24 * 3600)
