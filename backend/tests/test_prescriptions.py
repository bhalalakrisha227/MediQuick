import random
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apps.accounts.errors import ServiceError
from apps.catalogue.services import CatalogueService
from apps.prescriptions import rules
from apps.prescriptions.ocr.engines.base import OcrResult
from apps.prescriptions.ocr.errors import OcrError, OcrUnavailable
from apps.prescriptions.services import PrescriptionService, safe_filename
from apps.prescriptions.storage import FileStorage

from .fakes import FakeCategories, FakePrescriptions, FakeProducts
from .test_prescription_files import PDF, make_jpeg, make_png

LINES = [{"text": "Dr. Asha Rao", "confidence": 90.0},
         {"text": "1. Tab Paracetamol 500mg 1-0-1 x 5 days", "confidence": 88.0},
         {"text": "2. Cap Amoxicillin 250mg TDS", "confidence": 71.0}]


class Clock:
    def __init__(self):
        self.now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now


class FakeEngine:
    name = "fake"


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "private"
        self.clock = Clock()
        self.repo = FakePrescriptions()
        self.storage = FileStorage(self.root)
        self.products = FakeProducts()
        cat = CatalogueService(FakeCategories(), self.products, self.clock)
        cat.create_category({"name": "Pain & Fever"})
        self.para = cat.create_product({"name": "Paracetamol 500 mg Tablets", "category": "pain-fever", "pack_size": "Strip",
                                        "price_paise": 3000, "mrp_paise": 3500, "schedule": "OTC"})["id"]
        self.scheduled = []
        self.mode = "ok"
        self.runs = 0
        self.svc = self.make()

    def runner(self, data, kind, engine, **kw):
        self.runs += 1
        if self.mode == "unavailable":
            raise OcrUnavailable("no tesseract")
        if self.mode == "fail":
            raise OcrError("bad image")
        if self.mode == "crash":
            raise RuntimeError("boom")
        return OcrResult("\n".join(l["text"] for l in LINES), LINES, "fake")

    def make(self, **kw):
        return PrescriptionService(self.repo, self.storage, self.products, FakeEngine(), clock=self.clock,
                                   schedule=self.scheduled.append, ocr_runner=self.runner, max_bytes=1024 * 1024, **kw)

    def upload(self, user="u1", data=None, consent=True, **fields):
        return self.svc.upload(user, data or make_png(4, 3), "../../my rx?.png", {"consent": consent, **fields})

    def ready(self, user="u1", data=None):
        pid = self.upload(user, data)["id"]
        self.svc.process(pid)
        return pid

    def disk_files(self):
        return {
            p.relative_to(self.root).as_posix()
            for p in self.root.rglob("*")
            if p.is_file()
            }

    def code(self, fn, *a):
        with self.assertRaises(ServiceError) as c:
            fn(*a)
        return c.exception.code


