import random
import unittest
from datetime import timedelta

from apps.accounts.errors import ServiceError
from apps.orders import rules
from apps.orders.lifecycle import LifecycleService, public_return
from apps.orders.payments import MockPaymentAdapter, PaymentResult
from apps.orders.refunds import RefundService

from .fakes import FakeRefunds, FakeReturns
from .test_pharmacist_review import RxBase


class RecordingAdapter(MockPaymentAdapter):
    def __init__(self):
        self.calls, self.mode = [], "ok"

    def refund(self, order, amount_paise, idempotency_key, options):
        self.calls.append((order["_id"], amount_paise, idempotency_key))
        if self.mode == "raise":
            raise ConnectionError("provider down")
        if self.mode == "fail":
            return PaymentResult(False, message="declined")
        return PaymentResult(True, reference=f"REF-{len(self.calls)}")


class LifeBase(RxBase):
    def setUp(self):
        super().setUp()
        self.returns, self.refund_repo, self.adapter = FakeReturns(), FakeRefunds(), RecordingAdapter()
        self.refunds = RefundService(self.refund_repo, self.order_repo, self.adapter, self.clock)
        self.life = LifecycleService(self.orders, self.order_repo, self.returns, self.refunds, self.res, self.allow, self.clock)

    def paid(self, items=None, user="u1"):
        o = self.place(items or [(self.para, 3)], user)
        return self.orders.pay(user, o["id"], {})

    def delivered(self, items=None, user="u1"):
        o = self.paid(items, user)
        self.life.fulfil("m1", "pharmacy_manager", o["id"], "dispatch")
        return self.life.fulfil("m1", "pharmacy_manager", o["id"], "deliver")

    def on_hand(self, number):
        return self.batch(number)["quantity_on_hand"]

    def assert_ledger_balanced(self):
        for b in self.batches.docs.values():
            total = sum(m["delta"] for m in self.movements.docs if m["batch_id"] == b["_id"])
            self.assertEqual(b["quantity_on_hand"], total, b["batch_number"])

    def refunded(self, oid):
        return self.order_repo.docs[oid]["payment"]["refunded_paise"]


