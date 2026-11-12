# 🏛️ Architectural, Security & Financial-Correctness Audit Report

> **Role:** Principal Software Architect · Systems Auditor · CISO
> **System:** UAE-Sale Multi-Tenant Enterprise ERP & Financial Ledger
> **Date:** 2026-11-12
> **Scope:** Codebase, routing layer, background worker architecture, database persistence boundary
> **Applicability:** Universally adaptable to any production-grade accounting/ERP system

---

## Executive Summary

The UAE-Sale ERP is a mature, feature-rich multi-tenant platform (37 blueprints, 75 services, 51 models, 277 templates, 60 Alembic migrations) with strong foundational architecture: ORM-level tenant scoping, double-entry GL, moving-weighted-average inventory costing, Celery background workers with per-tenant scoping, and extensive test coverage (233+ Python tests, 17 TS tests, CI pipelines).

**Overall Posture: STRONG with targeted hardening opportunities.**

- **P0 (Critical):** No unmitigated cross-tenant breaches or data-destruction vectors found. Tenant isolation is enforced at ORM query level + Celery uses `_run_per_tenant`. Bulk DML is scoped (owner-only cleanup) or by foreign key.
- **P1 (High):** 103 service-layer `.commit()` calls (transaction boundary ownership violation); 927 `float()` calls (precision leaks, ~40 in financial-critical paths); 10 routes with unguarded `int/float(request...)` conversions.
- **P2/P3 (Medium/Low):** Orphan permission `admin` (fixed); audit-log deletion (compliance); raw SQL in migrations (expected/acceptable).

---

## Phase 1: Comprehensive Security & Integrity Audit Vectors

### 1.1 Tenant Isolation & Multi-Tenant Boundaries

#### ✅ Strengths
- **ORM-level tenancy filter:** `models/tenant_scope.py` installs SQLAlchemy events (`before_compile`, `before_flush`) that auto-inject `tenant_id` predicates on all tenant-scoped models. `TENANT_STRICT` mode blocks cross-tenant access.
- **TenantScopedMixin:** All business models inherit it; import-time assertion ensures `tenant_id` column exists.
- **Celery workers:** Use `_tenant_scopes()` + `_run_per_tenant()` to iterate active tenants and run each task inside `run_in_tenant_context(tenant_id, func)`. Cross-tenant leaks neutralized.
- **Webhooks/external ingestion:** `services/webhook_service.py`, `services/nowpayments_service.py` derive tenant from authenticated credentials (API keys), not payload bodies.
- **Owner routes:** Platform-level (owner/super_admin) with `admin_required` flag checks.

#### ⚠️ Findings
| ID | Severity | Finding | Location |
|----|----------|---------|----------|
| T-1 | P2 | Owner data-cleanup bulk deletes `AuditLog` and `ArchivedRecord` by date only (no tenant filter) — acceptable (owner-only, platform maintenance) but deletes audit trail (compliance concern) | `routes/owner.py:2914-2916` |
| T-2 | P2 | `AuditLog` model may not be tenant-scoped (verify) — if tenant-scoped, the cleanup bypasses tenant filter via bulk `.delete()` | `routes/owner.py` |
| T-3 | P3 | Celery `_tenant_scopes()` falls back to `run_in_platform_context` when no tenants exist (could run unscoped on empty DB) | `services/celery_tasks.py` |

#### 🛡️ Remediation
- T-1: Add `archived_by_tenant` filter or scope cleanup to per-tenant. Consider soft-delete or retention policy instead of hard delete (audit immutability).
- T-2: Verify `AuditLog` is registered in `_tenant_scoped_tables`; if yes, add explicit tenant predicate or use per-tenant iteration.
- T-3: Guard platform-context fallback with explicit allow-list of tasks that may run globally.

---

### 1.2 Transaction Safety & Atomicity

#### ✅ Strengths
- Routing layers own `commit`/`rollback` in most flows (sales, purchases, maintenance).
- `StockService` uses `begin_nested()` savepoints to isolate stock movement failures.
- `SELECT ... FOR UPDATE` used in `StockService.create_movement` (`with_for_update=True`).
- `db.session.flush()` used to obtain IDs before commit.

#### ⚠️ Findings
| ID | Severity | Finding | Location |
|----|----------|---------|----------|
| A-1 | P1 | **103 `.commit()` calls in 26 service files** — services own transaction boundaries, violating the architectural rule that only routing layers/transaction managers should commit. Risk: partial commits, inconsistent state on partial failure. | `services/*.py` (top: `erp_modules_service.py` 21, `hr_service.py` 9, `ai_commands.py` 8, `payment_service.py` 6, `sale_service.py` 4) |
| A-2 | P1 | **25 `.rollback()` calls in services** — paired with commits; indicates services handle their own error recovery, which can mask failures or leave connections in inconsistent state. | `services/*.py` |
| A-3 | P2 | Inbound shipment `put_away` calls `StockService.adjust_stock(..., post_gl=False)` then `db.session.commit()` — if stock movement succeeds but PO status update fails, partial commit possible (mitigated by savepoint in adjust_stock). | `services/inbound_shipment_service.py` |
| A-4 | P2 | `PurchaseOrderService.receive_po` now commits after stock+GL (fixed in this session) — verify atomicity of stock+GL+PO status. | `services/erp_modules_service.py` |

