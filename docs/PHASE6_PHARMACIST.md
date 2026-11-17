# Phase 6: Pharmacist portal and prescription medicines in orders

> **Only a pharmacist's explicit action approves a prescription.** OCR text and the customer's own list are shown to the pharmacist as unverified hints. Nothing is auto-filled, no substitution logic exists, and the pharmacy role and registration number are NOT verified by this software. This is not production-ready and makes no legal-compliance claim.

## What changed

- **Pharmacist queue** (new pages under **Review** in the top bar): submitted prescriptions, oldest first. Tabs: waiting/in review, claimed by me, waiting for customer, approved, rejected.
- **Review page:** the original file, the customer's list and notes (marked unverified), the automatic text (collapsed), then the actions.
- **Customer side:** the prescription page now shows the outcome: the pharmacist's question (and lets the customer reply), the rejection reason, or the approved medicines with units left and the valid-until date.
- **Orders:** prescription-only products can be added to the cart and ordered **only** within an approved prescription's medicines, quantities and dates.

Statuses: `submitted` > `in_review` (claimed) > `approved` | `rejected` | `clarification_requested` (customer replies and it goes back to `submitted`). There is no way to reach `approved` except the approve action.

## Rules enforced on the backend

| Rule | Where |
|---|---|
| Only role `pharmacist` can claim, approve, reject or ask a question. `pharmacy_manager` and `admin` can view the queue/details and **release** a stuck claim, nothing else. Everyone else: 403. Checked in the HTTP layer and again in the service | `views.py`, `review.py` |
| A decision is an atomic compare-and-set on `status == in_review AND assigned pharmacist == you`, so two pharmacists can never both decide and nobody can decide someone else's claim | `repository.staff_transition` |
| You cannot claim or decide your own prescription | `review.py` |
| You must have **opened the original file after claiming it** before any decision (the server checks its own file-access log) | `review.py` |
| Approval needs: your registration number (format only), a tick that you checked the original, 1-20 medicines you chose from the catalogue (must be prescription-only, active, sellable online), 1-100 units each, and validity days (max `PRESCRIPTION_VALIDITY_DAYS`, default 30) | `review.py` |
| Max 5 prescriptions claimed at once per pharmacist | `review.py` |
| Every staff action (claim, release, approve, reject, clarify) goes into the append-only `prescription_audit` log with a snapshot of what the customer listed; every staff detail/file view goes into `prescription_access` | `review.py`, `services.py` |
| The registration number is shown to staff, never to the customer | `review_block` |

## Prescription medicines in the cart and checkout

- Each approved medicine has `max_quantity` and `remaining`. A cart line for a prescription-only product needs **one** approved, unexpired prescription of that customer whose `remaining` covers the whole quantity. Lines are never split across prescriptions. Problem codes shown in the cart: `prescription_required`, `exceeds_prescription`.
- At checkout the units are taken **atomically** from the earliest-expiring prescription that covers the line (a single MongoDB update with a positional `$inc`), after stock is reserved. If anything later fails, the units are put back and the stock released, and the cart is restored.
- When an unpaid order is **cancelled or expires**, the units are returned **exactly once** (only the caller that wins the status change does it). A paid order keeps them used. Returns after payment are Phase 7.
- The order line stores `prescription_id`, so later phases (packing, dispatch, returns) can verify against it.
- Schedule X stays blocked online whatever a pharmacist approves.

## Commands (from `backend`, venv active)

```powershell
python manage.py check
python manage.py test
python manage.py create_indexes        # adds the review/allowance indexes and refreshes the duplicate-file index
python manage.py runserver
```

To try it you need a pharmacist account. There is still no staff sign-up screen, so make one with the existing command and a *different* email from your customer test account:

```powershell
python manage.py create_staff_user --email pharmacist.test@example.com --name "Test Pharmacist" --role pharmacist
```

(it asks for a password). Then: log in as a customer, upload and submit a prescription; log in as the pharmacist, open **Review**, **Claim**, read the file, add the medicines and quantities, enter a registration number (any 3-30 character test value), tick the confirmation and **Approve**; log back in as the customer, open the Rx product page, add it to the cart and check out. Do all of this with demo data only.

New setting: `PRESCRIPTION_VALIDITY_DAYS` in `backend/.env` (default 30; also the maximum a pharmacist may choose).

## API (`/api/v1/`, all need login)

Customer: `GET prescriptions/allowances/` (approved prescriptions and units left). Existing prescription endpoints now also accept edit/submit/withdraw while `clarification_requested`.

Staff:

| Method | Path | Roles |
|---|---|---|
| GET | `staff/prescriptions/?scope=queue\|mine\|clarification\|approved\|rejected` | pharmacist, pharmacy_manager, admin |
| GET | `staff/prescriptions/<id>/` (logged) | same |
| POST | `.../claim/`, `.../approve/`, `.../reject/`, `.../clarify/` | pharmacist only |
| POST | `.../release/` | pharmacist (own claim), pharmacy_manager, admin |

The file itself is `GET prescriptions/<id>/file/` (staff can open anything that is submitted or decided, never drafts; each open is logged).

## Tests performed (honest summary)

Run in the build sandbox with the standard-library runner and in-memory fakes:

- **261 tests pass** in the runnable suite (41 new in `test_pharmacist_review.py`, covering the review rules, allowances through cart and orders, and a 500-step random test proving, after every step, that each approved item's `remaining` equals its maximum minus the units on live orders, never negative and never over-restored).
- **Mutation checks:** I broke about 25 rules on purpose (role check, own-prescription block, open-the-original check, the claim-ownership guard, attestation, Rx-only and online-only product checks, validity maths, claim limit, release rule, access logging, quantity and expiry checks, restore-on-cancel, rollback on failure, cart quantity check) and a test failed each time. One redundant layer survived by design: the atomic ownership filter in `staff_transition` is also checked earlier, so I added a test that bypasses the earlier check to prove the atomic guard alone stops a race.
- **Real bugs found and fixed by these tests:** (1) a non-text `product_id` such as `{"$ne": 1}` crashed approval validation; (2) `consume(..., True)` took one unit because `True` is an integer in Python.
- Not runnable here, so **written but never executed:** `tests/test_review_api.py` (HTTP, needs Django/DRF) and the real MongoDB queries, in particular the positional/array-filter updates in `repository.py` (`consume_allowance`, `restore_allowance`). Please run `python manage.py test` and try the flow above. These two updates are the first things I would check if something misbehaves.
- The React pages were syntax-checked only, not rendered.

## Known limitations

- Roles and registration numbers are not verified (see COMPLIANCE_CHECKLIST.md). Anyone an admin makes a `pharmacist` can approve.
- One prescription can serve several orders until its approved units run out. Whether that is allowed is a compliance question.
- A customer cannot see or reuse a rejected file as a draft; they upload again.
- A paid order that is later cancelled/returned does not give units back yet (Phase 7).
- No notifications: the customer sees outcomes only when they open the page (Phase 10).
- A pharmacist who abandons a claim blocks it until they or a manager release it (no automatic timeout yet).

## Cleanup note

An earlier, interrupted attempt at this phase had left a half-built, different review design in the working folder (its own status names and test file). I replaced it with this one rather than merging two designs, and kept only two of its safety ideas: the own-prescription block and the must-open-the-original check.

## Next: Phase 7 (order lifecycle: cancel after payment, returns, refunds)
