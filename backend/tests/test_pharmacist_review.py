import random
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from apps.accounts.errors import ServiceError
from apps.orders.cart import CartService
from apps.orders.payments import MockPaymentAdapter
from apps.orders.services import OrderService
from apps.prescriptions import rules
from apps.prescriptions.allowance import AllowanceService
from apps.prescriptions.ocr.engines.base import OcrResult
from apps.prescriptions.review import MAX_CLAIMS, ReviewService
from apps.prescriptions.services import PrescriptionService
from apps.prescriptions.storage import FileStorage

from .fakes import FakePrescriptions
from .test_orders import Base as OrderBase
from .test_prescription_files import make_png

PH1 = {"id": "ph1", "role": "pharmacist", "name": "Rita Shah"}
PH2 = {"id": "ph2", "role": "pharmacist", "name": "Omar Khan"}
MGR = {"id": "mgr1", "role": "pharmacy_manager", "name": "Manager"}
ADM = {"id": "adm1", "role": "admin", "name": "Admin"}
INV = {"id": "inv1", "role": "inventory_staff", "name": "Stock"}
CUST = {"id": "u1", "role": "customer", "name": "Cust"}
REG = "MH-12345"


class RxBase(OrderBase):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.rx_repo = FakePrescriptions()
        self.allow = AllowanceService(self.rx_repo, self.clock)
        self.cart = CartService(self.carts, self.products, self.res, self.clock, allowances=self.allow)
        self.orders = OrderService(self.carts, self.order_repo, self.products, self.addresses, self.res,
                                   MockPaymentAdapter(), self.clock, allowances=self.allow)
        self.presc = PrescriptionService(
            self.rx_repo, FileStorage(Path(self._tmp.name) / "p"), self.products, mock.Mock(name="engine"), clock=self.clock,
            ocr_runner=lambda *a, **k: OcrResult("text", [{"text": "Tab Amoxicillin 500mg", "confidence": 80.0}], "fake"))
        self.review = ReviewService(self.rx_repo, self.products, self.clock)
        self.rx2 = self.product("Azithromycin", 11500, schedule="H")
        self.stock(self.rx2, "Z1", 400, 20)
        self.n = 0

    def claim(self, actor, pid):
        """Claim, then open the original (a decision requires it)."""
        out = self.review.claim(actor, pid)
        self.presc.file_for(actor["id"], actor["role"], pid)
        return out

    def submitted(self, user="u1", items=None):
        self.n += 1
        pid = self.presc.upload(user, make_png(4 + self.n, 3), "rx.png", {"consent": True})["id"]
        self.presc.process(pid)
        if items is not None:
            self.presc.update(user, pid, {"items": items})
        self.presc.submit(user, pid)
        return pid

    def approve(self, pid, items=None, actor=PH1, **over):
        self.claim(actor, pid)
        data = {"items": items or [{"product_id": self.rx, "max_quantity": 10}], "registration_number": REG,
                "attest_original_checked": True, "valid_days": 30, **over}
        return self.review.approve(actor, pid, data)

    def approved(self, user="u1", items=None, **over):
        pid = self.submitted(user)
        self.approve(pid, items, **over)
        return pid

    def code(self, fn, *a):
        with self.assertRaises(ServiceError) as c:
            fn(*a)
        return c.exception.code

    def remaining(self, pid, product=None):
        product = product or self.rx
        return next(i["remaining"] for i in self.rx_repo.docs[pid]["approval"]["items"] if i["product_id"] == product)