class UploadTests(Base):
    def test_upload_creates_processing_record_and_schedules_ocr(self):
        p = self.upload(notes="  for fever ")
        self.assertEqual((p["status"], p["notes"], p["editable"]), ("processing", "for fever", False))
        self.assertEqual(self.scheduled, [p["id"]])
        self.assertEqual(p["file"]["original_name"], "my rx.png")
        self.assertNotIn("path", str(p["file"]))
        self.assertNotIn("sha256", str(p))
        self.assertEqual(len(self.disk_files()), 1)

    def test_consent_required(self):
        for bad in (False, None, "no", "false", 0, ""):
            with self.subTest(bad):
                self.assertEqual(self.code(self.svc.upload, "u1", make_png(), "a.png", {"consent": bad}), "consent_required")
        self.assertEqual(self.disk_files(), set())

    def test_consent_recorded_with_version(self):
        self.upload()
        d = next(iter(self.repo.docs.values()))
        self.assertEqual(d["consent"]["version"], rules.CONSENT_VERSION)

    def test_invalid_files_store_nothing(self):
        for data in (b"", b"MZ" + b"0" * 50, PDF + b"/JavaScript", make_png(30000, 30000), b"x" * (1024 * 1024 + 1)):
            with self.subTest(data[:8]):
                with self.assertRaises(ServiceError) as c:
                    self.svc.upload("u1", data, "x", {"consent": True})
                self.assertEqual(c.exception.status, 400)
        self.assertEqual((self.disk_files(), self.repo.docs), (set(), {}))

    def test_bad_notes(self):
        self.assertEqual(self.code(self.svc.upload, "u1", make_png(), "a", {"consent": True, "notes": "x" * 301}), "validation_error")
        self.assertEqual(self.code(self.svc.upload, "u1", make_png(), "a", {"consent": True, "notes": 5}), "validation_error")

    def test_duplicate_file_rejected_per_user_only(self):
        self.upload("u1", make_png(5, 5))
        self.assertEqual(self.code(self.svc.upload, "u1", make_png(5, 5), "a", {"consent": True}), "duplicate_file")
        self.upload("u2", make_png(5, 5))
        self.assertEqual(len(self.disk_files()), 2)

    def test_duplicate_race_cleans_up_file(self):
        self.upload("u1", make_png(5, 5))
        self.repo.find_active_by_hash = lambda *a: None      # simulate losing the race: the unique index fires instead
        self.assertEqual(self.code(self.svc.upload, "u1", make_png(5, 5), "a", {"consent": True}), "duplicate_file")
        self.assertEqual(len(self.disk_files()), 1)

    def test_withdrawn_file_can_be_uploaded_again(self):
        pid = self.upload("u1", make_png(5, 5))["id"]
        self.svc.withdraw("u1", pid)
        self.upload("u1", make_png(5, 5))

    def test_draft_limit(self):
        for i in range(rules.MAX_DRAFTS):
            self.upload("u1", make_png(4 + i, 3))
        self.assertEqual(self.code(self.svc.upload, "u1", make_png(40, 3), "a", {"consent": True}), "too_many_drafts")
        self.upload("u2")

    def test_submitted_do_not_count_towards_draft_limit(self):
        for i in range(rules.MAX_DRAFTS):
            pid = self.ready("u1", make_png(4 + i, 3))
            self.svc.submit("u1", pid)
        self.upload("u1", make_png(60, 3))

    def test_storage_failure_creates_no_record(self):
        self.storage.save = lambda *a: (_ for _ in ()).throw(OSError("disk full"))
        self.assertEqual(self.code(self.svc.upload, "u1", make_png(), "a", {"consent": True}), "storage_error")
        self.assertEqual(self.repo.docs, {})

    def test_scheduler_failure_does_not_fail_upload(self):
        def boom(_):
            raise RuntimeError("queue down")
        self.svc.schedule = boom
        self.assertEqual(self.upload()["status"], "processing")

    def test_safe_filename(self):
        for raw, want in [("../../etc/passwd", "passwd"), ("C:\\x\\rx.jpg", "rx.jpg"), ("a<b>.png", "ab.png"), ("", "prescription"),
                          (None, "prescription"), ("...", "prescription"), ("x" * 200 + ".png", ("x" * 200)[:80])]:
            self.assertEqual(safe_filename(raw), want)

    def test_jpeg_and_pdf_accepted(self):
        self.upload("u1", make_jpeg())
        self.upload("u1", PDF)


