# Phase 7: Cancel after payment, returns and refunds

> **Payments and refunds are still a MOCK.** No gateway is connected and no money moves. "Dispatched" and "delivered" are set **by hand** by pharmacy staff until delivery is built (Phase 9); the screens say so. The return rules below are engineering placeholders, not verified legal rules. This is not production-ready and makes no legal-compliance claim.

## What changed

- **Customer cancels a paid order** (button on the order page, only while the order is still `confirmed`, i.e. before dispatch): the units go back on the shelf (ledger row per batch), prescription units are given back, and the full amount is refunded. This happens exactly once.
- **Manual fulfilment** (new staff page **Fulfilment**): `pharmacy_manager` / `admin` mark a paid order *dispatched*, then *delivered*. After dispatch the customer can no longer cancel.
- **Returns** (order page, only after *delivered*): a customer can ask to return items within **2 days** of delivery, only for a fixed set of reasons (wrong item, damaged, expired item, missing item). **"I changed my mind" is not accepted.** One open request per order; quantities are capped by what was delivered. `support_agent`, `pharmacy_manager` or `admin` approve or reject (reject needs a reason).
- **Refunds**: an approved return refunds **the item price only** (not delivery). **Returned medicine is never put back on sale and prescription units are not restored.**
- **Failed refunds** stay visible to staff (Fulfilment page) and can be retried, one retry at a time.

Order statuses now: `pending_payment`, `processing_payment`, `confirmed`, `dispatched`, `delivered`, `cancelled`, `expired`, `payment_review`. The payment label on an order becomes `partially_refunded` / `refunded` from the refund counter.

## Commands (from `backend`, venv active)

```powershell
python manage.py check
python manage.py test
python manage.py create_indexes     # adds returns/refunds indexes (unique refund key, one open return per order)
python manage.py runserver
```

To try it (demo data only): seed catalogue + inventory, place and mock-pay an order as a customer, then **Cancel order and refund** (or) log in as a manager (`python manage.py create_staff_user --email manager.test@example.com --name "Test Manager" --role pharmacy_manager`), open **Fulfilment**, mark it dispatched then delivered, log back in as the customer, request a return, then approve it as the manager (or a `support_agent`).

## Rules enforced on the backend

| Rule | Where |
|---|---|
| Paid cancel is an atomic `confirmed -> cancelled` change; only the winner restocks, restores prescription units and refunds | `lifecycle.cancel` |
| Restocking exists only for paid-but-undispatched cancellations; returns never restock | `lifecycle.py`, `reservations.restock` |
| A refund has a unique key `(order, kind, source)`: asking twice gives the same refund, never two | `refunds.issue`, unique index |
| Total refunded can never exceed what was paid: one atomic conditional update on the order | `repository.reserve_refund` |
| Provider failure or exception puts the counter back and keeps a `failed` refund for staff | `refunds._attempt` |
| Retrying a failed refund is claimed atomically so two staff cannot both send money | `repository.claim_retry` |
| Only `pharmacy_manager`/`admin` dispatch, deliver or retry refunds; only `support_agent`/`pharmacy_manager`/`admin` decide returns; everyone else 403 (HTTP layer and service) | `views.py`, `lifecycle.py` |
| A return is decided once (atomic `requested -> approved/rejected`) | `ReturnRepository.decide` |
| The customer never sees which staff member decided | `public_return` |

## API (`/api/v1/`, login required)

Customer: `POST orders/<id>/cancel/` (now also paid orders; response includes `refund`), `GET/POST orders/<id>/returns/`.
Staff: `GET staff/orders/`, `POST staff/orders/<id>/dispatch|deliver/`, `GET staff/returns/?status=`, `POST staff/returns/<id>/decision/ {decision, note}`, `GET staff/refunds/` (failed), `POST staff/refunds/<id>/retry/`.

## Tests performed (honest summary)

Standard-library runner with in-memory fakes in the build sandbox:

- **295 tests pass** in the runnable suite (34 new in `test_order_lifecycle.py`): cancel/restock/refund once, lost races, provider failure and exception, restock failure flag, prescription units on cancel and not on return, fulfilment roles and state machine, return window/reasons/quantity caps/one-open rule, decision roles and once-only, money-only refunds, idempotent refunds, the "never more than paid" cap, and a 500-step random test checking after every step that refunded amounts equal the sum of successful refunds and never exceed the total, the stock ledger balances for every batch, and prescription units left equal the maximum minus units on live orders.
- **Mutation checks:** I broke 19 rules on purpose (cancel race guard, restock, prescription restore, delivered-only and window checks, reason and quantity checks, approved-quantity accounting, both role gates, decide-once, refund-on-approve, idempotency, the refund cap, counter put-back, retry claim, restock amount) and a test failed each time. One survived by design: the "one open return" pre-check is duplicated by the database's unique index, which another test covers.
- **Not run here (written only):** `tests/test_lifecycle_api.py` and the updated `tests/test_orders_api.py` (need Django/DRF), and the real MongoDB queries, most importantly `reserve_refund` (an `$expr` conditional `$inc`) and the two partial unique indexes. Please run `python manage.py test` and the flow above.
- React pages were syntax-checked only.

## Known limitations

- **Manual dispatch/delivery** only; no delivery partner, tracking, failed delivery or return pickup.
- Return rules (2-day window, reasons, price-only refund, no restock) are placeholders to be set by the pharmacy and a compliance reviewer.
- A returned medicine is simply not restocked; there is no quarantine/destruction record yet.
- If restocking fails halfway during a paid cancel, the order is flagged `needs_attention = restock_failed` in the database but no screen lists these yet.
- Orders in `payment_review` (money taken, stock commit failed) still have no resolution flow.
- No notifications; customers see refund status only when they open the order.
- Orders paid before this phase have no `refunded_paise` field; the refund query treats it as 0.
- Real refunds need the Phase 8 payment adapter and its own idempotency/reconciliation.

## Next: Phase 8 (real payment adapter behind the same interface, webhooks, reconciliation)
