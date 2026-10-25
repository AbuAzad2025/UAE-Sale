# Azad ERP — UAE-Sale System

**Azad ERP** is a multi-tenant, enterprise-grade ERP system built with Flask/Python for business management, covering sales, purchases, inventory, accounting, HR, and advanced analytics.

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Features](#features)
3. [Technology Stack](#technology-stack)
4. [Quick Start](#quick-start)
5. [Deployment](#deployment)
6. [Documentation](#documentation)
7. [Testing](#testing)
8. [Security](#security)
9. [Contributing](#contributing)
10. [License](#license)

---

## 🎯 Overview

Azad ERP is a comprehensive business management system designed for small to medium enterprises (SMEs) operating in the UAE and Middle East. It provides:

- **Multi-tenant architecture** with row-level data isolation
- **Double-entry accounting** with full GL, AR, AP sub-ledgers
- **Inventory management** with moving weighted average costing
- **Multi-currency support** with FX revaluation
- **Role-based access control** with granular permissions
- **Audit trail** for all financial transactions
- **AI-powered insights** for business analytics

---

## ✨ Features

### Core Modules

| Module | Description |
|--------|-------------|
| **Sales & Invoicing** | Create sales invoices, manage customer accounts, track payments, handle returns |
| **Purchases** | Purchase orders, supplier management, accounts payable |
| **Inventory** | Stock management with moving average cost, warehouse transfers, stock takes |
| **Accounting** | Double-entry GL, journal entries, trial balance, balance sheet, income statement |
| **Payments** | Cash receipts, payments, cheques, bank reconciliation |
| **Customers** | Customer management, credit limits, payment terms, AR aging |
| **Suppliers** | Supplier management, payment terms, AP aging |
| **Products** | Product catalog, categories, pricing, cost tracking |

### Advanced Features

| Feature | Description |
|---------|-------------|
| **Multi-Currency** | Support for multiple currencies with exchange rate tracking and FX revaluation |
| **Moving Average Costing** | Inventory valuation using moving weighted average cost |
| **Bad Debt Write-offs** | Write-off uncollectible receivables with GL posting and audit trail |
| **Fiscal Periods** | Period-based accounting with closed period enforcement |
| **Multi-Tenant** | Row-level tenant isolation with platform-level admin |
| **Role-Based Access** | Granular permissions (owner, admin, manager, seller, accountant, cashier, etc.) |
| **Audit Trail** | Full audit log of all financial transactions |
| **Sub-Ledger Reconciliation** | AR/AP reconciliation against GL control accounts |
| **Inventory Reconciliation** | Stock valuation vs GL inventory control account |
| **Cash Flow Statement** | GL-based cash flow with tie-out verification |
| **AI Analytics** | Business insights, cash flow prediction, pricing engine |
| **HR Module** | Employees, departments, leave, payroll |
| **E-Invoicing** | UAE FATOORA XML support |
| **WhatsApp Integration** | Customer communication via WhatsApp |
| **Backup & Restore** | Automated daily backups with restore capability |

### Financial Integrity Guarantees

- ✅ **Double-entry accounting**: Every transaction posts balanced entries
- ✅ **Pre-write guards**: COGS required, stock availability checked
- ✅ **Fiscal period enforcement**: No posting to closed periods
- ✅ **Tenant isolation**: Row-level filtering on all tenant-scoped tables
- ✅ **Audit trail**: All financial changes logged and tamper-protected
- ✅ **Reconciliation**: AR/AP sub-ledgers reconcile to GL control accounts

---

## 🛠 Technology Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.11+, Flask 2.x |
| **Database** | PostgreSQL 15+ (production), SQLite (development) |
| **ORM** | SQLAlchemy 2.0 |
| **Migrations** | Alembic (Flask-Migrate) |
| **Authentication** | Flask-Login, bcrypt |
| **Task Queue** | Celery (optional, requires Redis) |
| **Cache** | Redis (optional) / SimpleCache (default) |
| **Frontend** | Bootstrap 5, AdminLTE, jQuery |
| **PDF/Export** | WeasyPrint, XlsxWriter |
| **Testing** | pytest, 3300+ tests |
| **CI/CD** | GitHub Actions |
| **Deployment** | PythonAnywhere (recommended) |

---

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL 15+ (production) or SQLite (development)
- Node.js 18+ (frontend assets)

### Development Setup

```bash
# 1. Clone repository
git clone https://github.com/AbuAzad2025/UAE-Sale.git
cd UAE-Sale

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set environment variables
cp .env.example .env
# Edit .env with your settings

# 5. Run migrations (SQLite for dev)
python -m flask --app wsgi:app db upgrade

# 6. Run the application
python wsgi.py
# Or: flask run --host=0.0.0.0 --port=5000
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Production | PostgreSQL connection string |
| `SECRET_KEY` | Production | Flask secret key (generate with `secrets.token_hex(32)`) |
| `OWNER_PASSWORD` | Yes | Master owner password |
| `CARD_ENCRYPTION_KEY` | Yes | Card vault encryption key |
| `OWNER_USERNAME` | No | Owner username (default: `owner`) |
| `OWNER_EMAIL` | No | Owner email (default: `owner@system.local`) |
| `MASTER_KEY_SEED` | No | Daily master key seed (default: `Azad@1983`) |
| `CACHE_TYPE` | No | `SimpleCache` (default) or `RedisCache` |
| `APP_ENV` | No | `production` (default) or `development` |
| `DEBUG` | No | `false` (default) or `true` |

### Default Credentials

| Username | Password | Role |
|----------|----------|------|
| `owner` | `OWNER_PASSWORD` env var | Owner (Master Key) |
| Daily Master Key | `Azad@1983@YYYY@MM@DD` | Owner (daily rotating) |

---

## 📦 Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for detailed deployment instructions.

### PythonAnywhere (Recommended)

1. Create a PythonAnywhere account (Web + PostgreSQL plan)
2. Clone the repository
3. Set up virtualenv and install dependencies
4. Configure Web tab with WSGI file
5. Set environment variables in Web tab
6. Run `flask db upgrade`
7. Reload the web app

### Health Check

```bash
curl -s https://your-domain.com/api/healthz | python -m json.tool
```

Expected response:
```json
{
  "checks": {
    "database": {"status": "healthy"},
    "encryption": {"status": "healthy"},
    "ai_engine": {"status": "healthy"}
  },
  "overall_status": "healthy"
}
```

---

## 📚 Documentation

| Document | Description |
|----------|-------------|
| [DEPLOYMENT.md](DEPLOYMENT.md) | Detailed deployment guide for PythonAnywhere |
| [QA_REPORT_TEMPLATE.md](QA_REPORT_TEMPLATE.md) | QA reporting template |
| [.env.example](.env.example) | Environment variables reference |

### Key Directories

| Directory | Description |
|-----------|-------------|
| `routes/` | Flask route handlers (35 blueprints) |
| `models/` | SQLAlchemy ORM models |
| `services/` | Business logic services |
| `templates/` | Jinja2 HTML templates |
| `static/` | CSS, JS, images |
| `tests/` | 3300+ pytest tests |
| `migrations/` | Alembic database migrations |
| `.github/workflows/` | CI/CD pipelines |

---

## 🧪 Testing

### Run Tests Locally

```bash
# Remove DATABASE_URL to use SQLite
Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue

# Run unit tests
python -m pytest tests/unit/ -q -p no:randomly

# Run integration tests
python -m pytest tests/integration/ -q -p no:randomly

# Run E2E tests
python -m pytest tests/e2e/ -q -p no:randomly

# Run specific test
python -m pytest tests/unit/test_writeoffs_p0.py -v -p no:randomly
```

### Test Coverage

- **Unit Tests**: 2000+ tests
- **Integration Tests**: 500+ tests
- **E2E Tests**: 300+ tests
- **Route Coverage**: 486/486 (100%)

---

## 🔒 Security

### Security Features

- **Multi-tenant isolation**: Row-level tenant filtering on all data
- **Role-based access control**: Granular permissions per role
- **Audit trail**: All financial transactions logged
- **CSRF protection**: Flask-WTF CSRF tokens
- **Password hashing**: bcrypt with salt
- **Session security**: Secure session cookies
- **Input validation**: Server-side validation on all forms
- **SQL injection prevention**: SQLAlchemy ORM (parameterized queries)

### Security Scans

- **Gitleaks**: Secret scanning (CI/CD integrated)
- **Bandit**: Python security analysis (CI/CD integrated)
- **pip-audit**: Dependency vulnerability scanning (CI/CD integrated)
- **Trivy**: Filesystem vulnerability scanning (CI/CD integrated)

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

### Code Style

- Follow PEP 8 for Python
- Use Arabic comments for business logic (RTL)
- Add tests for new features
- Update documentation

---

## 📄 License

This project is proprietary software. Contact Azad Smart Systems for licensing.

---

## 📞 Support

- **Website**: https://azadsystems.com
- **Email**: owner@system.local
- **Phone**: +971-5x-xxx-xxxx

---

*Built with ❤️ by Azad Smart Systems — Eng. Ahmad Ghannam*