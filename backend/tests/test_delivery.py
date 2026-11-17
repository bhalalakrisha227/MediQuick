import random
import unittest
from unittest import mock

from apps.orders import rules
from apps.orders.delivery import DeliveryService, handover_code, partner_view
from apps.orders.services import public_order

from .fakes import FakeUsers
from .test_order_lifecycle import LifeBase

SECRET = "test-secret"
MGR = ("m1", "pharmacy_manager")


class DelBase(LifeBase):
    def setUp(self):
        super().setUp()
        self.users = FakeUsers()
        for uid, name in (("rider1", "Ravi Kumar"), ("rider2", "Sana Khan")):
            self.users.insert({"_id": uid, "email": f"{uid}@x.test", "full_name": name, "role": "delivery_partner", "is_active": True})
        self.users.insert({"_id": "cust", "email": "c@x.test", "full_name": "Cust", "role": "customer", "is_active": True})
        self.users.insert({"_id": "gone", "email": "g@x.test", "full_name": "Gone", "role": "delivery_partner", "is_active": False})
        self.dl = DeliveryService(self.order_repo, self.users, self.refunds, SECRET, self.clock)

    def assigned(self, rider="rider1", user="u1", items=None):
        o = self.paid(items, user)
        self.dl.assign("m1", "pharmacy_manager", o["id"], rider)
        return o["id"]

    def picked(self, rider="rider1", user="u1", items=None):
        oid = self.assigned(rider, user, items)
        self.dl.pickup(rider, oid)
        return oid

    def code(self, oid, user="u1"):
        return self.dl.customer_status(user, oid)["handover_code"]

    def status(self, oid):
        return self.order_repo.docs[oid]["status"]

    def fail_times(self, oid, n, rider="rider1"):
        for _ in range(n):
            self.dl.fail(rider, oid, {"reason": "customer_unavailable"})


class FeeTests(DelBase):
    def setUp(self):
        super().setUp()
        mock.patch("apps.orders.rules.DELIVERY_FEE_PAISE", 4900).start()      # undo the zero-fee test default
        mock.patch("apps.orders.rules.FREE_DELIVERY_ABOVE_PAISE", 49900).start()
        self.addCleanup(mock.patch.stopall)

    def test_fee_rule(self):
        self.assertEqual(rules.delivery_fee(0), 0)
        self.assertEqual(rules.delivery_fee(100), 4900)
        self.assertEqual(rules.delivery_fee(49899), 4900)
        self.assertEqual(rules.delivery_fee(49900), 0)

    def test_order_total_includes_fee_and_it_is_snapshotted(self):
        o = self.place([(self.para, 1)])
        self.assertEqual(o["delivery_fee_paise"], 4900)
        self.assertEqual(o["total_paise"], o["subtotal_paise"] + 4900)
        with mock.patch("apps.orders.rules.DELIVERY_FEE_PAISE", 9900):
            self.assertEqual(self.order_repo.docs[o["id"]]["delivery_fee_paise"], 4900)

    def test_free_delivery_over_threshold(self):
        with mock.patch("apps.orders.rules.FREE_DELIVERY_ABOVE_PAISE", 1):
            o = self.place([(self.para, 1)])
        self.assertEqual((o["delivery_fee_paise"], o["total_paise"]), (0, o["subtotal_paise"]))

    def test_cart_shows_the_same_fee(self):
        self.cart.add("u1", {"product_id": self.para, "quantity": 1})
        c = self.cart.view("u1")
        self.assertEqual(c["delivery_fee_paise"], rules.delivery_fee(c["subtotal_paise"]))
        self.assertEqual(c["total_paise"], c["subtotal_paise"] + c["delivery_fee_paise"])

    def test_gateway_amount_uses_the_total_with_fee(self):
        o = self.place([(self.para, 1)])
        self.assertEqual(self.order_repo.docs[o["id"]]["total_paise"], o["subtotal_paise"] + 4900)


