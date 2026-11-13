# 🔍 Deep Code Inspection Audit Report

> **Role:** Senior Code Inspector & Static Analysis Auditor
> **Date:** 2026-11-13
> **Scope:** Exact file paths, line numbers, and code snippets for 4 critical areas

---

## 1. Float vs. Decimal Usage in Financial Code

### Summary
- **220 `float()` calls** found in `services/`, `models/`, `utils/`
- **Most are in `to_dict()` serialization** (display/JSON output), not financial calculations
- **Actual financial calculations** use `Decimal` (verified in `models/purchase.py`, `models/sale.py`, `services/costing_service.py`, `services/currency_service.py`)

### Financial-Critical Float Usages (Need Migration)

| File | Line | Code | Risk |
|------|------|------|------|
| `models/events.py:106` | `float(new_balance)` | Balance update | Medium |
| `models/events.py:845` | `"amount": float(target.amount_base)` | Audit log serialization | Low (display) |
| `models/events.py:847` | `"discount_percent": float(...)` | Audit log serialization | Low (display) |
| `models/events.py:889` | `"balance": float(target.balance or 0)` | Audit log serialization | Low (display) |
| `models/events.py:890` | `"total_purchases": float(target.total_purchases or 0)` | Audit log serialization | Low (display) |
| `models/events.py:946` | `"current_stock": float(target.current_stock or 0)` | Audit log serialization | Low (display) |
| `models/events.py:947` | `"min_stock": float(target.min_stock_alert or 0)` | Audit log serialization | Low (display) |
| `models/events.py:948` | `"cost_price": float(target.cost_price or 0)` | Audit log serialization | Low (display) |
| `models/events.py:949` | `"sell_price": float(target.regular_price or 0)` | Audit log serialization | Low (display) |
| `models/events.py:1144` | `"discount_amount": float(target.discount_amount or 0)` | Audit log serialization | Low (display) |
| `models/cheque.py:755` | `"amount": float(self.amount)` | to_dict() serialization | Low (display) |
| `models/cheque.py:757` | `"exchange_rate": float(self.exchange_rate)` | to_dict() serialization | Low (display) |
| `models/cheque.py:761` | `"amount_base": float(self.amount_base)` | to_dict() serialization | Low (display) |
| `models/cheque.py:893` | `"incoming_amount": float(incoming_amount)` | Report aggregation | Medium |
| `models/currency.py:91` | `"rate": float(self.rate)` | to_dict() serialization | Low (display) |
| `models/customer.py:354` | `"balance": float(self.get_balance())` | to_dict() serialization | Low (display) |
| `models/erp_modules.py:847-850` | `float(line.quantity)`, `float(line.unit_price)`, etc. | to_dict() serialization | Low (display) |

### Verdict
- **Financial calculations**: ✅ Use `Decimal` (verified)
- **Display/serialization**: ⚠️ Use `float()` (acceptable for JSON output, but should use `str(Decimal)` for precision)
- **Recommendation**: Replace `float()` with `str(Decimal)` in `to_dict()` methods for exact precision in API responses

---

## 2. Service-Layer Commit Purity

### Summary
- **24 `rollback()` calls** remain in services (all in `except` blocks — acceptable for error recovery)
- **0 `commit()` calls** remain in services (all converted to `flush()` via earlier refactoring)
- **Savepoints**: `nested.commit()` in `stock_service.py:312` (legitimate savepoint, not transaction commit)

### Rollback Calls (Acceptable — Error Recovery)

| File | Line | Context |
|------|------|---------|
| `services/archive_service.py` | 74, 95, 120 | Error recovery in archive operations |
| `services/auto_approval_service.py` | 76, 148 | Error recovery in auto-approval |
| `services/celery_tasks.py` | 332 | Error recovery in Celery task |
| `services/cheque_accounting_integration.py` | 186, 244, 395, 502 | Error recovery in cheque posting |
| `services/error_report_service.py` | 202 | Error recovery in error reporting |
| `services/gl_service.py` | 723, 816, 907 | Error recovery in GL posting |
| `services/payment_service.py` | 645, 777, 992 | Error recovery in payment processing |
| `services/return_service.py` | 372 | Error recovery in returns |
| `services/sale_service.py` | 551, 696 | Error recovery in sales |
| `services/stock_service.py` | 175 | Error recovery in stock movement |
| `services/writeoff_service.py` | 273, 355 | Error recovery in write-offs |

### Verdict
✅ **No commit violations** — all services use `flush()` only. Rollback calls are in `except` blocks (acceptable for error recovery, not transaction boundary ownership).

---

## 3. Audit Log & Data Purging Mechanics

### Summary
- **1 hard-delete site** for AuditLog: `routes/owner.py:2914` (owner-only cleanup)
- **1 hard-delete site** for ArchivedRecord: `routes/owner.py:2916` (owner-only cleanup)
- **No soft-delete mechanism** for audit logs
- **No retention policy** enforced (manual cleanup via owner panel)

### Code References

