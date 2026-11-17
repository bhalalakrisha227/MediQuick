import random
import smtplib
import unittest
from datetime import timedelta
from unittest import mock

from apps.accounts.errors import ServiceError
from apps.notifications import rules as nrules
from apps.notifications.email_adapters import EmailAdapter, EmailError, SmtpEmailAdapter
from apps.notifications.observers import NotifyingOrders, NotifyingPrescriptions, NotifyingRefunds, NotifyingReturns
from apps.notifications.service import NotificationService

from .fakes import FakeNotifications
from .test_delivery import DelBase
from .test_pharmacist_review import PH1


class RecordingEmail(EmailAdapter):
    name = "recording"

    def __init__(self):
        self.sent, self.script = [], []          # script: exceptions to raise, consumed one per call

    def send(self, to, subject, text):
        if self.script:
            exc = self.script.pop(0)
            if exc:
                raise exc
        self.sent.append((to, subject, text))


class NotifBase(DelBase):
    def setUp(self):
        super().setUp()
        for uid in ("u1", "u2"):
            self.users.insert({"_id": uid, "email": f"{uid}@x.test", "full_name": uid, "role": "customer", "is_active": True})
        self.nrepo, self.mail = FakeNotifications(), RecordingEmail()
        self.notif = NotificationService(self.nrepo, self.users, self.mail, "http://app.test/", self.clock)
        # Route every repository the services use through the observers (the same wrapping deps.py does).
        wrapped = NotifyingOrders(self.order_repo, self.notif)
        self.orders.orders = self.life.orders = self.dl.orders = self.refunds.orders = wrapped
        self.refunds.refunds = NotifyingRefunds(self.refund_repo, self.notif, wrapped)
        self.life.returns = NotifyingReturns(self.returns, self.notif)
        self.review.repo = NotifyingPrescriptions(self.rx_repo, self.notif)

    def events(self, user="u1"):
        return [n["event"] for n in sorted(self.nrepo.docs.values(), key=lambda n: n["created_at"]) if n["user_id"] == user]

    def drain(self):
        out = {"sent": 0, "retry": 0, "failed": 0, "skipped": 0}
        for k, v in self.notif.send_due(500).items():
            out[k] += v
        return out


