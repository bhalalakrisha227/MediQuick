import hashlib
import hmac
import json
import random
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import timedelta

from apps.accounts.errors import ServiceError
from apps.orders import rules
from apps.orders.gateway import STALE_CONFIRMING_MINUTES, STALE_PROCESSING_MINUTES, GatewayPaymentService
from apps.orders.lifecycle import LifecycleService
from apps.orders.payments import GatewayError, MockPaymentAdapter, RazorpayAdapter, default_http
from apps.orders.refunds import RefundService
from apps.orders.services import OrderService

from .fakes import FakePaymentEvents, FakeRefunds, FakeReturns
from .test_pharmacist_review import RxBase

KEY_ID, SECRET, WH_SECRET = "rzp_test_abc123", "very-secret-key-value", "whsec_value"


class FakeRazorpay:
    """A tiny stand-in for the Razorpay REST API (only the calls the adapter makes)."""

    def __init__(self):
        self.orders, self.payments, self.refunds, self.calls = {}, {}, {}, []
        self.refund_keys, self.down, self.refund_mode, self.n = {}, False, "ok", 0

    def __call__(self, method, url, *, auth, body=None, headers=None, timeout=15):
        assert auth == (KEY_ID, SECRET), "wrong credentials"
        path = url.split("/v1", 1)[1]
        self.calls.append((method, path, body, headers or {}))
        if self.down:
            raise GatewayError("The payment service could not be reached.")
        if method == "POST" and path == "/orders":
            self.n += 1
            oid = f"order_{self.n:08d}"
            self.orders[oid] = {"id": oid, "amount": body["amount"], "currency": body["currency"], "receipt": body["receipt"]}
            return 200, self.orders[oid]
        if method == "GET" and path.startswith("/payments/"):
            p = self.payments.get(path.split("/")[2])
            return (200, dict(p)) if p else (400, {"error": {"description": "not found"}})
        if method == "GET" and path.endswith("/payments") and path.startswith("/orders/"):
            oid = path.split("/")[2]
            return 200, {"items": [dict(p) for p in self.payments.values() if p["order_id"] == oid]}
        if method == "POST" and path.endswith("/capture"):
            p = self.payments[path.split("/")[2]]
            if p["status"] == "authorized":
                p["status"] = "captured"
            return 200, dict(p)
        if method == "POST" and path.endswith("/refund"):
            if self.refund_mode == "fail":
                return 500, {"error": {"description": "boom"}}
            key = headers["X-Refund-Idempotency"]
            if key in self.refund_keys:
                return 200, self.refund_keys[key]
            p = self.payments[path.split("/")[2]]
            done = sum(r["amount"] for r in self.refunds.values() if r["payment_id"] == p["id"])
            if done + body["amount"] > p["amount"]:
                return 400, {"error": {"description": "refund exceeds payment"}}
            rid = f"rfnd_{len(self.refunds) + 1:06d}"
            self.refunds[rid] = {"id": rid, "payment_id": p["id"], "amount": body["amount"], "status": "processed"}
            self.refund_keys[key] = self.refunds[rid]
            return 200, self.refunds[rid]
        return 404, {}

    def pay(self, gateway_order_id, status="captured", amount=None, currency="INR"):
        self.n += 1
        pid = f"pay_{self.n:010d}"
        self.payments[pid] = {"id": pid, "order_id": gateway_order_id, "amount": amount if amount is not None else self.orders[gateway_order_id]["amount"],
                              "currency": currency, "status": status}
        return pid


def sign(gw_order, pay_id, secret=SECRET):
    return hmac.new(secret.encode(), f"{gw_order}|{pay_id}".encode(), hashlib.sha256).hexdigest()


def body_sig(raw, secret=WH_SECRET):
    return hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


