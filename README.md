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
| **Maintenance** | Reception, diagnosis/repair, parts/services, warranty, discounts, invoices/receipts/printing, returns, accounting, cost reports |

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

### Maintenance Module Features

| Feature | Description | Permissions |
|---------|-------------|-------------|
| **Reception** | Create maintenance orders, device intake, customer info | `maintenance_receive` |
| **Diagnosis & Repair** | Add parts (at actual cost), services (labor tracking), status changes | `maintenance_work` |
| **Parts/Services Issue** | Post parts issue at actual moving-average cost to GL | `maintenance_work` |
| **Discounts** | Order-level discount with cap enforcement | `maintenance_discount` |
| **Warranty** | Warranty status tracking, warranty expense reclassification (6401) | `maintenance_work` |
| **Invoices** | Post invoice: revenue (net), VAT, labor cost accrual to Salaries Payable | `maintenance_close` |
| **Receipts** | Cash/bank collection, deposit receipts with GL posting | `maintenance_cashier` |
| **Printing** | Print receipt, invoice, intake with historical record banners | `maintenance_view` |
| **Returns** | Return parts after billing with credit note reversal | `maintenance_close` |
| **Credit Notes** | Reverse invoice revenue/VAT, unblock returns after billing | `maintenance_close` |
| **Cost Report** | Actual parts cost + labor cost vs net revenue analysis | `maintenance_view` |
| **Purchases** | Purchase parts from supplier, goods receipt, supplier payment | `maintenance_purchase` |
| **Device Registry** | Device serial numbers, warranty eligibility checks | `maintenance_settings` |
| **Quality Check** | Quality check recording, completion time tracking | `maintenance_work` |

### Financial Integrity Guarantees

- ✅ **Double-entry accounting**: Every transaction posts balanced entries
- ✅ **Pre-write guards**: COGS required, stock availability checked
- ✅ **Fiscal period enforcement**: No posting to closed periods
- ✅ **Tenant isolation**: Row-level filtering on all tenant-scoped tables
- ✅ **Audit trail**: All financial changes logged and tamper-protected (append-only)
- ✅ **Reconciliation**: AR/AP sub-ledgers reconcile to GL control accounts
- ✅ **No duplicate postings**: `_assert_not_posted` prevents duplicate GL entries per document reference
- ✅ **Fail-closed feature gates**: `utils/feature_guards.py` fails closed (503) on verification failure
- ✅ **No unsafe tenant derivation**: Tenant never derived from `current_user.id`

---

