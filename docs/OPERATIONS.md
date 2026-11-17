# Operations notes (backup, schedules, incidents)

These are practical notes, not a tested runbook. Practise a restore before you rely on any of it.

## What must run all the time or on a schedule
| Command (from `backend`) | How often | Why |
|---|---|---|
| `python manage.py send_notifications` | keep running | sends queued emails |
| `python manage.py reconcile_payments` | every 5 minutes | settles stuck payments, releases held stock |
| `python manage.py release_expired_reservations` | every 5 minutes | frees stock held by unpaid orders |
| `python manage.py process_pending_prescriptions` | every few minutes | picks up OCR work lost on a restart |
Windows: use Task Scheduler. If these stop, stock stays held, stuck payments stay stuck and emails stop; nothing tells you.

## Backups
- **Database:** use MongoDB Atlas backups (paid tiers) or `mongodump`. Example: `mongodump --uri "<read-only-uri>" --out backups\2026-11-15`. Restore with `mongorestore`. Restore into a **new** database first and check it before swapping.
- **Prescription files** live in `PRIVATE_STORAGE_DIR` on disk, **not** in MongoDB. Back them up with the database, to an encrypted, access-controlled place. A database restore without the files leaves broken prescriptions.
- Keep backups as protected as production: they contain health data and addresses.
- Test a restore on a schedule. An untested backup is a hope.

## Secrets
Keep them only in `backend\.env` (never committed or zipped). Rotating: change `DJANGO_SECRET_KEY` (signs nothing long-lived except delivery handover codes, so in-flight deliveries change), `JWT_SECRET_KEY` (logs everyone out), Razorpay and webhook secrets (change in the dashboard and `.env` together), `SMTP_PASSWORD`. If a secret was ever pasted into chat, email or a commit, treat it as leaked and rotate it.

## If something goes wrong
- **Suspected account takeover:** Admin -> Accounts -> switch the account off (effective on its next request), then investigate the audit log.
- **Payment problem:** Admin -> Needs attention. Money questions are settled in the payment dashboard; "mark as handled" records that a person did it.
- **Data exposure:** stop the site, preserve logs, rotate every secret, and get legal advice about notification duties. This project has no incident-response plan beyond this paragraph.

## Before going live (minimum)
1. `python manage.py doctor` and `python manage.py check --deploy` show no errors.
2. All tests pass **on your machine**: `python manage.py test` and the unittest commands in each phase doc.
3. `pip-audit` and `npm audit` reviewed.
4. A restore drill done.
5. Legal and pharmacy-licensing review done (see `docs/PRODUCTION_READINESS.md`).