class ReviewTests(RxBase):
    def test_roles_for_queue_and_detail(self):
        pid = self.submitted()
        for actor in (PH1, MGR, ADM):
            self.assertEqual(len(self.review.queue(actor)["results"]), 1)
            self.assertEqual(self.review.detail(actor, pid)["status"], "submitted")
        for actor in (CUST, INV, {"id": "x", "role": "delivery_partner"}, {"id": "", "role": "pharmacist"}, None, {}):
            self.assertEqual(self.code(self.review.queue, actor), "forbidden")
            self.assertEqual(self.code(self.review.detail, actor, pid), "forbidden")

    def test_cannot_decide_without_opening_the_original(self):
        pid = self.submitted()
        self.presc.file_for("ph1", "pharmacist", pid)           # looked at it before claiming: does not count
        self.clock.advance(1)
        self.review.claim(PH1, pid)
        payload = {"items": [{"product_id": self.rx, "max_quantity": 5}], "registration_number": REG, "attest_original_checked": True}
        self.assertEqual(self.code(self.review.approve, PH1, pid, payload), "open_original_first")
        self.assertEqual(self.code(self.review.reject, PH1, pid, {"reason": "unreadable"}), "open_original_first")
        self.assertEqual(self.code(self.review.clarify, PH1, pid, {"message": "which one?"}), "open_original_first")
        self.assertEqual(self.rx_repo.docs[pid]["status"], "in_review")
        self.clock.advance(1)
        self.presc.file_for("ph1", "pharmacist", pid)
        self.assertEqual(self.review.approve(PH1, pid, payload)["status"], "approved")

    def test_viewing_the_file_as_someone_else_does_not_count(self):
        pid = self.submitted()
        self.review.claim(PH1, pid)
        self.presc.file_for("ph2", "pharmacist", pid)
        payload = {"items": [{"product_id": self.rx, "max_quantity": 5}], "registration_number": REG, "attest_original_checked": True}
        self.assertEqual(self.code(self.review.approve, PH1, pid, payload), "open_original_first")

    def test_pharmacist_cannot_review_their_own_prescription(self):
        pid = self.submitted("ph1")
        self.assertEqual(self.code(self.review.claim, PH1, pid), "own_prescription")
        self.review.claim(PH2, pid)
        self.assertEqual(self.rx_repo.docs[pid]["assigned_to"]["id"], "ph2")
        # even if the claim were somehow forged, the decision itself re-checks
        self.rx_repo.docs[pid]["assigned_to"] = {"id": "ph1", "name": "x", "at": self.clock()}
        self.presc.file_for("ph1", "pharmacist", pid)
        self.assertEqual(self.code(self.review.reject, PH1, pid, {"reason": "my own"}), "own_prescription")

    def test_max_valid_days_is_configurable(self):
        pid = self.submitted()
        self.claim(PH1, pid)
        short = ReviewService(self.rx_repo, self.products, self.clock, max_valid_days=7)
        payload = {"items": [{"product_id": self.rx, "max_quantity": 5}], "registration_number": REG, "attest_original_checked": True}
        self.assertEqual(self.code(short.approve, PH1, pid, {**payload, "valid_days": 8}), "validation_error")
        short.approve(PH1, pid, payload)
        a = self.rx_repo.docs[pid]["approval"]
        self.assertEqual(a["valid_until"] - a["approved_at"], timedelta(days=7))

    def test_drafts_and_withdrawn_are_invisible_to_staff(self):
        pid = self.presc.upload("u1", make_png(), "a", {"consent": True})["id"]
        self.assertEqual(self.review.queue(PH1)["results"], [])
        self.assertEqual(self.code(self.review.detail, PH1, pid), "not_found")
        self.assertEqual(self.code(self.review.claim, PH1, pid), "not_found")
        self.assertEqual(self.code(self.review.detail, PH1, "nope"), "not_found")
        self.assertEqual(self.code(self.review.detail, PH1, {"$ne": 1}), "not_found")

    def test_queue_is_oldest_first_and_scopes(self):
        a = self.submitted("u1")
        self.clock.advance(5)
        b = self.submitted("u2")
        self.assertEqual([r["id"] for r in self.review.queue(PH1)["results"]], [a, b])
        self.claim(PH1, b)
        self.assertEqual([r["id"] for r in self.review.queue(PH1, "mine")["results"]], [b])
        self.assertEqual(self.review.queue(PH2, "mine")["results"], [])
        self.assertEqual(self.code(self.review.queue, PH1, "everything"), "validation_error")

    def test_detail_view_is_logged_and_marks_data_unverified(self):
        pid = self.submitted()
        view = self.review.detail(MGR, pid)
        self.assertIn("Neither is verified", view["notice"])
        self.assertEqual([a["action"] for a in self.rx_repo.access], ["view_detail"])
        self.assertNotIn("path", str(view["file"]))

    def test_only_pharmacists_can_claim_and_decide(self):
        pid = self.submitted()
        for actor in (MGR, ADM, INV, CUST):
            self.assertEqual(self.code(self.review.claim, actor, pid), "forbidden")
        self.claim(PH1, pid)
        payload = {"items": [{"product_id": self.rx, "max_quantity": 5}], "registration_number": REG, "attest_original_checked": True}
        for actor in (MGR, ADM, INV):
            self.assertEqual(self.code(self.review.approve, actor, pid, payload), "forbidden")
            self.assertEqual(self.code(self.review.reject, actor, pid, {"reason": "no reason"}), "forbidden")
            self.assertEqual(self.code(self.review.clarify, actor, pid, {"message": "question?"}), "forbidden")
        self.assertEqual(self.rx_repo.docs[pid]["status"], "in_review")

    def test_claim_is_exclusive_and_limited(self):
        pid = self.submitted()
        self.claim(PH1, pid)
        self.assertEqual(self.code(self.review.claim, PH2, pid), "conflict")
        self.assertEqual(self.code(self.review.claim, PH1, pid), "conflict")
        for i in range(MAX_CLAIMS - 1):
            self.claim(PH1, self.submitted("u2"))
        self.assertEqual(self.code(self.review.claim, PH1, self.submitted("u3")), "too_many_claims")
        self.claim(PH2, self.submitted("u3"))

    def test_release_rules(self):
        pid = self.submitted()
        self.claim(PH1, pid)
        self.assertEqual(self.code(self.review.release, PH2, pid), "conflict")           # not your claim
        self.assertEqual(self.code(self.review.release, INV, pid), "forbidden")
        self.review.release(MGR, pid)                                                    # managers unstick it
        self.assertEqual(self.rx_repo.docs[pid]["status"], "submitted")
        self.assertNotIn("assigned_to", self.rx_repo.docs[pid])
        self.claim(PH2, pid)
        self.review.release(PH2, pid)
        self.assertEqual(self.code(self.review.release, PH2, pid), "conflict")           # already released

    def test_approve_happy_path(self):
        pid = self.submitted()
        self.claim(PH1, pid)
        out = self.review.approve(PH1, pid, {"items": [{"product_id": self.rx, "max_quantity": 6}], "registration_number": " " + REG + " ",
                                             "attest_original_checked": True, "valid_days": 10, "note": "ok"})
        self.assertEqual(out["status"], "approved")
        a = self.rx_repo.docs[pid]["approval"]
        self.assertEqual((a["pharmacist"]["registration_number"], a["items"][0]["remaining"], a["items"][0]["name"]), (REG, 6, "Amoxicillin"))
        self.assertEqual(a["valid_until"] - a["approved_at"], timedelta(days=10))
        self.assertEqual(out["review"]["approval"]["registration_number"], REG)               # staff see it
        cust = self.presc.get("u1", pid)["review"]["approval"]
        self.assertEqual((cust["pharmacist_name"], cust["items"][0]["remaining"]), ("Rita Shah", 6))
        self.assertNotIn("registration_number", cust)
        self.assertNotIn(REG, str(self.presc.get("u1", pid)))

    def test_audit_trail_has_snapshot_and_order(self):
        pid = self.submitted(items=[{"name": "Amoxicillin 500"}])
        self.approve(pid)
        audit = self.rx_repo.audit
        self.assertEqual([a["action"] for a in audit], ["claim", "approve"])
        self.assertEqual(audit[1]["actor_id"], "ph1")
        self.assertEqual(audit[1]["details"]["customer_items_snapshot"][0]["name"], "Amoxicillin 500")
        self.assertEqual(audit[1]["details"]["registration_number"], REG)

    def test_approve_validation_changes_nothing(self):
        pid = self.submitted()
        self.claim(PH1, pid)
        otc = self.para
        restricted = self.restricted
        good = [{"product_id": self.rx, "max_quantity": 3}]
        bad = [
            {"attest_original_checked": False}, {"attest_original_checked": None}, {"registration_number": "x"},
            {"registration_number": "<script>"}, {"registration_number": None}, {"valid_days": 0}, {"valid_days": 181},
            {"valid_days": True}, {"valid_days": "30"}, {"note": "x" * 501}, {"items": []}, {"items": "x"}, {"items": None},
            {"items": [{"product_id": otc, "max_quantity": 1}]}, {"items": [{"product_id": restricted, "max_quantity": 1}]},
            {"items": [{"product_id": "nope", "max_quantity": 1}]}, {"items": [{"product_id": self.rx, "max_quantity": 0}]},
            {"items": [{"product_id": self.rx, "max_quantity": 101}]}, {"items": [{"product_id": self.rx, "max_quantity": True}]},
            {"items": [{"product_id": self.rx, "max_quantity": 1.5}]}, {"items": good * 2}, {"items": ["x"]},
            {"items": [{"product_id": self.rx, "max_quantity": 1}] * 1 + [{"product_id": {"$ne": 1}, "max_quantity": 1}]},
            {"items": [{"product_id": self.rx, "max_quantity": 1}] * 21},
        ]
        for patch in bad:
            payload = {"items": good, "registration_number": REG, "attest_original_checked": True, **patch}
            with self.subTest(str(patch)[:60]):
                self.assertEqual(self.code(self.review.approve, PH1, pid, payload), "validation_error")
        self.assertEqual(self.rx_repo.docs[pid]["status"], "in_review")
        self.assertNotIn("approval", self.rx_repo.docs[pid])

    def test_inactive_product_cannot_be_approved(self):
        pid = self.submitted()
        self.claim(PH1, pid)
        self.products.docs[self.rx]["is_active"] = False
        payload = {"items": [{"product_id": self.rx, "max_quantity": 1}], "registration_number": REG, "attest_original_checked": True}
        self.assertEqual(self.code(self.review.approve, PH1, pid, payload), "validation_error")

    def test_cannot_decide_unclaimed_or_someone_elses(self):
        pid = self.submitted()
        payload = {"items": [{"product_id": self.rx, "max_quantity": 5}], "registration_number": REG, "attest_original_checked": True}
        self.assertEqual(self.code(self.review.approve, PH1, pid, payload), "conflict")             # not claimed
        self.assertEqual(self.code(self.review.reject, PH1, pid, {"reason": "not claimed"}), "conflict")
        self.claim(PH1, pid)
        self.assertEqual(self.code(self.review.approve, PH2, pid, payload), "conflict")             # someone else's
        self.assertEqual(self.code(self.review.reject, PH2, pid, {"reason": "not mine"}), "conflict")
        self.assertEqual(self.code(self.review.clarify, PH2, pid, {"message": "not mine?"}), "conflict")
        self.assertEqual(self.rx_repo.docs[pid]["status"], "in_review")

    def test_atomic_guard_stops_a_decision_race_even_if_the_pre_check_is_bypassed(self):
        pid = self.submitted()
        self.claim(PH1, pid)
        self.presc.file_for("ph2", "pharmacist", pid)
        payload = {"items": [{"product_id": self.rx, "max_quantity": 5}], "registration_number": REG, "attest_original_checked": True}
        with mock.patch.object(self.review, "_opened_original"):          # simulate the pre-check passing just before a race
            self.assertEqual(self.code(self.review.approve, PH2, pid, payload), "conflict")
            self.assertEqual(self.code(self.review.reject, PH2, pid, {"reason": "not mine"}), "conflict")
        self.assertEqual(self.rx_repo.docs[pid]["status"], "in_review")

    def test_decision_is_final(self):
        pid = self.approved()
        self.assertEqual(self.code(self.review.reject, PH1, pid, {"reason": "changed my mind"}), "conflict")
        self.assertEqual(self.code(self.review.claim, PH1, pid), "conflict")
        self.assertEqual(self.rx_repo.docs[pid]["status"], "approved")
        self.assertEqual(self.code(self.presc.update, "u1", pid, {"notes": "x"}), "not_editable")
        self.assertEqual(self.code(self.presc.withdraw, "u1", pid), "cannot_withdraw")
        self.assertEqual(self.code(self.presc.submit, "u1", pid), "cannot_submit")
        self.assertEqual(self.code(self.presc.retry_ocr, "u1", pid), "cannot_retry")

    def test_reject_flow(self):
        pid = self.submitted()
        self.claim(PH1, pid)
        self.assertEqual(self.code(self.review.reject, PH1, pid, {"reason": "no"}), "validation_error")
        self.assertEqual(self.code(self.review.reject, PH1, pid, {}), "validation_error")
        out = self.review.reject(PH1, pid, {"reason": "Image is unreadable"})
        self.assertEqual(out["status"], "rejected")
        cust = self.presc.get("u1", pid)
        self.assertEqual((cust["status"], cust["review"]["rejection"]["reason"]), ("rejected", "Image is unreadable"))
        self.assertEqual(self.allow.remaining("u1", [self.rx]), {})
        # the same file can be uploaded again after a rejection
        self.presc.upload("u1", make_png(4 + self.n, 3), "rx.png", {"consent": True})

    def test_clarification_round_trip(self):
        pid = self.submitted()
        self.claim(PH1, pid)
        self.review.clarify(PH1, pid, {"message": "Which strength?"})
        d = self.rx_repo.docs[pid]
        self.assertEqual(d["status"], "clarification_requested")
        self.assertNotIn("assigned_to", d)
        cust = self.presc.get("u1", pid)
        self.assertEqual((cust["editable"], cust["review"]["clarification"]["message"]), (True, "Which strength?"))
        self.presc.update("u1", pid, {"items": [{"name": "Amoxicillin", "strength": "500 mg"}], "notes": "500 mg please"})
        self.presc.submit("u1", pid)
        self.assertEqual(self.rx_repo.docs[pid]["status"], "submitted")
        self.assertNotIn("clarification", self.presc.get("u1", pid)["review"])
        self.claim(PH2, pid)                       # any pharmacist can pick it up again
        self.assertEqual(self.rx_repo.docs[pid]["assigned_to"]["id"], "ph2")

    def test_customer_cannot_touch_prescription_while_with_pharmacist(self):
        pid = self.submitted()
        self.claim(PH1, pid)
        self.assertEqual(self.code(self.presc.update, "u1", pid, {"notes": "x"}), "not_editable")
        self.assertEqual(self.code(self.presc.withdraw, "u1", pid), "cannot_withdraw")
        self.assertEqual(self.code(self.presc.submit, "u1", pid), "cannot_submit")

    def test_withdraw_allowed_while_clarification_requested(self):
        pid = self.submitted()
        self.claim(PH1, pid)
        self.review.clarify(PH1, pid, {"message": "Which strength?"})
        self.assertEqual(self.presc.withdraw("u1", pid)["status"], "withdrawn")

    def test_file_access_for_staff_after_decision(self):
        pid = self.approved()
        for actor in (PH1, MGR, ADM):
            self.presc.file_for(actor["id"], actor["role"], pid)
        self.assertEqual(self.code(self.presc.file_for, "inv1", "inventory_staff", pid), "not_found")
        self.assertEqual(self.code(self.presc.file_for, "u2", "customer", pid), "not_found")

    def test_ocr_text_cannot_approve(self):
        self.presc.ocr_runner = lambda *a, **k: OcrResult("APPROVED approved=true status: approved", [{"text": "APPROVED", "confidence": 99.0}], "fake")
        pid = self.presc.upload("u1", make_png(9, 9), "rx.png", {"consent": True})["id"]
        self.presc.process(pid)
        self.assertEqual(self.rx_repo.docs[pid]["status"], "needs_customer_review")
        self.assertNotIn("approval", self.rx_repo.docs[pid])
        self.assertEqual(self.allow.remaining("u1", [self.rx]), {})