class CancelPaidTests(LifeBase):
    def test_restocks_refunds_and_is_balanced(self):
        before = self.on_hand("P1")
        o = self.paid([(self.para, 3)])
        self.assertEqual(self.on_hand("P1"), before - 3)
        out = self.life.cancel("u1", o["id"])
        self.assertEqual(out["order"]["status"], "cancelled")
        self.assertEqual(self.on_hand("P1"), before)
        self.assertEqual((out["refund"]["status"], out["refund"]["amount_paise"]), ("succeeded", o["total_paise"]))
        self.assertEqual((out["order"]["payment"]["status"], out["order"]["payment"]["refunded_paise"]), ("refunded", o["total_paise"]))
        self.assertEqual(self.adapter.calls, [(o["id"], o["total_paise"], f"{o['id']}:cancellation:{o['id']}")])
        self.assert_ledger_balanced()
        self.assertEqual(len([m for m in self.movements.docs if m["type"] == "order_cancel_restock"]), 1)

    def test_second_cancel_does_nothing(self):
        o = self.paid()
        self.life.cancel("u1", o["id"])
        self.assertEqual(self.code(self.life.cancel, "u1", o["id"]), "invalid_state")
        self.assertEqual((len(self.adapter.calls), self.refunded(o["id"])), (1, o["total_paise"]))
        self.assertEqual(self.on_hand("P1"), 20)    # 20 received; back to 20 exactly once, not 23
        self.assert_ledger_balanced()

    def test_lost_race_changes_nothing(self):
        o = self.paid()
        held = self.on_hand("P1")
        real = self.order_repo.transition
        self.order_repo.transition = lambda *a, **k: False
        self.assertEqual(self.code(self.life.cancel, "u1", o["id"]), "conflict")
        self.order_repo.transition = real
        self.assertEqual((self.adapter.calls, self.on_hand("P1")), ([], held))
        self.assertEqual(self.order_repo.docs[o["id"]]["status"], "confirmed")

    def test_unpaid_cancel_still_works_without_refund(self):
        o = self.place([(self.para, 2)])
        out = self.life.cancel("u1", o["id"])
        self.assertEqual((out["order"]["status"], out["refund"]), ("cancelled", None))
        self.assertEqual(self.adapter.calls, [])

    def test_cannot_cancel_after_dispatch_or_delivery_or_others_orders(self):
        o = self.paid()
        self.assertEqual(self.code(self.life.cancel, "u2", o["id"]), "not_found")
        self.life.fulfil("m1", "pharmacy_manager", o["id"], "dispatch")
        self.assertEqual(self.code(self.life.cancel, "u1", o["id"]), "invalid_state")
        self.life.fulfil("m1", "pharmacy_manager", o["id"], "deliver")
        self.assertEqual(self.code(self.life.cancel, "u1", o["id"]), "invalid_state")
        self.assertEqual(self.adapter.calls, [])

    def test_provider_failure_keeps_cancel_and_allows_one_retry(self):
        o = self.paid()
        self.adapter.mode = "fail"
        out = self.life.cancel("u1", o["id"])
        self.assertEqual((out["order"]["status"], out["refund"]["status"], self.refunded(o["id"])), ("cancelled", "failed", 0))
        self.assertEqual(self.on_hand("P1"), 20)
        rid = out["refund"]["id"]
        self.assertEqual(self.code(self.life.retry_refund, "customer", rid), "forbidden")
        self.assertEqual(self.code(self.life.retry_refund, "support_agent", rid), "forbidden")
        self.adapter.mode = "ok"
        self.assertEqual(self.life.retry_refund("pharmacy_manager", rid)["status"], "succeeded")
        self.assertEqual(self.refunded(o["id"]), o["total_paise"])
        self.assertEqual(self.code(self.life.retry_refund, "admin", rid), "not_retryable")
        self.assertEqual(self.refunded(o["id"]), o["total_paise"])

    def test_provider_exception_is_a_failed_refund_not_a_crash(self):
        o = self.paid()
        self.adapter.mode = "raise"
        out = self.life.cancel("u1", o["id"])
        self.assertEqual((out["refund"]["status"], self.refunded(o["id"])), ("failed", 0))
        self.assertEqual([r["id"] for r in self.life.failed_refunds("admin")["results"]], [out["refund"]["id"]])

    def test_restock_failure_is_flagged_but_refund_still_happens(self):
        o = self.paid()
        self.res.restock = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db"))
        out = self.life.cancel("u1", o["id"])
        self.assertEqual(out["refund"]["status"], "succeeded")
        self.assertEqual(self.order_repo.docs[o["id"]]["needs_attention"], "restock_failed")

    def test_prescription_units_return_on_paid_cancel_exactly_once(self):
        pid = self.approved(items=[{"product_id": self.rx, "max_quantity": 5}])
        o = self.paid([(self.rx, 4)])
        self.assertEqual(self.remaining(pid), 1)
        self.life.cancel("u1", o["id"])
        self.assertEqual(self.remaining(pid), 5)
        self.assertEqual(self.code(self.life.cancel, "u1", o["id"]), "invalid_state")
        self.assertEqual(self.remaining(pid), 5)


