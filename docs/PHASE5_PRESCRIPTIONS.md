# Phase 5: Prescription upload, OCR and customer review

> **OCR never approves anything.** The text read from an image is a suggestion to save the customer typing. The customer reviews it, then submits it to the pharmacist queue. There is no "approved" status in this phase at all. Approval, rejection and any substitute are a pharmacist's decision in Phase 6.
>
> **Not built yet:** pharmacist screens, approving or rejecting, ordering prescription medicines (Rx products are still blocked at the cart), retention/auto-deletion jobs. This is not production-ready and makes no legal-compliance claim.

## 1. Install Tesseract on Windows (the OCR program)

`pytesseract` (a Python package) only *talks to* the Tesseract program, so the program must be installed separately.

1. Download the Windows installer from the page "Tesseract at UB Mannheim" (search for `UB-Mannheim tesseract wiki` on GitHub) and run it. Keep the default folder `C:\Program Files\Tesseract-OCR`. English (`eng`) language data is included.
2. Open a **new** PowerShell window and check:
   ```powershell
   tesseract --version
   ```
   If it prints a version, you are done.
3. If it says the command is not found, either add `C:\Program Files\Tesseract-OCR` to your PATH (and open a new window), **or** put the full path in `backend\.env`:
   ```
   TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
   ```

If Tesseract is missing, nothing breaks: uploads still work, the screen says automatic reading is unavailable, and the customer can still add medicines by hand and send the original to the pharmacist.

## 2. Install the Python packages and run

From `backend` with the venv active:

```powershell
pip install -r requirements.txt
python manage.py check
python manage.py test
python manage.py create_indexes
python manage.py runserver
```

`create_indexes` now also creates the prescription indexes, including a unique index so the same file cannot be stored twice per customer. Run it once before using the feature.

Jobs run on the in-process thread pool (Phase 0). If the server restarts while a prescription is being read, run this to pick up lost jobs:

```powershell
python manage.py process_pending_prescriptions
```

Frontend: nothing new to install. Open **Prescriptions** in the top bar > **Upload a prescription**.

New `.env` settings are in `backend/.env.example` (`OCR_ENGINE`, `OCR_LANG`, `OCR_TIMEOUT_SECONDS`, `TESSERACT_CMD`, `MAX_PDF_PAGES`, `MAX_IMAGE_MEGAPIXELS`). `MAX_UPLOAD_SIZE_MB` (default 5) is enforced by the server; the upload page's "5 MB" text is a constant in `PrescriptionUploadPage.jsx` and must be edited if you change it.

## 3. Flow

1. **Upload** `POST /prescriptions/` (multipart: `file`, `consent=true`, optional `notes`). The consent box is required. The file is checked **by content** (magic bytes, size, pixel count, PDF active content), stored under a random name in `PRIVATE_STORAGE_DIR` (never served as static/media), and a record is created as `processing`.
2. **OCR in the background**: OpenCV cleans the image (grayscale, resize, denoise, deskew, adaptive threshold), Tesseract reads it, and a parser pulls out *candidate* medicine lines (name guess, strength, dosage like `1-0-1`/`TDS`, duration, quantity only when labelled). A matcher suggests up to 3 catalogue products per line.
3. The record becomes `needs_customer_review` **whether OCR worked, failed or was unavailable**. Nothing is chosen for the customer: the items list starts empty.
4. **Customer review**: the customer adds lines from the suggestions (or by hand), may link a line to a catalogue item (strength mismatches are flagged in red), edits, and saves (`PATCH`).
5. **Submit** `POST /prescriptions/<id>/submit/` moves it to `submitted` (the pharmacist queue; the pharmacist screens come in Phase 6). Submitted prescriptions cannot be edited or withdrawn by the customer.
6. **Withdraw** (before submitting) deletes the file and the OCR text.

Statuses: `processing` > `needs_customer_review` > `submitted`, or `withdrawn`.

## 4. API (all require login; `/api/v1/`)

| Method | Path | Purpose |
|---|---|---|
| GET / POST | `prescriptions/` | Your prescriptions / upload (rate limited: 10 uploads per minute) |
| GET / PATCH | `prescriptions/<id>/` | One of yours (404 for anyone else) / save items and notes |
| POST | `prescriptions/<id>/submit/` | Send to the pharmacist queue |
| POST | `prescriptions/<id>/withdraw/` | Withdraw and delete the file |
| POST | `prescriptions/<id>/retry-ocr/` | Re-run reading after a failure |
| GET | `prescriptions/<id>/file/` | The original file (see access rules) |

