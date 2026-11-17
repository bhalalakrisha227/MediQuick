# What stands between this project and real customers

**MediQuick is a working prototype built in 12 phases. It is not production-ready, and nothing in this project claims legal compliance.**

## Not verified (never run for real)
- Django HTTP layer and all React screens were never run in the build sandbox (no Django, DRF or npm there). Only the plain-Python logic was tested, against in-memory fakes.
- MongoDB queries and indexes (atomic updates, `$expr`, partial and TTL indexes, aggregation) were never run on a real MongoDB.
- Razorpay was only tested against a fake. SMTP only against a fake. OCR accuracy on real prescriptions was never measured and OCR never approves anything: a pharmacist always decides.
- Performance and load: never measured.

## Not built
Email verification, MFA, password reset by email, CAPTCHA, customer data export/deletion, SMS, push notifications, live delivery tracking, GST invoices, a courier integration, a shared rate-limit store, central logging and alerting, a payment_review resolution screen, an automated backup, CI.

## Needs people, not code
- Pharmacy licensing and the rules for selling medicines online, prescription-only (Schedule H/H1/X) handling, and who the registered pharmacist is.
- Data-protection duties for health and payment-adjacent data, privacy notice, consent, retention and breach procedure.
- Payment-provider onboarding and real-money review; tax and invoicing.
- Independent security review and penetration test.
- All placeholder business rules: fees, thresholds, return window, prescription validity, retention periods, attempt limits.

See `docs/COMPLIANCE_CHECKLIST.md` for the running list per phase.