class GwBase(RxBase):
    def setUp(self):
        super().setUp()
        self.gw = FakeRazorpay()
        self.adapter = RazorpayAdapter(KEY_ID, SECRET, WH_SECRET, http=self.gw)
        self.orders = OrderService(self.carts, self.order_repo, self.products, self.addresses, self.res, self.adapter,
                                   self.clock, allowances=self.allow)
        self.refund_repo, self.returns, self.events = FakeRefunds(), FakeReturns(), FakePaymentEvents()
        self.refunds = RefundService(self.refund_repo, self.order_repo, self.adapter, self.clock)
        self.life = LifecycleService(self.orders, self.order_repo, self.returns, self.refunds, self.res, self.allow, self.clock)
        self.gateway = GatewayPaymentService(self.orders, self.order_repo, self.adapter, self.res, self.refunds, self.events,
                                             self.allow, self.clock)
        self.eid = 0

    def started(self, items=None, user="u1"):
        o = self.place(items or [(self.para, 3)], user)
        info = self.gateway.start(user, o["id"])
        return o, info

    def verify(self, o, info, pay_id, **over):
        data = {"razorpay_order_id": info["gateway_order_id"], "razorpay_payment_id": pay_id,
                "razorpay_signature": sign(info["gateway_order_id"], pay_id), **over}
        return self.gateway.verify("u1", o["id"], data)

    def webhook(self, event="payment.captured", pay_id=None, gw_order=None, event_id=None, refund=None, tamper=False, sig=None):
        payload = {}
        if pay_id:
            payload["payment"] = {"entity": {"id": pay_id, "order_id": gw_order}}
        if refund:
            payload["refund"] = {"entity": {"id": refund}}
        raw = json.dumps({"event": event, "payload": payload}).encode()
        signature = sig if sig is not None else body_sig(raw)
        if tamper:
            raw = raw.replace(b"payment", b"paymenX")
        self.eid += 1
        return self.gateway.handle_webhook(raw, signature, event_id or f"evt_{self.eid}")

    def assert_ledger_balanced(self):
        for b in self.batches.docs.values():
            total = sum(m["delta"] for m in self.movements.docs if m["batch_id"] == b["_id"])
            self.assertEqual(b["quantity_on_hand"], total, b["batch_number"])

    def sales(self):
        return [m for m in self.movements.docs if m["type"] == "sale"]

    def status(self, oid):
        return self.order_repo.docs[oid]["status"]


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.gw = FakeRazorpay()
        self.a = RazorpayAdapter(KEY_ID, SECRET, WH_SECRET, http=self.gw)

    def test_requires_all_secrets_and_reports_mode(self):
        for args in (("", SECRET, WH_SECRET), (KEY_ID, "", WH_SECRET), (KEY_ID, SECRET, "")):
            with self.assertRaises(ValueError):
                RazorpayAdapter(*args)
        self.assertEqual((self.a.mode, RazorpayAdapter("rzp_live_x", "s", "w").mode), ("test", "live"))

    def test_payment_signature(self):
        good = sign("order_1", "pay_1")
        self.assertTrue(self.a.verify_payment_signature("order_1", "pay_1", good))
        for args in (("order_2", "pay_1", good), ("order_1", "pay_2", good), ("order_1", "pay_1", good[:-1] + "0"),
                     ("order_1", "pay_1", ""), ("order_1", "pay_1", None), (None, "pay_1", good), ("order_1", 5, good),
                     ("order_1", "pay_1", sign("order_1", "pay_1", "other-secret"))):
            self.assertFalse(self.a.verify_payment_signature(*args), args)

    def test_webhook_signature_uses_raw_body_and_webhook_secret(self):
        raw = b'{"event":"payment.captured"}'
        self.assertTrue(self.a.verify_webhook(raw, body_sig(raw)))
        self.assertFalse(self.a.verify_webhook(raw + b" ", body_sig(raw)))
        self.assertFalse(self.a.verify_webhook(raw, body_sig(raw, SECRET)))      # the API secret is not the webhook secret
        self.assertFalse(self.a.verify_webhook(raw, None))
        self.assertFalse(self.a.verify_webhook(raw.decode(), body_sig(raw)))

    def test_create_order_sends_paise_and_short_receipt(self):
        gid = self.a.create_gateway_order({"total_paise": 12345, "order_number": "MQ-" + "X" * 60})
        sent = self.gw.calls[-1]
        self.assertEqual((sent[1], sent[2]["amount"], sent[2]["currency"], len(sent[2]["receipt"])), ("/orders", 12345, "INR", 40))
        self.assertTrue(gid.startswith("order_"))

    def test_unexpected_gateway_order_amount_rejected(self):
        self.a._http = lambda *a, **k: (200, {"id": "order_x", "amount": 1})
        with self.assertRaises(GatewayError):
            self.a.create_gateway_order({"total_paise": 500, "order_number": "MQ-1"})

    def test_fetch_payment_validates_id_shape(self):
        for bad in ("../orders", "pay_1/../x", "x", "", None, "pay_?a=1", "pay_" + "a" * 50):
            with self.assertRaises(GatewayError):
                self.a.fetch_payment(bad)
        self.assertEqual(self.gw.calls, [])

    def test_errors_never_leak_secrets(self):
        self.a._http = lambda *a, **k: (401, {"error": {"description": f"bad key {SECRET}"}})
        with self.assertRaises(GatewayError) as c:
            self.a.fetch_payment("pay_abcdef123")
        self.assertNotIn(SECRET, str(c.exception))

    def test_refund_mapping_and_idempotency_header(self):
        pid = self.gw.pay(self.a.create_gateway_order({"total_paise": 1000, "order_number": "MQ-1"}))
        order = {"payment": {"reference": pid}, "order_number": "MQ-1"}
        r = self.a.refund(order, 400, "ord:1:cancellation:ord1", {})
        self.assertTrue(r.success)
        header = self.gw.calls[-1][3]["X-Refund-Idempotency"]
        self.assertRegex(header, r"^[A-Za-z0-9_-]{10,}$")
        again = self.a.refund(order, 400, "ord:1:cancellation:ord1", {})
        self.assertEqual(again.reference, r.reference)                     # same key -> same refund, not a second one
        self.assertFalse(self.a.refund(order, 5000, "other-key-12345", {}).success)    # more than paid
        self.assertFalse(self.a.refund({"payment": {}}, 10, "k" * 12, {}).success)
        self.gw.down = True
        self.assertFalse(self.a.refund(order, 10, "another-key-1234", {}).success)
        self.gw.down = False
        self.assertEqual(self.a.refund({"payment": {}, "order_number": "x"}, 100, "late-key-123456", {"payment_id": pid}).success, True)

    def test_charge_is_not_a_thing_for_gateways(self):
        self.assertFalse(self.a.charge({}, {}).success)
        self.assertTrue(self.a.is_gateway and not MockPaymentAdapter().is_gateway)


