# Phase 12 - Hardening

## Honest status
This phase is a **review and a set of safety nets**, not a certificate. Nothing here makes MediQuick secure, legally compliant or ready for real customers. A pharmacy handling prescriptions and payments needs an independent security review, a penetration test and legal sign-off. See `docs/PRODUCTION_READINESS.md`.
Django, DRF and MongoDB are not installed in the build sandbox, so the Django wrappers (middleware, error handler, check registration, the `doctor` command) are **unrun**. Their logic lives in plain-Python modules that **are** tested.

## What I audited
| Area | Result |
|---|---|
| Hostile input (NoSQL operators, wrong types, huge strings) against every service method | Test added (`test_input_fuzz`). Found one real gap: address update/delete accepted a non-string id. Fixed. A deliberately removed check was caught by the test. |
| Ownership (one customer reading another's order / prescription / notification) | Reviewed by reading; every customer path goes through an owner-scoped lookup. Covered by existing per-phase tests. Not proven for every future change. |
| Mass assignment (client setting role, price, status) | Reviewed: profile and address updates go through validators; role is never taken from input. |
| Rate limits | **Gap fixed:** only login/checkout/upload were limited. Now every endpoint has a default limit (anon 120/min, user 300/min) and the stricter scoped ones stay. |
| Rate-limit bypass | **Real bug fixed:** DRF's default setting believes a client-sent `X-Forwarded-For` header, so anyone could dodge every limit by sending a random value. Now `NUM_PROXIES` is 0 (connecting address only); behind a proxy set `THROTTLE_NUM_PROXIES`. A test pins this. |
| Response headers | **Gap fixed:** added CSP `default-src 'none'`, `frame-ancestors 'none'`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, and `Cache-Control: no-store` on every `/api/` response. |
| Errors | **Gap fixed:** unexpected errors now return one JSON shape with a generic message and a reference id; the stack trace goes to the server log only. |
| Unauthenticated surface | Pinned by a test to an exact list (catalogue reads, health, login/register/refresh/logout, payment webhook). Anything new must be added on purpose. |
| Production configuration | **New:** `python manage.py check --deploy` reports debug on, weak or shared secrets, localhost hosts/origins, http URLs, mock payments, console email, missing Razorpay secrets, live payments, and more. |
| Dangerous code patterns (`eval`, `pickle`, `shell=True`, `verify=False`, weak hashes) | None found in application code. |
| Secrets in the repo | None found (docs contain placeholders only). `.env` files are git-ignored and never zipped. |
| Dependency vulnerabilities | **NOT checked.** The sandbox cannot reach package registries. Run the scans below yourself. |

## New tools
- `python manage.py doctor` - one command that says what actually works on your machine: MongoDB, indexes, an admin account, Tesseract, OpenCV, PDF support, private storage, payment and email adapters. It prints no passwords (connection-string passwords are removed). **Please run it and send me the output.**
- `python manage.py check --deploy` - production configuration review.
- Tests: `tests.test_hardening` (22), `tests.test_input_fuzz` (2 broad tests covering about 250 service calls x 25 hostile values each). 24 deliberate breakages of the hardening code were all caught.

## Run the scans (PowerShell)
```
cd backend
pip install pip-audit
pip-audit -r requirements.txt
cd ..\frontend
npm install        # creates package-lock.json: commit it
npm audit
```
Also pin exact versions for production (`pip freeze > requirements.lock`) and keep a lock file for the frontend.

## Frontend hosting (the React app is separate from the API)
Serve it over HTTPS with at least these headers (adjust the API address):
```
Content-Security-Policy: default-src 'self'; script-src 'self' https://checkout.razorpay.com; frame-src https://api.razorpay.com https://checkout.razorpay.com; connect-src 'self' https://api.yourdomain.in https://lumberjack.razorpay.com; img-src 'self' data:; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'self'
X-Content-Type-Options: nosniff
Referrer-Policy: no-referrer
Strict-Transport-Security: max-age=31536000
```
Test the payment popup with this policy before relying on it; Razorpay may need more hosts. The refresh token lives in `sessionStorage`, so any XSS bug could steal it. That is why the CSP matters and why no `dangerouslySetInnerHTML` is used anywhere (checked).

## Known issues and trade-offs
- Rate limiting is in process memory. With several server processes each has its own counter. A shared store (not Redis-dependent today) is future work.
- Registering with an existing email says it is taken (account enumeration). Accepted trade-off for usability; login does not reveal which part was wrong.
- Repeated wrong passwords lock an account for a while, which can be abused to annoy a specific user. The per-IP limit is the mitigation.
- No MFA for staff or admin accounts, no email verification of customers, no CAPTCHA.
- No customer data export or deletion feature (India's data-protection law will need one).
- Public database health endpoint pings MongoDB on request (rate limited). Consider restricting it in production.
- Logs are plain text to the console with no central collection or alerting.