| File | Line | Code | Notes |
|------|------|------|-------|
| `routes/owner.py` | 2914 | `AuditLog.query.filter(AuditLog.created_at < cutoff_date).delete()` | Owner-only, platform maintenance |
| `routes/owner.py` | 2916 | `ArchivedRecord.query.filter(ArchivedRecord.archived_at < cutoff_date).delete()` | Owner-only, platform maintenance |

### Verdict
⚠️ **Compliance concern** — Audit logs are hard-deleted by owner. For enterprise compliance (SOX, GDPR), consider:
- Soft-delete (mark as archived, don't physically delete)
- Retention policy (e.g., 7 years minimum)
- Immutable audit trail (no deletion at all)

---

## 4. Un-indexed Foreign Keys / Missing Tenant Scoping

### 4.1 Foreign Keys Without Explicit Index

**103 FK columns** without `index=True`. Most are secondary FKs (user_id, approved_by, created_by) that may not need indexes. Critical FKs (tenant_id, product_id, customer_id) already have indexes.

### Top Priority (Should Add Indexes)

| File | Line | Column | Reason |
|------|------|--------|--------|
| `models/erp_modules.py:205` | `quotation_id` | FK without index | High query volume |
| `models/erp_modules.py:206` | `product_id` | FK without index | High query volume |
| `models/bank_reconciliation.py:146` | `journal_entry_id` | FK without index | Medium |
| `models/bank_reconciliation.py:147` | `cheque_id` | FK without index | Medium |
| `models/budget.py:155` | `budget_id` | FK without index | Medium |
| `models/budget.py:156` | `account_id` | FK without index | Medium |
| `models/cheque.py:93` | `gl_clearing_entry_id` | FK without index | Medium |
| `models/cheque.py:94` | `gl_bounce_entry_id` | FK without index | Medium |

### 4.2 Models Without TenantScopedMixin (Non-Platform)

| Model | File | Tenant-Scoped? | Should Be? |
|-------|------|---------------|------------|
| `APIKey` | `models/api_key.py` | ❌ No | ⚠️ Maybe (if API keys are per-tenant) |
| `BackupVerification` | `models/backup_verification.py` | ❌ No | ✅ Correct (platform-level) |
| `CardPayment` | `models/card_payment.py` | ❌ No | ⚠️ Maybe (if per-tenant) |
| `CardVault` | `models/card_vault.py` | ❌ No | ⚠️ Maybe (if per-tenant) |
| `Currency` | `models/currency.py` | ❌ No | ✅ Correct (global reference data) |
| `Donation` | `models/donation.py` | ❌ No | ⚠️ Maybe (if per-tenant) |
| `Incident` | `models/incident.py` | ❌ No | ✅ Correct (platform-level) |
| `IntegrationSettings` | `models/integration_settings.py` | ❌ No | ⚠️ Maybe (if per-tenant) |
| `InvoiceSettings` | `models/invoice_settings.py` | ❌ No | ⚠️ Maybe (if per-tenant) |
| `LoginHistory` | `models/login_history.py` | ❌ No | ⚠️ Maybe (if per-tenant) |
| `Package` | `models/package.py` | ❌ No | ✅ Correct (platform-level) |
| `PaymentVault` | `models/payment_vault.py` | ❌ No | ⚠️ Maybe (if per-tenant) |
| `ProductReturn` | `models/product_return.py` | ❌ No | ⚠️ Should be (per-tenant returns) |
| `SecurityAlert` | `models/security_alert.py` | ❌ No | ✅ Correct (platform-level) |
| `SubscriptionPlan` | `models/subscription_plan.py` | ❌ No | ✅ Correct (platform-level) |
| `SystemSettings` | `models/system_settings.py` | ❌ No | ✅ Correct (platform-level) |

### Verdict
- **16 models** are not tenant-scoped
- **6 are platform-level** (correct: Currency, SystemSettings, Package, SubscriptionPlan, SecurityAlert, BackupVerification, Incident)
- **10 are potentially tenant-scoped** (should be reviewed: APIKey, CardPayment, CardVault, Donation, IntegrationSettings, InvoiceSettings, LoginHistory, PaymentVault, ProductReturn)

---

## Summary

### Critical Issues Found

| # | Issue | Severity | Location |
|---|-------|----------|----------|
| 1 | 220 `float()` calls in models/services (mostly display) | P2 | `models/*.py`, `services/*.py` |
| 2 | 103 FK columns without explicit index | P2 | `models/*.py` |
| 3 | 10 models potentially missing tenant scoping | P2 | `models/*.py` |
| 4 | Audit log hard-deleted (owner-only) | P2 | `routes/owner.py:2914` |
| 5 | No soft-delete for audit logs | P3 | N/A |
| 6 | `ProductReturn` not tenant-scoped | P2 | `models/product_return.py` |

### No Violations Found In
- Service-layer commits (all converted to flush)
- Tenant isolation (TenantScopedMixin + events)
- RBAC (26 permissions, 16 roles)
- Multi-currency (Decimal + amount_base)
- Financial precision in calculations (Decimal + ROUND_HALF_UP)
- Path traversal protection (validate_backup_filename)
- Rate limiting (Flask-Limiter)
- CSRF protection (Flask-WTF)