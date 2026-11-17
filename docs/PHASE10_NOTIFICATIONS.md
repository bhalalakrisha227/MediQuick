# Phase 10 - Notifications (in-app + email)

## Honest status
- **In-app alerts** (bell + Notifications page) always work. **Email** works only when you configure SMTP and run the worker. **SMS is NOT implemented** and the UI says so.
- The SMTP adapter has been tested only against a fake SMTP object, never a real mail server. Try it with a test inbox (for example Mailtrap) first.
- Django HTTP tests and the React pages could not be run in the build sandbox. The "claim one due email" and lease queries are Mongo-only and untested on a real MongoDB.
- There is **no email verification** of customer addresses, so an email can reach someone who mistyped their address. That is why messages are minimal.

## What triggers a message
Order confirmed, payment under review, out for delivery, delivered, delivery failed, cancelled (not for unpaid orders the customer cancelled), refund issued, return approved/rejected, prescription approved/rejected/needs clarification.
Triggers sit on the one atomic status-change call each repository already has (`apps/notifications/observers.py`), so a message exists exactly when the change really happened, from any code path. A notification failure is logged and swallowed; it can never block or undo an order, payment or review.

## Privacy rules (tested)
Messages never contain medicine names, addresses, phone numbers, prescription details or the delivery handover code. They carry the order number and a link; details stay behind the login.

## Email outbox
- One notification per (event, entity, occurrence): a unique key stops duplicates.
- Nothing is sent inside a web request. Run the worker: `python manage.py send_notifications` (keeps running; `--once` for a scheduler).
- Atomic claim with a 10-minute lease, 5 attempts with back-off (1, 5, 30, 120 min), permanent errors (refused address, bad message) fail at once. Failed emails stay visible in the database (`email.status = failed`, `last_error`, no secrets).
- Users can switch email off at any time (Notifications page); it also stops emails already queued.

## Setup (PowerShell)
```
# backend\.env
EMAIL_PROVIDER=smtp          # none (default) | console (DEBUG only, prints to the log) | smtp
EMAIL_FROM=MediQuick <no-reply@example.com>
SMTP_HOST=sandbox.smtp.mailtrap.io
SMTP_PORT=587
SMTP_USER=...
SMTP_PASSWORD=...
FRONTEND_URL=http://localhost:5173
python manage.py create_indexes
python manage.py send_notifications
```

## Tests
`tests.test_notifications`: 32 tests (events, privacy, dedupe, worker retries/lease, inbox, settings, SMTP adapter, 300-step randomized outbox invariant). About 20 deliberate code breakages were all caught except the Mongo-only lease query. `tests.test_notifications_api` is for `python manage.py test` and has not been run.

## Known issues
- Customers only; staff are not alerted (failed refunds, `payment_review`, `needs_attention` still need a screen or alert, a good fit for Phase 11).
- Polling once a minute, no push. Notifications are deleted after 180 days.
- English only, plain text only. No SMS/WhatsApp. No unsubscribe link (the switch is in the app).
- Which messages are legally "transactional", and rules on messaging customers, are not reviewed.