class PipelineTests(Base):
    def test_success_goes_to_customer_review_with_candidates(self):
        pid = self.upload()["id"]
        self.assertTrue(self.svc.process(pid))
        p = self.svc.get("u1", pid)
        self.assertEqual((p["status"], p["ocr"]["status"], p["editable"]), ("needs_customer_review", "done", True))
        names = [c["name_guess"] for c in p["ocr"]["candidates"]]
        self.assertEqual(names, ["Paracetamol", "Amoxicillin"])
        top = p["ocr"]["candidates"][0]["suggestions"][0]
        self.assertEqual((top["product_id"], top["strength_match"]), (self.para, True))
        self.assertEqual(p["items"], [])            # nothing is pre-selected on the customer's behalf

    def test_ocr_never_submits_or_approves(self):
        pid = self.upload()["id"]
        self.svc.process(pid)
        self.assertNotIn(self.repo.docs[pid]["status"], ("submitted", "approved"))
        self.assertNotIn("submitted_at", self.repo.docs[pid])

    def test_failure_modes_still_reach_review(self):
        for mode, expected in (("fail", "failed"), ("unavailable", "unavailable"), ("crash", "failed")):
            with self.subTest(mode):
                self.mode = mode
                pid = self.upload("u1", make_png(10 + len(mode), 3))["id"]
                self.svc.process(pid)
                p = self.svc.get("u1", pid)
                self.assertEqual((p["status"], p["ocr"]["status"], p["editable"]), ("needs_customer_review", expected, True))
                self.svc.submit("u1", pid)          # manual reading by the pharmacist remains possible

    def test_claim_prevents_double_run(self):
        pid = self.upload()["id"]
        self.assertTrue(self.svc.process(pid))
        self.assertFalse(self.svc.process(pid))
        self.assertEqual(self.runs, 1)

    def test_concurrent_claim_only_one_wins(self):
        pid = self.upload()["id"]
        claims = [self.repo.claim_ocr(pid, self.clock(), self.clock() - timedelta(minutes=10)) for _ in range(5)]
        self.assertEqual(sum(1 for c in claims if c), 1)

    def test_stale_running_job_can_be_reclaimed(self):
        pid = self.upload()["id"]
        self.repo.claim_ocr(pid, self.clock(), self.clock() - timedelta(minutes=10))     # worker "dies" while running
        self.assertFalse(self.svc.process(pid))
        self.clock.now += timedelta(minutes=11)
        self.assertEqual(self.svc.recover_pending(), 1)
        self.assertEqual(self.repo.docs[pid]["status"], "needs_customer_review")

    def test_recover_pending_runs_lost_jobs(self):
        a, b = self.upload("u1", make_png(5, 5))["id"], self.upload("u2", make_png(6, 5))["id"]
        self.assertEqual(self.svc.recover_pending(), 2)
        self.assertEqual({self.repo.docs[a]["status"], self.repo.docs[b]["status"]}, {"needs_customer_review"})
        self.assertEqual(self.svc.recover_pending(), 0)

    def test_withdrawn_while_processing_is_not_resurrected(self):
        pid = self.upload()["id"]
        self.svc.withdraw("u1", pid)
        self.assertFalse(self.svc.process(pid))
        self.assertEqual(self.repo.docs[pid]["status"], "withdrawn")

    def test_withdraw_during_run_wins(self):
        pid = self.upload()["id"]
        orig = self.runner

        def run_and_withdraw(*a, **k):
            self.svc.withdraw("u1", pid)
            return orig(*a, **k)
        self.svc.ocr_runner = run_and_withdraw
        self.svc.process(pid)
        self.assertEqual(self.repo.docs[pid]["status"], "withdrawn")

    def test_retry_only_after_failure(self):
        self.mode = "fail"
        pid = self.ready()
        self.mode = "ok"
        p = self.svc.retry_ocr("u1", pid)
        self.assertEqual(p["status"], "processing")
        self.assertIn(pid, self.scheduled)
        self.svc.process(pid)
        self.assertEqual(self.svc.get("u1", pid)["ocr"]["status"], "done")
        self.assertEqual(self.code(self.svc.retry_ocr, "u1", pid), "cannot_retry")

    def test_retry_while_processing_is_refused_unless_stuck(self):
        pid = self.upload()["id"]
        self.assertEqual(self.code(self.svc.retry_ocr, "u1", pid), "still_processing")

    def test_retry_other_users_prescription_is_404(self):
        self.mode = "fail"
        pid = self.ready("u1")
        self.assertEqual(self.code(self.svc.retry_ocr, "u2", pid), "not_found")

    def test_ocr_text_capped(self):
        self.svc.ocr_runner = lambda *a, **k: OcrResult("A" * 50_000, [{"text": "B" * 900, "confidence": 1}] * 500, "fake")
        pid = self.ready()
        o = self.repo.docs[pid]["ocr"]
        self.assertEqual(len(o["text"]), rules.MAX_OCR_TEXT)
        self.assertEqual(len(o["lines"]), rules.MAX_OCR_LINES)
        self.assertTrue(all(len(l["text"]) <= 200 for l in o["lines"]))