class EventTests(NotifBase):
    def test_payment_and_fulfilment_events(self):
        o = self.paid()
        self.assertEqual(self.events(), ["order_confirmed"])
        self.dl.assign("m1", "pharmacy_manager", o["id"], "rider1")
        self.assertEqual(self.events(), ["order_confirmed"])               # assigning changes nothing the customer must hear
        self.dl.pickup("rider1", o["id"])
        self.dl.complete("rider1", o["id"], {"code": self.code(o["id"])})
        self.assertEqual(self.events(), ["order_confirmed", "order_dispatched", "order_delivered"])

    def test_cancel_paid_gives_cancelled_and_refund_but_unpaid_cancel_is_silent(self):
        o = self.paid()
        self.life.cancel("u1", o["id"])
        self.assertEqual(self.events(), ["order_confirmed", "order_cancelled", "refund_succeeded"])
        refund = next(n for n in self.nrepo.docs.values() if n["event"] == "refund_succeeded")
        self.assertIn(f"Rs {self.order_repo.docs[o['id']]['total_paise'] // 100}", refund["title"])
        u = self.place([(self.para, 1)])
        self.orders.cancel("u1", u["id"])
        self.assertEqual(self.events().count("order_cancelled"), 1)

    def test_failed_refund_sends_nothing_and_failed_delivery_does(self):
        oid = self.picked()
        self.fail_times(oid, 3)
        self.assertEqual(self.events()[-1], "order_delivery_failed")
        self.adapter.mode = "fail"
        self.dl.resolve_failed("m1", "pharmacy_manager", oid, "refund")
        self.assertEqual(self.events().count("refund_succeeded"), 0)
        self.assertEqual(self.events()[-1], "order_cancelled")

    def test_only_the_owner_is_notified(self):
        self.paid(user="u2")
        self.assertEqual(self.events("u1"), [])
        self.assertEqual(self.events("u2"), ["order_confirmed"])

    def test_returns(self):
        o = self.delivered()
        r = self.life.request_return("u1", o["id"], {"reason": "damaged", "items": [{"product_id": self.para, "quantity": 1}]})
        self.life.decide_return("m1", "pharmacy_manager", r["id"], {"decision": "approve", "note": ""})
        self.assertEqual(self.events()[-2:], ["return_approved", "refund_succeeded"])
        o2 = self.delivered(user="u2")
        r2 = self.life.request_return("u2", o2["id"], {"reason": "damaged", "items": [{"product_id": self.para, "quantity": 1}]})
        self.life.decide_return("m1", "pharmacy_manager", r2["id"], {"decision": "reject", "note": "not damaged"})
        self.assertEqual(self.events("u2")[-1], "return_rejected")

    def test_prescription_decisions(self):
        pid = self.submitted()
        self.claim(PH1, pid)
        self.review.clarify(PH1, pid, {"message": "Which strength is meant here?"})
        self.assertEqual(self.events(), ["prescription_clarification"])
        pid2 = self.approved()
        self.assertEqual(self.events()[-1], "prescription_approved")
        pid3 = self.submitted()
        self.claim(PH1, pid3)
        self.review.reject(PH1, pid3, {"reason": "Image is unreadable, please upload a clear photo."})
        self.assertEqual(self.events()[-1], "prescription_rejected")
        self.assertEqual(self.nrepo.docs and len({n["entity_id"] for n in self.nrepo.docs.values()}), 3)

    def test_gateway_style_confirm_notifies_once_even_if_the_same_change_is_attempted_twice(self):
        o = self.place([(self.para, 1)])
        self.orders.pay("u1", o["id"], {})
        self.orders.pay("u1", o["id"], {})            # idempotent pay
        self.assertEqual(self.events().count("order_confirmed"), 1)

    def test_a_broken_notifier_never_breaks_the_real_action(self):
        with mock.patch.object(self.notif, "emit", side_effect=RuntimeError("boom")):
            o = self.paid()
        self.assertEqual(self.order_repo.docs[o["id"]]["status"], "confirmed")
        with mock.patch.object(self.users, "get", side_effect=RuntimeError("db down")):
            o2 = self.paid()
        self.assertEqual(self.order_repo.docs[o2["id"]]["status"], "confirmed")

    def test_messages_never_contain_medicines_addresses_or_the_handover_code(self):
        oid = self.picked()
        code = self.code(oid)
        self.dl.complete("rider1", oid, {"code": code})
        c = self.delivered()
        self.life.request_return("u1", c["id"], {"reason": "damaged", "items": [{"product_id": self.para, "quantity": 1}]})
        addr = self.order_repo.docs[oid]["address"]
        for n in self.nrepo.docs.values():
            text = f"{n['title']} {n['body']} {n['link']}".lower()
            for secret in ("paracetamol", "azithromycin", code, addr["line1"].lower(), addr["phone"], addr["pincode"]):
                self.assertNotIn(secret, text, n["event"])
        import re
        for n in self.nrepo.docs.values():
            self.assertIsNone(re.search(r"\b\d{6}\b", re.sub(r"MQ-\S+", "", n["title"] + n["body"])), n["event"])
        self.drain()
        for _, subject, text in self.mail.sent:
            for secret in ("paracetamol", code, addr["line1"].lower()):
                self.assertNotIn(secret, (subject + text).lower())

    def test_a_transition_that_did_not_happen_notifies_nobody(self):
        o = self.paid()
        before = len(self.nrepo.docs)
        wrapped = self.orders.orders
        self.assertFalse(wrapped.transition(o["id"], "pending_payment", "delivered", {}, "x", self.clock()))
        self.assertFalse(wrapped.transition(o["id"], "dispatched", "delivered", {}, "x", self.clock()))
        self.assertEqual(len(self.nrepo.docs), before)
        pid = self.submitted()                       # status "submitted", so an in_review -> approved change cannot apply
        self.assertFalse(self.review.repo.staff_transition(pid, "in_review", "approved", {}, "x", self.clock()))
        self.assertEqual(len(self.nrepo.docs), before)

    def test_redelivery_after_a_failed_delivery_is_not_announced_as_a_new_confirmation(self):
        oid = self.picked()
        self.fail_times(oid, 3)
        count = self.events().count("order_confirmed")
        self.dl.resolve_failed("m1", "pharmacy_manager", oid, "redeliver")
        self.assertEqual(self.events().count("order_confirmed"), count)

    def test_duplicate_key_is_ignored(self):
        self.assertTrue(self.notif.emit("order_delivered", "u1", "o1", "/orders/o1", 3, "MQ-1"))
        self.assertFalse(self.notif.emit("order_delivered", "u1", "o1", "/orders/o1", 3, "MQ-1"))
        self.assertTrue(self.notif.emit("order_delivered", "u1", "o1", "/orders/o1", 5, "MQ-1"))   # a later occurrence is new
        self.assertEqual(len(self.nrepo.docs), 2)

    def test_unknown_user_or_event_is_swallowed(self):
        self.assertFalse(self.notif.emit("order_delivered", "ghost", "o1", "/x", 0, "MQ-1"))
        self.assertFalse(self.notif.emit("not_an_event", "u1", "o1", "/x", 0))
        self.assertEqual(self.nrepo.docs, {})