class ServiceabilityTests(DelBase):
    def test_empty_prefixes_means_everywhere(self):
        self.assertTrue(rules.serviceable("560001", ()))

    def test_prefix_match(self):
        self.assertTrue(rules.serviceable("560001", ("56", "40")))
        self.assertFalse(rules.serviceable("110001", ("56", "40")))

    def test_checkout_refuses_unserviceable_pin_before_touching_cart_or_stock(self):
        self.orders.pincode_prefixes = ("99",)
        before = self.on_hand("P1")
        self.cart.add("u1", {"product_id": self.para, "quantity": 2})
        with self.assertRaises(Exception) as cm:
            self.orders.create("u1", {"address_id": self.addr})
        self.assertEqual(getattr(cm.exception, "code", None), "not_serviceable")
        self.assertEqual(self.on_hand("P1"), before)
        self.assertEqual(len(self.carts.get("u1")["items"]), 1)    # cart untouched
        self.assertEqual(self.order_repo.docs, {})


class AssignTests(DelBase):
    def test_only_fulfilment_roles(self):
        o = self.paid()
        for role in ("customer", "delivery_partner", "pharmacist"):
            self.assertEqual(self.code_of(lambda: self.dl.assign("x", role, o["id"], "rider1")), "forbidden")

    def code_of(self, fn):
        try:
            fn()
        except Exception as exc:
            return exc.code
        return None

    def test_must_be_an_active_delivery_partner(self):
        o = self.paid()
        for pid in ("cust", "gone", "nobody", None, 7):
            self.assertEqual(self.code_of(lambda: self.dl.assign("m1", "pharmacy_manager", o["id"], pid)), "validation_error", pid)
        self.assertEqual(self.order_repo.docs[o["id"]]["delivery"]["partner_id"], None)

    def test_assigns_confirmed_and_reassigns_dispatched_but_not_unpaid_or_delivered(self):
        oid = self.assigned("rider1")
        self.assertEqual(self.dl.my_deliveries("rider1")["results"][0]["id"], oid)
        self.dl.pickup("rider1", oid)
        self.dl.assign("m1", "pharmacy_manager", oid, "rider2")           # reassign after pickup
        self.assertEqual(self.dl.my_deliveries("rider1")["results"], [])
        unpaid = self.place([(self.para, 1)])
        self.assertEqual(self.code_of(lambda: self.dl.assign("m1", "pharmacy_manager", unpaid["id"], "rider1")), "invalid_state")
        self.life.fulfil("m1", "pharmacy_manager", oid, "deliver")
        self.assertEqual(self.code_of(lambda: self.dl.assign("m1", "pharmacy_manager", oid, "rider1")), "invalid_state")

    def test_partners_list(self):
        names = {p["full_name"] for p in self.dl.partners("pharmacy_manager")["results"]}
        self.assertEqual(names, {"Ravi Kumar", "Sana Khan"})          # inactive and non-partners hidden
        self.assertEqual(self.code_of(lambda: self.dl.partners("customer")), "forbidden")


