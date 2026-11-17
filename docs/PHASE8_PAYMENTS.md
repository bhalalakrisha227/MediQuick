# Phase 8 - Real payments (Razorpay, TEST MODE only)

## Honest status
- The Razorpay adapter has **never contacted real Razorpay**. It is tested only against a fake Razorpay API and a local HTTP server. Your first real test-mode payment is the first real check.
- Only `rzp_test_` keys are accepted. Live keys (`rzp_live_`) are refused at startup unless `PAYMENT_ALLOW_LIVE=true`, which you should not set until a compliance review is done.
- The mock adapter still exists and works only when `DEBUG=True`.
- Django HTTP tests and the React pages were written but could not be run in the build sandbox. MongoDB queries (`$expr`, partial indexes) are untested on a real MongoDB.

## Setup (PowerShell)
1. Create a Razorpay account, switch to **Test Mode**, and copy the key id and key secret.
2. In `backend\.env` set:
   ```
   PAYMENT_PROVIDER=razorpay
   RAZORPAY_KEY_ID=rzp_test_xxxxxxxx
   RAZORPAY_KEY_SECRET=your_test_secret
   RAZORPAY_WEBHOOK_SECRET=a_long_random_string_you_choose
   ```
3. In the Razorpay dashboard enable **auto-capture** (if you do not, the server captures "authorized" payments itself).
4. Webhooks need a public URL. For local testing use a tunnel to `http://localhost:8000`, then add webhook `https://<tunnel>/api/payments/webhook/` with the same secret and events `payment.captured`, `order.paid`, `refund.failed`.
5. Re-run indexes: `python manage.py create_indexes`
6. Schedule (every 5 minutes): `python manage.py reconcile_payments`

## How it works
- Browser gets only the key id, gateway order id and amount. Secrets stay on the server.
- After the popup, the server checks the signature **and** fetches the payment from Razorpay, comparing payment id, order id, amount and currency. The browser is never trusted.
- Webhooks are signature-checked on the raw body and are idempotent by event id.
- Late payment on a cancelled/expired order is refunded automatically, once.
- Extra or duplicate payments, or mismatched amounts, set `needs_attention` on the order for a human. There is no staff screen for this yet.
- Refund status `pending` counts as success; a `refund.failed` webhook reopens it.
- New status `confirming_payment` (short step while stock is committed). Stuck ones go to `payment_review` via reconcile.

## Tests
`tests.test_gateway_payments`: 50 tests (adapter, signatures, start/verify, webhooks, late payments, cancel, reconcile, 1500-step randomized invariant: every captured payment is confirmed, refunded or flagged; refunds never exceed totals). Full runnable suite: 345 passing.

## Known issues
- Checkout.js loads from checkout.razorpay.com (allow it in any CSP).
- No staff UI for `needs_attention` orders or payment_review.
- Delivery-fee, taxes and legal/payment compliance are not addressed.