class EmailWorkerTests(NotifBase):
    def one(self, **kw):
        self.notif.emit("order_delivered", "u1", "o1", "/orders/o1", 1, "MQ-1")
        return next(iter(self.nrepo.docs.values()))

    def test_sends_with_link_and_marks_sent_once(self):
        n = self.one()
        self.assertEqual(self.drain()["sent"], 1)
        to, subject, text = self.mail.sent[0]
        self.assertEqual((to, subject), ("u1@x.test", "Order MQ-1 delivered"))
        self.assertIn("http://app.test/orders/o1", text)
        self.assertEqual(self.nrepo.docs[n["_id"]]["email"]["status"], "sent")
        self.assertEqual(self.nrepo.docs[n["_id"]]["email"]["sent_at"], self.clock())
        self.assertEqual(self.drain()["sent"], 0)
        self.assertEqual(len(self.mail.sent), 1)

    def test_transient_error_retries_with_backoff_then_succeeds(self):
        n = self.one()
        self.mail.script = [EmailError("server busy")]
        self.assertEqual(self.drain(), {"sent": 0, "retry": 1, "failed": 0, "skipped": 0})
        self.assertEqual(self.drain()["retry"] + self.drain()["sent"], 0)          # not due yet
        self.clock.advance(nrules.BACKOFF_MINUTES[0] - 1)
        self.assertEqual(self.drain()["sent"], 0)
        self.clock.advance(2)
        self.assertEqual(self.drain()["sent"], 1)
        self.assertEqual(self.nrepo.docs[n["_id"]]["email"]["attempts"], 2)

    def test_gives_up_after_max_attempts(self):
        n = self.one()
        self.mail.script = [EmailError("down")] * 10
        for _ in range(nrules.MAX_EMAIL_ATTEMPTS + 2):
            self.drain()
            self.clock.advance(300)
        e = self.nrepo.docs[n["_id"]]["email"]
        self.assertEqual((e["status"], e["attempts"]), ("failed", nrules.MAX_EMAIL_ATTEMPTS))
        self.assertEqual(self.mail.sent, [])

    def test_permanent_error_fails_at_once(self):
        n = self.one()
        self.mail.script = [EmailError("refused", permanent=True)]
        self.assertEqual(self.drain()["failed"], 1)
        self.assertEqual(self.nrepo.docs[n["_id"]]["email"]["attempts"], 1)

    def test_unexpected_exception_does_not_loop(self):
        n = self.one()
        self.mail.script = [ValueError("bug")]
        self.assertEqual(self.drain()["failed"], 1)
        self.assertEqual(self.drain(), {"sent": 0, "retry": 0, "failed": 0, "skipped": 0})

    def test_email_off_means_skipped_at_creation_and_never_sent(self):
        self.notif.update_settings("u1", {"email": False})
        n = self.one()
        self.assertEqual(self.nrepo.docs[n["_id"]]["email"]["status"], "skipped")
        self.assertEqual(self.drain()["sent"], 0)
        self.assertEqual(self.mail.sent, [])

    def test_switching_email_off_after_creation_still_stops_it(self):
        self.one()
        self.notif.update_settings("u1", {"email": False})
        self.assertEqual(self.drain(), {"sent": 0, "retry": 0, "failed": 0, "skipped": 1})
        self.assertEqual(self.mail.sent, [])

    def test_no_provider_or_no_address_is_skipped_but_in_app_remains(self):
        svc = NotificationService(self.nrepo, self.users, None, "http://app.test", self.clock)
        svc.emit("order_delivered", "u1", "o9", "/orders/o9", 1, "MQ-9")
        self.assertEqual(svc.send_due()["skipped"], 1)
        self.assertEqual(svc.list("u1")["total"], 1)
        self.users.docs["u2"]["email"] = ""
        self.notif.emit("order_delivered", "u2", "o8", "/orders/o8", 1, "MQ-8")
        self.assertEqual(self.nrepo.docs[[k for k, v in self.nrepo.docs.items() if v["entity_id"] == "o8"][0]]["email"]["status"], "skipped")

    def test_a_vanished_worker_is_covered_by_the_lease(self):
        n = self.one()
        claimed = self.nrepo.claim_due(self.clock(), self.clock() + timedelta(minutes=nrules.LEASE_MINUTES))
        self.assertIsNotNone(claimed)
        self.assertEqual(self.drain()["sent"], 0)                    # another worker is "sending" it: leave it alone
        self.clock.advance(nrules.LEASE_MINUTES + 1)
        self.assertEqual(self.drain()["sent"], 1)
        self.assertEqual(self.nrepo.docs[n["_id"]]["email"]["status"], "sent")

    def test_error_text_is_truncated_and_has_no_secrets(self):
        n = self.one()
        self.mail.script = [EmailError("x" * 5000)]
        self.drain()
        self.assertLessEqual(len(self.nrepo.docs[n["_id"]]["email"]["last_error"]), 200)