class ReviewTests(Base):
    def items(self, **over):
        return [{"name": "Paracetamol", "strength": "500 mg", "dosage": "1-0-1", "duration": "5 days", "quantity": 10,
                 "product_id": self.para, **over}]

    def test_update_items_and_notes(self):
        pid = self.ready()
        p = self.svc.update("u1", pid, {"items": self.items(), "notes": "hello"})
        self.assertEqual(p["items"][0]["product_name"], "Paracetamol 500 mg Tablets")
        self.assertEqual(p["notes"], "hello")

    def test_update_replaces_all_items(self):
        pid = self.ready()
        self.svc.update("u1", pid, {"items": self.items()})
        self.assertEqual(self.svc.update("u1", pid, {"items": []})["items"], [])

    def test_free_text_item_without_product_is_fine(self):
        pid = self.ready()
        p = self.svc.update("u1", pid, {"items": [{"name": "Some Syrup"}]})
        self.assertIsNone(p["items"][0]["product_id"])

    def test_validation(self):
        pid = self.ready()
        bad = [{"items": "x"}, {"items": [{"name": ""}]}, {"items": [{"name": "A"}]}, {"items": ["x"]},
               {"items": [{"name": "Okay", "quantity": 0}]}, {"items": [{"name": "Okay", "quantity": True}]},
               {"items": [{"name": "Okay", "quantity": 1000}]}, {"items": [{"name": "Okay", "strength": "x" * 41}]},
               {"items": [{"name": "Okay", "product_id": "nope"}]}, {"items": [{"name": "Okay", "product_id": 5}]},
               {"items": [{"name": "Okay"}] * 31}, {"notes": "x" * 301}, {}]
        for data in bad:
            with self.subTest(str(data)[:40]):
                self.assertEqual(self.code(self.svc.update, "u1", pid, data), "validation_error")
        self.assertEqual(self.repo.docs[pid]["items"], [])

    def test_inactive_product_rejected(self):
        pid = self.ready()
        self.products.docs[self.para]["is_active"] = False
        self.assertEqual(self.code(self.svc.update, "u1", pid, {"items": self.items()}), "validation_error")

    def test_cannot_edit_while_processing_or_after_submit(self):
        pid = self.upload()["id"]
        self.assertEqual(self.code(self.svc.update, "u1", pid, {"notes": "x"}), "not_editable")
        self.svc.process(pid)
        self.svc.submit("u1", pid)
        self.assertEqual(self.code(self.svc.update, "u1", pid, {"notes": "x"}), "not_editable")

    def test_submit_flow(self):
        pid = self.ready()
        self.svc.update("u1", pid, {"items": self.items()})
        p = self.svc.submit("u1", pid)
        self.assertEqual((p["status"], p["editable"]), ("submitted", False))
        self.assertIsNotNone(p["submitted_at"])
        self.assertEqual(self.code(self.svc.submit, "u1", pid), "cannot_submit")

    def test_cannot_submit_while_processing(self):
        pid = self.upload()["id"]
        self.assertEqual(self.code(self.svc.submit, "u1", pid), "cannot_submit")

    def test_submit_withdraw_rules(self):
        pid = self.ready()
        self.svc.submit("u1", pid)
        self.assertEqual(self.code(self.svc.withdraw, "u1", pid), "cannot_withdraw")
        self.assertEqual(len(self.disk_files()), 1)

    def test_withdraw_deletes_file_and_scrubs_text(self):
        pid = self.ready()
        self.svc.update("u1", pid, {"items": self.items()})
        p = self.svc.withdraw("u1", pid)
        self.assertEqual((p["status"], p["ocr"]["text"], p["items"]), ("withdrawn", "", []))
        self.assertEqual(self.disk_files(), set())
        self.assertEqual(self.code(self.svc.withdraw, "u1", pid), "cannot_withdraw")

    def test_withdraw_succeeds_even_if_file_delete_fails(self):
        pid = self.ready()
        self.storage.delete = lambda p: (_ for _ in ()).throw(OSError("locked"))
        self.assertEqual(self.svc.withdraw("u1", pid)["status"], "withdrawn")