class LocalHttpTests(unittest.TestCase):
    def test_default_http_against_a_local_server(self):
        seen = {}

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                seen["auth"], seen["path"] = self.headers.get("Authorization"), self.path
                code = 404 if self.path == "/missing" else 200
                body = b"not json" if self.path == "/garbage" else json.dumps({"ok": True}).encode()
                self.send_response(code)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        base = f"http://127.0.0.1:{srv.server_port}"
        self.assertEqual(default_http("GET", base + "/x", auth=("id", "sec")), (200, {"ok": True}))
        self.assertTrue(seen["auth"].startswith("Basic "))
        self.assertEqual(default_http("GET", base + "/missing", auth=("a", "b"))[0], 404)
        self.assertEqual(default_http("GET", base + "/garbage", auth=("a", "b")), (200, {}))
        with self.assertRaises(GatewayError):
            default_http("GET", "http://127.0.0.1:1/x", auth=("a", "b"), timeout=2)


class StartTests(GwBase):
    def test_start_moves_to_processing_keeps_stock_and_exposes_no_secret(self):
        o, info = self.started()
        self.assertEqual(self.status(o["id"]), "processing_payment")
        self.assertEqual(self.batch("P1")["quantity_reserved"], 3)
        self.assertEqual((info["amount_paise"], info["currency"], info["key_id"], info["mode"]), (o["total_paise"], "INR", KEY_ID, "test"))
        self.assertNotIn(SECRET, json.dumps(info))
        self.assertNotIn(WH_SECRET, json.dumps(info))
        self.assertNotIn("gateway_order_id", json.dumps(self.orders.get("u1", o["id"])))   # not in the public order

    def test_start_is_idempotent_and_resumable(self):
        o, info = self.started()
        again = self.gateway.start("u1", o["id"])
        self.assertEqual(again["gateway_order_id"], info["gateway_order_id"])
        self.assertEqual(len(self.gw.orders), 1)

    def test_other_users_and_bad_states(self):
        o, _ = self.started()
        self.assertEqual(self.code(self.gateway.start, "u2", o["id"]), "not_found")
        done = self.place([(self.cet, 1)])
        self.life.cancel("u1", done["id"])
        self.assertEqual(self.code(self.gateway.start, "u1", done["id"]), "invalid_state")

    def test_expired_reservation_cannot_start(self):
        o = self.place([(self.para, 1)])
        self.clock.advance(rules.RESERVATION_MINUTES + 1)
        self.assertEqual(self.code(self.gateway.start, "u1", o["id"]), "reservation_expired")
        self.assertEqual((self.status(o["id"]), self.batch("P1")["quantity_reserved"], self.gw.orders), ("expired", 0, {}))

    def test_gateway_down_leaves_order_pending(self):
        o = self.place([(self.para, 1)])
        self.gw.down = True
        self.assertEqual(self.code(self.gateway.start, "u1", o["id"]), "gateway_error")
        self.assertEqual(self.status(o["id"]), "pending_payment")

    def test_mock_provider_has_no_gateway_flow(self):
        g = GatewayPaymentService(self.orders, self.order_repo, MockPaymentAdapter(), self.res, self.refunds, self.events, self.allow, self.clock)
        self.assertEqual(g.config(), {"provider": "mock", "key_id": None, "mode": None})
        o = self.place([(self.para, 1)])
        self.assertEqual(self.code(g.start, "u1", o["id"]), "not_gateway")
        self.assertEqual(self.code(g.handle_webhook, b"{}", "x", "e"), "not_gateway")

    def test_direct_pay_endpoint_refused_for_gateways(self):
        o = self.place([(self.para, 1)])
        self.assertEqual(self.code(self.orders.pay, "u1", o["id"], {}), "use_gateway")
        self.assertEqual(self.status(o["id"]), "pending_payment")

    def test_config_exposes_only_public_values(self):
        self.assertEqual(self.gateway.config(), {"provider": "razorpay", "key_id": KEY_ID, "mode": "test"})