class FulfilmentTests(LifeBase):
    def test_roles(self):
        o = self.paid()
        for role in ("pharmacist", "customer", "support_agent", "inventory_staff", "delivery_partner", "", None):
            self.assertEqual(self.code(self.life.fulfil, "x", role, o["id"], "dispatch"), "forbidden")
        self.assertEqual(self.life.fulfil("a1", "admin", o["id"], "dispatch")["status"], "dispatched")

    def test_state_machine(self):
        o = self.paid()
        self.assertEqual(self.code(self.life.fulfil, "m", "pharmacy_manager", o["id"], "deliver"), "invalid_state")
        self.life.fulfil("m", "pharmacy_manager", o["id"], "dispatch")
        self.assertEqual(self.code(self.life.fulfil, "m", "pharmacy_manager", o["id"], "dispatch"), "invalid_state")
        d = self.life.fulfil("m", "pharmacy_manager", o["id"], "deliver")
        self.assertIsNotNone(d["delivered_at"])
        self.assertEqual(self.code(self.life.fulfil, "m", "pharmacy_manager", o["id"], "deliver"), "invalid_state")
        pending = self.place([(self.cet, 1)])
        self.assertEqual(self.code(self.life.fulfil, "m", "pharmacy_manager", pending["id"], "dispatch"), "invalid_state")
        self.assertEqual(self.code(self.life.fulfil, "m", "pharmacy_manager", "nope", "dispatch"), "not_found")
        self.assertEqual(self.code(self.life.fulfil, "m", "pharmacy_manager", o["id"], "explode"), "validation_error")

    def test_staff_order_list_roles_and_content(self):
        a, b = self.paid(), self.paid([(self.cet, 1)])
        self.life.fulfil("m", "pharmacy_manager", b["id"], "dispatch")
        self.assertEqual({o["id"] for o in self.life.staff_orders("admin")["results"]}, {a["id"], b["id"]})
        self.assertEqual([o["id"] for o in self.life.staff_orders("admin", "dispatched")["results"]], [b["id"]])
        self.assertEqual(self.code(self.life.staff_orders, "pharmacist"), "forbidden")


class ReturnRequestTests(LifeBase):
    def req(self, oid, items=None, reason="damaged", user="u1", **extra):
        return self.life.request_return(user, oid, {"reason": reason, "items": items or [{"product_id": self.para, "quantity": 1}], **extra})

    def test_needs_delivery_and_window(self):
        o = self.paid()
        self.assertEqual(self.code(self.req, o["id"]), "not_delivered")
        self.life.fulfil("m", "pharmacy_manager", o["id"], "dispatch")
        self.assertEqual(self.code(self.req, o["id"]), "not_delivered")
        self.life.fulfil("m", "pharmacy_manager", o["id"], "deliver")
        self.clock.now += timedelta(days=rules.RETURN_WINDOW_DAYS, minutes=1)
        self.assertEqual(self.code(self.req, o["id"]), "return_window_closed")

    def test_inside_window_ok_and_amount_excludes_delivery(self):
        o = self.delivered()
        self.clock.now += timedelta(days=rules.RETURN_WINDOW_DAYS - 1)
        r = self.req(o["id"], [{"product_id": self.para, "quantity": 2}], details="  box crushed ")
        self.assertEqual((r["status"], r["amount_paise"], r["details"], r["restocked"]), ("requested", 6000, "box crushed", False))

    def test_validation(self):
        o = self.delivered([(self.para, 3), (self.cet, 1)])
        bad = [dict(reason="changed_my_mind"), dict(reason=None), dict(reason="damaged", items=[]), dict(reason="damaged", items="x"),
               dict(reason="damaged", items=[{"product_id": "nope", "quantity": 1}]),
               dict(reason="damaged", items=[{"product_id": self.para, "quantity": 4}]),
               dict(reason="damaged", items=[{"product_id": self.para, "quantity": 0}]),
               dict(reason="damaged", items=[{"product_id": self.para, "quantity": True}]),
               dict(reason="damaged", items=[{"product_id": self.para, "quantity": 1}] * 2),
               dict(reason="damaged", items=[{"product_id": {"$ne": 1}, "quantity": 1}]),
               dict(reason="damaged", items=["x"]), dict(reason="damaged", details="x" * 501), dict(reason="damaged", details=5)]
        for data in bad:
            with self.subTest(str(data)[:70]):
                data.setdefault("items", [{"product_id": self.para, "quantity": 1}])
                self.assertEqual(self.code(self.life.request_return, "u1", o["id"], data), "validation_error")
        self.assertEqual(self.returns.docs, {})

    def test_one_open_request_and_cap_across_approved_returns(self):
        o = self.delivered([(self.para, 3)])
        first = self.req(o["id"], [{"product_id": self.para, "quantity": 2}])
        self.assertEqual(self.code(self.req, o["id"]), "return_open")
        self.life.decide_return("s1", "support_agent", first["id"], {"decision": "approve"})
        self.assertEqual(self.code(self.req, o["id"], [{"product_id": self.para, "quantity": 2}]), "validation_error")
        self.req(o["id"], [{"product_id": self.para, "quantity": 1}])

    def test_rejected_return_does_not_use_up_quantity(self):
        o = self.delivered([(self.para, 3)])
        r = self.req(o["id"], [{"product_id": self.para, "quantity": 3}])
        self.life.decide_return("s1", "support_agent", r["id"], {"decision": "reject", "note": "photo shows no damage"})
        self.req(o["id"], [{"product_id": self.para, "quantity": 3}])

    def test_unique_index_race_maps_to_clean_error(self):
        o = self.delivered()
        self.req(o["id"])
        self.returns.list_for_order = lambda oid: []          # the pre-check misses it; the unique index catches it
        self.assertEqual(self.code(self.req, o["id"]), "return_open")

    def test_isolation(self):
        o = self.delivered()
        self.assertEqual(self.code(lambda: self.req(o["id"], user="u2")), "not_found")
        self.req(o["id"])
        self.assertEqual(self.code(self.life.customer_returns, "u2", o["id"]), "not_found")
        self.assertEqual(len(self.life.customer_returns("u1", o["id"])["returns"]), 1)