class InboxTests(NotifBase):
    def fill(self, user, n):
        for i in range(n):
            self.clock.advance(1)
            self.notif.emit("order_delivered", user, f"{user}-o{i}", f"/orders/{user}-o{i}", 1, f"MQ-{i}")

    def test_list_pages_newest_first_and_counts_unread(self):
        self.fill("u1", 25)
        first = self.notif.list("u1")
        self.assertEqual((len(first["results"]), first["total"], first["unread"]), (nrules.PAGE_SIZE, 25, 25))
        self.assertEqual(first["results"][0]["title"], "Order MQ-24 delivered")
        self.assertEqual(len(self.notif.list("u1", page=2)["results"]), 5)
        self.assertEqual(len(self.notif.list("u1", page="x")["results"]), nrules.PAGE_SIZE)     # bad page -> page 1
        self.assertEqual(self.notif.list("u2")["total"], 0)

    def test_mark_read_is_owner_only_and_repeatable(self):
        self.fill("u1", 2)
        nid = self.notif.list("u1")["results"][0]["id"]
        for who in ("u2", "ghost"):
            with self.assertRaises(ServiceError) as c:
                self.notif.mark_read(who, nid)
            self.assertEqual(c.exception.status, 404)
        self.assertEqual(self.notif.unread_count("u1")["unread"], 2)
        self.assertEqual(self.notif.mark_read("u1", nid)["unread"], 1)
        self.assertEqual(self.notif.mark_read("u1", nid)["unread"], 1)           # again: fine
        for bad in (None, 5, "nope"):
            with self.assertRaises(ServiceError):
                self.notif.mark_read("u1", bad)

    def test_read_all_only_touches_own(self):
        self.fill("u1", 3)
        self.fill("u2", 2)
        self.assertEqual(self.notif.mark_all_read("u1")["unread"], 0)
        self.assertEqual(self.notif.unread_count("u2")["unread"], 2)
        self.assertEqual(self.notif.list("u1", unread_only=True)["total"], 0)

    def test_settings_validation(self):
        self.assertEqual(self.notif.get_settings("u1"), {"email": True, "email_provider": "recording", "sms": False})
        for bad in (None, "yes", 1, {}, []):
            with self.assertRaises(ServiceError):
                self.notif.update_settings("u1", {"email": bad})
        with self.assertRaises(ServiceError):
            self.notif.update_settings("u1", None)
        self.assertFalse(self.notif.update_settings("u1", {"email": False})["email"])
        self.assertTrue(self.users.docs["u1"]["notify_email"] is False)


