# MediQuick

AI-powered online pharmacy and medicine delivery platform (development build, built from scratch in phases).

> **Status: all 12 planned phases are delivered. This is a PROTOTYPE: it is NOT production-ready and makes no claim of legal compliance.** It has accounts, catalogue, inventory, cart/checkout, OCR-assisted prescription upload with pharmacist review, cancel/return/refund, Razorpay payments (test mode only, tested only against a fake), own-staff delivery with a handover code, in-app and email notifications (no SMS), an admin dashboard and a hardening pass. Payments default to a MOCK that moves no money. Much of it (the Django layer, the React screens, real MongoDB, real Razorpay and SMTP) has never been run for real. Read `docs/PRODUCTION_READINESS.md` and `docs/COMPLIANCE_CHECKLIST.md`.

## Stack

React + Vite, Bootstrap 5, React Router, Axios | Django REST Framework | MongoDB Atlas via PyMongo | JWT auth (Phase 1) | OpenCV + Tesseract OCR (Phase 5)

## Folders

```
mediquick/
├── backend/    Django REST API (config/, apps/, common/, tests/)
├── frontend/   React + Vite app
└── docs/       Architecture, setup guides, compliance checklist
```

## Start here

1. `docs/SETUP_WINDOWS.md` - install tools and run both servers (step by step)
2. `docs/MONGODB_ATLAS.md` - create the Atlas cluster and fill in `backend/.env`
3. `docs/PHASE1_ACCOUNTS.md` - accounts API, new commands, security decisions
4. `docs/PHASE2_CATALOGUE.md` - catalogue API, demo data, product rules
5. `docs/PHASE3_INVENTORY.md` - batches, expiry, stock ledger, availability, staff screen
6. `docs/PHASE4_CART_ORDERS.md` - cart, reservations, orders, mock payment
7. `docs/PHASE5_PRESCRIPTIONS.md` - prescription upload, OCR, Tesseract install on Windows, limits
8. `docs/PHASE6_PHARMACIST.md` - pharmacist portal, approvals, prescription allowances in orders
9. `docs/PHASE7_ORDER_LIFECYCLE.md` - cancel after payment, returns, refunds
10. `docs/PHASE8_PAYMENTS.md` - Razorpay test-mode payments, webhooks, reconcile
11. `docs/PHASE9_DELIVERY.md` - delivery fee, partners, handover code, failed deliveries
12. `docs/PHASE10_NOTIFICATIONS.md` - alerts, email outbox, privacy rules
13. `docs/PHASE11_ADMIN.md` - admin dashboard, attention queue, accounts, audit log
14. `docs/PHASE12_HARDENING.md` - security review, `doctor` and `check --deploy`
15. `docs/OPERATIONS.md` - schedules, backups, incidents
16. `docs/PRODUCTION_READINESS.md` - what is NOT done
17. `docs/TESTING_GUIDE.md` - how to test every feature by hand
18. `docs/ARCHITECTURE.md` - design decisions, MongoDB + DRF notes, phase plan

## Quick commands (after setup, from the project root, PowerShell)

```powershell
# Backend (terminal 1)
cd backend
.\.venv\Scripts\Activate.ps1
python manage.py runserver

# Frontend (terminal 2)
cd frontend
npm run dev
```

Backend: http://localhost:8000/api/v1/health/ | Frontend: http://localhost:5173 (setup check at /status)
