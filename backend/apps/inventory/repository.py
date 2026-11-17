from datetime import datetime, timezone

from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError

from apps.accounts.errors import DuplicateError

from .queries import build_batch_query, sellable_match


class BatchRepository:
    def __init__(self, db):
        self.col = db["inventory_batches"]

    def insert(self, doc):
        try:
            self.col.insert_one(doc)
        except DuplicateKeyError as exc:
            raise DuplicateError from exc

    def get(self, batch_id):
        return self.col.find_one({"_id": batch_id})

    def list(self, f, today_dt, warning_days, skip, limit):
        query = build_batch_query(f, today_dt, warning_days)
        total = self.col.count_documents(query)
        cursor = self.col.find(query).sort([("expiry_date", ASCENDING), ("batch_number", ASCENDING)]).skip(skip).limit(limit)
        return list(cursor), total

    def adjust_on_hand(self, batch_id, delta):
        """Atomic: applies delta only if the result stays >= 0 and >= reserved. Returns new quantity or None."""
        doc = self.col.find_one_and_update(
            {"_id": batch_id, "$expr": {"$and": [
                {"$gte": [{"$add": ["$quantity_on_hand", delta]}, 0]},
                {"$gte": [{"$add": ["$quantity_on_hand", delta]}, "$quantity_reserved"]},
            ]}},
            {"$inc": {"quantity_on_hand": delta}, "$set": {"updated_at": datetime.now(timezone.utc)}},
            return_document=ReturnDocument.AFTER,
        )
        return doc["quantity_on_hand"] if doc else None

    def set_status(self, batch_id, status, now):
        self.col.update_one({"_id": batch_id}, {"$set": {"status": status, "updated_at": now}})

    def sellable_batches(self, product_id, cutoff_dt):
        """Batches that may be sold for one product, earliest expiry first (FEFO)."""
        cursor = self.col.find(sellable_match([product_id], cutoff_dt)).sort(
            [("expiry_date", ASCENDING), ("batch_number", ASCENDING)])
        return list(cursor)

    def reserve(self, batch_id, qty):
        """Atomic: hold qty units for an order only if that many are free in an active batch."""
        result = self.col.update_one(
            {"_id": batch_id, "status": "active",
             "$expr": {"$gte": [{"$subtract": ["$quantity_on_hand", "$quantity_reserved"]}, qty]}},
            {"$inc": {"quantity_reserved": qty}},
        )
        return result.modified_count == 1

    def release(self, batch_id, qty):
        result = self.col.update_one(
            {"_id": batch_id, "quantity_reserved": {"$gte": qty}}, {"$inc": {"quantity_reserved": -qty}})
        return result.modified_count == 1

    def commit(self, batch_id, qty):
        """Atomic: turn a reservation into a real deduction. Returns new on-hand, or None if refused."""
        doc = self.col.find_one_and_update(
            {"_id": batch_id, "quantity_reserved": {"$gte": qty}, "quantity_on_hand": {"$gte": qty}},
            {"$inc": {"quantity_on_hand": -qty, "quantity_reserved": -qty},
             "$set": {"updated_at": datetime.now(timezone.utc)}},
            return_document=ReturnDocument.AFTER,
        )
        return doc["quantity_on_hand"] if doc else None

    def sellable_summary(self, product_ids, cutoff_dt):
        pipeline = [
            {"$match": sellable_match(product_ids, cutoff_dt)},
            {"$group": {"_id": "$product_id",
                        "sellable": {"$sum": {"$subtract": ["$quantity_on_hand", "$quantity_reserved"]}},
                        "earliest_expiry": {"$min": "$expiry_date"}}},
        ]
        return {row["_id"]: {"sellable": row["sellable"], "earliest_expiry": row["earliest_expiry"]}
                for row in self.col.aggregate(pipeline)}


class MovementRepository:
    def __init__(self, db):
        self.col = db["stock_movements"]

    def insert(self, doc):
        self.col.insert_one(doc)

    def list_for_batch(self, batch_id, limit):
        return list(self.col.find({"batch_id": batch_id}).sort("created_at", DESCENDING).limit(limit))


def ensure_indexes(db):
    db["inventory_batches"].create_index([("product_id", ASCENDING), ("batch_number", ASCENDING)], unique=True, name="uniq_product_batch")
    db["inventory_batches"].create_index([("product_id", ASCENDING), ("status", ASCENDING), ("expiry_date", ASCENDING)], name="sellable")
    db["inventory_batches"].create_index([("expiry_date", ASCENDING)], name="by_expiry")
    db["stock_movements"].create_index([("batch_id", ASCENDING), ("created_at", DESCENDING)], name="by_batch")
