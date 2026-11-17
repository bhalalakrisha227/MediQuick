# MongoDB Atlas Setup (beginner guide)

Atlas's website changes over time, so button names may differ slightly. The concepts stay the same.

## 1. Create an account and cluster

1. Go to https://www.mongodb.com/cloud/atlas and sign up.
2. Create a new **Project** named `MediQuick`.
3. Choose **Create a cluster**, pick the **free (M0)** tier, a cloud provider, and a region near you (for India, a Mumbai region if offered).
4. Name the cluster `mediquick-dev` and create it. It takes a few minutes.

## 2. Create a database user (Database Access)

1. Open **Database Access** → **Add New Database User**.
2. Authentication: **Password**. Username e.g. `mediquick_app`.
3. Click **Autogenerate Secure Password** and copy it somewhere safe (a password manager). Prefer letters and numbers only; special characters must be URL-encoded in the connection string (`@` becomes `%40`, `:` becomes `%3A`, `/` becomes `%2F`).
4. Privileges: **Read and write to any database** is fine for development. For production, restrict to the `mediquick` database.

## 3. Allow your IP (Network Access)

1. Open **Network Access** → **Add IP Address** → **Add Current IP Address**.
2. Avoid `0.0.0.0/0` (open to the world). If your home IP changes, come back and add the new one.

## 4. Get the connection string

1. In **Database** (Clusters), click **Connect** on your cluster → **Drivers** → Python.
2. Copy the string. It looks like:
   `mongodb+srv://<db_user>:<db_password>@<cluster-host>/?retryWrites=true&w=majority&appName=mediquick-dev`
3. Replace `<db_user>` and `<db_password>` with your values.

## 5. Put it in `backend/.env` (never in code)

```powershell
cd backend
Copy-Item .env.example .env
notepad .env
```

Fill in:

```
MONGODB_URI=mongodb+srv://mediquick_app:YOUR_PASSWORD@your-cluster-host/?retryWrites=true&w=majority&appName=mediquick-dev
MONGODB_DB_NAME=mediquick
```

Rules:
- Do not add quotes or spaces around the value.
- `.env` is git-ignored. Check with `git status`: `.env` must not be listed.
- Never paste the connection string into chat, screenshots, or GitHub.
- If it leaks, change the database user's password in Atlas immediately and update `.env`.

## 6. Test it

With the backend running (`python manage.py runserver`), open http://localhost:8000/api/v1/health/db/ . Expected: `{"status":"ok","database":"reachable"}`.

Common problems:
- **503 / unreachable**: your IP is not in Network Access, the password is wrong or not URL-encoded, or your network blocks the connection. The exact error is printed in the terminal running the server.
- **`MONGODB_URI is not set`**: `.env` is missing or in the wrong folder (it must be `backend/.env`).
- **DNS errors with `mongodb+srv://`**: confirm `pymongo[srv]` installed (it is in `requirements.txt`) and try another network.
