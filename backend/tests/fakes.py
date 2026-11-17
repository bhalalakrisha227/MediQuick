"""In-memory repositories with the same interface as apps/accounts/repository.py."""
from copy import deepcopy

from apps.accounts.errors import DuplicateError


def _set_fields(doc, fields):
    """Like Mongo $set: dotted keys reach into sub-documents."""
    for key, value in deepcopy(fields).items():
        parts = key.split(".")
        target = doc
        for p in parts[:-1]:
            target = target.setdefault(p, {})
        target[parts[-1]] = value


class FakeUsers:
    def __init__(self):
        self.docs = {}

    def insert(self, doc):
        if any(d["email"] == doc["email"] for d in self.docs.values()):
            raise DuplicateError
        self.docs[doc["_id"]] = deepcopy(doc)

    def get(self, user_id):
        d = self.docs.get(user_id)
        return deepcopy(d) if d else None

    def get_by_email(self, email):
        return next((deepcopy(d) for d in self.docs.values() if d["email"] == email), None)

    def update(self, user_id, fields):
        self.docs[user_id].update(deepcopy(fields))

    def list_page(self, escaped_query, role, skip, limit):
        import re
        rows = [d for d in self.docs.values() if (not role or d["role"] == role) and
                (not escaped_query or re.search(escaped_query, d["email"], re.I) or re.search(escaped_query, d.get("full_name", ""), re.I))]
        rows.sort(key=lambda d: d["created_at"], reverse=True)
        return [deepcopy(d) for d in rows[skip:skip + limit]], len(rows)

    def count_active_admins(self):
        return sum(1 for d in self.docs.values() if d["role"] == "admin" and d.get("is_active"))

    def list_by_role(self, role, limit=200):
        return [deepcopy(d) for d in self.docs.values() if d.get("role") == role and d.get("is_active")][:limit]


class FakeTokens:
    def __init__(self):
        self.docs = {}

    def insert(self, doc):
        self.docs[doc["_id"]] = deepcopy(doc)

    def get_by_hash(self, token_hash):
        return next((deepcopy(d) for d in self.docs.values() if d["token_hash"] == token_hash), None)

    def mark_used(self, token_id):
        if self.docs[token_id]["used"]:
            return False
        self.docs[token_id]["used"] = True
        return True

    def revoke_family(self, family_id):
        for d in self.docs.values():
            if d["family_id"] == family_id:
                d["revoked"] = True


class FakeAddresses:
    def __init__(self):
        self.docs = {}

    def list(self, user_id):
        return sorted((deepcopy(d) for d in self.docs.values() if d["user_id"] == user_id),
                      key=lambda d: d["created_at"])

    def count(self, user_id):
        return len(self.list(user_id))

    def insert(self, doc):
        self.docs[doc["_id"]] = deepcopy(doc)

    def get(self, user_id, address_id):
        d = self.docs.get(address_id)
        return deepcopy(d) if d and d["user_id"] == user_id else None

    def update(self, user_id, address_id, fields):
        if self.get(user_id, address_id):
            self.docs[address_id].update(deepcopy(fields))

    def delete(self, user_id, address_id):
        if self.get(user_id, address_id):
            del self.docs[address_id]

    def clear_default(self, user_id):
        for d in self.docs.values():
            if d["user_id"] == user_id:
                d["is_default"] = False


# ---- catalogue -------------------------------------------------------------
class FakeCategories:
    def __init__(self):
        self.docs = {}

    def list_active(self):
        rows = [deepcopy(d) for d in self.docs.values() if d["is_active"]]
        return sorted(rows, key=lambda d: (d.get("sort_order", 0), d["name"]))

    def get_by_slug(self, slug):
        return next((deepcopy(d) for d in self.docs.values() if d["slug"] == slug), None)

    def insert(self, doc):
        if any(d["name"] == doc["name"] or d["slug"] == doc["slug"] for d in self.docs.values()):
            raise DuplicateError
        self.docs[doc["_id"]] = deepcopy(doc)


