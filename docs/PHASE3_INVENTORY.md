# Phase 3: Inventory (batches, expiry, stock movements, availability)

## New commands (from `backend`, venv active)

```powershell
python manage.py test
python manage.py create_indexes        # now also creates inventory indexes
python manage.py seed_demo_catalogue   # if you have not already
python manage.py seed_demo_inventory   # labelled DEMO batches (safe to repeat)
python manage.py runserver
```

To try the staff screen, create a staff login (you will be prompted for a password):

```powershell
python manage.py create_staff_user --email stock@example.com --name "Stock Clerk" --role inventory_staff
python manage.py create_staff_user --email manager@example.com --name "Test Manager" --role pharmacy_manager
```

Log in at http://localhost:5173/login and open **Inventory** in the top bar (`/staff/inventory`).

## Concepts

- **Batch:** one received lot of one product: batch number, expiry date, quantity received, quantity on hand, quantity reserved (used by checkout in Phase 4), status.
- **Stock movement (ledger):** an append-only record of every change (receipt, adjustment, status change) with who did it, when, the reason, and the quantity after. Nothing edits or deletes ledger rows.
- **Sellable stock:** units in batches that are `active`, have at least 30 days of shelf life left, and are not reserved. Expired, quarantined, recalled and near-expiry batches never count.
- **FEFO:** batches are listed earliest-expiry-first, and the earliest expiry among sellable stock is what customers see.

## Staff API (`/api/v1/`, enforced on the backend)

| Method | Path | Roles | Purpose |
|---|---|---|---|
| GET | `inventory/overview/` | inventory_staff, pharmacy_manager, admin, pharmacist | Expired-with-stock, expiring soon, low/out of stock |
| GET | `inventory/batches/` | same four (read) | List batches: `state` = all / in_stock / expiring / expired, `product_id`, `status`, `page`, `page_size` |
| POST | `inventory/batches/` | inventory_staff, pharmacy_manager, admin | Receive stock (creates batch + ledger entry) |
| POST | `inventory/batches/<id>/adjust/` | same three | `delta` (+/-), `reason`, `note` |
| POST | `inventory/batches/<id>/status/` | same three; **recall / un-recall: pharmacy_manager, admin only** | active / quarantined / recalled, with a required note |
| GET | `inventory/batches/<id>/movements/` | four read roles | Ledger history, newest first |

Adjustment reasons: `stock_count`, `correction` (note required), `damage`, `expired_writeoff`, `returned_to_supplier` (the last three must reduce stock).

## Public availability

`GET products/` and `GET products/<slug>/` now return `availability`:
`{"status": "in_stock" | "low_stock" | "out_of_stock", "earliest_expiry": "YYYY-MM-DD" | null}`.
Exact quantities are never exposed to the public. `availability` is `null` only if no inventory source is connected. Listings fetch availability for the whole page in one query, not one per product.

## Safety properties (and how they are tested)

- Stock changes use one atomic conditional database update that refuses to go below zero or below the reserved quantity, so two simultaneous clerks cannot oversell a batch.
- Every successful change writes a ledger row, and a refused change writes nothing. A randomized test runs 300 operations (many refused) and checks that on-hand quantity always equals the sum of ledger changes and never drops below zero or reserved.
- Expired stock cannot be received. Duplicate batch numbers per product are rejected (unique index).
- Several of these tests were checked by deliberately breaking the rule and confirming a test fails.

## Business rules to confirm (in `apps/inventory/rules.py`)

These are engineering defaults, **not verified policy**. Confirm with your pharmacist or pharmacy manager, and with legal advice for expiry and recall handling:

| Setting | Default |
|---|---|
| Minimum shelf life to sell | 30 days |
| Low-stock threshold | 10 sellable units |
| "Expiring soon" window | 60 days |
| Who may recall a batch | pharmacy_manager, admin |

## Known limits

- The stock change and its ledger row are two separate writes. If the server dies between them, the ledger could miss an entry. MongoDB transactions (available on Atlas) would close this gap and are a hardening-phase item. A reconciliation report is also planned.
- Reservations (`quantity_reserved`) are created and consumed by checkout (Phase 4, see `PHASE4_CART_ORDERS.md`) and respected by all stock rules.
- Low-stock alerts consider up to 500 active products, and the product picker on the receive form shows up to 50 matches.
- There are no purchase prices, supplier records, barcode scanning or stock-take workflows yet.
- Frontend code could only be syntax-checked in my environment, not built or run.