#### 🛡️ Remediation
- A-1: Refactor services to **flush-only**; move `commit`/`rollback` to route handlers or a `@transactional` decorator/manager. Introduce `TransactionManager` wrapper. Estimated effort: high (103 call sites).
- A-2: Pair with A-1; services raise exceptions, routes decide rollback.
- A-3/A-4: Wrap multi-step operations in explicit `try/except/rollback` at route level.

---

### 1.3 Input Validation & Financial Data Precision

#### ✅ Strengths
- `Decimal` used extensively in models (`Numeric(15,3)`), services (`CostingService`, `CurrencyService`).
- `ROUND_HALF_UP` rounding in financial calculations.
- `safe_float()` helper in routes with fallback.
- Tax treatment validation (`standard`/`zero`/`exempt`).

#### ⚠️ Findings
| ID | Severity | Finding | Location |
|----|----------|---------|----------|
| V-1 | P1 | **927 `float()` calls** across codebase — many in financial paths (`routes/products.py` 28, `routes/sales.py` 14, `models/sale.py` 10, `services/aging_analysis_service.py` 33, `services/cash_flow_service.py` 38). Binary float can introduce rounding errors in monetary calculations. | Multiple |
| V-2 | P1 | **10 routes** with unguarded `int(request...)/float(request...)` conversions — can raise `ValueError`/`TypeError` → 500 instead of 400. | `routes/advanced_ledger.py`, `approvals.py`, `auth.py`, `customers.py`, `maintenance.py`, `owner.py`, `payment_vault.py`, `products.py`, `purchases.py`, `sales.py` |
| V-3 | P1 | **Silent-zero coercion:** `safe_float(value, default=0.0)` returns 0.0 for invalid input — can silently create zero-cost products, tax-free transactions. (Partially mitigated: maintenance module uses `_decimal()` with validation.) | `routes/products.py`, `routes/purchases.py` |
| V-4 | P2 | `float()` in `models/sale.py` and `models/events.py` for financial fields. | `models/sale.py`, `models/events.py` |
| V-5 | P3 | `_decimal()` helper in maintenance service raises `ValidationError` on invalid input (good pattern) — should be adopted platform-wide. | `services/maintenance_service.py` |

#### 🛡️ Remediation
- V-1: Replace `float()` with `Decimal()` in all financial paths. Keep `float()` only for display/reporting (with explicit conversion at boundary). Estimated: ~40 financial-critical call sites.
- V-2: Wrap all `int(request...)/float(request...)` in try/except → return 400. Or use WTForms validators. Adopt `_decimal()` pattern platform-wide.
- V-3: Remove silent-zero coercion in financial fields; raise `ValidationError` instead. Keep 0.0 default only for non-financial (quantities, alerts).
- V-4/V-5: Adopt maintenance module's `_decimal()` helper as platform standard.

---

### 1.4 Authentication, Authorization & Secrets Management

#### ✅ Strengths
- All secrets from env vars (`.env` gitignored). `config.py` reads from environment.
- CSRF protection (Flask-WTF) on all forms.
- Rate limiting (`Flask-Limiter`) on login, product creation, purchases.
- `permission_required` decorator on all gated routes.
- `must_change_password` enforced on first login.
- Login lockout after failed attempts.
- Cost visibility permission-driven (`can_see_costs()`).

#### ⚠️ Findings
| ID | Severity | Finding | Location |
|----|----------|---------|----------|
| S-1 | P1 | **Weak dev secrets in `.env` on disk:** `SECRET_KEY=test-secret-key`, `CARD_ENCRYPTION_KEY=test-card-enc-key`, `OWNER_PASSWORD=test-owner-password`, `DATABASE_URL=postgresql://postgres:123@...`, `MASTER_KEY_SEED=Azad@1983`. Not committed but on disk; risk if deployed as-is. | `.env` (gitignored) |
| S-2 | P1 | **Hardcoded licensing seed** (obfuscated char codes = "Azad@1983") in `utils/licensing.py` — overridable via `MASTER_KEY_SEED` env but default is weak and discoverable. | `utils/licensing.py` |
| S-3 | P2 | **`render.yaml` ships `APP_ENV=development` and `SYSTEM_INTEGRITY_FORCE=1`** in production start command — dev mode in production. | `render.yaml` |
| S-4 | P2 | **Auto-generation of `SECRET_KEY`/`CARD_ENCRYPTION_KEY`** to `instance/secret_key` / random if env missing — breaks sessions/decryption across deploys. Should fail-closed in production. | `config.py` |
| S-5 | P2 | **`OWNER_PASSWORD` optional** (warns only) — should be required in production. | `config.py` |
| S-6 | P3 | **`admin` permission orphan** (fixed in this session). | `utils/system_init.py` |
| S-7 | P3 | **Excel import permission gate** (fixed in this session — added `manage_products`). | `routes/ai.py` |