class FakeProducts:
    """Python re-implementation of build_query/SORTS semantics (no MongoDB available in tests)."""

    def __init__(self):
        self.docs = {}

    def get(self, product_id):
        d = self.docs.get(product_id)
        return deepcopy(d) if d else None

    def get_by_slug(self, slug):
        return next((deepcopy(d) for d in self.docs.values() if d["slug"] == slug), None)

    def get_many(self, product_ids):
        return {i: deepcopy(self.docs[i]) for i in set(product_ids) if i in self.docs}

    def list_active(self, limit):
        rows = sorted((d for d in self.docs.values() if d["is_active"]), key=lambda d: d["name_lower"])
        return [deepcopy(d) for d in rows[:limit]]

    def insert(self, doc):
        if any(d["slug"] == doc["slug"] for d in self.docs.values()):
            raise DuplicateError
        self.docs[doc["_id"]] = deepcopy(doc)

    def update(self, product_id, fields):
        self.docs[product_id].update(deepcopy(fields))

    def search(self, f, sort, skip, limit):
        from apps.catalogue.queries import SEARCH_FIELDS, SORTS

        rows = [d for d in self.docs.values() if d["is_active"]]
        if f.get("category"):
            rows = [d for d in rows if d["category"] == f["category"]]
        if f.get("rx") == "otc":
            rows = [d for d in rows if not d["requires_prescription"]]
        if f.get("rx") == "prescription":
            rows = [d for d in rows if d["requires_prescription"]]
        if f.get("min_price") is not None:
            rows = [d for d in rows if d["price_paise"] >= f["min_price"]]
        if f.get("max_price") is not None:
            rows = [d for d in rows if d["price_paise"] <= f["max_price"]]
        if f.get("q"):
            needle = f["q"].lower()
            rows = [d for d in rows if any(needle in d.get(k, "").lower() for k in SEARCH_FIELDS)]
        for key, direction in reversed(SORTS[sort]):
            rows.sort(key=lambda d: d[key], reverse=direction == -1)
        return [deepcopy(d) for d in rows[skip:skip + limit]], len(rows)


# ---- inventory -------------------------------------------------------------
class FakeBatches:
    """Python re-implementation of the repository's query semantics."""

    def __init__(self):
        self.docs = {}

    def insert(self, doc):
        if any(d["product_id"] == doc["product_id"] and d["batch_number"] == doc["batch_number"]
               for d in self.docs.values()):
            raise DuplicateError
        self.docs[doc["_id"]] = deepcopy(doc)

    def get(self, batch_id):
        d = self.docs.get(batch_id)
        return deepcopy(d) if d else None

    def list(self, f, today_dt, warning_days, skip, limit):
        from datetime import timedelta

        rows = list(self.docs.values())
        if f.get("product_id"):
            rows = [d for d in rows if d["product_id"] == f["product_id"]]
        if f.get("status"):
            rows = [d for d in rows if d["status"] == f["status"]]
        state = f.get("state", "all")
        if state == "expired":
            rows = [d for d in rows if d["expiry_date"] < today_dt and d["quantity_on_hand"] > 0]
        elif state == "expiring":
            end = today_dt + timedelta(days=warning_days)
            rows = [d for d in rows if today_dt <= d["expiry_date"] <= end and d["quantity_on_hand"] > 0]
        elif state == "in_stock":
            rows = [d for d in rows if d["quantity_on_hand"] > 0]
        rows.sort(key=lambda d: (d["expiry_date"], d["batch_number"]))
        return [deepcopy(d) for d in rows[skip:skip + limit]], len(rows)

    def adjust_on_hand(self, batch_id, delta):
        d = self.docs[batch_id]
        new = d["quantity_on_hand"] + delta
        if new < 0 or new < d["quantity_reserved"]:
            return None
        d["quantity_on_hand"] = new
        return new

    def set_status(self, batch_id, status, now):
        self.docs[batch_id]["status"] = status

    def sellable_batches(self, product_id, cutoff_dt):
        rows = [d for d in self.docs.values()
                if d["product_id"] == product_id and d["status"] == "active" and d["expiry_date"] >= cutoff_dt
                and d["quantity_on_hand"] > d["quantity_reserved"]]
        rows.sort(key=lambda d: (d["expiry_date"], d["batch_number"]))
        return [deepcopy(d) for d in rows]

    def reserve(self, batch_id, qty):
        d = self.docs[batch_id]
        if d["status"] != "active" or d["quantity_on_hand"] - d["quantity_reserved"] < qty:
            return False
        d["quantity_reserved"] += qty
        return True

    def release(self, batch_id, qty):
        d = self.docs[batch_id]
        if d["quantity_reserved"] < qty:
            return False
        d["quantity_reserved"] -= qty
        return True

    def commit(self, batch_id, qty):
        d = self.docs[batch_id]
        if d["quantity_reserved"] < qty or d["quantity_on_hand"] < qty:
            return None
        d["quantity_on_hand"] -= qty
        d["quantity_reserved"] -= qty
        return d["quantity_on_hand"]

    def sellable_summary(self, product_ids, cutoff_dt):
        out = {}
        for d in self.docs.values():
            if (d["product_id"] in product_ids and d["status"] == "active" and d["expiry_date"] >= cutoff_dt
                    and d["quantity_on_hand"] > d["quantity_reserved"]):
                row = out.setdefault(d["product_id"], {"sellable": 0, "earliest_expiry": d["expiry_date"]})
                row["sellable"] += d["quantity_on_hand"] - d["quantity_reserved"]
                row["earliest_expiry"] = min(row["earliest_expiry"], d["expiry_date"])
        return out


