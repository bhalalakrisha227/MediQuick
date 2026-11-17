from pymongo import ASCENDING, DESCENDING


class AuditRepository:
    def __init__(self, db):
        self.col = db["admin_audit"]

    def insert(self, doc):
        self.col.insert_one(doc)

    def list_recent(self, skip, limit):
        return list(self.col.find().sort("at", DESCENDING).skip(skip).limit(limit)), self.col.count_documents({})


def ensure_indexes(db):
    db["admin_audit"].create_index([("at", DESCENDING)], name="by_time")
    db["admin_audit"].create_index([("target_id", ASCENDING), ("at", DESCENDING)], name="by_target")
