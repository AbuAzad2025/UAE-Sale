# Changelog

All notable changes to the Azad ERP system are documented here.

## [2.0.0] - 2026-10-25

### 🔴 Major Financial Integrity Fixes (P0)

#### Multi-Tenant Isolation
- **TenantScopeMixin**: Row-level filtering on all tenant-scoped tables
- **TENANT_LESS_SCOPE**: Users without tenant see only `tenant_id IS NULL` rows
- **Fail-closed**: Authenticated users without tenant get 403
- **19 CHECK constraints** added to production schema via Alembic

#### Accounting Integrity
- **GL Service**: `purge_by_reference` refuses to delete posted entries
- **GL Model**: Type validation, system account protection, reversal linkage
- **Single Source of Truth**: AR/AP balances derived from source documents
- **Currency Conversion**: All financial reports use `amount_base` (base currency)
- **Balance Sheet**: Now verifies accounting equation (Assets = Liabilities + Equity)
- **VAT Report**: Includes returns, uses base currency
- **Cash Flow**: Ending balance read from GL, not computed

#### Inventory Integrity
- **Moving Weighted Average**: Inventory valued at `current_stock × average_cost`
- **COGS Fail-Closed**: Invoices without cost basis are rejected
- **Stock Service**: `get_warehouse_quantity` = simple SUM of movements
- **Sale Deletion**: Properly restores stock on deletion and reversal

#### Fiscal Period Guard
- **Period Enforcement**: No posting to closed or non-existent periods
- **Auto-Open**: Current fiscal year opened automatically on startup
- **Test Coverage**: Periods opened for `current_year-15 .. current_year+1`

### 🟠 New Features

#### Due Dates & Aging
- **Due Date Column**: Added to Sales and Purchases
- **Customer Payment Terms**: `payment_terms_days` on Customer
- **Overdue Buckets**: Aging based on actual overdue days, not invoice age
- **Overdue Buckets**: `not_due`, `1-30`, `31-60`, `61-90`, `90+`

#### Bad Debt Write-offs
- **WriteOff Entity**: Full lifecycle (draft → posted → void)
- **GL Posting**: Dr Bad Debt Expense (6960) / Cr AR Control (1130)
- **Tenant Scoping**: Write-offs are tenant-isolated
- **Audit Trail**: All write-offs logged
- **Reversibility**: Void reverses GL entry and restores balance

#### FX Revaluation
- **IAS 21 Compliance**: Foreign currency balances revalued at current rates
- **Scheduler**: Daily automated revaluation (03:30)
- **Idempotency**: One revaluation per currency per period
- **Reversibility**: Posted entries linked and reversible
- **Owner Route**: `/owner/fx-revaluation/` for manual runs

#### Cash Flow Tie-out
- **GL-Based**: Ending cash balance read from ledger (not computed)
- **Tie-out Verification**: Difference between GL and computed values reported
- **Template**: Tie-out box shown in cash flow report

### 🟡 Improvements

#### Route Coverage
- **486/486 routes** now covered by E2E tests (100%)
- **Frontend Contract Routes**: 10 new routes for UI integration
- **AI Endpoints**: 12 AI service bugs fixed

#### Deployment Readiness
- **PythonAnywhere**: Full deployment guide and configuration
- **Health Check**: `/api/healthz` with 503 on unhealthy
- **Security**: gitleaks, bandit, pip-audit, trivy all clean
- **CI/CD**: GitHub Actions for CI, E2E, Alembic round-trip

### 🐛 Bug Fixes

- Fixed inventory valuation using last purchase cost instead of moving average
- Fixed `purge_by_reference` deleting posted entries
- Fixed `customer.balance` having 13 writers with 2 different formulas
- Fixed `Purchase.paid_amount` never being written
- Fixed `Receipt.sale_id` being empty
- Fixed allocation mixing currencies
- Fixed invoices without COGS inflating profits
- Fixed GL entries mixing transaction and base currency
- Fixed VAT report ignoring returns and mixing currencies
- Fixed audit log deletion passing silently
- Fixed AI endpoints exposing cost data
- Fixed `Session.enable_loader_criteria` not existing in SQLAlchemy 2.0
- Fixed `StockService` fail-closed behavior

### 📊 Test Suite

- **Unit Tests**: 2000+ tests
- **Integration Tests**: 500+ tests
- **E2E Tests**: 300+ tests
- **New P0 Tests**: 141 tests (due dates, write-offs, costing, cash flow, FX, aging)

### 🔒 Security

- **Gitleaks**: Secret scanning with allowlist for templates
- **Bandit**: Python security analysis
- **pip-audit**: Dependency vulnerability scanning (clean)
- **Trivy**: Filesystem vulnerability scanning
- **Tenant Isolation**: Row-level filtering verified
- **Audit Trail**: Protected from tampering

---

## [1.0.0] - 2026-09-20

### Initial Release

- Basic ERP functionality
- Sales, purchases, inventory, accounting
- Multi-currency support
- Role-based access control
- HR module
- AI analytics

---

*For detailed deployment instructions, see [DEPLOYMENT.md](DEPLOYMENT.md).*