class FakeMovements:
    def __init__(self):
        self.docs = []

    def insert(self, doc):
        self.docs.append(deepcopy(doc))

    def list_for_batch(self, batch_id, limit):
        rows = [deepcopy(d) for d in self.docs if d["batch_id"] == batch_id]
        return sorted(rows, key=lambda d: d["created_at"], reverse=True)[:limit]


# ---- orders ----------------------------------------------------------------
class FakeCarts:
    def __init__(self):
        self.docs = {}

    def get(self, user_id):
        d = self.docs.get(user_id)
        return deepcopy(d) if d else None

    def save(self, user_id, items, now):
        if not items:
            self.docs.pop(user_id, None)
        else:
            self.docs[user_id] = {"_id": user_id, "items": deepcopy(items), "updated_at": now}

    def claim(self, user_id):
        return self.docs.pop(user_id, None)

    def restore_if_empty(self, user_id, items, now):
        if user_id not in self.docs:
            self.docs[user_id] = {"_id": user_id, "items": deepcopy(items), "updated_at": now}


class FakeOrders:
    def __init__(self):
        self.docs = {}

    def insert(self, doc):
        if any(d["order_number"] == doc["order_number"] for d in self.docs.values()):
            raise DuplicateError
        self.docs[doc["_id"]] = deepcopy(doc)

    def get(self, order_id):
        d = self.docs.get(order_id)
        return deepcopy(d) if d else None

    def get_for_user(self, user_id, order_id):
        d = self.docs.get(order_id)
        return deepcopy(d) if d and d["user_id"] == user_id else None

    def list_for_user(self, user_id, skip, limit):
        rows = sorted((d for d in self.docs.values() if d["user_id"] == user_id),
                      key=lambda d: d["created_at"], reverse=True)
        return [deepcopy(d) for d in rows[skip:skip + limit]], len(rows)

    def transition(self, order_id, from_status, to_status, fields, note, now):
        d = self.docs[order_id]
        if d["status"] != from_status:
            return False
        _set_fields(d, fields)
        d["status"], d["updated_at"] = to_status, now
        d["status_history"].append({"status": to_status, "at": now, "note": note})
        return True

    def list_created_between(self, start, end, limit):
        rows = sorted((d for d in self.docs.values() if start <= d["created_at"] < end), key=lambda d: d["created_at"])
        return [deepcopy(d) for d in rows[:limit]]

    def count_by_status(self):
        out = {}
        for d in self.docs.values():
            out[d["status"]] = out.get(d["status"], 0) + 1
        return out

    def list_needing_attention(self, limit):
        rows = sorted((d for d in self.docs.values() if isinstance(d.get("needs_attention"), str)), key=lambda d: d["updated_at"])
        return [deepcopy(d) for d in rows[:limit]]

    def clear_attention(self, order_id, flag):
        d = self.docs[order_id]
        if d.get("needs_attention") != flag:
            return False
        del d["needs_attention"]
        return True

    def list_for_partner(self, partner_id, statuses, limit):
        rows = [d for d in self.docs.values() if (d.get("delivery") or {}).get("partner_id") == partner_id and d["status"] in statuses]
        return [deepcopy(d) for d in sorted(rows, key=lambda d: d["updated_at"])[:limit]]

    def bump_code_tries(self, order_id, partner_id, limit):
        d = self.docs[order_id]
        dv = d.get("delivery") or {}
        if d["status"] != "dispatched" or dv.get("partner_id") != partner_id or dv.get("code_tries", 0) >= limit:
            return None
        dv["code_tries"] = dv.get("code_tries", 0) + 1
        return dv["code_tries"]

    def record_failed_attempt(self, order_id, partner_id, reason, now):
        d = self.docs[order_id]
        dv = d.get("delivery") or {}
        if d["status"] != "dispatched" or dv.get("partner_id") != partner_id:
            return None
        dv["failed_count"] = dv.get("failed_count", 0) + 1
        dv.setdefault("attempts", []).append({"reason": reason, "at": now, "by": partner_id})
        d["updated_at"] = now
        return dv["failed_count"]

    def find_expired_pending(self, now, limit):
        rows = [deepcopy(d) for d in self.docs.values()
                if d["status"] == "pending_payment" and d["reservation_expires_at"] <= now]
        return rows[:limit]

    def set_fields(self, order_id, fields):
        _set_fields(self.docs[order_id], fields)

    def find_by_gateway_order(self, gateway_order_id):
        return next((deepcopy(d) for d in self.docs.values() if d["payment"].get("gateway_order_id") == gateway_order_id), None)

    def find_stale(self, status, before, limit):
        return [deepcopy(d) for d in self.docs.values() if d["status"] == status and d["updated_at"] <= before][:limit]

    def list_by_status(self, statuses, limit):
        rows = sorted((d for d in self.docs.values() if d["status"] in statuses), key=lambda d: d["updated_at"])
        return [deepcopy(d) for d in rows[:limit]]

    def reserve_refund(self, order_id, amount):
        d = self.docs[order_id]
        if d["payment"]["status"] != "paid" or d["payment"].get("refunded_paise", 0) + amount > d["total_paise"]:
            return False
        d["payment"]["refunded_paise"] = d["payment"].get("refunded_paise", 0) + amount
        return True

    def release_refund(self, order_id, amount):
        self.docs[order_id]["payment"]["refunded_paise"] -= amount