class VerifyTests(GwBase):
    def test_happy_path_commits_stock_once(self):
        before = self.batch("P1")["quantity_on_hand"]
        o, info = self.started()
        pid = self.gw.pay(info["gateway_order_id"])
        out = self.verify(o, info, pid)
        self.assertEqual((out["status"], out["payment"]["status"], out["payment"]["reference"]), ("confirmed", "paid", pid))
        self.assertEqual((self.batch("P1")["quantity_on_hand"], self.batch("P1")["quantity_reserved"]), (before - 3, 0))
        self.assertEqual(len(self.sales()), 1)
        self.assertEqual(self.verify(o, info, pid)["status"], "confirmed")           # replay is harmless
        self.assertEqual(len(self.sales()), 1)
        self.assert_ledger_balanced()

    def test_bad_signatures_change_nothing(self):
        o, info = self.started()
        pid = self.gw.pay(info["gateway_order_id"])
        other = self.gw.pay(info["gateway_order_id"])
        for over in ({"razorpay_signature": "0" * 64}, {"razorpay_signature": None}, {"razorpay_signature": sign("order_other", pid)},
                     {"razorpay_order_id": "order_other"}, {"razorpay_payment_id": other}, {"razorpay_order_id": None}):
            with self.subTest(str(over)[:40]):
                self.assertEqual(self.code(lambda: self.verify(o, info, pid, **over)), "invalid_signature")
        self.assertEqual((self.status(o["id"]), len(self.sales())), ("processing_payment", 0))

    def test_browser_cannot_substitute_the_gateway_order(self):
        o, info = self.started()
        other_o, other_info = self.started([(self.cet, 1)])
        pid = self.gw.pay(other_info["gateway_order_id"])                               # a REAL cheap payment for another order
        data = {"razorpay_order_id": other_info["gateway_order_id"], "razorpay_payment_id": pid,
                "razorpay_signature": sign(other_info["gateway_order_id"], pid)}
        self.assertEqual(self.code(self.gateway.verify, "u1", o["id"], data), "invalid_signature")
        self.assertEqual(self.status(o["id"]), "processing_payment")

    def test_wrong_amount_or_currency_never_confirms(self):
        o, info = self.started()
        for amount, cur in ((1, "INR"), (o["total_paise"], "USD"), (o["total_paise"] + 1, "INR")):
            pid = self.gw.pay(info["gateway_order_id"], amount=amount, currency=cur)
            self.assertEqual(self.code(lambda: self.verify(o, info, pid)), "payment_review")
        self.assertEqual((self.status(o["id"]), len(self.sales())), ("processing_payment", 0))
        self.assertTrue(self.order_repo.docs[o["id"]]["needs_attention"].startswith("payment_mismatch"))

    def test_payment_for_a_different_gateway_order_is_a_mismatch(self):
        o, info = self.started()
        _, other = self.started([(self.cet, 1)])
        pid = self.gw.pay(other["gateway_order_id"])
        self.gw.payments[pid]["amount"] = o["total_paise"]
        self.assertEqual(self.code(lambda: self.verify(o, info, pid)), "payment_review")
        self.assertEqual(self.status(o["id"]), "processing_payment")

    def test_authorized_payment_is_captured_then_confirmed(self):
        o, info = self.started()
        pid = self.gw.pay(info["gateway_order_id"], status="authorized")
        self.assertEqual(self.verify(o, info, pid)["status"], "confirmed")
        self.assertIn("/payments/%s/capture" % pid, [c[1] for c in self.gw.calls])

    def test_failed_or_created_payment_is_not_a_payment(self):
        o, info = self.started()
        for st in ("failed", "created"):
            pid = self.gw.pay(info["gateway_order_id"], status=st)
            self.assertEqual(self.code(lambda: self.verify(o, info, pid)), "payment_not_completed")
        self.assertEqual((self.status(o["id"]), len(self.sales())), ("processing_payment", 0))

    def test_gateway_outage_during_verify_is_retryable(self):
        o, info = self.started()
        pid = self.gw.pay(info["gateway_order_id"])
        self.gw.down = True
        self.assertEqual(self.code(lambda: self.verify(o, info, pid)), "gateway_error")
        self.gw.down = False
        self.assertEqual(self.verify(o, info, pid)["status"], "confirmed")

    def test_commit_failure_after_payment_goes_to_review(self):
        o, info = self.started()
        pid = self.gw.pay(info["gateway_order_id"])
        self.res.commit = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db"))
        self.gateway.os.reservations.commit = self.res.commit
        self.assertEqual(self.gateway.confirm_payment(o["id"], pid), "review")
        self.assertEqual(self.status(o["id"]), "payment_review")

    def test_confirm_race_commits_once(self):
        o, info = self.started()
        pid = self.gw.pay(info["gateway_order_id"])
        real = self.order_repo.transition
        calls = []

        def racing(oid, frm, to, fields, note, now):
            if (frm, to) == ("processing_payment", "confirming_payment") and not calls:
                calls.append(1)
                self.assertEqual(self.gateway.confirm_payment(o["id"], pid), "confirmed")   # the other worker finishes first
            return real(oid, frm, to, fields, note, now)
        self.order_repo.transition = racing
        self.assertEqual(self.gateway.confirm_payment(o["id"], pid), "already")
        self.order_repo.transition = real
        self.assertEqual(len(self.sales()), 1)
        self.assert_ledger_balanced()


