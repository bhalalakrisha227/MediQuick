"""MongoDB (PyMongo) repositories for accounts. All collection access lives here."""
from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError

from .errors import DuplicateError


class UserRepository:
    def __init__(self, db):
        self.col = db["users"]

    def insert(self, doc: dict) -> None:
        try:
            self.col.insert_one(doc)
        except DuplicateKeyError as exc:
            raise DuplicateError from exc

    def get(self, user_id: str):
        return self.col.find_one({"_id": user_id})

    def get_by_email(self, email: str):
        return self.col.find_one({"email": email})

    def list_page(self, escaped_query, role, skip, limit):
        query = {}
        if role:
            query["role"] = role
        if escaped_query:
            query["$or"] = [{"email": {"$regex": escaped_query, "$options": "i"}}, {"full_name": {"$regex": escaped_query, "$options": "i"}}]
        return list(self.col.find(query).sort("created_at", -1).skip(skip).limit(limit)), self.col.count_documents(query)

    def count_active_admins(self):
        return self.col.count_documents({"role": "admin", "is_active": True})

    def list_by_role(self, role: str, limit: int = 200) -> list:
        return list(self.col.find({"role": role, "is_active": True}).limit(limit))

    def update(self, user_id: str, fields: dict) -> None:
        self.col.update_one({"_id": user_id}, {"$set": fields})


class RefreshTokenRepository:
    def __init__(self, db):
        self.col = db["refresh_tokens"]

    def insert(self, doc: dict) -> None:
        self.col.insert_one(doc)

    def get_by_hash(self, token_hash: str):
        return self.col.find_one({"token_hash": token_hash})

    def mark_used(self, token_id: str) -> bool:
        """Atomically flip used False -> True. False means someone already used it."""
        doc = self.col.find_one_and_update(
            {"_id": token_id, "used": False}, {"$set": {"used": True}}, return_document=ReturnDocument.AFTER
        )
        return doc is not None

    def revoke_family(self, family_id: str) -> None:
        self.col.update_many({"family_id": family_id}, {"$set": {"revoked": True}})


class AddressRepository:
    def __init__(self, db):
        self.col = db["addresses"]

    def list(self, user_id: str) -> list:
        return list(self.col.find({"user_id": user_id}).sort("created_at", ASCENDING))

    def count(self, user_id: str) -> int:
        return self.col.count_documents({"user_id": user_id})

    def insert(self, doc: dict) -> None:
        self.col.insert_one(doc)

    def get(self, user_id: str, address_id: str):
        return self.col.find_one({"_id": address_id, "user_id": user_id})

    def update(self, user_id: str, address_id: str, fields: dict) -> None:
        self.col.update_one({"_id": address_id, "user_id": user_id}, {"$set": fields})

    def delete(self, user_id: str, address_id: str) -> None:
        self.col.delete_one({"_id": address_id, "user_id": user_id})

    def clear_default(self, user_id: str) -> None:
        self.col.update_many({"user_id": user_id, "is_default": True}, {"$set": {"is_default": False}})


def ensure_indexes(db) -> None:
    db["users"].create_index([("email", ASCENDING)], unique=True, name="uniq_email")
    db["refresh_tokens"].create_index([("token_hash", ASCENDING)], unique=True, name="uniq_token_hash")
    db["refresh_tokens"].create_index([("family_id", ASCENDING)], name="by_family")
    db["refresh_tokens"].create_index([("expires_at", ASCENDING)], expireAfterSeconds=0, name="ttl_expiry")
    db["addresses"].create_index([("user_id", ASCENDING), ("created_at", DESCENDING)], name="by_user")
