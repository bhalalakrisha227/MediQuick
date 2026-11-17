# Phase 11 - Admin dashboard

## Honest status
- Numbers come from the app's own database. With mock payments they are **demo numbers**; the dashboard says so.
- Reports read up to 20,000 orders in Python and say when they were cut short. Fine for a small shop, **not** a real analytics system.
- Django HTTP tests and the React page could not be run in the build sandbox. The Mongo queries (`$group`, `$type` filters, projections) are untested on a real MongoDB.
- This is not an accounting or tax tool. Gross/net here are not GST or accounting figures.

## Who can do what
| Screen | pharmacy_manager | admin |
|---|---|---|
| Overview (sales, delivery, stock, prescriptions) | yes | yes |
| Needs attention (list and "mark as handled") | yes | yes |
| Accounts (list, switch on/off) and Audit log | no | yes |
Every check is on the server. Other roles get 403.

## Definitions (also shown in the app)
- An order counts on the day it was **created**, in Indian time (UTC+05:30).
- **Gross** = total of orders whose payment succeeded (even if later cancelled/returned). **Refunded** = refunds on those orders, shown on the order's creation day. **Net** = gross - refunded.
- Top products count only orders that are confirmed, dispatched or delivered.
- Delivery time = first "confirmed" to delivered. Failed-delivery rate = orders that ever failed / orders that were ever dispatched.

## Needs attention
Lists what the system flags but must not fix alone: `needs_attention` flags (`payment_mismatch`, `duplicate_payment`, `restock_failed`), orders in `payment_review`, `delivery_failed` orders, and failed refunds.
"Mark as handled" (flagged orders only) clears the flag **only if it is still the same flag**, requires a 5-500 character note, and writes an audit entry. It moves no money and changes no stock.
**Gap:** `payment_review` orders have no in-app fix yet (stock state after a failed commit needs a careful human decision). They are listed so they stop being invisible.

## Accounts
Admin can list/search accounts and switch one on or off (reason required, audited). Not allowed: your own account, or the last active admin (checked after the change and reverted if it would leave none). Roles are not editable in the app on purpose. A switched-off account is refused on its next request and cannot refresh its session.
Password hashes are never returned.

## Setup
`python manage.py create_indexes` (adds order `created_at` and `needs_attention` indexes, and the audit collection). No new settings.

## Tests
`tests.test_adminpanel`: 28 tests; 32 deliberate code breakages, all caught. `tests.test_adminpanel_api` is for `python manage.py test` and has not been run.

## Known issues
- No export (CSV), charts are simple bars, no comparison to a previous period.
- Counts by status are all-time. Audit log has no retention rule or paging UI beyond the first 50.
- The audit log is writable only by this code, but a database administrator can still edit it. It is not tamper-proof.
- Nobody is pushed an alert when something needs attention; staff must open the dashboard (the tab shows a count).
