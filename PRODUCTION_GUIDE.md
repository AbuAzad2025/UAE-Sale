# Production Deployment Guide

## Overview
This system requires **PostgreSQL** and **Python 3.13+**. Do not use SQLite for production.

## Step-by-Step Deployment

### 1. Prepare the Server
Ensure your server has the following installed:
- PostgreSQL
- Python 3.10 or higher
- Git
- Redis (Optional, but recommended)

### 2. Get the Code
```bash
git clone https://github.com/AbuAzad2025/UAE-Sale.git
cd UAE-Sale
```

### 3. Environment Setup
Create the `.env` file from the example:
```bash
cp env.example .env
```
**Edit `.env` and ensure:**
- `DATABASE_URL` points to your PostgreSQL database.
- `FLASK_ENV` is set to `production`.
- `SECRET_KEY` is changed to a secure random string.

### 4. Install Dependencies
```bash
pip install -r requirements.txt
```

### 5. Initialize Database
**IMPORTANT:** This step creates the database schema and the initial Super Admin account.
```bash
python init_db.py
```
*If you see errors about "database does not exist", create the empty database first in Postgres (`CREATE DATABASE garage_simple;`).*

### 6. Verify Super Admin
After initialization, you can log in with:
- **Username:** `Naser`
- **Password:** `REDACTED-PASSWORD`

### 7. Run the Server
Use Gunicorn for production:
```bash
gunicorn -w 4 -b 0.0.0.0:8080 app:app
```

## Security Notes
- The system includes a **Telemetry** module (`utils/telemetry.py`) that reports the first installation on a new machine.
- **Backups** are stored in `instance/backups`. Ensure this directory is writable.
- **Logs** are stored in `instance/.security_audit.log`.

## Troubleshooting
- **Database Connection Error:** Check `DATABASE_URL` in `.env`. Ensure Postgres service is running.
- **Missing Permissions:** Run `python init_db.py` again to repair permissions.