**File access rules (backend-enforced):** the owner can always open their file. Pharmacist, pharmacy manager and admin can open it **only after it is submitted**, and each of those opens is written to the `prescription_access` collection (who, when). Everyone else gets 404. Responses use `Content-Disposition: attachment`, `X-Content-Type-Options: nosniff` and `Cache-Control: private, no-store`.

## 5. Limits and rules

- Types: JPEG, PNG, PDF. Max size 5 MB, max 25 megapixels, PDFs read up to 3 pages. PDFs containing `/JavaScript`, `/JS`, `/Launch`, `/EmbeddedFile` or `/RichMedia` are refused (a best-effort byte search, not a virus scanner).
- Max 10 unfinished prescriptions per customer; the same file twice (SHA-256) is refused while the first is active.
- Max 30 items per prescription, notes up to 300 characters, OCR text kept up to 20,000 characters.
- A catalogue product linked to a line must exist and be active; the server stores the product name at that moment.
- The OCR job is claimed atomically, so it cannot run twice. A job stuck "running" for 10 minutes can be retried.

## 6. Tests performed (honest summary)

Run in the build sandbox with the Python standard library test runner, in-memory fakes and a temporary folder:

- **103 new tests, all passing; whole runnable suite 220 passing.**
- Upload validation (valid PNG/JPEG/PDF, spoofed types, truncated/corrupt images, pixel bombs, PDF active content, 5,000 randomly corrupted files never crash it); storage (round trip, never overwrites, path traversal, symlink escape, bad ids).
- Parser and matcher (typical prescription lines, non-medicine lines skipped, garbage fuzzing, timing check against slow-regex inputs, strength mismatch flagged and score-capped, inactive products never suggested).
- **Real OpenCV + Tesseract runs** on computer-generated images of typed text (clean and slightly tilted) in the sandbox. That is *not* a measure of accuracy on real prescriptions.
- Service rules with fakes: consent, duplicates, draft limit, OCR success/failure/unavailable/crash all ending in customer review, double-run prevention, withdraw-during-OCR, owner isolation, staff file access and logging, and a 600-step random state-machine test (statuses stay valid, files on disk always equal the non-withdrawn records).
- **Mutation checks:** I deliberately broke 26 small rules (size limit, type check, PDF check, pixel limit, traversal guard, no-overwrite, owner scoping, staff-access rule, staff logging, duplicate guard, draft limit, consent, OCR claim, submit/withdraw states, OCR-must-not-submit) and confirmed a test fails for each. Three mutants survived because they are redundant safety layers (a second `..` check, a pre-check that the unique index also covers, and a "high confidence" condition already prevented by the score cap).
- One real bug was found and fixed by these tests: an empty/undecodable image raised a raw OpenCV error instead of a clean OCR failure.

## 7. NOT verified (please run these on your machine)

- `python manage.py test` for the new HTTP tests (`tests/test_prescriptions_api.py`) and the real MongoDB repository: Django, DRF and PyMongo cannot be installed in the build sandbox, so these were only syntax-checked.
- The React pages were syntax-checked only (not rendered in a browser).
- OCR on **real photos of prescriptions** (handwriting, phone photos, stamps): not tested at all. Expect Tesseract to do poorly on handwriting; that is why a human always reviews. No accuracy figure is claimed.
- The sandbox used OpenCV 5.0; your install will use 4.x or newer. Only functions common to both are used, but this is untested on 4.x.
- PDF reading (PyMuPDF) was tested only with an injected fake renderer, since PyMuPDF is not installed in the sandbox.
- Windows file permissions: files are created owner-only on Linux/macOS; on Windows `chmod` has little effect, so protect the storage folder with normal folder permissions.

## 8. Known limitations and honest notes

- **No encryption at rest, no malware scanning, no retention/auto-delete job.** Listed in `COMPLIANCE_CHECKLIST.md`.
- The consent wording is a placeholder that needs legal review.
- The thread-pool job runner loses jobs on restart (use the command above). Several server processes would each run their own pool (the atomic claim keeps results correct).
- The medicine parser is deliberately conservative and English/Latin-script only; bare lines like just "Paracetamol" are not treated as medicine lines.
- Matching is name-based. A suggestion is never a substitution: a different strength is flagged, never offered as equivalent.

## 9. Next: Phase 6 (pharmacist portal) - built, see PHASE6_PHARMACIST.md

Pharmacist queue of submitted prescriptions, viewing the original with the customer's list, approve / reject with reason / ask for clarification, all audited; linking an approved prescription to an Rx order line. Only then do prescription medicines become orderable.