class WebhookTests(GwBase):
    def test_captured_event_confirms_and_duplicates_are_noops(self):
        o, info = self.started()
        pid = self.gw.pay(info["gateway_order_id"])
        self.assertEqual(self.webhook(pay_id=pid, gw_order=info["gateway_order_id"], event_id="evt_same")["status"], "ok")
        self.assertEqual(self.status(o["id"]), "confirmed")
        self.assertEqual(self.webhook(pay_id=pid, gw_order=info["gateway_order_id"], event_id="evt_same")["status"], "duplicate")
        self.assertEqual(self.webhook(event="order.paid", pay_id=pid, gw_order=info["gateway_order_id"])["status"], "ok")
        self.assertEqual(len(self.sales()), 1)

    def test_browser_verify_and_webhook_together_commit_once(self):
        o, info = self.started()
        pid = self.gw.pay(info["gateway_order_id"])
        self.webhook(pay_id=pid, gw_order=info["gateway_order_id"])
        self.verify(o, info, pid)
        self.assertEqual(len(self.sales()), 1)

    def test_bad_signature_or_missing_id_or_garbage_rejected(self):
        o, info = self.started()
        pid = self.gw.pay(info["gateway_order_id"])
        self.assertEqual(self.code(lambda: self.webhook(pay_id=pid, gw_order=info["gateway_order_id"], sig="0" * 64)), "invalid_signature")
        self.assertEqual(self.code(lambda: self.webhook(pay_id=pid, gw_order=info["gateway_order_id"], tamper=True)), "invalid_signature")
        self.assertEqual(self.code(self.gateway.handle_webhook, b"{}", None, "e1"), "invalid_signature")
        raw = b'{"event":"payment.captured","payload":{}}'
        self.assertEqual(self.code(self.gateway.handle_webhook, raw, body_sig(raw), None), "validation_error")
        junk = b"not json"
        self.assertEqual(self.code(self.gateway.handle_webhook, junk, body_sig(junk), "e2"), "validation_error")
        for odd in (b"[]", b"null", b'{"event": 5}'):
            try:
                self.gateway.handle_webhook(odd, body_sig(odd), "e3-" + odd.decode())
            except ServiceError as exc:
                self.assertEqual(exc.status, 400)
        self.assertEqual((self.status(o["id"]), len(self.sales()), self.events.ids.get("e2")), ("processing_payment", 0, None))

    def test_unknown_order_is_acknowledged_without_crashing(self):
        self.assertEqual(self.webhook(pay_id="pay_0000000099", gw_order="order_nope")["status"], "ok")

    def test_event_is_recorded_only_after_it_was_handled(self):
        o, info = self.started()
        pid = self.gw.pay(info["gateway_order_id"])
        self.gw.down = True
        self.assertEqual(self.code(lambda: self.webhook(pay_id=pid, gw_order=info["gateway_order_id"], event_id="evt_retry")), "gateway_error")
        self.assertFalse(self.events.seen("evt_retry"))
        self.gw.down = False
        self.assertEqual(self.webhook(pay_id=pid, gw_order=info["gateway_order_id"], event_id="evt_retry")["status"], "ok")
        self.assertEqual(self.status(o["id"]), "confirmed")

    def test_failed_event_changes_nothing_but_is_recorded(self):
        o, info = self.started()
        self.assertEqual(self.webhook(event="payment.failed", pay_id=self.gw.pay(info["gateway_order_id"], status="failed"),
                                      gw_order=info["gateway_order_id"], event_id="evt_f")["status"], "ok")
        self.assertEqual(self.status(o["id"]), "processing_payment")
        self.assertTrue(self.events.seen("evt_f"))

    def test_webhook_cannot_confirm_without_a_real_captured_payment(self):
        o, info = self.started()
        with self.assertRaises(ServiceError):
            self.webhook(pay_id="pay_0000000777", gw_order=info["gateway_order_id"])      # gateway has no such payment
        pid = self.gw.pay(info["gateway_order_id"], status="failed")
        self.webhook(pay_id=pid, gw_order=info["gateway_order_id"])                        # claims captured; gateway says failed
        self.assertEqual((self.status(o["id"]), len(self.sales())), ("processing_payment", 0))

    def test_gateway_reports_a_refund_failed_later(self):
        o, info = self.started()
        pid = self.gw.pay(info["gateway_order_id"])
        self.verify(o, info, pid)
        out = self.life.cancel("u1", o["id"])
        self.assertEqual((out["refund"]["status"], self.order_repo.docs[o["id"]]["payment"]["refunded_paise"]), ("succeeded", o["total_paise"]))
        ref = next(iter(self.refund_repo.docs.values()))
        self.webhook(event="refund.failed", refund=ref["reference"])
        self.assertEqual((ref["status"], self.order_repo.docs[o["id"]]["payment"]["refunded_paise"]), ("failed", 0))
        self.assertEqual(self.life.retry_refund("admin", ref["_id"])["status"], "succeeded")
        self.assertEqual(self.order_repo.docs[o["id"]]["payment"]["refunded_paise"], o["total_paise"])