class ReturnDecisionTests(LifeBase):
    def setUp(self):
        super().setUp()
        self.o = self.delivered([(self.para, 3)])
        self.r = self.life.request_return("u1", self.o["id"], {"reason": "wrong_item", "items": [{"product_id": self.para, "quantity": 2}]})

    def test_roles(self):
        for role in ("customer", "pharmacist", "inventory_staff", "delivery_partner", "", None):
            self.assertEqual(self.code(self.life.decide_return, "x", role, self.r["id"], {"decision": "approve"}), "forbidden")
            self.assertEqual(self.code(self.life.staff_returns, role), "forbidden")
        self.assertEqual(self.returns.docs[self.r["id"]]["status"], "requested")
        for role in ("support_agent", "pharmacy_manager", "admin"):
            self.life.staff_returns(role)

    def test_approve_refunds_money_only(self):
        stock_before, moves = self.on_hand("P1"), len(self.movements.docs)
        out = self.life.decide_return("s1", "support_agent", self.r["id"], {"decision": "approve", "note": "ok"})
        self.assertEqual((out["status"], out["refund"]["status"], out["refund"]["amount_paise"]), ("approved", "succeeded", 6000))
        self.assertEqual(self.refunded(self.o["id"]), 6000)
        self.assertEqual(self.order_repo.docs[self.o["id"]]["payment"]["refunded_paise"], 6000)
        self.assertEqual((self.on_hand("P1"), len(self.movements.docs)), (stock_before, moves))   # never restocked
        self.assertEqual(self.orders.get("u1", self.o["id"])["payment"]["status"], "partially_refunded")
        self.assertEqual(self.adapter.calls[-1][2], f"{self.o['id']}:return:{self.r['id']}")

    def test_returned_prescription_units_are_not_restored(self):
        pid = self.approved(items=[{"product_id": self.rx, "max_quantity": 5}])
        o = self.delivered([(self.rx, 2)])
        r = self.life.request_return("u1", o["id"], {"reason": "damaged", "items": [{"product_id": self.rx, "quantity": 2}]})
        self.life.decide_return("m", "pharmacy_manager", r["id"], {"decision": "approve"})
        self.assertEqual(self.remaining(pid), 3)

    def test_reject_needs_reason_and_pays_nothing(self):
        for note in (None, "", "no", 5):
            self.assertEqual(self.code(self.life.decide_return, "s", "support_agent", self.r["id"], {"decision": "reject", "note": note}), "validation_error")
        out = self.life.decide_return("s", "support_agent", self.r["id"], {"decision": "reject", "note": "does not match records"})
        self.assertEqual((out["status"], out["refund"], self.refunded(self.o["id"])), ("rejected", None, 0))
        self.assertEqual(self.adapter.calls, [])

    def test_decided_once_only(self):
        self.life.decide_return("s", "support_agent", self.r["id"], {"decision": "approve"})
        for d in ({"decision": "approve"}, {"decision": "reject", "note": "changed my mind"}):
            self.assertEqual(self.code(self.life.decide_return, "s2", "admin", self.r["id"], d), "already_decided")
        self.assertEqual((len(self.adapter.calls), self.refunded(self.o["id"])), (1, 6000))

    def test_invalid_input(self):
        self.assertEqual(self.code(self.life.decide_return, "s", "admin", self.r["id"], {"decision": "maybe"}), "validation_error")
        self.assertEqual(self.code(self.life.decide_return, "s", "admin", "nope", {"decision": "approve"}), "not_found")
        self.assertEqual(self.code(self.life.decide_return, "s", "admin", {"$ne": 1}, {"decision": "approve"}), "not_found")

    def test_refund_failure_leaves_return_approved_and_retryable(self):
        self.adapter.mode = "fail"
        out = self.life.decide_return("s", "support_agent", self.r["id"], {"decision": "approve"})
        self.assertEqual((out["status"], out["refund"]["status"], self.refunded(self.o["id"])), ("approved", "failed", 0))
        self.adapter.mode = "ok"
        self.life.retry_refund("admin", out["refund"]["id"])
        self.assertEqual(self.refunded(self.o["id"]), 6000)
        shown = self.life.customer_returns("u1", self.o["id"])
        self.assertEqual(shown["returns"][0]["refund"]["status"], "succeeded")

    def test_customer_view_hides_staff_identity(self):
        self.life.decide_return("secret-staff-id", "support_agent", self.r["id"], {"decision": "approve", "note": "fine"})
        shown = str(self.life.customer_returns("u1", self.o["id"]))
        self.assertNotIn("secret-staff-id", shown)


