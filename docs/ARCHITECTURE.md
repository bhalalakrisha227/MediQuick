# MediQuick Architecture (Phase 0)

## 1. Overview

```
Browser (React SPA)
   │  HTTPS + JWT in Authorization header
   ▼
Django REST Framework  ──►  permission checks (backend, role-based)
   │
   ├─► services (business rules)
   │      └─► repositories ──► PyMongo ──► MongoDB Atlas
   ├─► private file storage (prescriptions)
   └─► task runner (OCR etc.): thread pool now, real queue later
```

## 2. Folder layout

```
backend/
  config/        settings (all from environment), urls, wsgi/asgi
  common/        mongo.py (only place a MongoClient is created), tasks.py (task runner interface)
  apps/
    core/        health endpoints (Phase 0)
    accounts/    (Phase 1)  catalog/ (2)  inventory/ (3)  orders/ (4,7)
    prescriptions/ (5,6)  payments/ (8)  delivery/ (9)  notifications/ (10)  audit/ (12)
  tests/         backend tests
frontend/
  src/api/       Axios client
  src/pages/     one folder/file per screen (more from Phase 1)
```

Each future app follows: `views.py` (HTTP) → `serializers.py` (validation) → `services.py` (rules) → `repository.py` (MongoDB access).

## 3. MongoDB with Django REST Framework: compatibility

| Django feature | Works with MongoDB/PyMongo? | What we do |
|---|---|---|
| ORM (`models.Model`) and migrations | No. They target relational databases. | Not used. Each app has a repository class over PyMongo. |
| `django.contrib.admin` | No (needs the ORM). | Not installed. The admin dashboard is our own React UI over role-protected API endpoints. |
| `django.contrib.auth` User model | No (ORM-backed). | Not installed. Users live in a Mongo `users` collection; password hashing uses Django's hashers; JWT handled in Phase 1 with a custom authentication class. |
| DRF `ModelSerializer`, `ModelViewSet` | No. | Use plain `Serializer` classes and `APIView`/`ViewSet` with our repositories. |
| Sessions, CSRF | Not needed for header-based JWT. | Not installed. If tokens ever move to cookies, CSRF protection must be added back. |
| Schema and indexes | No migrations. | Indexes are created by an explicit setup command (added with the first collections). Schema validation is done in serializers (and optionally Mongo JSON-schema validators). |
| Transactions | Needs a replica set. | Atlas clusters are replica sets, so multi-document transactions are available (check your tier's limits). Stock reservation will use atomic updates. |

Alternatives considered (Djongo, django-mongodb-backend, MongoEngine) were not chosen because they either lag Django versions, limit features, or replace PyMongo with a different library. PyMongo directly is the most predictable option.

Phase 0 sets `DATABASES` to Django's dummy backend purely so Django starts.

## 4. Configuration plan

All settings come from environment variables, loaded from `backend/.env` (git-ignored). `backend/.env.example` lists every variable.

| Variable | Purpose |
|---|---|
| `DJANGO_SECRET_KEY` | Required unless DEBUG is True |
| `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS` | Environment behaviour |
| `MONGODB_URI`, `MONGODB_DB_NAME`, `MONGODB_TIMEOUT_MS` | Atlas connection |
| `MAX_UPLOAD_SIZE_MB`, `PRIVATE_STORAGE_DIR` | Prescription upload limits and private location |
| `TASK_RUNNER`, `TASK_MAX_WORKERS` | Background task backend |

Frontend: `frontend/.env` holds only `VITE_API_BASE_URL` (nothing secret, since it ships to the browser).

Safe defaults: debug off, strict HTTPS settings when not in debug, and every API endpoint denied by default until a view explicitly opens it.

## 5. Background tasks (no Docker/Redis/Celery)

`common/tasks.py` defines a `TaskRunner` interface with an in-process thread-pool implementation. OCR code (Phase 5) calls only the interface, so Celery/RQ can replace it later without touching feature code. Known limits: jobs are lost on server restart and do not scale across processes, so job status will be stored in MongoDB from Phase 5.

## 6. OCR design (Phase 5, built; details in PHASE5_PRESCRIPTIONS.md)

- `ocr/preprocess.py` (OpenCV: grayscale, denoise, threshold, deskew)
- `ocr/engines/base.py` (engine interface), `tesseract.py` first, `paddle.py` possible later
- `ocr/parser.py` (candidate medicine, strength, dosage, quantity), `ocr/matcher.py` (catalogue matching)
- OCR output is only a suggestion. Prescription status changes only by an authorized pharmacist's action (Phase 6), enforced in the backend and logged. Accuracy will be measured on sample data and reported honestly.

## 7. Dependencies

Phase 5 added opencv-python-headless, pytesseract and PyMuPDF. Installed in Phase 0: Django, djangorestframework, pymongo[srv], python-dotenv, django-cors-headers, certifi; React, react-dom, react-router-dom, axios, bootstrap, Vite.

Planned (added only when needed): `djangorestframework-simplejwt` or PyJWT (Phase 1), Pillow, opencv-python-headless, pytesseract, PyMuPDF for PDF pages (Phase 5), a payment SDK behind an adapter (Phase 8).

## 8. Phases

| # | Phase | Outcome |
|---|---|---|
| 0 | Foundation | This setup, health checks, Atlas connection |
| 1 | Accounts | Registration, login, JWT, roles, addresses |
| 2 | Catalogue | Categories, products, search, Rx flag, product pages |
| 3 | Inventory | Batches, expiry, stock movements |
| 4 | Cart and checkout | With prescription-required rules |
| 5 | Prescription pipeline | Secure upload, OpenCV, Tesseract, matching |
| 6 | Pharmacist portal | Verification queue, audit trail |
| 7 | Orders | Lifecycle, cancellations, returns, refunds |
| 8 | Payments | Adapter and mock, real gateway later |
| 9 | Delivery | Serviceability, assignment, tracking |
| 10 | Notifications | In-app first |
| 11 | Admin dashboard | Analytics |
| 12 | Hardening | Security review, tests, deployment config |
