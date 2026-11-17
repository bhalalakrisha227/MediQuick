import unittest
from datetime import date, datetime, timedelta, timezone
from unittest import mock

from apps.accounts.errors import ServiceError
from apps.adminpanel import rules
from apps.adminpanel.analytics import AnalyticsService, parse_range
from apps.adminpanel.attention import AttentionService, AuditLog
from apps.adminpanel.users import UserAdminService

from .fakes import FakeAudit
from .test_delivery import DelBase

ADMIN, MGR = ("a1", "admin"), ("m1", "pharmacy_manager")


class AdminBase(DelBase):
    def setUp(self):
        super().setUp()
        for uid, role in (("a1", "admin"), ("a2", "admin"), ("m1", "pharmacy_manager")):
            self.users.insert({"_id": uid, "email": f"{uid}@staff.test", "full_name": f"Staff {uid}", "role": role,
                               "is_active": True, "created_at": self.clock()})
        for uid in ("u1", "u2"):
            self.users.insert({"_id": uid, "email": f"{uid}@x.test", "full_name": uid, "role": "customer", "is_active": True})
        for doc in self.users.docs.values():
            doc.setdefault("created_at", self.clock())
        self.audit_repo = FakeAudit()
        self.audit = AuditLog(self.audit_repo, self.clock)
        self.attn = AttentionService(self.order_repo, self.refund_repo, self.audit, self.clock)
        self.useradmin = UserAdminService(self.users, self.audit, self.clock)
        self.an = AnalyticsService(self.order_repo, self.rx_repo, lambda: {"low_stock": []}, self.attn.counts, self.clock)

    def err(self, fn, *a):
        with self.assertRaises(ServiceError) as c:
            fn(*a)
        return c.exception.code

    def sales(self, **params):
        return self.an.sales("admin", params)


class RangeTests(unittest.TestCase):
    T = date(2026, 6, 1)

    def test_defaults_to_the_last_30_days_ending_today(self):
        s, e = parse_range({}, self.T)
        self.assertEqual((e, (e - s).days + 1), (self.T, 30))

    def test_explicit_and_boundaries(self):
        self.assertEqual(parse_range({"from": "2026-01-01", "to": "2026-01-01"}, self.T), (date(2026, 1, 1), date(2026, 1, 1)))
        s, e = parse_range({"from": "2025-05-31", "to": "2026-05-31"}, self.T)           # exactly 366 days
        self.assertEqual((e - s).days + 1, 366)

    def test_rejects_bad_ranges(self):
        for params in ({"from": "2026-13-45"}, {"to": "20261105"}, {"from": "2026-1-5"}, {"from": 5}, {"to": "x"},
                       {"from": "2026-06-02", "to": "2026-06-01"}, {"from": "2025-05-30", "to": "2026-05-31"}):
            with self.assertRaises(ServiceError, msg=str(params)) as c:
                parse_range(params, self.T)
            self.assertEqual(c.exception.code, "validation_error")