class RefundSafetyTests(LifeBase):
    def test_same_refund_twice_is_one_refund(self):
        o = self.paid()
        order = self.order_repo.docs[o["id"]]
        a = self.refunds.issue(order, 1000, "return", "r1", "x")
        b = self.refunds.issue(order, 1000, "return", "r1", "x")
        self.assertEqual((a["id"] if "id" in a else a["_id"], len(self.refund_repo.docs), len(self.adapter.calls)), (b["_id"], 1, 1))
        self.assertEqual(self.refunded(o["id"]), 1000)

    def test_never_more_than_paid(self):
        o = self.paid()
        order = self.order_repo.docs[o["id"]]
        total = order["total_paise"]
        self.refunds.issue(order, total - 100, "return", "r1", "x")
        over = self.refunds.issue(order, 200, "return", "r2", "x")
        self.assertEqual((over["status"], self.refunded(o["id"]), len(self.adapter.calls)), ("failed", total - 100, 1))
        self.assertEqual(self.refunds.issue(order, 100, "return", "r3", "x")["status"], "succeeded")
        self.assertEqual(self.refunded(o["id"]), total)

    def test_unpaid_order_cannot_be_refunded(self):
        o = self.place([(self.para, 1)])
        r = self.refunds.issue(self.order_repo.docs[o["id"]], 100, "return", "r", "x")
        self.assertEqual((r["status"], self.adapter.calls), ("failed", []))

    def test_bad_amounts(self):
        o = self.paid()
        for amount in (0, -5, True, 1.5, "10", None):
            with self.assertRaises(ServiceError):
                self.refunds.issue(self.order_repo.docs[o["id"]], amount, "return", f"r{amount}", "x")

    def test_retry_unknown_or_non_failed(self):
        self.assertEqual(self.code(self.refunds.retry, "nope"), "not_found")
        o = self.paid()
        r = self.refunds.issue(self.order_repo.docs[o["id"]], 100, "return", "r1", "x")
        self.assertEqual(self.code(self.refunds.retry, r["_id"]), "not_retryable")

    def test_concurrent_retries_send_money_once(self):
        o = self.paid()
        self.adapter.mode = "fail"
        r = self.refunds.issue(self.order_repo.docs[o["id"]], 500, "return", "r1", "x")
        self.adapter.mode = "ok"
        self.assertTrue(self.refund_repo.claim_retry(r["_id"], self.clock()))     # another staff member got there first
        self.assertEqual(self.code(self.refunds.retry, r["_id"]), "not_retryable")