class LatePaymentTests(GwBase):
    def test_payment_after_customer_cancelled_is_refunded_once(self):
        o, info = self.started()
        self.assertEqual(self.life.cancel("u1", o["id"])["order"]["status"], "cancelled")
        self.assertEqual(self.batch("P1")["quantity_reserved"], 0)
        pid = self.gw.pay(info["gateway_order_id"])
        self.webhook(pay_id=pid, gw_order=info["gateway_order_id"])
        self.webhook(pay_id=pid, gw_order=info["gateway_order_id"])
        self.assertEqual((self.status(o["id"]), len(self.sales())), ("cancelled", 0))
        self.assertEqual(len(self.gw.refunds), 1)
        self.assertEqual(self.order_repo.docs[o["id"]]["payment"]["refunded_paise"], o["total_paise"])
        self.assertEqual(self.batch("P1")["quantity_on_hand"], 20)
        self.assert_ledger_balanced()

    def test_payment_after_page_was_abandoned_and_swept_is_refunded(self):
        o, info = self.started()
        self.clock.advance(STALE_PROCESSING_MINUTES + 1)
        self.assertEqual(self.gateway.reconcile()["expired"], 1)
        self.assertEqual((self.status(o["id"]), self.batch("P1")["quantity_reserved"]), ("expired", 0))
        pid = self.gw.pay(info["gateway_order_id"])
        self.assertEqual(self.gateway.confirm_payment(o["id"], pid), "late_refunded")
        self.assertEqual((self.status(o["id"]), len(self.gw.refunds)), ("expired", 1))

    def test_late_payment_through_browser_verify_says_refunded(self):
        o, info = self.started()
        self.life.cancel("u1", o["id"])
        pid = self.gw.pay(info["gateway_order_id"])
        self.assertEqual(self.code(lambda: self.verify(o, info, pid)), "payment_refunded")

    def test_stock_becoming_unsellable_after_payment_refunds_and_releases(self):
        o, info = self.started()
        batch = self.batch("P1")
        self.inv.set_status({"id": "mgr-1", "role": "pharmacy_manager"}, batch["_id"], {"status": "recalled", "note": "recall"})
        pid = self.gw.pay(info["gateway_order_id"])
        self.assertEqual(self.gateway.confirm_payment(o["id"], pid), "cancelled_refunded")
        self.assertEqual((self.status(o["id"]), self.batch("P1")["quantity_reserved"], len(self.sales())), ("cancelled", 0, 0))
        self.assertEqual(self.order_repo.docs[o["id"]]["payment"]["refunded_paise"], o["total_paise"])

    def test_prescription_units_return_when_a_gateway_checkout_is_cancelled(self):
        pid = self.approved(items=[{"product_id": self.rx, "max_quantity": 5}])
        o, info = self.started([(self.rx, 4)])
        self.assertEqual(self.remaining(pid), 1)
        self.life.cancel("u1", o["id"])
        self.assertEqual(self.remaining(pid), 5)

    def test_second_payment_for_a_paid_order_is_flagged_not_refunded_blindly(self):
        o, info = self.started()
        first = self.gw.pay(info["gateway_order_id"])
        self.verify(o, info, first)
        second = self.gw.pay(info["gateway_order_id"])
        self.assertEqual(self.gateway.confirm_payment(o["id"], second), "duplicate")
        self.assertEqual(self.order_repo.docs[o["id"]]["needs_attention"], f"duplicate_payment:{second}")
        self.assertEqual((self.gw.refunds, self.order_repo.docs[o["id"]]["payment"]["reference"]), ({}, first))


    def test_extra_payments_on_a_closed_order_are_flagged_not_refund_looped(self):
        o, info = self.started()
        self.life.cancel("u1", o["id"])
        first, second = self.gw.pay(info["gateway_order_id"]), self.gw.pay(info["gateway_order_id"])
        self.assertEqual(self.gateway.confirm_payment(o["id"], first), "late_refunded")
        self.assertEqual(self.gateway.confirm_payment(o["id"], second), "duplicate")
        self.assertEqual(self.order_repo.docs[o["id"]]["needs_attention"], f"duplicate_payment:{second}")
        self.assertEqual(len(self.refund_repo.docs), 1)
        self.assertEqual(self.gateway.confirm_payment(o["id"], first), "late_refunded")  # replay: same refund, not a second
        self.assertEqual(len(self.refund_repo.docs), 1)


