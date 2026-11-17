# Compliance Checklist (starter, not legal advice)

This is a list of topics to verify with a qualified Indian pharmacy/healthcare lawyer and licensing authorities **before any real medicine sale**. It does not state what the law requires, and MediQuick makes no compliance claim. Rules change and some areas (online pharmacy) have been in flux, so each item needs current professional confirmation.

## Licensing and pharmacy operations
- [ ] Applicable drug licences (retail/wholesale) under the Drugs and Cosmetics Act and Rules, and state-level requirements
- [ ] Registered pharmacist involvement and who may verify prescriptions
- [ ] Legal status of online pharmacy / e-pharmacy operations at the time of launch
- [ ] Storage, batch, expiry and recall record-keeping obligations

## Prescriptions and restricted drugs
- [ ] Which schedules (e.g. H, H1, X) and narcotic/psychotropic drugs may or may not be sold online
- [ ] What a valid prescription must contain, validity period, and retention rules
- [ ] Limits on substitution and on repeat/partial fulfilment
- [ ] Records the pharmacist must keep per verification

## Data protection and security
- [ ] Digital Personal Data Protection Act obligations: consent, notice, retention, deletion, breach reporting
- [ ] Handling of health data and prescription images (encryption, access logs, minimum retention)
- [ ] Privacy policy, terms, refund/return policy (medicine returns are legally restricted)

## Payments and delivery
- [ ] Payment gateway onboarding and RBI-related requirements
- [ ] Delivery restrictions by product type and location; cold-chain items

## Engineering controls tracked in this project
- [ ] Backend-enforced roles (Phase 1+)
- [ ] OCR never approves prescriptions; only a pharmacist action does (Phase 5-6)
- [ ] Audit log for verifications, stock changes and refunds (Phase 12)
- [ ] Security review and penetration testing before launch

## Added in Phase 5 (prescription upload) - open items for a lawyer / compliance reviewer
- [ ] Review and replace the DRAFT consent wording (`apps/prescriptions/rules.py`, `CONSENT_TEXT`, version `draft-1`)
- [ ] Retention period for prescription images and OCR text; deletion on request; what "withdraw" must keep (currently: file and OCR text are deleted on withdraw, submitted ones are kept)
- [ ] Encryption at rest for prescription files (NOT implemented: files are plain files with owner-only permissions in `PRIVATE_STORAGE_DIR`; use an encrypted disk/volume or object storage with encryption before real use)
- [ ] Virus/malware scanning of uploads (NOT implemented; only type, size, pixel-count and PDF active-content checks)
- [ ] Who may view a prescription and for how long (currently: owner, and pharmacist / pharmacy manager / admin only after submission, each staff view logged in `prescription_access`)

## Added in Phase 6 (pharmacist review and Rx orders) - open items for a pharmacist / lawyer / compliance reviewer
- [ ] The pharmacist registration number is only format-checked. It is NOT verified against any pharmacy council register, and the person's role (`pharmacist`) is assigned by an admin, not verified
- [ ] Prescription validity (`PRESCRIPTION_VALIDITY_DAYS`, default 30, also the maximum a pharmacist can pick) and the per-line caps are placeholders
- [ ] Records the law may require when dispensing (for example Schedule H1 register details: patient, prescriber, quantity) are NOT captured. Prescriber and patient details exist only in the image
- [ ] Dispensing is not tied to a pharmacist check yet: an order made against an approved prescription is recorded (`lines[].prescription_id`) but nobody re-verifies at packing/dispatch until Phases 7 and 9
- [ ] Whether one approved prescription may be used for several orders (this build allows it up to the approved quantities) and for how long
- [ ] Retention and access rules for the audit log (`prescription_audit`) and file-access log (`prescription_access`)
- [ ] Controlled/restricted drugs: Schedule X stays blocked online by a placeholder rule, and approval cannot unlock it

## Added in Phase 7 (returns and refunds) - open items for a pharmacy / compliance reviewer
- [ ] Which returns of medicines may be accepted at all, the time window (placeholder: 2 days), and the allowed reasons
- [ ] What must happen to a returned medicine (destruction/quarantine record); the software never restocks it
- [ ] Whether prescription units should be restored after a return (currently: no)
- [ ] Refund timelines, partial-refund policy, delivery-fee refunds, and consumer-law requirements
- [ ] Who may mark orders dispatched/delivered (currently pharmacy_manager/admin, by hand, unverified)

## Added in Phase 8 (payments) - open items for a finance / compliance reviewer
- [ ] Razorpay adapter is verified only against a fake; run real test-mode payments before trusting it
- [ ] Live keys are refused; going live needs PCI/RBI-related, tax (GST invoicing) and settlement review
- [ ] Duplicate/mismatched payments are flagged (`needs_attention`) but no staff process or screen exists
- [ ] Refund timelines, failed-refund handling and reconciliation against Razorpay settlement reports
- [ ] Webhook secret rotation, and who monitors `reconcile_payments`

## Added in Phase 9 (delivery) - open items for a pharmacy / legal reviewer
- [ ] Who may deliver medicines, rider vetting and training; cold-chain and storage rules
- [ ] Delivery fee, free-delivery threshold and the service area are placeholders
- [ ] No pharmacist check at packing/pickup (especially for prescription orders) and no dispatch record for scheduled drugs
- [ ] Handling of undelivered medicines (they are never restocked; physical return and destruction process is undefined)
- [ ] Rider personal data (name, phone shown to customers only as first name) and customer address exposure to riders

## Added in Phase 10 (notifications) - open items for a legal / privacy reviewer
- [ ] Customer emails are not verified; wrong-recipient risk (messages are kept minimal on purpose)
- [ ] Consent/opt-out rules for transactional vs promotional messages (only transactional exist; none are promotional)
- [ ] Data retention of notifications (placeholder: 180 days) and of email addresses in third-party mail services
- [ ] No SMS, so no sender-registration/DLT questions yet; they arrive if SMS is added
- [ ] Staff alerts for payment problems and failed refunds do not exist yet

## Added in Phase 11 (admin dashboard) - open items for a security / compliance reviewer
- [ ] Admin accounts are powerful (see all customer accounts, switch accounts off): who gets them, MFA (not built), and review of the audit log
- [ ] The audit log is not tamper-proof and has no retention rule
- [ ] Reports are operational numbers, not accounting or GST figures
- [ ] Unresolved payment_review orders have no in-app procedure

## Added in Phase 12 (hardening) - open items
- [ ] Independent security review / penetration test (this phase was a self-review)
- [ ] pip-audit and npm audit run and reviewed by a person (not possible in the build sandbox)
- [ ] Restore drill for the database AND the private prescription files
- [ ] Customer data export and deletion (not built); retention periods are placeholders
- [ ] MFA for staff/admin and email verification for customers (not built)
- [ ] Frontend security headers/CSP configured on the real host and tested with the payment popup
