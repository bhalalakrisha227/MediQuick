"""
Sales and operations reports. No Django / MongoDB imports.

Definitions (shown to the user on the dashboard, so nobody misreads a number):
 * An order counts in a range by the day it was CREATED, in Indian time (IST).
 * "Gross paid" = total of orders whose payment status is paid (even if later cancelled or returned).
 * "Refunded" = money refunded on those orders (the refund is attributed to the order's creation day, not the refund day).
 * "Net" = gross paid - refunded.
 * Mock payments move no real money. If any order in the range used the mock provider the report says so.
 * Reports read at most MAX_ROWS_SCANNED orders and say when they were cut short. This is fine for a small shop and
   NOT for a large one (a real analytics pipeline would use database aggregation).
"""
import re
from datetime import date, datetime, time, timedelta

from apps.accounts.errors import ServiceError

from . import rules

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _forbidden():
    return ServiceError("forbidden", "You do not have permission to perform this action.", 403)


def _day(raw):
    if raw in (None, ""):
        return None
    if not isinstance(raw, str) or not _DATE.match(raw):
        raise ServiceError("validation_error", "Dates must look like 2026-11-05.", 400, {"range": "Invalid date."})
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ServiceError("validation_error", "Dates must look like 2026-11-05.", 400, {"range": "Invalid date."}) from None


def parse_range(params: dict, today: date) -> tuple[date, date]:
    end = _day(params.get("to")) or today
    start = _day(params.get("from")) or end - timedelta(days=rules.DEFAULT_RANGE_DAYS - 1)
    if start > end:
        raise ServiceError("validation_error", "The start date must not be after the end date.", 400, {"range": "from is after to."})
    if (end - start).days + 1 > rules.MAX_RANGE_DAYS:
        raise ServiceError("validation_error", f"Choose at most {rules.MAX_RANGE_DAYS} days.", 400, {"range": "Too long."})
    return start, end


def _bounds(start: date, end: date):
    return (datetime.combine(start, time.min, tzinfo=rules.IST), datetime.combine(end + timedelta(days=1), time.min, tzinfo=rules.IST))


def _first(history, status):
    for h in history or []:
        if h["status"] == status:
            return h["at"]
    return None


def _ratio(a, b):
    return round(a / b, 4) if b else None


class AnalyticsService:
    def __init__(self, orders, prescriptions, inventory_overview, attention_counts, clock):
        self.orders, self.prescriptions, self.inventory_overview = orders, prescriptions, inventory_overview
        self.attention_counts, self.clock = attention_counts, clock

    def today(self) -> date:
        return self.clock().astimezone(rules.IST).date()

    def sales(self, role: str, params: dict) -> dict:
        if role not in rules.ANALYTICS_ROLES:
            raise _forbidden()
        start, end = parse_range(params if isinstance(params, dict) else {}, self.today())
        lo, hi = _bounds(start, end)
        rows = self.orders.list_created_between(lo, hi, rules.MAX_ROWS_SCANNED + 1)
        truncated = len(rows) > rules.MAX_ROWS_SCANNED
        rows = rows[:rules.MAX_ROWS_SCANNED]

        days = {start + timedelta(days=i): {"orders": 0, "paid_orders": 0, "gross_paise": 0, "refunded_paise": 0}
                for i in range((end - start).days + 1)}
        by_status, products = {}, {}
        gross = refunded = fees = paid_n = 0
        mock = False
        delivered_hours, delivered_n, ever_dispatched, ever_failed, failed_attempts = [], 0, 0, 0, 0
        for o in rows:
            by_status[o["status"]] = by_status.get(o["status"], 0) + 1
            day = days.get(o["created_at"].astimezone(rules.IST).date())
            if day is not None:
                day["orders"] += 1
            pay = o.get("payment") or {}
            if pay.get("status") == "paid":
                paid_n += 1
                gross += o["total_paise"]
                refunded += pay.get("refunded_paise", 0)
                fees += o.get("delivery_fee_paise", 0)
                mock = mock or pay.get("provider") == "mock"
                if day is not None:
                    day["paid_orders"] += 1
                    day["gross_paise"] += o["total_paise"]
                    day["refunded_paise"] += pay.get("refunded_paise", 0)
                if o["status"] in rules.SOLD_STATUSES:
                    for line in o["lines"]:
                        p = products.setdefault(line["product_id"], {"product_id": line["product_id"], "name": line["name"], "units": 0, "revenue_paise": 0})
                        p["units"] += line["quantity"]
                        p["revenue_paise"] += line["line_total_paise"]
            history = o.get("status_history") or []
            if _first(history, "dispatched"):
                ever_dispatched += 1
            if _first(history, "delivery_failed"):
                ever_failed += 1
            failed_attempts += (o.get("delivery") or {}).get("failed_count", 0)
            if o["status"] == "delivered" and o.get("delivered_at") and _first(history, "confirmed"):
                delivered_n += 1
                delivered_hours.append((o["delivered_at"] - _first(history, "confirmed")).total_seconds() / 3600)

        top = sorted(products.values(), key=lambda p: (-p["units"], p["name"]))[:rules.TOP_PRODUCTS]
        return {
            "range": {"from": start.isoformat(), "to": end.isoformat(), "timezone": "IST (UTC+05:30)"},
            "truncated": truncated, "rows_scanned": len(rows), "includes_mock_payments": mock,
            "totals": {"orders": len(rows), "paid_orders": paid_n, "gross_paise": gross, "refunded_paise": refunded,
                       "net_paise": gross - refunded, "delivery_fees_paise": fees,
                       "average_order_paise": gross // paid_n if paid_n else None,
                       "refund_rate": _ratio(refunded, gross)},
            "orders_by_status": by_status,
            "cancel_rate": _ratio(by_status.get("cancelled", 0) + by_status.get("expired", 0), len(rows)),
            "daily": [{"date": d.isoformat(), **v} for d, v in sorted(days.items())],
            "top_products": top,
            "delivery": {"delivered": delivered_n, "average_hours_confirmed_to_delivered":
                         round(sum(delivered_hours) / len(delivered_hours), 1) if delivered_hours else None,
                         "orders_with_failed_delivery": ever_failed, "failed_attempts": failed_attempts,
                         "failed_delivery_rate": _ratio(ever_failed, ever_dispatched)},
        }

    def operations(self, role: str) -> dict:
        if role not in rules.ANALYTICS_ROLES:
            raise _forbidden()
        return {"orders_by_status": self.orders.count_by_status(),
                "prescriptions_by_status": self.prescriptions.count_by_status(),
                "attention": self.attention_counts(),
                "inventory": self.inventory_overview()}