from apps.prescriptions import rules as _rx

ACTIVE, DRAFTS, EDITABLE = _rx.ACTIVE_STATUSES, _rx.DRAFT_STATUSES, _rx.CUSTOMER_EDITABLE


class FakePrescriptions:
    """In-memory twin of PrescriptionRepository (same atomic-conditional semantics)."""

    def __init__(self):
        self.docs, self.access, self.audit = {}, [], []

    def insert(self, doc):
        for d in self.docs.values():
            if (d["user_id"] == doc["user_id"] and d["file"]["sha256"] == doc["file"]["sha256"]
                    and d["status"] in ACTIVE):
                raise DuplicateError
        self.docs[doc["_id"]] = deepcopy(doc)

    def get(self, pid):
        d = self.docs.get(pid)
        return deepcopy(d) if d else None

    def get_for_user(self, user_id, pid):
        d = self.docs.get(pid)
        return deepcopy(d) if d and d["user_id"] == user_id else None

    def list_for_user(self, user_id, limit):
        rows = sorted((d for d in self.docs.values() if d["user_id"] == user_id and d["status"] != "withdrawn"),
                      key=lambda d: d["created_at"], reverse=True)
        return [deepcopy(d) for d in rows[:limit]]

    def count_drafts(self, user_id):
        return sum(1 for d in self.docs.values() if d["user_id"] == user_id and d["status"] in DRAFTS)

    def find_active_by_hash(self, user_id, sha):
        for d in self.docs.values():
            if d["user_id"] == user_id and d["file"]["sha256"] == sha and d["status"] in ACTIVE:
                return deepcopy(d)
        return None

    def _claimable(self, d, stale_before):
        o = d.get("ocr", {})
        return d["status"] == "processing" and (o.get("status") == "pending"
                                                or (o.get("status") == "running" and o.get("started_at") <= stale_before))

    def claim_ocr(self, pid, now, stale_before):
        d = self.docs.get(pid)
        if not d or not self._claimable(d, stale_before):
            return None
        out = deepcopy(d)
        d["ocr"] = {**d["ocr"], "status": "running", "started_at": now}
        d["updated_at"] = now
        return out

    def finish_ocr(self, pid, ocr, now):
        d = self.docs.get(pid)
        if not d or d["status"] != "processing":
            return False
        d["ocr"], d["status"], d["updated_at"] = deepcopy(ocr), "needs_customer_review", now
        d["status_history"].append({"status": "needs_customer_review", "at": now, "note": f"ocr {ocr.get('status')}"})
        return True

    def reset_for_retry(self, user_id, pid, now):
        d = self.docs.get(pid)
        if not d or d["user_id"] != user_id or d["status"] != "needs_customer_review" or d["ocr"].get("status") not in ("failed", "unavailable"):
            return False
        d["status"], d["ocr"], d["updated_at"] = "processing", {"status": "pending"}, now
        d["status_history"].append({"status": "processing", "at": now, "note": "ocr retry"})
        return True

    def update_review(self, user_id, pid, fields, now):
        d = self.docs.get(pid)
        if not d or d["user_id"] != user_id or d["status"] not in EDITABLE:
            return False
        d.update(deepcopy(fields))
        d["updated_at"] = now
        return True

    def transition(self, pid, user_id, from_statuses, to_status, fields, note, now):
        d = self.docs.get(pid)
        if not d or d["user_id"] != user_id or d["status"] not in from_statuses:
            return False
        d.update(deepcopy(fields))
        d["status"], d["updated_at"] = to_status, now
        d["status_history"].append({"status": to_status, "at": now, "note": note})
        return True

    def find_pending(self, now, stale_before, limit):
        return [d["_id"] for d in self.docs.values() if self._claimable(d, stale_before)][:limit]

    def log_access(self, doc):
        self.access.append(deepcopy(doc))

    # ---- pharmacist review ----

    def list_for_staff(self, statuses, limit, assigned_to=None, oldest_first=True):
        rows = [d for d in self.docs.values() if d["status"] in statuses and (not assigned_to or (d.get("assigned_to") or {}).get("id") == assigned_to)]
        key = (lambda d: d.get("submitted_at") or d["created_at"]) if oldest_first else (lambda d: d["updated_at"])
        return [deepcopy(d) for d in sorted(rows, key=key, reverse=not oldest_first)[:limit]]

    def staff_transition(self, pid, from_status, to_status, fields, note, now, assignee_id=None, unset=None):
        d = self.docs.get(pid)
        if not d or d["status"] != from_status:
            return False
        if assignee_id and (d.get("assigned_to") or {}).get("id") != assignee_id:
            return False
        d.update(deepcopy(fields))
        for k in unset or []:
            d.pop(k, None)
        d["status"], d["updated_at"] = to_status, now
        d["status_history"].append({"status": to_status, "at": now, "note": note})
        return True

    def count_by_status(self):
        out = {}
        for d in self.docs.values():
            out[d["status"]] = out.get(d["status"], 0) + 1
        return out

    def count_claims(self, user_id):
        return sum(1 for d in self.docs.values() if d["status"] == "in_review" and (d.get("assigned_to") or {}).get("id") == user_id)

    def log_audit(self, doc):
        self.audit.append(deepcopy(doc))

    def audit_for(self, pid, limit=100):
        return [deepcopy(a) for a in self.audit if a["prescription_id"] == pid][:limit]

    # ---- allowances ----
    def list_approved(self, user_id, now):
        rows = [d for d in self.docs.values() if d["user_id"] == user_id and d["status"] == "approved" and d["approval"]["valid_until"] > now]
        return [deepcopy(d) for d in sorted(rows, key=lambda d: d["approval"]["valid_until"])]

    def consume_allowance(self, user_id, product_id, quantity, now):
        for d in sorted((d for d in self.docs.values() if d["user_id"] == user_id and d["status"] == "approved"
                         and d["approval"]["valid_until"] > now), key=lambda d: d["approval"]["valid_until"]):
            for item in d["approval"]["items"]:
                if item["product_id"] == product_id and item["remaining"] >= quantity:
                    item["remaining"] -= quantity
                    return d["_id"]
        return None

    def restore_allowance(self, pid, product_id, quantity, now):
        d = self.docs.get(pid)
        if not d or not d.get("approval"):
            return False
        for item in d["approval"]["items"]:
            if item["product_id"] == product_id:
                item["remaining"] += quantity
                return True
        return False

    def has_file_view(self, pid, actor_id, since):
        return any(a["prescription_id"] == pid and a["actor_id"] == actor_id and a["action"] == "view_file" and a["at"] >= since
                   for a in self.access)