class SalesTests(AdminBase):
    def test_roles(self):
        for role in ("customer", "pharmacist", "inventory_staff", "delivery_partner", "support_agent", ""):
            self.assertEqual(self.err(self.an.sales, role, {}), "forbidden", role)
            self.assertEqual(self.err(self.an.operations, role), "forbidden", role)
        self.assertEqual(self.an.sales("pharmacy_manager", {})["totals"]["orders"], 0)

    def test_empty_period_has_no_division_errors(self):
        r = self.sales()
        self.assertEqual((r["totals"]["gross_paise"], r["totals"]["average_order_paise"], r["totals"]["refund_rate"],
                          r["cancel_rate"], r["delivery"]["average_hours_confirmed_to_delivered"]), (0, None, None, None, None))
        self.assertEqual(len(r["daily"]), 30)

    def test_money_definitions(self):
        a = self.paid([(self.para, 3)])                  # paid, stays confirmed
        b = self.paid([(self.para, 2)], user="u2")
        self.life.cancel("u2", b["id"])                  # paid then cancelled and refunded in full
        unpaid = self.place([(self.para, 1)])            # never paid
        self.orders.cancel("u1", unpaid["id"])
        r = self.sales()
        ta, tb = (self.order_repo.docs[x["id"]]["total_paise"] for x in (a, b))
        t = r["totals"]
        self.assertEqual((t["orders"], t["paid_orders"]), (3, 2))
        self.assertEqual((t["gross_paise"], t["refunded_paise"], t["net_paise"]), (ta + tb, tb, ta))
        self.assertEqual(t["average_order_paise"], (ta + tb) // 2)
        self.assertEqual(r["orders_by_status"], {"confirmed": 1, "cancelled": 2})
        self.assertAlmostEqual(r["cancel_rate"], round(2 / 3, 4))
        self.assertTrue(r["includes_mock_payments"])
        today = next(d for d in r["daily"] if d["orders"])
        self.assertEqual((today["date"], today["orders"], today["paid_orders"], today["gross_paise"]), ("2026-06-01", 3, 2, ta + tb))

    def test_top_products_count_only_sold_orders(self):
        self.paid([(self.para, 3)])
        b = self.paid([(self.para, 2)], user="u2")
        self.life.cancel("u2", b["id"])
        top = self.sales()["top_products"]
        self.assertEqual([(p["name"], p["units"]) for p in top], [(top[0]["name"], 3)])      # the cancelled 2 are not counted
        self.assertEqual(top[0]["revenue_paise"], self.order_repo.docs[next(iter(self.order_repo.docs))]["lines"][0]["line_total_paise"])

    def test_top_products_are_ranked_by_units_and_capped(self):
        other = self.product("Ibuprofen", 5000)
        self.stock(other, "IB1", 400, 50)
        self.paid([(self.para, 3), (other, 1)])
        self.paid([(other, 1)], user="u2")
        extra = []
        for i in range(rules.TOP_PRODUCTS + 2):
            pid = self.product(f"Extra{i:02d}", 1000)
            self.stock(pid, f"E{i}", 400, 5)
            extra.append(pid)
        self.paid([(pid, 1) for pid in extra])
        top = self.sales()["top_products"]
        self.assertEqual(len(top), rules.TOP_PRODUCTS)
        self.assertEqual([(p["units"]) for p in top[:2]], [3, 2])
        self.assertEqual(top[0]["product_id"], self.para)
        self.assertEqual(top[1]["product_id"], other)
        self.assertEqual([p["units"] for p in top], sorted((p["units"] for p in top), reverse=True))

    def test_days_are_indian_days(self):
        o = self.paid([(self.para, 1)])
        # 18:45 UTC on 31 May is 00:15 IST on 1 June.
        self.order_repo.docs[o["id"]]["created_at"] = datetime(2026, 5, 31, 18, 45, tzinfo=timezone.utc)
        r = self.sales(**{"from": "2026-05-31", "to": "2026-06-01"})
        self.assertEqual({d["date"]: d["orders"] for d in r["daily"]}, {"2026-05-31": 0, "2026-06-01": 1})
        self.order_repo.docs[o["id"]]["created_at"] = datetime(2026, 5, 31, 18, 29, tzinfo=timezone.utc)   # 23:59 IST on 31 May
        r = self.sales(**{"from": "2026-05-31", "to": "2026-06-01"})
        self.assertEqual({d["date"]: d["orders"] for d in r["daily"]}, {"2026-05-31": 1, "2026-06-01": 0})

    def test_orders_outside_the_range_are_excluded(self):
        self.paid([(self.para, 1)])
        self.assertEqual(self.sales(**{"from": "2026-05-01", "to": "2026-05-31"})["totals"]["orders"], 0)
        self.assertEqual(self.sales(**{"from": "2026-06-01", "to": "2026-06-01"})["totals"]["orders"], 1)

    def test_delivery_statistics(self):
        o = self.assigned()
        self.dl.pickup("rider1", o)
        self.clock.advance(90)
        self.dl.complete("rider1", o, {"code": self.code(o)})
        f = self.picked(user="u2")
        self.fail_times(f, 3)
        d = self.sales()["delivery"]
        self.assertEqual((d["delivered"], d["orders_with_failed_delivery"], d["failed_attempts"], d["failed_delivery_rate"]), (1, 1, 3, 0.5))
        self.assertAlmostEqual(d["average_hours_confirmed_to_delivered"], 1.5, places=1)

    def test_truncation_is_reported(self):
        for _ in range(5):
            self.paid([(self.para, 1)])
        with mock.patch.object(rules, "MAX_ROWS_SCANNED", 3):
            r = self.sales()
        self.assertEqual((r["truncated"], r["rows_scanned"], r["totals"]["orders"]), (True, 3, 3))
        self.assertFalse(self.sales()["truncated"])

    def test_report_holds_no_customer_details(self):
        self.paid([(self.para, 1)])
        text = repr(self.sales())
        a = next(iter(self.order_repo.docs.values()))["address"]
        for secret in (a["recipient_name"], a["phone"], a["line1"], "u1"):
            self.assertNotIn(secret, text)

    def test_operations_counts(self):
        self.paid([(self.para, 1)])
        ops = self.an.operations("admin")
        self.assertEqual(ops["orders_by_status"], {"confirmed": 1})
        self.assertEqual(set(ops), {"orders_by_status", "prescriptions_by_status", "attention", "inventory"})


class AttentionTests(AdminBase):
    def flagged(self, flag="duplicate_payment:pay_X1"):
        o = self.paid()
        self.order_repo.set_fields(o["id"], {"needs_attention": flag})
        return o["id"]

    def test_lists_every_kind_oldest_first(self):
        a = self.flagged("payment_mismatch:pay_A")
        self.clock.advance(5)
        d = self.picked(user="u2")
        self.fail_times(d, 3)
        r = self.paid(user="u2")
        self.order_repo.transition(r["id"], "confirmed", "payment_review", {}, "x", self.clock())
        self.adapter.mode = "fail"
        c = self.picked(user="u1")
        self.fail_times(c, 3)
        self.dl.resolve_failed("m1", "pharmacy_manager", c, "refund")
        items = self.attn.list("admin")["results"]
        self.assertEqual({i["kind"] for i in items}, {"needs_attention", "delivery_failed", "payment_review", "failed_refund"})
        self.assertEqual(items[0]["order_id"], a)
        self.assertEqual(items[0]["reference"], "pay_A")
        self.assertEqual([i["since"] for i in items], sorted(i["since"] for i in items))
        self.assertTrue(all(i["detail"] for i in items))
        self.assertEqual(self.attn.counts(), {"needs_attention": 1, "delivery_failed": 1, "payment_review": 1, "failed_refund": 1})
        self.assertFalse(any(i["resolvable"] for i in items if i["kind"] != "needs_attention"))

    def test_items_are_sorted_by_age_across_kinds(self):
        c = self.picked(user="u1")
        self.fail_times(c, 3)
        self.adapter.mode = "fail"
        self.dl.resolve_failed("m1", "pharmacy_manager", c, "refund")         # oldest: a failed refund
        self.clock.advance(10)
        self.flagged()                                                        # newer: a flagged order
        kinds = [i["kind"] for i in self.attn.list("admin")["results"]]
        self.assertEqual(kinds, ["failed_refund", "needs_attention"])

    def test_resolve_clears_the_flag_and_is_audited(self):
        oid = self.flagged()
        out = self.attn.resolve("a1", "admin", oid, "duplicate_payment:pay_X1", "  Refunded pay_X1 in the dashboard  ")
        self.assertEqual(out["resolved"], "duplicate_payment:pay_X1")
        self.assertNotIn("needs_attention", self.order_repo.docs[oid])
        self.assertEqual(self.attn.list("admin")["results"], [])
        a = self.audit_repo.docs[0]
        self.assertEqual((a["action"], a["actor_id"], a["target_id"], a["details"]["note"]),
                         ("attention_resolved", "a1", oid, "Refunded pay_X1 in the dashboard"))

    def test_a_stale_flag_cannot_clear_a_newer_one(self):
        oid = self.flagged("duplicate_payment:pay_1")
        self.order_repo.set_fields(oid, {"needs_attention": "duplicate_payment:pay_2"})
        self.assertEqual(self.err(self.attn.resolve, "a1", "admin", oid, "duplicate_payment:pay_1", "looked at it"), "already_resolved")
        self.assertEqual(self.order_repo.docs[oid]["needs_attention"], "duplicate_payment:pay_2")
        self.assertEqual(self.audit_repo.docs, [])
        self.attn.resolve("a1", "admin", oid, "duplicate_payment:pay_2", "looked at it")
        self.assertEqual(self.err(self.attn.resolve, "a1", "admin", oid, "duplicate_payment:pay_2", "again please"), "already_resolved")
        self.assertEqual(len(self.audit_repo.docs), 1)

    def test_validation_and_roles(self):
        oid = self.flagged()
        flag = "duplicate_payment:pay_X1"
        for note in (None, "", "    ", "abc", "x" * 501, 7):
            self.assertEqual(self.err(self.attn.resolve, "a1", "admin", oid, flag, note), "validation_error", note)
        for bad in (None, "", 5):
            self.assertEqual(self.err(self.attn.resolve, "a1", "admin", oid, bad, "a proper note"), "validation_error")
        self.assertEqual(self.err(self.attn.resolve, "a1", "admin", "nope", flag, "a proper note"), "not_found")
        self.assertEqual(self.err(self.attn.resolve, "a1", "admin", None, flag, "a proper note"), "not_found")
        for role in ("customer", "pharmacist", "support_agent", "delivery_partner", "inventory_staff"):
            self.assertEqual(self.err(self.attn.resolve, "x", role, oid, flag, "a proper note"), "forbidden", role)
            self.assertEqual(self.err(self.attn.list, role), "forbidden", role)
        self.assertEqual(self.order_repo.docs[oid]["needs_attention"], flag)
        self.attn.resolve("m1", "pharmacy_manager", oid, flag, "a proper note")

    def test_resolving_changes_no_money_status_or_stock(self):
        oid = self.flagged()
        before = {k: v for k, v in self.order_repo.docs[oid].items() if k not in ("needs_attention",)}
        stock = self.on_hand("P1")
        self.attn.resolve("a1", "admin", oid, "duplicate_payment:pay_X1", "checked and handled")
        after = dict(self.order_repo.docs[oid])
        self.assertEqual(before, after)
        self.assertEqual(self.on_hand("P1"), stock)
        self.assertEqual(self.adapter.calls, [])


class UserAdminTests(AdminBase):
    def test_list_filters_and_hides_secrets(self):
        self.users.docs["u1"]["password_hash"] = "SECRETHASH"
        out = self.useradmin.list("admin", {})
        self.assertGreaterEqual(out["total"], 8)
        self.assertNotIn("SECRETHASH", repr(out))
        self.assertNotIn("password", repr(out))
        self.assertEqual({u["role"] for u in self.useradmin.list("admin", {"role": "admin"})["results"]}, {"admin"})
        self.assertEqual(len(self.useradmin.list("admin", {"q": "staff a1"})["results"]), 1)
        self.assertEqual(self.useradmin.list("admin", {"q": ".*"})["total"], 0)             # regex characters are literal
        self.assertEqual(self.useradmin.list("admin", {"q": "a2@STAFF"})["total"], 1)       # case-insensitive

    def test_list_validation_roles_and_paging(self):
        self.assertEqual(self.err(self.useradmin.list, "admin", {"role": "king"}), "validation_error")
        self.assertEqual(self.err(self.useradmin.list, "admin", {"q": "x" * 101}), "validation_error")
        self.assertEqual(self.err(self.useradmin.list, "admin", {"q": ["a"]}), "validation_error")
        for role in ("pharmacy_manager", "customer", "pharmacist", "support_agent"):
            self.assertEqual(self.err(self.useradmin.list, role, {}), "forbidden", role)
            self.assertEqual(self.err(self.useradmin.set_active, "x", role, "u1", {"active": False, "note": "a reason"}), "forbidden", role)
            self.assertEqual(self.err(self.audit.recent, role), "forbidden", role)
        for i in range(30):
            self.users.insert({"_id": f"x{i}", "email": f"x{i}@p.test", "full_name": "P", "role": "customer", "is_active": True, "created_at": self.clock()})
        self.assertEqual(len(self.useradmin.list("admin", {"page": "1"})["results"]), rules.USER_PAGE_SIZE)
        self.assertGreater(len(self.useradmin.list("admin", {"page": "2"})["results"]), 0)
        self.assertEqual(self.useradmin.list("admin", {"page": "zzz"})["page"], 1)

    def test_deactivate_and_reactivate_with_audit(self):
        out = self.useradmin.set_active("a1", "admin", "u1", {"active": False, "note": "Left the company"})
        self.assertFalse(out["is_active"])
        self.assertFalse(self.users.docs["u1"]["is_active"])
        self.useradmin.set_active("a1", "admin", "u1", {"active": True, "note": "Came back"})
        self.assertTrue(self.users.docs["u1"]["is_active"])
        self.assertEqual([a["action"] for a in self.audit_repo.docs], ["account_deactivated", "account_activated"])
        self.assertEqual(self.audit.recent("admin")["total"], 2)

    def test_idempotent_change_is_not_audited_twice(self):
        self.useradmin.set_active("a1", "admin", "u1", {"active": False, "note": "reason one"})
        self.useradmin.set_active("a1", "admin", "u1", {"active": False, "note": "reason two"})
        self.assertEqual(len(self.audit_repo.docs), 1)

    def test_validation(self):
        for data in ({}, {"active": "false", "note": "reason ok"}, {"active": 0, "note": "reason ok"}, {"active": False},
                     {"active": False, "note": "no"}, {"active": False, "note": "x" * 501}, None):
            self.assertEqual(self.err(self.useradmin.set_active, "a1", "admin", "u1", data), "validation_error", data)
        self.assertEqual(self.err(self.useradmin.set_active, "a1", "admin", "ghost", {"active": False, "note": "reason ok"}), "not_found")
        self.assertEqual(self.err(self.useradmin.set_active, "a1", "admin", None, {"active": False, "note": "reason ok"}), "not_found")
        self.assertTrue(self.users.docs["u1"]["is_active"])
        self.assertEqual(self.audit_repo.docs, [])

    def test_cannot_change_own_account(self):
        self.assertEqual(self.err(self.useradmin.set_active, "a1", "admin", "a1", {"active": False, "note": "reason ok"}), "own_account")
        self.assertTrue(self.users.docs["a1"]["is_active"])

    def test_the_last_admin_cannot_be_switched_off(self):
        self.useradmin.set_active("a1", "admin", "a2", {"active": False, "note": "reason ok"})           # a1 remains
        self.users.docs["a2"]["is_active"] = True
        self.users.docs["a2"]["role"] = "customer"                       # now a1 is the only admin
        self.assertEqual(self.err(self.useradmin.set_active, "m9", "admin", "a1", {"active": False, "note": "reason ok"}), "last_admin")
        self.assertTrue(self.users.docs["a1"]["is_active"])               # restored
        self.assertEqual([a["target_id"] for a in self.audit_repo.docs], ["a2"])

    def test_staff_accounts_other_than_admin_can_be_switched_off(self):
        self.useradmin.set_active("a1", "admin", "m1", {"active": False, "note": "reason ok"})
        self.assertFalse(self.users.docs["m1"]["is_active"])


if __name__ == "__main__":
    unittest.main()
