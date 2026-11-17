# Phase 1: Accounts, JWT, Roles, Addresses

## New commands (run once after pulling Phase 1, from `backend` with the venv active)

```powershell
pip install -r requirements.txt          # adds PyJWT
python manage.py create_indexes          # unique email, token TTL, address index (needs Atlas configured)
python manage.py test
python manage.py runserver
```

Create a staff account (staff can never self-register; you are prompted for the password and it is not echoed):

```powershell
python manage.py create_staff_user --email pharmacist@example.com --name "Test Pharmacist" --role pharmacist
```

Roles: `customer`, `pharmacist`, `pharmacy_manager`, `inventory_staff`, `delivery_partner`, `support_agent`, `admin`.

## API (all under `/api/v1/`)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `auth/register/` | none | Create a customer account; returns user + tokens |
| POST | `auth/login/` | none | Returns user + tokens |
| POST | `auth/refresh/` | none | Exchange a refresh token for a new pair (rotation) |
| POST | `auth/logout/` | none | Revoke the session's refresh tokens (204) |
| GET, PATCH | `me/` | Bearer | View / update `full_name`, `phone` |
| GET, POST | `me/addresses/` | Bearer | List / add addresses (max 10) |
| PATCH, DELETE | `me/addresses/<id>/` | Bearer | Update / delete one of your addresses |

Errors look like `{"error": {"code": "...", "message": "...", "fields": {...}}}`.

Try it in PowerShell (server running):

```powershell
$body = @{ email="me@example.com"; full_name="Test User"; password="a-good-long-pass" } | ConvertTo-Json
$r = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/auth/register/ -ContentType "application/json" -Body $body
Invoke-RestMethod -Uri http://localhost:8000/api/v1/me/ -Headers @{ Authorization = "Bearer $($r.access_token)" }
```

## Design decisions

- **Passwords:** scrypt (Python standard library) with a random salt per password. Minimum 10 characters, rejects common/all-digit passwords and passwords containing the email name.
- **Access token:** HS256 JWT, 15 minutes. The user (role, active flag) is re-read from MongoDB on every request, so deactivating an account or changing a role takes effect immediately.
- **Refresh token:** random string, 14 days, stored only as a SHA-256 hash. Single-use with rotation. Presenting an already-used token revokes the whole token family (theft detection). Expired tokens are deleted by a MongoDB TTL index.
- **Login protection:** identical error for unknown email and wrong password, a dummy hash check to equalize timing, lockout for 15 minutes after 5 failures, and a 20/min per-IP request limit on the auth endpoints.
- **Roles:** the server always assigns `customer` at registration and ignores any `role` in the request. `has_role(...)` in `apps/accounts/permissions.py` is the backend gate for later phases (pharmacist portal, etc.).
- **Ownership:** every address query includes the owner's `user_id`, so one user cannot read or change another's addresses (they get 404).
- **Frontend:** the access token is kept in memory only; the refresh token is in `sessionStorage`. The login page, route guard and navbar are conveniences; the backend enforces everything.

## Known limits (to address before production)

- The refresh token in `sessionStorage` is exposed to any XSS bug. An httpOnly cookie with CSRF protection is the safer design (hardening phase).
- The login rate limit uses Django's default per-process memory cache, so it does not hold across several server processes. A shared cache is needed for multi-process deployment.
- Registration reveals whether an email is already registered (common trade-off for usability).
- No email verification, password reset, or phone OTP yet.
- Failed-login counting is a simple read-modify-write, so parallel guesses can slightly undercount attempts.
- Locked accounts and role changes have no admin UI yet (admin dashboard phase).