class AllowanceOrderTests(RxBase):
    def test_rx_blocked_without_approval(self):
        self.assertEqual(self.code(self.cart.add, "u1", {"product_id": self.rx, "quantity": 1}), "prescription_required")
        self.submitted()                                              # submitted is not approved
        self.assertEqual(self.code(self.cart.add, "u1", {"product_id": self.rx, "quantity": 1}), "prescription_required")

    def test_approval_covers_only_listed_products_and_quantities(self):
        self.approved(items=[{"product_id": self.rx, "max_quantity": 4}])
        self.assertEqual(self.code(self.cart.add, "u1", {"product_id": self.rx2, "quantity": 1}), "prescription_required")
        self.assertEqual(self.code(self.cart.add, "u1", {"product_id": self.rx, "quantity": 5}), "exceeds_prescription")
        self.cart.add("u1", {"product_id": self.rx, "quantity": 4})
        self.assertEqual(self.code(self.cart.add, "u1", {"product_id": self.rx, "quantity": 1}), "exceeds_prescription")
        self.assertTrue(self.cart.view("u1")["can_checkout"])

    def test_other_customers_cannot_use_my_approval(self):
        self.approved("u1")
        self.assertEqual(self.code(self.cart.add, "u2", {"product_id": self.rx, "quantity": 1}), "prescription_required")

    def test_expired_approval_is_useless(self):
        pid = self.approved(valid_days=2)
        self.cart.add("u1", {"product_id": self.rx, "quantity": 1})
        self.clock.now += timedelta(days=3)
        v = self.cart.view("u1")
        self.assertEqual((v["items"][0]["problem"], v["can_checkout"]), ("prescription_required", False))
        with self.assertRaises(ServiceError) as c:
            self.orders.create("u1", {"address_id": self.addr})
        self.assertEqual((c.exception.code, c.exception.fields), ("cart_invalid", {self.rx: "prescription_required"}))
        self.assertEqual(self.remaining(pid), 10)

    def test_approval_does_not_unlock_restricted_schedule_x(self):
        self.assertEqual(self.code(self.cart.add, "u1", {"product_id": self.restricted, "quantity": 1}), "not_purchasable")

    def test_checkout_consumes_and_records_prescription(self):
        pid = self.approved(items=[{"product_id": self.rx, "max_quantity": 6}])
        order = self.place([(self.rx, 4)])
        self.assertEqual(order["lines"][0]["prescription_id"], pid)
        self.assertEqual(self.remaining(pid), 2)
        self.assertEqual(self.code(self.cart.add, "u1", {"product_id": self.rx, "quantity": 3}), "exceeds_prescription")
        self.place([(self.rx, 2)])
        self.assertEqual(self.remaining(pid), 0)
        self.assertEqual(self.code(self.cart.add, "u1", {"product_id": self.rx, "quantity": 1}), "prescription_required")

    def test_cancel_restores_exactly_once(self):
        pid = self.approved()
        order = self.place([(self.rx, 3)])
        self.assertEqual(self.remaining(pid), 7)
        self.orders.cancel("u1", order["id"])
        self.assertEqual(self.remaining(pid), 10)
        self.assertEqual(self.code(self.orders.cancel, "u1", order["id"]), "invalid_state")
        self.assertEqual(self.remaining(pid), 10)

    def test_expiry_restores_exactly_once(self):
        pid = self.approved()
        self.place([(self.rx, 3)])
        self.clock.advance(16)
        self.assertEqual(self.orders.release_expired(), 1)
        self.assertEqual(self.orders.release_expired(), 0)
        self.assertEqual(self.remaining(pid), 10)

    def test_paid_order_keeps_consumption(self):
        pid = self.approved()
        order = self.place([(self.rx, 3)])
        self.orders.pay("u1", order["id"], {})
        self.clock.advance(60)
        self.orders.release_expired()
        self.assertEqual(self.remaining(pid), 7)
        self.assertEqual(self.code(self.orders.cancel, "u1", order["id"]), "invalid_state")

    def test_failed_payment_keeps_hold_until_expiry_then_restores(self):
        pid = self.approved()
        order = self.place([(self.rx, 3)])
        with self.assertRaises(ServiceError):
            self.orders.pay("u1", order["id"], {"simulate": "fail"})
        self.assertEqual(self.remaining(pid), 7)
        self.clock.advance(16)
        self.orders.release_expired()
        self.assertEqual(self.remaining(pid), 10)

    def test_failure_after_consumption_rolls_everything_back(self):
        pid = self.approved()
        self.cart.add("u1", {"product_id": self.rx, "quantity": 3})
        self.cart.add("u1", {"product_id": self.para, "quantity": 2})
        with mock.patch.object(self.orders, "_insert_with_number", side_effect=RuntimeError("db down")):
            with self.assertRaises(RuntimeError):
                self.orders.create("u1", {"address_id": self.addr})
        self.assertEqual(self.remaining(pid), 10)
        self.assertEqual(self.batch("R1")["quantity_reserved"], 0)
        self.assertEqual(len(self.carts.docs["u1"]["items"]), 2)

    def test_allowance_taken_by_someone_else_in_a_race_blocks_checkout_cleanly(self):
        pid = self.approved()
        self.cart.add("u1", {"product_id": self.rx, "quantity": 3})
        self.cart.add("u1", {"product_id": self.para, "quantity": 2})
        with mock.patch.object(self.allow, "consume", return_value=None):
            with self.assertRaises(ServiceError) as c:
                self.orders.create("u1", {"address_id": self.addr})
        self.assertEqual(c.exception.code, "cart_invalid")
        self.assertEqual((self.remaining(pid), self.batch("R1")["quantity_reserved"], self.batch("P1")["quantity_reserved"]), (10, 0, 0))
        self.assertEqual(self.order_repo.docs, {})
        self.assertEqual(len(self.carts.docs["u1"]["items"]), 2)

    def test_uses_earliest_expiring_prescription_and_never_splits(self):
        late = self.approved(items=[{"product_id": self.rx, "max_quantity": 5}], valid_days=60)
        early = self.approved(items=[{"product_id": self.rx, "max_quantity": 3}], valid_days=10)
        self.place([(self.rx, 2)])
        self.assertEqual((self.remaining(early), self.remaining(late)), (1, 5))
        self.assertEqual(self.code(self.cart.add, "u1", {"product_id": self.rx, "quantity": 6}), "exceeds_prescription")

    def test_mixed_order_otc_and_rx(self):
        pid = self.approved()
        order = self.place([(self.rx, 1), (self.para, 2)])
        self.assertEqual({l["product_id"]: l["prescription_id"] for l in order["lines"]}, {self.rx: pid, self.para: None})

    def test_consume_rejects_bad_quantities_and_expired_prescriptions(self):
        pid = self.approved(valid_days=2)
        for bad in (0, -1, True, "3", 2.0, None):
            self.assertIsNone(self.allow.consume("u1", self.rx, bad))
        self.assertEqual(self.remaining(pid), 10)
        self.assertIsNotNone(self.allow.consume("u1", self.rx, 1))
        self.clock.now += timedelta(days=3)          # it expires between pricing and consuming
        self.assertIsNone(self.allow.consume("u1", self.rx, 1))
        self.assertIsNone(self.allow.consume("u2", self.rx, 1))
        self.assertEqual(self.remaining(pid), 9)

    def test_without_allowance_provider_rx_stays_blocked(self):
        cart = CartService(self.carts, self.products, self.res, self.clock)
        self.approved()
        self.assertEqual(self.code(cart.add, "u1", {"product_id": self.rx, "quantity": 1}), "prescription_required")


