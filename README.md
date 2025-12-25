# UAE-Sale | Enterprise Warehouse Management System

<div align="center">

[![Version](https://img.shields.io/badge/version-2.0.0-blue.svg)](https://github.com/AbuAzad2025/UAE-Sale/releases)
[![Python](https://img.shields.io/badge/python-3.13-brightgreen.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/flask-3.0-orange.svg)](https://flask.palletsprojects.com/)
[![Status](https://img.shields.io/badge/status-Production-success.svg)](https://uaesale-azad.pythonanywhere.com/)
[![License](https://img.shields.io/badge/license-Proprietary-red.svg)](LICENSE)

**Professional warehouse and sales management system for enterprises**

🌐 **[Live Demo](https://uaesale-azad.pythonanywhere.com/)** • [Docs](AZAD_SYSTEM_COMPLETE_GUIDE.md)

</div>

---

## 📋 Overview - نظرة عامة

**UAE-Sale** is a comprehensive enterprise resource planning (ERP) system specifically designed for warehouse and sales management. Built with modern technologies and intelligent automation.

### Core Capabilities
- 📦 **Inventory Management**
- 💰 **Sales Management**
- 🧾 **Receipt System**
- 👥 **Customer & Supplier CRM**
- 💳 **Payment Processing**
- 🏦 **Check Management**
- 💱 **Multi-Currency**
- 📊 **Advanced Analytics**
- 🤖 **AI Assistant**

---

## 🛠 Tech Stack

- **Backend:** Flask 3.0 (Python 3.13)
- **Database:** PostgreSQL (Required)
- **ORM:** SQLAlchemy 2.0
- **Frontend:** AdminLTE 3, Bootstrap 4
- **Security:** RBAC, Encrypted Data, Telemetry

---

## 🚀 Production Setup (PostgreSQL)

This system is designed to run on **PostgreSQL**. Follow these steps for production deployment:

### 1. Prerequisites
- Python 3.13+
- PostgreSQL 14+
- Redis (Recommended for Caching)

### 2. Installation

```bash
# Clone the repository
git clone https://github.com/AbuAzad2025/UAE-Sale.git
cd UAE-Sale

# Install dependencies
pip install -r requirements.txt
```

### 3. Configuration
Copy `env.example` to `.env` and update the values:

```bash
cp env.example .env
nano .env
```

**Crucial Settings:**
- `DATABASE_URL`: Must be a valid PostgreSQL connection string.
  - Example: `postgresql://user:password@localhost:5432/garage_simple`
- `SECRET_KEY`: Generate a strong random key.

### 4. Database Initialization
Run the initialization script to create tables and the Super Admin account:

```bash
python init_db.py
```

This will create:
- All database tables.
- **Super Admin User:** `Naser` (Password: `REDACTED-PASSWORD`)
- Essential roles and permissions.

### 5. Run the Application

```bash
# Using Gunicorn (Recommended for Production)
gunicorn -w 4 -b 0.0.0.0:8080 app:app
```

---

## 🔐 Security Features

- **Master Key System:** Hardcoded recovery mechanisms.
- **Telemetry:** Automated installation reporting.
- **Machine Locking:** Token-based duplicate prevention.
- **Encrypted Storage:** AES-256 for sensitive fields.

---

## 🐳 Docker Deployment

```bash
docker-compose up -d
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for detailed guide.

---

## 📞 Support

**Azad Systems - Eng. Ahmad Ghannam**
- Email: rafideen.ahmadghannam@gmail.com
- Phone: +970-598-953-362
