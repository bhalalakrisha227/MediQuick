# Phase 4: Cart, Checkout, Orders (mock payment)

> **Payment is a MOCK.** No payment gateway is connected and no money is ever charged. The mock refuses to start unless `DJANGO_DEBUG=True`, and every screen that involves it says so. Real payments are Phase 8.

## New commands (from `backend`, venv active)

```powershell
python manage.py test
python manage.py create_indexes               # now also creates order indexes
python manage.py release_expired_reservations # frees stock held by unpaid, expired orders
python manage.py runserver
```

Run `release_expired_reservations` every few minutes in real use (Windows Task Scheduler works; there is no background worker yet). Without it, expiry is still applied whenever anyone checks out, opens an order or the order list, but held stock could look unavailable on product pages until then.

To try it: seed the demo catalogue and inventory (Phase 2-3 commands), register a customer, save an address in **My account**, add an item on a product page, then Cart > Checkout > Place order > **Pay (mock)**. Then log in as the stock clerk and see the batch's on-hand quantity drop.

## Flow

1. **Cart** (server-side, one per user). Adding does not reserve stock. Limits: 10 per product, 30 products. Prescription-only and online-restricted products are rejected.
2. **Place order** `POST /orders/ {address_id}`: claims the cart atomically, re-prices every line, **reserves stock earliest-expiry-first** across batches (all-or-nothing), snapshots prices and the address, and creates an order in `pending_payment` holding the stock for **15 minutes**.
3. **Pay** `POST /orders/<id>/pay/` (mock): on success the held units are deducted batch by batch with a `sale` row in the stock ledger, and the order becomes `confirmed`. A failed payment leaves the order unpaid and the hold in place so the customer can retry until it expires.
4. **Cancel** `POST /orders/<id>/cancel/` (unpaid orders only) or **expiry** frees the hold. Cancelling after payment is Phase 7 (returns/refunds).

Statuses: `pending_payment`, `processing_payment`, `confirmed`, `cancelled`, `expired`, `payment_review`.

## API (all require login; `/api/v1/`)

| Method | Path | Purpose |
|---|---|---|
| GET / DELETE | `cart/` | View (with live problems per line) / empty the cart |
| POST | `cart/items/` | `{product_id, quantity}` |
| PATCH / DELETE | `cart/items/<product_id>/` | Set quantity (0 removes) / remove |
| GET / POST | `orders/` | Your orders / place an order |
| GET | `orders/<id>/` | One of your orders (404 for anyone else's) |
| POST | `orders/<id>/pay/` | Mock payment; `{"simulate": "fail"}` tests the failure path |
| POST | `orders/<id>/cancel/` | Cancel an unpaid order |

## Safety design

- **No double orders:** the cart is claimed with one atomic delete, so a double click or two tabs cannot create two orders. If checkout fails for any reason the cart is restored (without overwriting a cart the shopper rebuilt meanwhile).
- **No overselling:** reservations are atomic conditional updates that only succeed if enough unreserved stock exists in an active batch. Partial failures release everything reserved so far.
- **Exactly-once payment and release:** every status change is an atomic compare-and-set, so an order is paid, cancelled or expired once, and its stock is released once. Paying a confirmed order again returns it unchanged (no second deduction).
- **Prescription gate:** prescription-only (and Schedule X) items cannot enter a cart, and checkout re-checks every line, so a product that became prescription-only after being added blocks the order. Prescription ordering arrives with Phases 5-6.
- **Recalled stock never ships:** if a held batch is quarantined, recalled or expired before payment, payment is refused, the order is cancelled and nothing is charged.
- **Traceability:** each order line records which batches (and batch numbers) supplied it. Customers do not see this; staff views come later.
- **Prices are snapshots:** later price changes never alter an existing order.
- **Failure after payment is never silent:** if stock cannot be committed after a successful charge, the order goes to `payment_review` for a human, not to `confirmed`.

## What is tested

- 38 new tests (117 across all phases), including a randomized run of 600 mixed actions (add, checkout, pay, fail, cancel, time passing, stock adjustments) that checks after every step that: reserved stock equals the open orders' holds, on-hand never goes negative or below reserved, on-hand equals the sum of ledger changes, and units sold equal units on confirmed orders.
- I broke twelve of the rules above on purpose (rollback, cart restore, atomic claim, prescription and restricted checks, expiry check, recall check, release on cancel, cross-user access, ledger writes, idempotent pay, payment claim) and confirmed tests fail each time.
- The HTTP tests in `tests/test_orders_api.py` (including the check that the mock refuses to run when debug is off) need Django and run with `python manage.py test` on your machine.

## Business rules to confirm (`apps/orders/rules.py`)

Engineering defaults, **not verified policy**: 10 units per product, 30 products per order, 15-minute hold, delivery fee 0 (real pricing comes with delivery), no GST/tax breakdown or invoice yet. Selling medicines online has legal conditions in India that must be confirmed professionally before any real sale (see `COMPLIANCE_CHECKLIST.md`).

## Known limits

- **Concurrency is designed in, but my tests cannot run truly parallel requests.** The safety relies on MongoDB's atomic conditional updates. Load-test against Atlas before relying on it.
- **Order status and stock are separate writes**, not one database transaction. A crash between a successful charge and the stock commit would leave an order in `processing_payment` with no recovery job yet (a hardening-phase item, with MongoDB transactions).
- No background scheduler (see the command above).
- Cart edits from two tabs are last-write-wins.
- No delivery serviceability check, delivery fee, tax invoice, coupons, or notifications yet.
- No staff screens for `payment_review` orders yet.
- Frontend code was only syntax-checked, not built or run.