#### 🛡️ Remediation
- S-1: Remove `.env` from disk or replace with production values; add pre-deploy check.
- S-2: Remove hardcoded seed; require `MASTER_KEY_SEED` env var (fail-closed).
- S-3: Change `render.yaml` to `APP_ENV=production`, remove `SYSTEM_INTEGRITY_FORCE=1`.
- S-4: Fail-closed in production if `SECRET_KEY`/`CARD_ENCRYPTION_KEY` missing.
- S-5: Require `OWNER_PASSWORD` in production (fail-closed).
- S-6/S-7: Fixed.

---

### 1.5 Public/Unauthenticated Routes

#### ✅ Strengths
- Public routes (public_bp, auth login) have rate limiting.
- Login lockout after failed attempts.
- CSRF on all forms.

#### ⚠️ Findings
| ID | Severity | Finding | Location |
|----|----------|---------|----------|
| P-1 | P2 | Public checkout/notification relay endpoints need abuse prevention audit (rate limits, payload size limits). | `routes/public.py`, `routes/whatsapp.py` |
| P-2 | P3 | `websocket_bp` defined but not registered — dead code. | `app.py` |

---

## Phase 2: Systematic Remediation Plan

### P0 (Critical / Data Destruction / Cross-Tenant Breach)
**Status: No unmitigated P0 findings.** Tenant isolation is enforced at ORM level; Celery uses per-tenant scoping; bulk DML is owner-only or FK-scoped.

| Item | Action | Effort |
|------|--------|--------|
| Verify AuditLog tenant-scoping | Check `_tenant_scoped_tables`; if scoped, add tenant predicate to owner cleanup | Low |
| Guard Celery platform-context fallback | Allow-list global tasks only | Low |

### P1 (High / Data Loss / Financial Inaccuracy / Security Exposure)

| # | Item | Action | Effort | Files |
|---|------|--------|--------|-------|
| 1 | Service-layer commits (A-1) | Refactor 103 `.commit()` calls to flush-only; move commit/rollback to routes or `@transactional` decorator | High | 26 service files |
| 2 | Float precision leaks (V-1) | Replace `float()` with `Decimal()` in 40 financial-critical call sites (products, sales, sale model, aging, cash flow) | Medium | `routes/products.py`, `routes/sales.py`, `models/sale.py`, `services/aging_analysis_service.py`, `services/cash_flow_service.py`, `models/events.py` |
| 3 | Unguarded int/float conversions (V-2) | Wrap in try/except → 400; adopt `_decimal()` pattern platform-wide | Medium | 10 route files |
| 4 | Silent-zero coercion (V-3) | Remove 0.0 fallback in financial fields; raise ValidationError | Medium | `routes/products.py`, `routes/purchases.py` |
| 5 | Weak dev secrets (S-1, S-2) | Remove `.env` from disk or replace; remove hardcoded licensing seed | Low | `.env`, `utils/licensing.py` |
| 6 | Production config (S-3, S-4, S-5) | `render.yaml`: APP_ENV=production; fail-closed on missing secrets | Low | `render.yaml`, `config.py` |

### P2 (Medium / Robustness)

| # | Item | Action | Effort |
|---|------|--------|--------|
| 7 | Audit-log deletion compliance (T-1) | Soft-delete or retention policy instead of hard delete | Medium |
| 8 | Inbound shipment atomicity (A-3) | Wrap put_away in try/except/rollback at route level | Low |
| 9 | Public route abuse prevention (P-1) | Rate limits + payload size limits on public/whatsapp endpoints | Low |
| 10 | Remove dead `websocket_bp` registration (P-2) | Remove unused blueprint | Low |
| 11 | Adopt `_decimal()` platform-wide (V-5) | Extract to `utils/validation.py`, use in all routes | Medium |

### P3 (Low / Cleanup)

| # | Item | Action | Effort |
|---|------|--------|--------|
| 12 | Remove orphan `admin` permission (S-6) | ✅ Done in this session | — |
| 13 | Excel import permission gate (S-7) | ✅ Done in this session | — |
| 14 | Remove `template_products.xlsx` reference cleanup | ✅ Done in this session | — |