class FakeReturns:
    def __init__(self):
        self.docs = {}

    def insert(self, doc):
        if any(d["order_id"] == doc["order_id"] and d["status"] == "requested" for d in self.docs.values()):
            raise DuplicateError
        self.docs[doc["_id"]] = deepcopy(doc)

    def get(self, rid):
        d = self.docs.get(rid)
        return deepcopy(d) if d else None

    def list_for_order(self, order_id):
        return [deepcopy(d) for d in sorted(self.docs.values(), key=lambda d: d["created_at"]) if d["order_id"] == order_id]

    def list_by_status(self, status, limit):
        return [deepcopy(d) for d in sorted(self.docs.values(), key=lambda d: d["created_at"]) if d["status"] == status][:limit]

    def decide(self, rid, to_status, fields, now):
        d = self.docs.get(rid)
        if not d or d["status"] != "requested":
            return False
        d.update(deepcopy(fields))
        d["status"], d["updated_at"] = to_status, now
        return True


class FakeRefunds:
    def __init__(self):
        self.docs = {}

    def insert(self, doc):
        if any(d["key"] == doc["key"] for d in self.docs.values()):
            raise DuplicateError
        self.docs[doc["_id"]] = deepcopy(doc)

    def get(self, rid):
        d = self.docs.get(rid)
        return deepcopy(d) if d else None

    def get_by_key(self, key):
        return next((deepcopy(d) for d in self.docs.values() if d["key"] == key), None)

    def list_for_order(self, order_id):
        return [deepcopy(d) for d in sorted(self.docs.values(), key=lambda d: d["created_at"]) if d["order_id"] == order_id]

    def list_by_status(self, status, limit):
        return [deepcopy(d) for d in self.docs.values() if d["status"] == status][:limit]

    def get_by_reference(self, ref):
        return next((deepcopy(d) for d in self.docs.values() if d.get("reference") == ref), None)

    def fail_after_success(self, rid, message, now):
        d = self.docs.get(rid)
        if not d or d["status"] != "succeeded":
            return False
        d["status"], d["message"], d["updated_at"] = "failed", message, now
        return True

    def claim_retry(self, rid, now):
        d = self.docs.get(rid)
        if not d or d["status"] != "failed":
            return False
        d["status"], d["updated_at"] = "pending", now
        d["attempts"] += 1
        return True

    def finish(self, rid, status, fields, now):
        d = self.docs.get(rid)
        if not d or d["status"] != "pending":
            return False
        d.update(deepcopy(fields))
        d["status"], d["updated_at"] = status, now
        return True