class HandoverTests(DelBase):
    def code_of(self, fn):
        try:
            fn()
        except Exception as exc:
            return exc.code
        return None

    def test_full_flow_with_the_customers_code(self):
        oid = self.assigned()
        self.assertIsNone(self.code(oid))                         # no code before pickup
        self.dl.pickup("rider1", oid)
        self.assertEqual(self.status(oid), "dispatched")
        code = self.code(oid)
        self.assertRegex(code, r"^\d{6}$")
        out = self.dl.complete("rider1", oid, {"code": code})
        self.assertEqual(out["status"], "delivered")
        d = self.order_repo.docs[oid]
        self.assertEqual(d["delivered_by"], "rider1")
        self.assertIsNotNone(d["delivered_at"])
        self.assertIsNone(self.code(oid))                         # code disappears after delivery

    def test_code_is_not_stored_anywhere_and_not_in_public_views(self):
        oid = self.picked()
        code = self.code(oid)
        self.assertNotIn(code, repr(self.order_repo.docs[oid]))
        self.assertNotIn(code, repr(public_order(self.order_repo.docs[oid])))
        self.assertNotIn(code, repr(partner_view(self.order_repo.docs[oid])))
        self.assertNotIn("salt", repr(public_order(self.order_repo.docs[oid])))

    def test_code_depends_on_secret_order_and_salt(self):
        a = handover_code("s1", "o1", "x")
        self.assertEqual(a, handover_code("s1", "o1", "x"))
        self.assertTrue(len({a, handover_code("s2", "o1", "x"), handover_code("s1", "o2", "x"), handover_code("s1", "o1", "y")}) >= 3)

    def test_wrong_code_counts_down_then_locks_even_for_the_right_code(self):
        oid = self.picked()
        good = self.code(oid)
        bad = "000000" if good != "000000" else "111111"
        for left in (4, 3, 2, 1, 0):
            with self.assertRaises(Exception) as cm:
                self.dl.complete("rider1", oid, {"code": bad})
            self.assertEqual(cm.exception.code, "wrong_code")
            self.assertEqual(cm.exception.fields["code_tries_left"], left)
        self.assertEqual(self.code_of(lambda: self.dl.complete("rider1", oid, {"code": good})), "code_locked")
        self.assertEqual(self.status(oid), "dispatched")
        # staff can unlock by reassigning (resets the tries)
        self.dl.assign("m1", "pharmacy_manager", oid, "rider1")
        self.assertEqual(self.dl.complete("rider1", oid, {"code": good})["status"], "delivered")

    def test_malformed_codes_are_rejected_without_using_a_try(self):
        oid = self.picked()
        for bad in (None, 123456, "12345", "1234567", "12345a", "١٢٣٤٥٦", " 12345", ""):
            self.assertEqual(self.code_of(lambda: self.dl.complete("rider1", oid, {"code": bad})), "validation_error", bad)
        self.assertEqual(self.order_repo.docs[oid]["delivery"]["code_tries"], 0)

    def test_other_partner_and_customer_cannot_act(self):
        oid = self.picked()
        code = self.code(oid)
        self.assertEqual(self.code_of(lambda: self.dl.complete("rider2", oid, {"code": code})), "not_found")
        self.assertEqual(self.code_of(lambda: self.dl.pickup("rider2", oid)), "not_found")
        self.assertEqual(self.code_of(lambda: self.dl.fail("rider2", oid, {"reason": "wrong_address"})), "not_found")
        self.assertEqual(self.code_of(lambda: self.dl.customer_status("someone-else", oid)), "not_found")
        self.assertEqual(self.status(oid), "dispatched")

    def test_cannot_pickup_twice_or_complete_before_pickup(self):
        oid = self.assigned()
        self.assertEqual(self.code_of(lambda: self.dl.complete("rider1", oid, {"code": "123456"})), "invalid_state")
        self.dl.pickup("rider1", oid)
        self.assertEqual(self.code_of(lambda: self.dl.pickup("rider1", oid)), "invalid_state")

    def test_cannot_deliver_twice(self):
        oid = self.picked()
        code = self.code(oid)
        self.dl.complete("rider1", oid, {"code": code})
        self.assertIn(self.code_of(lambda: self.dl.complete("rider1", oid, {"code": code})), ("invalid_state", "not_found"))

    def test_a_cancelled_order_cannot_be_picked_up(self):
        o = self.paid()
        self.dl.assign("m1", "pharmacy_manager", o["id"], "rider1")
        self.life.cancel("u1", o["id"])
        self.assertEqual(self.code_of(lambda: self.dl.pickup("rider1", o["id"])), "invalid_state")

    def test_customer_sees_first_name_only(self):
        oid = self.picked()
        self.assertEqual(self.dl.customer_status("u1", oid)["partner_name"], "Ravi")

    def test_partner_view_hides_medicines_prices_and_payment(self):
        oid = self.picked()
        v = self.dl.my_deliveries("rider1")["results"][0]
        text = repr(v)
        for secret in ("Paracetamol", "price", "payment", "total", "prescription", "pharmacy"):
            self.assertNotIn(secret.lower(), text.lower())
        self.assertEqual(v["item_count"], 3)
        self.assertEqual(v["recipient_name"], self.order_repo.docs[oid]["address"]["recipient_name"])