class CancelAndReconcileTests(GwBase):
    def test_cancel_while_paying_frees_stock(self):
        o, _ = self.started()
        out = self.life.cancel("u1", o["id"])
        self.assertEqual((out["order"]["status"], out["refund"], self.batch("P1")["quantity_reserved"]), ("cancelled", None, 0))

    def test_reconcile_expires_only_stale_unpaid_checkouts(self):
        fresh, _ = self.started()
        self.clock.advance(STALE_PROCESSING_MINUTES - 5)
        self.assertEqual(self.gateway.reconcile(), {"confirmed": 0, "expired": 0, "flagged": 0})
        self.clock.advance(10)
        self.assertEqual(self.gateway.reconcile()["expired"], 1)
        self.assertEqual(self.status(fresh["id"]), "expired")

    def test_reconcile_settles_a_payment_whose_callbacks_were_lost(self):
        o, info = self.started()
        self.gw.pay(info["gateway_order_id"])
        self.clock.advance(STALE_PROCESSING_MINUTES + 1)
        self.assertEqual(self.gateway.reconcile()["confirmed"], 1)
        self.assertEqual((self.status(o["id"]), len(self.sales())), ("confirmed", 1))

    def test_reconcile_never_expires_an_order_that_has_a_captured_payment(self):
        o, info = self.started()
        self.gw.pay(info["gateway_order_id"], amount=1)          # money was taken, but the amount does not match
        self.clock.advance(STALE_PROCESSING_MINUTES + 1)
        self.assertEqual(self.gateway.reconcile(), {"confirmed": 0, "expired": 0, "flagged": 0})
        self.assertEqual(self.status(o["id"]), "processing_payment")
        self.assertTrue(self.order_repo.docs[o["id"]]["needs_attention"].startswith("payment_mismatch"))

    def test_reconcile_with_gateway_down_changes_nothing(self):
        o, info = self.started()
        self.clock.advance(STALE_PROCESSING_MINUTES + 1)
        self.gw.down = True
        self.assertEqual(self.gateway.reconcile()["expired"], 0)
        self.assertEqual(self.status(o["id"]), "processing_payment")

    def test_stuck_confirming_orders_are_flagged_for_a_human(self):
        o, info = self.started()
        self.order_repo.docs[o["id"]]["status"] = "confirming_payment"
        self.order_repo.docs[o["id"]]["updated_at"] = self.clock()
        self.clock.advance(STALE_CONFIRMING_MINUTES + 1)
        self.assertEqual(self.gateway.reconcile()["flagged"], 1)
        self.assertEqual(self.status(o["id"]), "payment_review")


