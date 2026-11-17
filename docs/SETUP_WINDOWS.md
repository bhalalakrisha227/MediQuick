# Windows Setup (Phase 0)

Use **PowerShell**. No Docker, WSL2, Redis or Celery needed.

## 1. Install prerequisites

| Tool | Version | Check command |
|---|---|---|
| Python (64-bit) | 3.11 or 3.12 | `python --version` |
| Node.js | 20 LTS or newer | `node --version` and `npm --version` |
| Git | any recent | `git --version` |
| VS Code (optional) | any | |

When installing Python, tick **Add python.exe to PATH**. Close and reopen PowerShell after installing anything.

Tesseract OCR is not needed until Phase 5; install it then.

## 2. Create the project folder

If you downloaded this project, open PowerShell in its root folder (the one containing `backend` and `frontend`). Then:

```powershell
git init
git add .
git status
```

Confirm no `.env` file appears in the list, then `git commit -m "Phase 0 foundation"`.

## 3. Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell says scripts are disabled, run this once, then retry:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

Your prompt should now start with `(.venv)`. Install dependencies:

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Create your config file and a secret key:

```powershell
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(50))"
notepad .env
```

Paste the printed key after `DJANGO_SECRET_KEY=`. Then follow `docs/MONGODB_ATLAS.md` to fill `MONGODB_URI`.

Check and run:

```powershell
python manage.py check
python manage.py test
python manage.py create_indexes   # Phase 1+, needs Atlas configured
python manage.py runserver
```

Open http://localhost:8000/api/v1/health/ (expect `{"status":"ok","service":"mediquick-api"}`) and http://localhost:8000/api/v1/health/db/ (expect `"database":"reachable"` once Atlas is configured).

`python manage.py test` uses a mocked database, so it does not need Atlas.

## 4. Frontend (new PowerShell window)

```powershell
cd frontend
Copy-Item .env.example .env
npm install
npm run dev
```

Open http://localhost:5173 . You should see two rows, "Backend API" and "Database", showing **Connected** when the backend is running (and Atlas is configured).

## 5. Troubleshooting

- `python` not found: reinstall Python with "Add to PATH", or use `py` instead of `python`.
- Port 8000 busy: `python manage.py runserver 8001` and set `VITE_API_BASE_URL` in `frontend/.env` to match.
- Frontend shows "Not reachable": backend not running, or `CORS_ALLOWED_ORIGINS` in `backend/.env` does not include `http://localhost:5173`. Restart the backend after editing `.env`.
- `ImproperlyConfigured: DJANGO_SECRET_KEY`: `.env` is missing, in the wrong folder, or `DJANGO_DEBUG` is not `True`.