class FailureTests(DelBase):
    def code_of(self, fn):
        try:
            fn()
        except Exception as exc:
            return exc.code
        return None

    def test_reason_must_be_listed(self):
        oid = self.picked()
        for bad in (None, "", "lazy", 5):
            self.assertEqual(self.code_of(lambda: self.dl.fail("rider1", oid, {"reason": bad})), "validation_error")
        self.assertEqual(self.order_repo.docs[oid]["delivery"]["failed_count"], 0)

    def test_failures_are_recorded_and_the_third_sends_it_to_staff(self):
        oid = self.picked()
        self.fail_times(oid, 2)
        self.assertEqual(self.status(oid), "dispatched")
        self.assertEqual(self.dl.my_deliveries("rider1")["results"][0]["failed_count"], 2)
        self.dl.fail("rider1", oid, {"reason": "wrong_address"})
        self.assertEqual(self.status(oid), "delivery_failed")
        self.assertEqual([a["reason"] for a in self.order_repo.docs[oid]["delivery"]["attempts"]],
                         ["customer_unavailable", "customer_unavailable", "wrong_address"])
        self.assertEqual(self.code_of(lambda: self.dl.fail("rider1", oid, {"reason": "wrong_address"})), "invalid_state")
        self.assertIn(oid, [o["id"] for o in self.life.staff_orders("pharmacy_manager")["results"]])

    def test_failed_order_cannot_be_delivered_by_code(self):
        oid = self.picked()
        code = self.code(oid)
        self.fail_times(oid, 3)
        self.assertEqual(self.code_of(lambda: self.dl.complete("rider1", oid, {"code": code})), "invalid_state")
        self.assertIsNone(self.code(oid))

    def test_redeliver_goes_back_to_confirmed_unassigned_with_a_new_code_next_time(self):
        oid = self.picked()
        old = self.code(oid)
        self.fail_times(oid, 3)
        self.dl.resolve_failed("m1", "pharmacy_manager", oid, "redeliver")
        d = self.order_repo.docs[oid]
        self.assertEqual((d["status"], d["delivery"]["partner_id"], d["delivery"]["failed_count"]), ("confirmed", None, 0))
        self.assertEqual(len(d["delivery"]["attempts"]), 3)              # history kept
        self.dl.assign("m1", "pharmacy_manager", oid, "rider2")
        self.dl.pickup("rider2", oid)
        self.assertNotEqual(old, self.code(oid))     # fresh salt (a 1-in-a-million collision would flake this)
        self.assertEqual(self.dl.complete("rider2", oid, {"code": self.code(oid)})["status"], "delivered")

    def test_refund_is_full_once_and_never_restocks(self):
        oid = self.picked()
        total = self.order_repo.docs[oid]["total_paise"]
        on_hand = self.on_hand("P1")
        self.fail_times(oid, 3)
        out = self.dl.resolve_failed("m1", "pharmacy_manager", oid, "refund")
        self.assertEqual(out["status"], "cancelled")
        self.assertEqual(self.refunded(oid), total)
        self.assertEqual(len(self.adapter.calls), 1)
        self.assertEqual(self.on_hand("P1"), on_hand)                    # medicines are NOT put back on sale
        self.assertEqual(self.code_of(lambda: self.dl.resolve_failed("m1", "pharmacy_manager", oid, "refund")), "invalid_state")
        self.assertEqual(len(self.adapter.calls), 1)
        self.assert_ledger_balanced()

    def test_refund_failure_leaves_a_retryable_failed_refund(self):
        oid = self.picked()
        self.fail_times(oid, 3)
        self.adapter.mode = "fail"
        self.dl.resolve_failed("m1", "pharmacy_manager", oid, "refund")
        self.assertEqual(self.refunded(oid), 0)
        failed = self.life.failed_refunds("pharmacy_manager")["results"]
        self.assertEqual(len(failed), 1)
        self.adapter.mode = "ok"
        self.life.retry_refund("pharmacy_manager", failed[0]["id"])
        self.assertEqual(self.refunded(oid), self.order_repo.docs[oid]["total_paise"])

    def test_resolve_needs_role_valid_action_and_failed_state(self):
        oid = self.picked()
        self.fail_times(oid, 3)
        self.assertEqual(self.code_of(lambda: self.dl.resolve_failed("x", "customer", oid, "refund")), "forbidden")
        self.assertEqual(self.code_of(lambda: self.dl.resolve_failed("m1", "pharmacy_manager", oid, "burn")), "validation_error")
        ok = self.picked(user="u2")
        self.assertEqual(self.code_of(lambda: self.dl.resolve_failed("m1", "pharmacy_manager", ok, "refund")), "invalid_state")
        self.assertEqual(self.refunded(ok), 0)


