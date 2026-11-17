from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

from apps.accounts.errors import DuplicateError


class CartRepository:
    def __init__(self, db):
        self.col = db["carts"]

    def get(self, user_id):
        return self.col.find_one({"_id": user_id})

    def save(self, user_id, items, now):
        if not items:
            self.col.delete_one({"_id": user_id})  # an empty cart is no document
        else:
            self.col.replace_one({"_id": user_id}, {"_id": user_id, "items": items, "updated_at": now}, upsert=True)

    def claim(self, user_id):
        """Atomically take and delete the cart. Only one concurrent caller gets it."""
        return self.col.find_one_and_delete({"_id": user_id})

    def restore_if_empty(self, user_id, items, now):
        """Put a claimed cart back, but never overwrite a cart the shopper has rebuilt meanwhile."""
        self.col.update_one({"_id": user_id}, {"$setOnInsert": {"items": items, "updated_at": now}}, upsert=True)


class OrderRepository:
    def __init__(self, db):
        self.col = db["orders"]

    def insert(self, doc):
        try:
            self.col.insert_one(doc)
        except DuplicateKeyError as exc:
            raise DuplicateError from exc

    def get(self, order_id):
        return self.col.find_one({"_id": order_id})

    def get_for_user(self, user_id, order_id):
        return self.col.find_one({"_id": order_id, "user_id": user_id})

    def list_for_user(self, user_id, skip, limit):
        query = {"user_id": user_id}
        total = self.col.count_documents(query)
        return list(self.col.find(query).sort("created_at", DESCENDING).skip(skip).limit(limit)), total

    def transition(self, order_id, from_status, to_status, fields, note, now):
        """Atomic compare-and-set on status. True only if this call made the change."""
        result = self.col.update_one(
            {"_id": order_id, "status": from_status},
            {"$set": {**fields, "status": to_status, "updated_at": now},
             "$push": {"status_history": {"status": to_status, "at": now, "note": note}}},
        )
        return result.modified_count == 1

    _REPORT_FIELDS = {"status": 1, "created_at": 1, "total_paise": 1, "delivery_fee_paise": 1, "payment.status": 1,
                      "payment.provider": 1, "payment.refunded_paise": 1, "lines.product_id": 1, "lines.name": 1,
                      "lines.quantity": 1, "lines.line_total_paise": 1, "status_history": 1, "delivered_at": 1,
                      "delivery.failed_count": 1}

    def list_created_between(self, start, end, limit):
        """Slim copies of orders created in [start, end): no addresses, allocations or prescription data."""
        return list(self.col.find({"created_at": {"$gte": start, "$lt": end}}, self._REPORT_FIELDS).sort("created_at", ASCENDING).limit(limit))

    def count_by_status(self):
        return {r["_id"]: r["n"] for r in self.col.aggregate([{"$group": {"_id": "$status", "n": {"$sum": 1}}}])}

    def list_needing_attention(self, limit):
        return list(self.col.find({"needs_attention": {"$type": "string"}}).sort("updated_at", ASCENDING).limit(limit))

    def clear_attention(self, order_id, flag):
        """Removes the flag only if it is still exactly this one (a newer flag must not be cleared by a stale click)."""
        return self.col.update_one({"_id": order_id, "needs_attention": flag}, {"$unset": {"needs_attention": ""}}).modified_count == 1

    def list_for_partner(self, partner_id, statuses, limit):
        return list(self.col.find({"delivery.partner_id": partner_id, "status": {"$in": list(statuses)}})
                    .sort("updated_at", ASCENDING).limit(limit))

    def bump_code_tries(self, order_id, partner_id, limit):
        """Atomically counts one handover-code try. Returns the new count, or None if locked / not this partner's dispatched order."""
        doc = self.col.find_one_and_update(
            {"_id": order_id, "status": "dispatched", "delivery.partner_id": partner_id, "delivery.code_tries": {"$lt": limit}},
            {"$inc": {"delivery.code_tries": 1}}, return_document=True)
        return doc["delivery"]["code_tries"] if doc else None

    def record_failed_attempt(self, order_id, partner_id, reason, now):
        """Atomically records one failed attempt on this partner's dispatched order. Returns the new failed count, or None."""
        doc = self.col.find_one_and_update(
            {"_id": order_id, "status": "dispatched", "delivery.partner_id": partner_id},
            {"$inc": {"delivery.failed_count": 1}, "$push": {"delivery.attempts": {"reason": reason, "at": now, "by": partner_id}},
             "$set": {"updated_at": now}}, return_document=True)
        return doc["delivery"]["failed_count"] if doc else None

    def find_by_gateway_order(self, gateway_order_id):
        return self.col.find_one({"payment.gateway_order_id": gateway_order_id})

    def find_stale(self, status, before, limit):
        return list(self.col.find({"status": status, "updated_at": {"$lte": before}}).limit(limit))

    def set_fields(self, order_id, fields):
        self.col.update_one({"_id": order_id}, {"$set": fields})

    def list_by_status(self, statuses, limit):
        return list(self.col.find({"status": {"$in": list(statuses)}}).sort("updated_at", ASCENDING).limit(limit))

    def reserve_refund(self, order_id, amount):
        """Atomically adds amount to payment.refunded_paise ONLY IF the total stays <= what was paid."""
        result = self.col.update_one(
            {"_id": order_id, "payment.status": "paid",
             "$expr": {"$lte": [{"$add": [{"$ifNull": ["$payment.refunded_paise", 0]}, amount]}, "$total_paise"]}},
            {"$inc": {"payment.refunded_paise": amount}},
        )
        return result.modified_count == 1

    def release_refund(self, order_id, amount):
        self.col.update_one({"_id": order_id}, {"$inc": {"payment.refunded_paise": -amount}})

    def find_expired_pending(self, now, limit):
        return list(self.col.find({"status": "pending_payment", "reservation_expires_at": {"$lte": now}}).limit(limit))