class GatewayInvariantTests(GwBase):
    def test_random_activity_never_loses_money_or_stock(self):
        rnd = random.Random(88)
        self.stock(self.para, "P2", 2000, 200)
        self.stock(self.cet, "C2", 2000, 200)
        live = []
        for step in range(1500):
            op = rnd.choice(["order", "start", "start", "pay", "pay", "verify", "hook", "cancel", "tick", "reconcile", "outage", "dup", "refund_mode"])
            try:
                if op == "order":
                    live.append(self.place([rnd.choice([(self.para, 1), (self.para, 2), (self.cet, 1)])])["id"])
                elif op == "start" and live:
                    self.gateway.start("u1", rnd.choice(live))
                elif op == "pay":
                    gws = [o["payment"]["gateway_order_id"] for o in self.order_repo.docs.values() if o["payment"].get("gateway_order_id")]
                    if gws:
                        self.gw.pay(rnd.choice(gws), status=rnd.choice(["captured", "captured", "failed", "authorized"]))
                elif op in ("verify", "hook", "dup") and self.gw.payments:
                    p = rnd.choice(list(self.gw.payments.values()))
                    oid = next((i for i, o in self.order_repo.docs.items() if o["payment"].get("gateway_order_id") == p["order_id"]), None)
                    if op == "verify" and oid:
                        self.gateway.verify("u1", oid, {"razorpay_order_id": p["order_id"], "razorpay_payment_id": p["id"],
                                                         "razorpay_signature": sign(p["order_id"], p["id"])})
                    elif op == "hook":
                        self.webhook(pay_id=p["id"], gw_order=p["order_id"])
                    elif oid:
                        self.gateway.confirm_payment(oid, p["id"])
                elif op == "cancel" and live:
                    self.life.cancel("u1", rnd.choice(live))
                elif op == "tick":
                    self.clock.advance(rnd.randint(1, 25))
                elif op == "reconcile":
                    self.gateway.reconcile()
                elif op == "outage":
                    self.gw.down = rnd.random() < 0.3
                else:
                    self.gw.refund_mode = rnd.choice(["ok", "ok", "fail"])
            except ServiceError:
                pass
            self.check_books()
        self.drain()
        self.assertGreater(len(self.gw.payments), 25)
        self.assertTrue(any(o["status"] == "confirmed" for o in self.order_repo.docs.values()))
        self.assertTrue(any(r["kind"] == "late_payment" for r in self.refund_repo.docs.values()))

    def reserved_by_batch(self):
        out = {}
        for o in self.order_repo.docs.values():
            if o["status"] in ("pending_payment", "processing_payment", "confirming_payment"):
                for line in o["lines"]:
                    for a in line["allocations"]:
                        out[a["batch_id"]] = out.get(a["batch_id"], 0) + a["quantity"]
        return out

    def check_books(self):
        self.assert_ledger_balanced()
        want = self.reserved_by_batch()
        for b in self.batches.docs.values():
            self.assertEqual(b["quantity_reserved"], want.get(b["_id"], 0), b["batch_number"])
        for oid, o in self.order_repo.docs.items():
            ok = sum(r["amount_paise"] for r in self.refund_repo.docs.values() if r["order_id"] == oid and r["status"] == "succeeded")
            self.assertEqual(o["payment"].get("refunded_paise", 0), ok)
            self.assertLessEqual(ok, o["total_paise"])
            if o["status"] in ("confirmed", "confirming_payment"):
                self.assertTrue(o["payment"]["reference"])
        sold = {}
        for m in self.sales():
            sold[m["reason"]] = sold.get(m["reason"], 0) + -m["delta"]
        for o in self.order_repo.docs.values():
            if o["status"] == "confirmed":
                self.assertEqual(sold.get(o["order_number"], 0), sum(l["quantity"] for l in o["lines"]))

    def drain(self):
        """Every captured payment must end up either on a confirmed order, fully refunded, or flagged for a human."""
        self.gw.down, self.gw.refund_mode = False, "ok"
        for p in list(self.gw.payments.values()):
            self.webhook(pay_id=p["id"], gw_order=p["order_id"], event_id=f"drain-{p['id']}")
        for r in list(self.refund_repo.docs.values()):
            if r["status"] == "failed":
                self.life.retry_refund("admin", r["_id"])
        self.clock.advance(60)
        self.gateway.reconcile()
        self.check_books()
        for p in self.gw.payments.values():
            if p["status"] != "captured":
                continue
            o = next(o for o in self.order_repo.docs.values() if o["payment"].get("gateway_order_id") == p["order_id"])
            refunded = sum(r["amount"] for r in self.gw.refunds.values() if r["payment_id"] == p["id"])
            confirmed_here = o["status"] in ("confirmed", "dispatched", "delivered") and o["payment"]["reference"] == p["id"]
            flagged = bool(o.get("needs_attention"))
            self.assertTrue(confirmed_here or refunded == p["amount"] or flagged, (p, o["status"], refunded))
            if confirmed_here:
                self.assertEqual(refunded, 0)


if __name__ == "__main__":
    unittest.main()