---

## Phase 3: Automated Verification & Compliance Gates

### 3.1 Static Analysis Rules

| Rule | Tool | Description |
|------|------|-------------|
| No service-layer commits | Custom AST lint / Semgrep | Flag `.commit()` calls in `services/` (except transaction managers) |
| No unscoped bulk DML | Semgrep/AST | Flag `.query...delete()`/`.update()` without tenant filter in non-owner routes |
| No float in financial paths | Ruff custom rule / Semgrep | Flag `float(` in `models/`, `services/*gl*`, `services/*cost*`, `services/*tax*` |
| No hardcoded secrets | Gitleaks (already configured) | `.gitleaks.toml` patterns for API keys, passwords, seeds |
| No raw SQL in app code | Bandit B608 | Flag `text()` with string interpolation (migrations exempt) |

### 3.2 Test Coverage Gates

| Gate | Metric | Target |
|------|--------|--------|
| Unit tests (SQLite) | Pass rate | 100% |
| Integration tests (PostgreSQL) | Pass rate | 100% |
| E2E tests | Pass rate | 100% |
| Security tests | Pass rate | 100% |
| Frontend tests (Vitest) | Pass rate | 100% |
| Alembic round-trip | Pass | 100% |
| Coverage (core accounting) | Line coverage | ≥ 90% |
| Coverage (stock valuation) | Line coverage | ≥ 90% |
| Coverage (data ingestion) | Line coverage | ≥ 85% |

### 3.3 CI Pipeline (existing + recommended additions)

**Existing (`.github/workflows/ci.yml`):**
- ✅ Unit tests (SQLite)
- ✅ Integration tests (PostgreSQL) with `ALLOW_DESTRUCTIVE_POSTGRES_TESTS=1`
- ✅ E2E tests
- ✅ Frontend tests (Vitest)
- ✅ Security scan (Bandit + Gitleaks + pip-audit)
- ✅ Alembic round-trip

**Recommended additions:**
- Add static analysis gate (Semgrep/Bandit) with `--severity high` blocking
- Add coverage threshold enforcement (`--cov-fail-under=85`)
- Add dependency vulnerability scan (Trivy — already in CI)
- Add migration lint (ensure no `db.create_all()` in production paths)

### 3.4 Production Readiness Checklist

- [ ] All P0 findings mitigated (✅ None unmitigated)
- [ ] All P1 findings addressed or risk-accepted with documented justification
- [ ] P2 findings addressed or scheduled
- [ ] No hardcoded secrets in tracked files (Gitleaks clean)
- [ ] `.env` removed from disk or contains production values
- [ ] `render.yaml` uses `APP_ENV=production`
- [ ] `SECRET_KEY`, `CARD_ENCRYPTION_KEY`, `OWNER_PASSWORD` set via env (fail-closed)
- [ ] `MASTER_KEY_SEED` set via env (no hardcoded default)
- [ ] All CI gates green on latest commit
- [ ] Database migrations applied (`alembic upgrade head`)
- [ ] Backup/restore tested
- [ ] Monitoring/alerting configured

---

## Appendix A: Codebase Metrics

| Metric | Value |
|--------|-------|
| Route blueprints | 37 active |
| Service files | 75 |
| Model files | 51 |
| Template files | 277 |
| Static files | 2,148 |
| Migrations | 60 (head: `b38_maintenance_multi_currency`) |
| Test files (Python) | 233 |
| Test files (TS) | 17 |
| Permissions (production) | 26 |
| Roles | 16 (3 platform + 13 operational) |
| Service-layer `.commit()` calls | 103 |
| `float()` calls | 927 |
| `int/float(request...)` conversions (unguarded) | 10 routes |
| Celery task functions | 14 |

## Appendix B: Key Files Reference

| Purpose | File |
|---------|------|
| App factory | `app.py::create_app()` |
| Tenant scoping | `models/tenant_scope.py` |
| Permission seeding | `utils/system_init.py` |
| Stock service | `services/stock_service.py` |
| Costing service | `services/costing_service.py` |
| GL service | `services/gl_service.py` |
| Currency service | `services/currency_service.py` |
| Celery tasks | `services/celery_tasks.py` |
| Maintenance service | `services/maintenance_service.py` |
| Maintenance accounting | `services/maintenance_accounting.py` |
| Auth routes | `routes/auth.py` |
| Owner routes | `routes/owner.py` |
| Product routes | `routes/products.py` |
| Purchase routes | `routes/purchases.py` |
| Sales routes | `routes/sales.py` |
| Maintenance routes | `routes/maintenance.py` |

---

**End of Audit Report.** Prepared by Principal Software Architect / Systems Auditor / CISO.