def ensure_indexes(db):
    db["orders"].create_index([("order_number", ASCENDING)], unique=True, name="uniq_order_number")
    db["orders"].create_index([("user_id", ASCENDING), ("created_at", DESCENDING)], name="by_user")
    db["orders"].create_index([("status", ASCENDING), ("reservation_expires_at", ASCENDING)], name="pending_expiry")
    db["orders"].create_index([("status", ASCENDING), ("updated_at", ASCENDING)], name="by_status")
    db["orders"].create_index([("created_at", ASCENDING)], name="by_created")
    db["orders"].create_index([("needs_attention", ASCENDING)], name="needs_attention",
                              partialFilterExpression={"needs_attention": {"$type": "string"}})
    db["orders"].create_index([("delivery.partner_id", ASCENDING), ("status", ASCENDING)], name="by_partner",
                              partialFilterExpression={"delivery.partner_id": {"$type": "string"}})
    db["order_returns"].create_index([("order_id", ASCENDING), ("created_at", ASCENDING)], name="by_order")
    db["order_returns"].create_index([("order_id", ASCENDING)], unique=True, name="one_open_return_per_order",
                                     partialFilterExpression={"status": "requested"})
    db["order_returns"].create_index([("status", ASCENDING), ("created_at", ASCENDING)], name="by_status")
    db["orders"].create_index([("payment.gateway_order_id", ASCENDING)], name="by_gateway_order",
                              partialFilterExpression={"payment.gateway_order_id": {"$exists": True}})
    db["payment_events"].create_index([("received_at", ASCENDING)], name="events_ttl", expireAfterSeconds=90 * 24 * 3600)
    db["refunds"].create_index([("reference", ASCENDING)], name="by_reference",
                               partialFilterExpression={"reference": {"$type": "string"}})
    db["refunds"].create_index([("key", ASCENDING)], unique=True, name="uniq_refund_key")
    db["refunds"].create_index([("order_id", ASCENDING), ("created_at", ASCENDING)], name="by_order")
    db["refunds"].create_index([("status", ASCENDING), ("created_at", ASCENDING)], name="by_status")


class ReturnRepository:
    def __init__(self, db):
        self.col = db["order_returns"]

    def insert(self, doc):
        try:
            self.col.insert_one(doc)
        except DuplicateKeyError as exc:
            raise DuplicateError from exc

    def get(self, return_id):
        return self.col.find_one({"_id": return_id})

    def list_for_order(self, order_id):
        return list(self.col.find({"order_id": order_id}).sort("created_at", ASCENDING))

    def list_by_status(self, status, limit):
        return list(self.col.find({"status": status}).sort("created_at", ASCENDING).limit(limit))

    def decide(self, return_id, to_status, fields, now):
        """Atomic: only a still-'requested' return can be decided, once."""
        result = self.col.update_one({"_id": return_id, "status": "requested"},
                                     {"$set": {**fields, "status": to_status, "updated_at": now}})
        return result.modified_count == 1


class RefundRepository:
    def __init__(self, db):
        self.col = db["refunds"]

    def insert(self, doc):
        try:
            self.col.insert_one(doc)
        except DuplicateKeyError as exc:
            raise DuplicateError from exc

    def get(self, refund_id):
        return self.col.find_one({"_id": refund_id})

    def get_by_key(self, key):
        return self.col.find_one({"key": key})

    def list_for_order(self, order_id):
        return list(self.col.find({"order_id": order_id}).sort("created_at", ASCENDING))

    def list_by_status(self, status, limit):
        return list(self.col.find({"status": status}).sort("created_at", ASCENDING).limit(limit))

    def get_by_reference(self, reference):
        return self.col.find_one({"reference": reference})

    def fail_after_success(self, refund_id, message, now):
        """succeeded -> failed (the gateway reported the refund failed later). True only for the winner."""
        result = self.col.update_one({"_id": refund_id, "status": "succeeded"},
                                     {"$set": {"status": "failed", "message": message, "updated_at": now}})
        return result.modified_count == 1

    def claim_retry(self, refund_id, now):
        """failed -> pending, atomically, so two staff clicking retry cannot both send money."""
        result = self.col.update_one({"_id": refund_id, "status": "failed"},
                                     {"$set": {"status": "pending", "updated_at": now}, "$inc": {"attempts": 1}})
        return result.modified_count == 1

    def finish(self, refund_id, status, fields, now):
        result = self.col.update_one({"_id": refund_id, "status": "pending"},
                                     {"$set": {**fields, "status": status, "updated_at": now}})
        return result.modified_count == 1


class PaymentEventRepository:
    """Webhook events already handled (the gateway delivers some events more than once)."""

    def __init__(self, db):
        self.col = db["payment_events"]

    def seen(self, event_id):
        return self.col.count_documents({"_id": event_id}, limit=1) == 1

    def record(self, event_id, event, now):
        try:
            self.col.insert_one({"_id": event_id, "event": event, "received_at": now})
        except DuplicateKeyError:
            pass