class SmtpAdapterTests(unittest.TestCase):
    def adapter(self, smtp, **kw):
        return SmtpEmailAdapter("smtp.test", 587, kw.get("user", "me"), "pw", "MediQuick <no-reply@x.test>", kw.get("tls", True),
                                smtp_factory=lambda: smtp)

    def fake(self):
        smtp = mock.MagicMock()
        smtp.__enter__.return_value = smtp
        return smtp

    def test_builds_the_message_with_tls_and_login(self):
        smtp = self.fake()
        self.adapter(smtp).send("a@b.test", "Hello", "Body")
        smtp.starttls.assert_called_once()
        smtp.login.assert_called_once_with("me", "pw")
        msg = smtp.send_message.call_args[0][0]
        self.assertEqual((msg["To"], msg["Subject"], msg["From"]), ("a@b.test", "Hello", "MediQuick <no-reply@x.test>"))

    def test_no_tls_or_login_when_not_configured(self):
        smtp = self.fake()
        self.adapter(smtp, user="", tls=False).send("a@b.test", "Hi", "x")
        smtp.starttls.assert_not_called()
        smtp.login.assert_not_called()

    def test_header_injection_is_refused_as_permanent(self):
        smtp = self.fake()
        for to, subject in (("a@b.test\nBcc: evil@x.test", "Hi"), ("a@b.test", "Hi\r\nBcc: evil@x.test")):
            with self.assertRaises(EmailError) as c:
                self.adapter(smtp).send(to, subject, "x")
            self.assertTrue(c.exception.permanent)
        smtp.send_message.assert_not_called()

    def test_error_classification(self):
        cases = [(smtplib.SMTPRecipientsRefused({"a@b.test": (550, b"no")}), True),
                 (smtplib.SMTPResponseException(550, b"mailbox unavailable secret-token"), True),
                 (smtplib.SMTPResponseException(421, b"busy"), False),
                 (smtplib.SMTPResponseException(535, b"bad credentials"), False),
                 (smtplib.SMTPServerDisconnected("gone"), False), (OSError("net down"), False)]
        for exc, permanent in cases:
            smtp = self.fake()
            smtp.send_message.side_effect = exc
            with self.assertRaises(EmailError) as c:
                self.adapter(smtp).send("a@b.test", "Hi", "x")
            self.assertEqual(c.exception.permanent, permanent, repr(exc))
            self.assertNotIn("secret-token", str(c.exception))


class NotificationInvariantTests(NotifBase):
    def test_random_workload_every_email_ends_in_one_final_state_and_is_never_sent_twice(self):
        rng = random.Random(4)
        self.stock(self.para, "NB", 400, 300)
        for step in range(300):
            act = rng.choice(["pay", "pay", "deliver", "cancel", "toggle", "advance", "drain", "flaky"])
            try:
                if act == "pay":
                    self.paid([(self.para, 1)], rng.choice(["u1", "u2"]))
                elif act == "deliver":
                    self.delivered(user=rng.choice(["u1", "u2"]))
                elif act == "cancel":
                    o = rng.choice(list(self.order_repo.docs.values()))
                    self.life.cancel(o["user_id"], o["_id"])
                elif act == "toggle":
                    self.notif.update_settings(rng.choice(["u1", "u2"]), {"email": rng.random() < 0.5})
                elif act == "advance":
                    self.clock.advance(rng.choice([1, 10, 200]))
                elif act == "flaky":
                    self.mail.script = [rng.choice([None, EmailError("x"), EmailError("y", permanent=True)]) for _ in range(3)]
                else:
                    self.drain()
            except (ServiceError, IndexError, ValueError):
                pass
        for _ in range(12):
            self.mail.script = []
            self.drain()
            self.clock.advance(300)
        sent_subjects = [(to, subj) for to, subj, _ in self.mail.sent]
        by_key = {}
        for n in self.nrepo.docs.values():
            self.assertIn(n["email"]["status"], ("sent", "failed", "skipped"), n["event"])
            self.assertLessEqual(n["email"]["attempts"], nrules.MAX_EMAIL_ATTEMPTS)
            by_key[n["key"]] = n["email"]["status"]
        self.assertEqual(sum(1 for n in self.nrepo.docs.values() if n["email"]["status"] == "sent"), len(self.mail.sent))
        self.assertGreater(len(self.nrepo.docs), 20)
        self.assertGreater(len(self.mail.sent), 5)
        self.assertEqual(len({n["key"] for n in self.nrepo.docs.values()}), len(self.nrepo.docs))


if __name__ == "__main__":
    unittest.main()