class DeliveryInvariantTests(DelBase):
    def test_random_walk_keeps_money_stock_and_codes_consistent(self):
        rng = random.Random(9)
        self.stock(self.para, "WALK", 400, 300)
        orders = []
        for step in range(500):
            act = rng.choice(["new", "assign", "pickup", "good", "bad", "fail", "resolve", "manual", "cancel"])
            try:
                if act == "new" or not orders:
                    orders.append(self.paid([(self.para, rng.randint(1, 3))], rng.choice(["u1", "u2"]))["id"])
                    continue
                oid = rng.choice(orders)
                rider = rng.choice(["rider1", "rider2"])
                owner = self.order_repo.docs[oid]["user_id"]
                if act == "assign":
                    self.dl.assign("m1", "pharmacy_manager", oid, rider)
                elif act == "pickup":
                    self.dl.pickup(rider, oid)
                elif act == "good":
                    self.dl.complete(rider, oid, {"code": self.code(oid, owner) or "000000"})
                elif act == "bad":
                    self.dl.complete(rider, oid, {"code": "%06d" % rng.randrange(10**6)})
                elif act == "fail":
                    self.dl.fail(rider, oid, {"reason": rng.choice(rules.FAIL_REASONS)})
                elif act == "resolve":
                    self.dl.resolve_failed("m1", "pharmacy_manager", oid, rng.choice(["redeliver", "refund"]))
                elif act == "manual":
                    self.life.fulfil("m1", "pharmacy_manager", oid, rng.choice(["dispatch", "deliver"]))
                elif act == "cancel":
                    self.life.cancel(owner, oid)
            except Exception as exc:
                self.assertTrue(hasattr(exc, "code"), repr(exc))      # only clean, expected refusals
            for o in self.order_repo.docs.values():
                dv = o["delivery"]
                self.assertLessEqual(dv["failed_count"], rules.MAX_FAILED_ATTEMPTS)
                self.assertLessEqual(dv["code_tries"], rules.MAX_CODE_TRIES)
                self.assertLessEqual(o["payment"]["refunded_paise"], o["total_paise"])
                if o["status"] == "delivered":
                    self.assertIsNotNone(o["delivered_at"])
                if o["status"] == "delivery_failed":
                    self.assertEqual(dv["failed_count"], rules.MAX_FAILED_ATTEMPTS)
                if o["status"] == "cancelled" and o["payment"]["status"] == "paid" and o["payment"]["refunded_paise"]:
                    self.assertEqual(o["payment"]["refunded_paise"], o["total_paise"])
        self.assert_ledger_balanced()
        self.assertTrue({o["status"] for o in self.order_repo.docs.values()} & {"delivered", "delivery_failed", "cancelled"})


if __name__ == "__main__":
    unittest.main()
