from pymongo import ASCENDING
from pymongo.errors import DuplicateKeyError

from .errors import DuplicateError
from .queries import SORTS, build_query


class CategoryRepository:
    def __init__(self, db):
        self.col = db["categories"]

    def list_active(self):
        return list(self.col.find({"is_active": True}).sort([("sort_order", 1), ("name", 1)]))

    def get_by_slug(self, slug):
        return self.col.find_one({"slug": slug})

    def insert(self, doc):
        try:
            self.col.insert_one(doc)
        except DuplicateKeyError as exc:
            raise DuplicateError from exc


class ProductRepository:
    def __init__(self, db):
        self.col = db["products"]

    def get(self, product_id):
        return self.col.find_one({"_id": product_id})

    def get_by_slug(self, slug):
        return self.col.find_one({"slug": slug})

    def get_many(self, product_ids):
        """Returns {id: product} for the given ids (one query)."""
        ids = list(set(product_ids))
        return {p["_id"]: p for p in self.col.find({"_id": {"$in": ids}})} if ids else {}

    def list_active(self, limit):
        return list(self.col.find({"is_active": True}).sort("name_lower", 1).limit(limit))

    def insert(self, doc):
        try:
            self.col.insert_one(doc)
        except DuplicateKeyError as exc:
            raise DuplicateError from exc

    def update(self, product_id, fields):
        self.col.update_one({"_id": product_id}, {"$set": fields})

    def search(self, filters, sort, skip, limit):
        query = build_query(filters)
        total = self.col.count_documents(query)
        cursor = self.col.find(query).sort(SORTS[sort]).skip(skip).limit(limit)
        return list(cursor), total


def ensure_indexes(db):
    db["categories"].create_index([("slug", ASCENDING)], unique=True, name="uniq_slug")
    db["categories"].create_index([("name", ASCENDING)], unique=True, name="uniq_name")
    db["products"].create_index([("slug", ASCENDING)], unique=True, name="uniq_slug")
    db["products"].create_index([("is_active", ASCENDING), ("category", ASCENDING), ("price_paise", ASCENDING)], name="browse")
    db["products"].create_index([("is_active", ASCENDING), ("name_lower", ASCENDING)], name="by_name")