class AllowanceInvariantTests(RxBase):
    def test_random_orders_never_overdraw_or_leak_allowance(self):
        rnd = random.Random(2026)
        p1 = self.approved("u1", items=[{"product_id": self.rx, "max_quantity": 12}, {"product_id": self.rx2, "max_quantity": 8}])
        p2 = self.approved("u2", items=[{"product_id": self.rx, "max_quantity": 9}], valid_days=40)
        orders = []
        for _ in range(500):
            user = rnd.choice(["u1", "u2"])
            op = rnd.choice(["order", "order", "cancel", "pay", "advance", "sweep"])
            try:
                if op == "order":
                    for pid, qty in rnd.sample([(self.rx, rnd.randint(1, 4)), (self.rx2, rnd.randint(1, 3)), (self.para, 1)], rnd.randint(1, 2)):
                        self.cart.add(user, {"product_id": pid, "quantity": qty})
                    orders.append(self.orders.create(user, {"address_id": self.addr if user == "u1" else self.addr2})["id"])
                elif op == "cancel" and orders:
                    self.orders.cancel(user, rnd.choice(orders))
                elif op == "pay" and orders:
                    self.orders.pay(user, rnd.choice(orders), {})
                elif op == "advance":
                    self.clock.advance(rnd.choice([1, 10, 20]))
                else:
                    self.orders.release_expired()
            except ServiceError:
                pass
            live = ("pending_payment", "processing_payment", "confirmed", "payment_review")
            for pres_id in (p1, p2):
                for item in self.rx_repo.docs[pres_id]["approval"]["items"]:
                    used = sum(l["rx"]["quantity"] for o in self.order_repo.docs.values() if o["status"] in live
                               for l in o["lines"] if l.get("rx") and l["rx"]["prescription_id"] == pres_id
                               and l["rx"]["product_id"] == item["product_id"])
                    self.assertGreaterEqual(item["remaining"], 0)
                    self.assertEqual(item["remaining"], item["max_quantity"] - used)
        self.assertGreater(len(self.order_repo.docs), 10)


if __name__ == "__main__":
    unittest.main()
