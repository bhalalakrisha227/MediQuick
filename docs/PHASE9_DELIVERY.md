# Phase 9 - Delivery (our own delivery partners)

## Honest status
- There is **no courier or tracking integration** and no live map. A "delivery partner" is a staff account with the `delivery_partner` role that uses this app.
- Fee, free-delivery threshold, attempt limits and failure reasons are **placeholders** in `apps/orders/rules.py`.
- Service area is only a list of PIN code prefixes (`DELIVERY_PINCODE_PREFIXES`). Empty means "deliver everywhere" (demo).
- Django HTTP tests and the React pages could not be run in the build sandbox. Core logic is tested against in-memory fakes (31 tests plus a 500-step randomized check); MongoDB atomic updates are untested on a real MongoDB.

## Flow
1. Order is paid (`confirmed`). Staff (pharmacy_manager/admin) opens **Fulfilment** and assigns a delivery partner.
2. The partner opens **My deliveries**, taps *picked up*. Order becomes `dispatched`; a random salt is stored.
3. The customer's order page shows a **6-digit handover code**. The partner types it to mark `delivered`.
4. If delivery fails the partner records a reason. After 3 failed attempts the order becomes `delivery_failed`. Staff choose **Redeliver** (back to `confirmed`, unassigned) or **Refund in full** (order cancelled, full refund through the existing refund system, medicines are NOT restocked).
5. Staff can still mark dispatched/delivered by hand (override that skips the code).

## Safety design
- The handover code is **never stored**: it is an HMAC of the order id, the per-pickup salt and `DJANGO_SECRET_KEY`. Set `DJANGO_SECRET_KEY` in `.env`, otherwise a debug restart changes every code.
- Wrong codes are counted by one atomic update; after 5 the order locks (even the right code is refused) until staff reassign it.
- A partner only sees orders assigned to them (others look like "not found"), and only recipient, phone, address and **item count**: no medicine names, prices, payment or prescription details. No cash on delivery exists.
- Every status change is an atomic compare-and-set; the third failure and a simultaneous delivery cannot both win.
- Delivery fee is computed on the server at checkout and stored with the order; PIN code is checked before stock or cart are touched.

## Setup (PowerShell)
```
cd backend
# .env: DJANGO_SECRET_KEY=<long random>, optional DELIVERY_PINCODE_PREFIXES=5600,4110
python manage.py create_indexes
python manage.py create_staff_user --role delivery_partner --email rider@example.com --name "Ravi Kumar"
```
(Check `python manage.py create_staff_user --help` for the exact argument names.)

## Tests
`tests.test_delivery` (31 tests; 19 deliberate code breakages all caught). `tests.test_delivery_api` is for `python manage.py test` and has not been run.

## Known issues
- No notifications yet (Phase 10): the customer must open the page to see the code.
- No rider location, ETA, routing or proof-of-delivery photo.
- Prescription orders are not re-verified by a pharmacist at pickup.
- Fee/threshold/service area are placeholders; taxes and delivery-law questions are open.
