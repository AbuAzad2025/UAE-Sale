# UAE-Sale ERP

Flask/SQLAlchemy/PostgreSQL ERP for automotive parts businesses in the UAE.

## Features

### Multi-Tenant Row-Level Isolation
- Every business table (Sales, Customers, Products, Purchases, Payments, etc.) is scoped to a tenant via `tenant_id` FK.
- Automatic query filtering via SQLAlchemy `before_compile` event — no manual filtering needed.
- Owner user bypasses tenant filtering; non-owner users see only their tenant's data.
- Alembic migration backfills existing rows to the default tenant (non-destructive).

### Configurable Approval Workflows
- Multi-level approval chains (e.g., "Sales > 10,000 AED → manager → owner").
- Amount thresholds with min/max ranges, per entity type (sale, payment, purchase).
- Full audit trail on submit/approve/reject.
- API: `POST /approvals/submit`, `POST /approvals/<id>/approve`, `POST /approvals/<id>/reject`.

### Reports & Export
- **Inventory Valuation** — stock qty × cost by category.
- **AP Aging** — supplier payables bucketed 0-30/31-60/61-90/90+ days.
- **Cash Flow Statement** — operating/investing/financing from GL data.
- **VAT Report** — UAE 5% VAT (output − input = net payable).
- Export to Excel (.xlsx), PDF (weasyprint), and CSV with RTL Arabic support.

### Distributed Locking
- Redis-based distributed lock for `generate_number()` (sale/purchase/payment numbering).
- Applied to balance repair operations.
- Falls back to in-process lock if Redis is unavailable (fail-open).

### Security
- Account lockout after failed login attempts.
- IDOR protection on sales (sellers can only view/edit their own).
- CHECK constraints on financial columns (non-negative amounts, positive quantities).
- Rate limiting, CSRF protection, security headers.

## Running Tests

```bash
# Unit tests (SQLite, fast)
pytest tests/unit/ -v

# Integration tests (PostgreSQL, full workflow)
pytest tests/integration/ -v

# Full suite
pytest tests/unit/ tests/integration/ -v

# With coverage
pytest tests/ --cov=. --cov-config=.coveragerc --cov-report=term
```

### CI Jobs (GitHub Actions)
| Job | DB | Purpose |
|-----|-----|---------|
| `test` | SQLite | Unit tests (fast, no services) |
| `integration` | PostgreSQL 15 | Full workflow tests with migrations |
| `alembic-smoke` | PostgreSQL 15 | Verify migrations apply cleanly |
| `lint` | — | flake8 critical errors |
| `security-scan` | — | bandit + pip-audit |
| `repo-security` | — | gitleaks + trivy |

## Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run locally
DATABASE_URL=sqlite:///instance/dev.db flask run

# Run migrations
flask db upgrade head
```

## Tech Stack
- **Backend**: Flask 3.0, SQLAlchemy 2.0, Flask-Migrate/Alembic
- **Database**: PostgreSQL 15 (production), SQLite (dev/tests)
- **Cache**: Redis (optional, with in-memory fallback)
- **Auth**: Flask-Login, bcrypt
- **Export**: openpyxl (Excel), weasyprint (PDF), csv (CSV)
- **Tests**: pytest, pytest-cov