class IsolationAndFileAccessTests(Base):
    def test_other_users_cannot_see_or_change(self):
        pid = self.ready("u1")
        for fn, args in ((self.svc.get, ()), (self.svc.update, ({"notes": "x"},)), (self.svc.submit, ()), (self.svc.withdraw, ())):
            with self.subTest(fn.__name__):
                self.assertEqual(self.code(fn, "u2", pid, *args), "not_found")
        self.assertEqual(self.svc.list("u2")["results"], [])
        self.assertEqual(self.repo.docs[pid]["status"], "needs_customer_review")

    def test_unknown_ids_404(self):
        for pid in ("nope", "", None, {"$ne": 1}, 5):
            self.assertEqual(self.code(self.svc.get, "u1", pid), "not_found")

    def test_list_summary_hides_ocr_text_and_withdrawn(self):
        a = self.ready("u1", make_png(5, 5))
        b = self.ready("u1", make_png(6, 5))
        self.svc.withdraw("u1", b)
        rows = self.svc.list("u1")["results"]
        self.assertEqual([r["id"] for r in rows], [a])
        self.assertNotIn("ocr", rows[0])

    def test_owner_gets_file(self):
        data = make_png(7, 7)
        pid = self.ready("u1", data)
        body, ctype, name = self.svc.file_for("u1", "customer", pid)
        self.assertEqual((body, ctype, name), (data, "image/png", "my rx.png"))
        self.assertEqual(self.repo.access, [])

    def test_other_customer_cannot_get_file(self):
        pid = self.ready("u1")
        self.assertEqual(self.code(self.svc.file_for, "u2", "customer", pid), "not_found")

    def test_staff_cannot_get_unsubmitted_file(self):
        pid = self.ready("u1")
        for role in rules.STAFF_FILE_ROLES:
            self.assertEqual(self.code(self.svc.file_for, "s1", role, pid), "not_found")
        self.assertEqual(self.repo.access, [])

    def test_staff_can_get_submitted_file_and_it_is_logged(self):
        pid = self.ready("u1")
        self.svc.submit("u1", pid)
        for role in rules.STAFF_FILE_ROLES:
            self.svc.file_for("s1", role, pid)
        self.assertEqual([a["actor_role"] for a in self.repo.access], list(rules.STAFF_FILE_ROLES))
        self.assertTrue(all(a["prescription_id"] == pid and a["action"] == "view_file" for a in self.repo.access))

    def test_non_pharmacy_staff_cannot_get_file_even_if_submitted(self):
        pid = self.ready("u1")
        self.svc.submit("u1", pid)
        for role in ("inventory_staff", "delivery_partner", "support_agent", "customer", ""):
            self.assertEqual(self.code(self.svc.file_for, "s1", role, pid), "not_found")

    def test_withdrawn_file_is_gone_for_everyone(self):
        pid = self.ready("u1")
        self.svc.withdraw("u1", pid)
        self.assertEqual(self.code(self.svc.file_for, "u1", "customer", pid), "not_found")

    def test_missing_file_on_disk_is_404(self):
        pid = self.ready("u1")
        for f in self.root.rglob("*.png"):
            f.unlink()
        self.assertEqual(self.code(self.svc.file_for, "u1", "customer", pid), "not_found")

    def test_tampered_stored_path_cannot_escape(self):
        pid = self.ready("u1")
        secret = Path(self._tmp.name) / "secret.txt"
        secret.write_text("x")
        self.repo.docs[pid]["file"]["path"] = "../secret.txt"
        self.assertEqual(self.code(self.svc.file_for, "u1", "customer", pid), "not_found")
        self.svc.withdraw("u1", pid)
        self.assertTrue(secret.exists())


class StateMachineInvariantTests(Base):
    def test_random_operations_keep_invariants(self):
        rnd = random.Random(99)
        users = ["u1", "u2", "u3"]
        known = []
        allowed = {"processing", "needs_customer_review", "submitted", "withdrawn"}
        for step in range(600):
            op = rnd.choice(["upload", "process", "update", "submit", "withdraw", "retry", "file", "mode", "staff"])
            user = rnd.choice(users)
            pid = rnd.choice(known)[0] if known else "x"
            try:
                if op == "upload":
                    known.append((self.upload(user, make_png(rnd.randint(3, 40), rnd.randint(3, 40)))["id"], user))
                elif op == "process":
                    self.svc.process(pid)
                elif op == "update":
                    self.svc.update(user, pid, {"notes": "n"})
                elif op == "submit":
                    self.svc.submit(user, pid)
                elif op == "withdraw":
                    self.svc.withdraw(user, pid)
                elif op == "retry":
                    self.svc.retry_ocr(user, pid)
                elif op == "file":
                    self.svc.file_for(user, "customer", pid)
                elif op == "staff":
                    self.svc.file_for("s", "pharmacist", pid)
                else:
                    self.mode = rnd.choice(["ok", "fail", "unavailable"])
            except ServiceError:
                pass
            for d in self.repo.docs.values():
                self.assertIn(d["status"], allowed)
                if d["status"] == "submitted":
                    self.assertEqual(d["status_history"][-1]["status"], "submitted")
                    self.assertIn("needs_customer_review", [h["status"] for h in d["status_history"]])
            # submitted records are never withdrawn/changed: history of a submitted record never contains 'withdrawn'
            for d in self.repo.docs.values():
                if d.get("submitted_at"):
                    self.assertNotIn("withdrawn", [h["status"] for h in d["status_history"]])
            on_disk = self.disk_files()
            expected = {d["file"]["path"] for d in self.repo.docs.values() if d["status"] != "withdrawn"}
            self.assertEqual(on_disk, expected)
        self.assertGreater(len(known), 20)
        self.assertTrue(any(d["status"] == "submitted" for d in self.repo.docs.values()))


if __name__ == "__main__":
    unittest.main()