class FakePaymentEvents:
    def __init__(self):
        self.ids = {}

    def seen(self, event_id):
        return event_id in self.ids

    def record(self, event_id, event, now):
        self.ids.setdefault(event_id, event)


class FakeNotifications:
    def __init__(self):
        self.docs = {}

    def insert(self, doc):
        if any(d["key"] == doc["key"] for d in self.docs.values()):
            raise DuplicateError
        self.docs[doc["_id"]] = deepcopy(doc)

    def get(self, nid):
        d = self.docs.get(nid)
        return deepcopy(d) if d else None

    def list_for_user(self, user_id, unread_only, skip, limit):
        rows = sorted((d for d in self.docs.values() if d["user_id"] == user_id and (not unread_only or d["read_at"] is None)),
                      key=lambda d: d["created_at"], reverse=True)
        return [deepcopy(d) for d in rows[skip:skip + limit]], len(rows)

    def unread_count(self, user_id):
        return sum(1 for d in self.docs.values() if d["user_id"] == user_id and d["read_at"] is None)

    def mark_read(self, user_id, nid, now):
        d = self.docs.get(nid)
        if not d or d["user_id"] != user_id or d["read_at"] is not None:
            return False
        d["read_at"] = now
        return True

    def mark_all_read(self, user_id, now):
        for d in self.docs.values():
            if d["user_id"] == user_id and d["read_at"] is None:
                d["read_at"] = now

    def claim_due(self, now, lease_until):
        rows = [d for d in self.docs.values()
                if (d["email"]["status"] == "pending" and d["email"]["next_attempt_at"] <= now)
                or (d["email"]["status"] == "sending" and d["email"]["lease_until"] <= now)]
        if not rows:
            return None
        d = min(rows, key=lambda x: x["email"]["next_attempt_at"])
        before = deepcopy(d)
        d["email"]["status"], d["email"]["lease_until"] = "sending", lease_until
        return before

    def finish_email(self, nid, fields):
        self.docs[nid]["email"].update(deepcopy(fields))
        self.docs[nid]["email"]["lease_until"] = None


class FakeAudit:
    def __init__(self):
        self.docs = []

    def insert(self, doc):
        self.docs.append(deepcopy(doc))

    def list_recent(self, skip, limit):
        rows = sorted(self.docs, key=lambda d: d["at"], reverse=True)
        return [deepcopy(d) for d in rows[skip:skip + limit]], len(rows)