## 🛠 Technology Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.11+, Flask 3.1+ |
| **Database** | PostgreSQL 15+ (stable dev DB on `localhost:5433` / `ERPLite2026`; production Postgres); SQLite in-memory only for isolated unit tests |
| **ORM** | SQLAlchemy 2.0 |
| **Migrations** | Alembic (Flask-Migrate) — 71 revisions, head `b49_alter_column_widths` |
| **Authentication** | Flask-Login, Werkzeug PBKDF2 (`generate_password_hash`); daily master key for the owner |
| **Task Queue** | Celery (optional, requires Redis) |
| **Cache** | Redis (optional) / SimpleCache (default) |
| **Frontend** | Bootstrap 5, AdminLTE, jQuery |
| **PDF/Export** | WeasyPrint, openpyxl |
| **Testing** | pytest — see [Testing](#testing) for current counts |
| **CI/CD** | GitHub Actions — 8 green jobs in `ci.yml`, plus `e2e.yml` and `alembic_roundtrip.yml` |
| **Deployment** | Render (container + persistent disk via `DATA_DIR=/data`); see [DEPLOYMENT.md](DEPLOYMENT.md) |

---

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL 15+ (the stable local dev DB runs on `localhost:5433`, database `ERPLite2026`; see `.env`)
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

# 5. Run migrations (PostgreSQL — dev DB ERPLite2026, or your configured DATABASE_URL)
python -m flask --app wsgi:app db upgrade head

# 6. Run the application (dev serves at http://localhost:5000/)
python app.py
# Or: flask --app wsgi:app run --host=0.0.0.0 --port=5000
# Production uses gunicorn via the Procfile.
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes (dev & prod) | PostgreSQL connection string (`postgresql://…@localhost:5433/ERPLite2026` in dev) |
| `SECRET_KEY` | Production | Flask secret key (generate with `secrets.token_hex(32)`); auto-generated & persisted if unset |
| `OWNER_PASSWORD` | Deprecated | Ignored for login — the owner has a random password and authenticates via the daily master key |
| `CARD_ENCRYPTION_KEY` | Production | Card vault encryption key |
| `OWNER_USERNAME` | No | Owner username (default: `owner`) |
| `OWNER_EMAIL` | No | Owner email (default: empty) |
| `MASTER_KEY_SEED` | No | Seed for the daily master key; if unset, auto-generated and persisted to `instance/master_seed`. Format: `<seed>@YYYY@MM@DD` (UTC) |
| `DATA_DIR` | Production | Persistent root for backups/uploads (Render mounts `/data`); defaults to `instance/` |
| `CACHE_TYPE` | No | `SimpleCache` (default) or `RedisCache` |
| `APP_ENV` | No | `production` (default) or `development` |
| `DEBUG` | No | `false` (default) or `true` |
| `APP_VERSION` | No | Reported version (default: `1.0.0`) |

### Default Credentials

| Username | Password | Role |
|----------|----------|------|
| `owner` | Daily master key (not a fixed password) | Owner / platform admin |
| Daily Master Key | `<seed>@YYYY@MM@DD` (e.g. `Azad@1983@2026@11@18`) | Owner (UTC daily rotating) |

The master key seed comes from `MASTER_KEY_SEED`, else `instance/master_seed`, else an auto-generated persisted value. `OWNER_PASSWORD` does **not** enable login.

---

## 📦 Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for detailed deployment instructions.

### Render (current deployment target)

The repository ships `render.yaml` (web service + PostgreSQL + 1 GB persistent disk mounted at `/data`) and a `Procfile` (gunicorn). Backups and uploads live on the persistent disk via `DATA_DIR=/data` so they survive redeploys. See [DEPLOYMENT.md](DEPLOYMENT.md) for the full guide.

1. Create the services from `render.yaml` (or use the Render dashboard)
2. Set `SECRET_KEY`, `OWNER_PASSWORD`, and `MASTER_KEY_SEED` (`sync: false` — set them manually)
3. Run `flask db upgrade head` once against the production DB
4. Health check path: `/api/health`

> **No deployment has been performed yet.** These are the prepared deployment assets, not a live environment.

### Health Check

```bash
curl -s http://localhost:5000/api/healthz | python -m json.tool
# or on the deployed domain: curl -s https://your-domain.com/api/healthz
```

Expected response (five checks — `nowpayments` may be a warning before the vault is initialized):
```json
{
  "checks": {
    "database": {"status": "healthy"},
    "nowpayments": {"status": "healthy"},
    "encryption": {"status": "healthy"},
    "system": {"status": "healthy"},
    "ai_engine": {"status": "healthy"}
  },
  "overall_status": "healthy"
}
```

---

## 📚 Documentation

| Document | Description |
|----------|-------------|
| [docs/USER_GUIDE.md](docs/USER_GUIDE.md) | **Complete user guide** (Arabic + English) — all modules |
| [docs/TECHNICAL_STATUS.md](docs/TECHNICAL_STATUS.md) | **Authoritative current-state report** — architecture, isolation, security, finance, CI, deployment |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Deployment guide (Render + local dev) |
| [docs/MIGRATIONS.md](docs/MIGRATIONS.md) | Migration chain & golden rules |
| [CHANGELOG.md](CHANGELOG.md) | Version history & current-state notes |
| [.env.example](.env.example) | Environment variables reference |

> `FULL_USER_GUIDE.md` and `OWNER_USER_GUIDE.md` at the repo root are the
> machine-readable guides consumed by the AI assistant (`ai_knowledge/guide_loader.py`);
> the human-facing guide is `docs/USER_GUIDE.md`. Older per-topic audit reports were
> consolidated into `docs/TECHNICAL_STATUS.md` (2026-11-18).

### Key Directories

| Directory | Description |
|----------|-------------|
| `routes/` | Flask route handlers (37 blueprints) |
| `models/` | SQLAlchemy ORM models (~103 classes) |
| `services/` | Business logic services (GL posting is service-layer, `GLService`, flush-only) |
| `templates/` | Jinja2 HTML templates |
| `static/` | CSS, JS, images |
| `tests/` | pytest suites (`unit`, `security`, `integration`, `e2e`, `simulation`) |
| `migrations/` | Alembic migrations (71 revisions, head `b49_alter_column_widths`) |
| `.github/workflows/` | CI/CD pipelines (`ci.yml`, `e2e.yml`, `alembic_roundtrip.yml`) |

---

## 🧪 Testing

### Run Tests Locally

```bash
# Unit + security (in-memory SQLite; no DATABASE_URL needed)
python -m pytest tests/unit/ tests/security/ -q -p no:randomly

# Integration (real PostgreSQL; set DATABASE_URL, ALLOW_DESTRUCTIVE_POSTGRES_TESTS=1)
python -m pytest tests/integration/ -q -p no:randomly

# E2E vertical slice (305 tests; the big combinatorial matrix runs in CI shards)
python -m pytest tests/e2e/ --ignore=tests/e2e/test_matrix.py -q -p no:randomly

# PostgreSQL-only financial integrity tests (run in CI's alembic-smoke job)
python -m pytest tests/unit/test_financial_seed_integrity.py \
  tests/unit/test_financial_domains_integrity.py \
  tests/unit/test_financial_gaps_integrity.py -q -p no:cacheprovider -o addopts=

# Run a specific test
python -m pytest tests/unit/test_writeoffs_p0.py -v -p no:randomly
```

### Test Coverage

| Test Suite | Count | Description |
|------------|-------|-------------|
| **Unit** | ~3,577 | Business logic, GL/reports, tenant isolation, feature gates, schema parity, financial seeds |
| **Security** | ~80 | Tenant isolation / zero-trust, maintenance finance & safety |
| **Integration** | ~507 | Full HTTP-level tests on real PostgreSQL |
| **E2E vertical slice** | ~305 | Browser-path smoke tests over real HTTP with CSRF |
| **E2E combinatorial matrix** | ~28,350 | 30 domains × 2 CI shards (`e2e.yml`) |
| **Route census** | ≥545 | Every route classified by isolation scope (`test_route_isolation_census.py`) |

All CI workflows are green: `ci.yml` (8 jobs: lint, security-scan, verify-boot, frontend, test, integration, repo-security, alembic-smoke), `e2e.yml`, and `alembic_roundtrip.yml`.

### Permanent financial-integrity tests

- `tests/unit/test_financial_seed_integrity.py` — sale, payment, purchase+VAT, return, write-off
- `tests/unit/test_financial_domains_integrity.py` — cheques, multi-currency/FX, maintenance, payroll
- `tests/unit/test_financial_gaps_integrity.py` — fixed assets/depreciation, maintenance sub-types, partner shares, FX-difference
- `tests/unit/test_feature_gates.py` — package flags are real HTTP controls (403 disabled / 503 fail-closed)
- `tests/unit/test_schema_parity.py` — model/migration drift guard

---

## 🔒 Security

### Security Features

- **Load-time tenant isolation**: `do_orm_execute` + `with_loader_criteria` (`install_tenant_loader_criteria()`) filters all ~79 registered tenant-scoped tables — including `session.get()`, relationships, aliases and paginated queries. A `before_flush` guard stamps/validates `tenant_id` on writes. Platform rows (roles, tax rulesets, fiscal periods) stay visible via an `OR tenant_id IS NULL` criterion. See [docs/TECHNICAL_STATUS.md](docs/TECHNICAL_STATUS.md).
- **Role-based access control**: Granular permissions per role (27 seeded codes)
- **Feature gates (package enforcement)**: `install_feature_gate()` on `api`, `ai`, `ledger` (`gl`), `reports`, `maintenance`, `api_enhanced`, `api_analytics`, `graphql`. Disabled feature → 403; verification failure → 503 (fail-closed); infra endpoints exempt. `enable_api` defaults to **False**; other `enable_*` flags default True.
- **Audit trail**: All financial transactions logged (append-only, soft-delete via `b41`)
- **CSRF protection**: Flask-WTF CSRF tokens
- **Password hashing**: Werkzeug PBKDF2 with per-user salt; owner authenticates via a daily master key
- **Session security**: Secure session cookies + inactivity timeout
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