class LifecycleInvariantTests(LifeBase):
    def test_random_activity_keeps_money_and_stock_balanced(self):
        rnd = random.Random(2026)
        pid = self.approved(items=[{"product_id": self.rx, "max_quantity": 60}])
        self.stock(self.para, "P2", 400, 200)
        self.stock(self.rx, "R2", 400, 200)
        orders, open_returns = [], []
        roles = ["pharmacy_manager", "admin", "support_agent", "customer", "pharmacist"]
        for step in range(500):
            op = rnd.choice(["order", "cancel", "dispatch", "deliver", "return", "decide", "retry", "mode", "tick"])
            try:
                if op == "order":
                    item = rnd.choice([(self.para, rnd.randint(1, 4)), (self.rx, rnd.randint(1, 3)), (self.cet, 2)])
                    o = self.paid([item])
                    orders.append(o["id"])
                elif op == "cancel" and orders:
                    self.life.cancel("u1", rnd.choice(orders))
                elif op in ("dispatch", "deliver") and orders:
                    self.life.fulfil("m", rnd.choice(roles), rnd.choice(orders), op)
                elif op == "return" and orders:
                    oid = rnd.choice(orders)
                    line = self.order_repo.docs[oid]["lines"][0]
                    r = self.life.request_return("u1", oid, {"reason": "damaged", "items": [
                        {"product_id": line["product_id"], "quantity": rnd.randint(1, line["quantity"])}]})
                    open_returns.append(r["id"])
                elif op == "decide" and open_returns:
                    d = rnd.choice(["approve", "reject"])
                    self.life.decide_return("s", rnd.choice(roles), rnd.choice(open_returns), {"decision": d, "note": "valid reason"})
                elif op == "retry":
                    failed = self.life.failed_refunds("admin")["results"]
                    if failed:
                        self.life.retry_refund("admin", rnd.choice(failed)["id"])
                elif op == "mode":
                    self.adapter.mode = rnd.choice(["ok", "ok", "fail", "raise"])
                else:
                    self.clock.now += timedelta(hours=rnd.randint(1, 20))
            except ServiceError:
                pass
            self.check_books(pid)
        self.assertGreater(len(orders), 20)
        self.assertTrue(any(r["status"] == "succeeded" for r in self.refund_repo.docs.values()))

    def check_books(self, pid):
        self.assert_ledger_balanced()
        for b in self.batches.docs.values():
            self.assertGreaterEqual(b["quantity_on_hand"], b["quantity_reserved"])
        for oid, o in self.order_repo.docs.items():
            if o["payment"]["status"] != "paid":
                continue
            ok = sum(r["amount_paise"] for r in self.refund_repo.docs.values() if r["order_id"] == oid and r["status"] == "succeeded")
            self.assertEqual(o["payment"]["refunded_paise"], ok)
            self.assertLessEqual(ok, o["total_paise"])
        live = sum(l["rx"]["quantity"] for o in self.order_repo.docs.values() if o["status"] not in ("cancelled", "expired")
                   for l in o["lines"] if l.get("rx"))
        self.assertEqual(self.remaining(pid), 60 - live)


if __name__ == "__main__":
    unittest.main()
