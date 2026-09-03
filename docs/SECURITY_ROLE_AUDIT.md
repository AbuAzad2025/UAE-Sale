# Security Role Audit — UAE-Sale Multi-Tenant ERP & POS

**Status:** complete · **CI:** all jobs green with strict gates (no `continue-on-error` in any security step)
**Scope:** zero-trust audit — every role gets a tailored dashboard/navigation matching its scope,
cross-tenant/branch isolation, Master Key scoping, no privilege leakage or UI clutter for lower-tier roles.

---

## 1. Roles (10 slugs)

| Slug | Level¹ | Seeded by `system_init` | Permissions | Notes |
|---|---|---|---|---|
| `owner` | 100 (flag) | yes — all 19 permissions | **ALL** | Master Key. `is_owner=True`. Bypasses tenant filter. Seeded owner user. |
| `super_admin` | 90 | yes — all 19 permissions | **ALL** | "Full system access (except Owner Panel)". Passes `super_admin_required`. |
| `developer` | 0 in hierarchy² | yes — all 19 permissions | **ALL** | Passes `owner_required` via explicit slug check (`decorators.py:155`). Fail-closed for role assignment. |
| `manager` | 70 | no (operator-created) | sales, customers, products, purchases, payments, reports, expenses, warehouse | Broad ops, but NOT ledger/admin. Cannot reach `/owner/*` (404). |
| `hr` | 60 | no | `manage_hr` | HR module only (`/hr/`). |
| `accountant` | 50 | no | view/manage_ledger, expenses, reports, payments | Ledger + finance, NOT sales/POS. |
| `seller` | 40 | no | sales, customers, products | POS + catalog. No ledger, no users, no reports-admin. |
| `cashier` | 40 | no | payments, reports | Receipts + reports. No sales/customers/products/ledger/HR. |
| `inventory` | 30 | no | warehouse, view_products | Warehouse only (`/warehouse/`). No sales/ledger/payments. |
| `viewer` | 10 | no | reports | Read-only reports. Zero write actions anywhere. |

¹ `_ROLE_LEVELS` (`utils/decorators.py:178`); enforced by `_enforce_target_role_not_higher` — an actor may only assign/mutate roles **at or below** their own level.
² `developer` is intentionally absent from `_ROLE_LEVELS` → level 0, so a developer cannot mint higher roles; owner-panel access is granted separately and explicitly.

## 2. Permissions (19 seeded codes)

`manage_sales`, `manage_purchases`, `manage_products`, `manage_customers`, `manage_suppliers`,
`manage_payments`, `manage_expenses`, `view_reports`, `manage_users`, `manage_warehouse`,
`view_ledger`, `manage_ledger`, `admin`, `manage_backups`,
`manage_hr`, `manage_approvals`, `manage_settings`, `view_products`, `view_costs`
(`utils/system_init.py:_ensure_permissions`; verified by `TestPermissionCompleteness`).

## 3. Enforcement layers

1. **Route decorators** — `permission_required(code)` (403), `admin_required`, `super_admin_required` (403),
   `owner_required` (**404**, stealth — hides panel existence), `seller_or_above`.
2. **Tenant auto-filter** — `install_tenant_filter_events()` appends `tenant_id == current` to every query
   whose primary entity is registered; `TENANT_STRICT=True` by default (`config.py:135`) warns on any
   unfiltered access to a registered table.
3. **Write guards** — `before_flush` auto-stamps `tenant_id` on insert, blocks cross-tenant inserts and
   `tenant_id` mutation for non-owner actors.
4. **UI gating** — nav (`templates/base.html`), command palette (Ctrl+K), dashboard quick-action cards
   (`templates/dashboard.html`) and in-page action buttons are all wrapped in `has_permission(...)`.
5. **Role-assignment ceiling** — `_enforce_target_role_not_higher` prevents vertical escalation via `role_id`.

## 4. Tenant-scoped registry (14 tables)

`sales`, `sale_lines`, `purchases`, `purchase_lines`, `payments`, `receipts`, `customers`, `suppliers`,
`products`, `stock_movements`, `cheques`, `gl_journal_entries`, **`gl_journal_lines`**, `warehouses`
(`models/__init__.py:61`; asserted exactly by `test_core_scoped_registry_unchanged`).

### Decision log
- **`gl_journal_lines.tenant_id` (migration `13_add_gl_line_tenant`, head).**
  Lines previously relied solely on reaching them through a tenant-scoped `GLJournalEntry` (JOIN/relationship).
  Direct queries on `gl_journal_lines` were unfiltered. The model now carries `TenantScopedMixin` + `tenant_id`
  (indexed FK, `SET NULL`) and is registered; existing rows are backfilled from their parent entry.
  Reversible (`downgrade` drops index + column), inspector-guarded for Postgres/SQLite.
- **`User.tenant_id` intentionally UNregistered.** Users are platform identity (login must resolve before any
  tenant context exists). Tenant binding on users is informational, never a query filter — documented here so it
  is not mistaken for a gap.
- **Dashboard "New Invoice" buttons gated.** The Recent-Sales header/empty-state `sales.create` links rendered for
  every role; they are now wrapped in `has_permission('manage_sales')` (`templates/dashboard.html:143,229`).
  Route-level 403 already blocked the action — this removes the clutter/misleading affordance.
- **`/payments/` has no index route** (list page is `/payments/receipts`); tests assert on the real URL.

## 5. Test coverage

| Suite | File | Tests | What it proves |
|---|---|---|---|
| Role isolation | `tests/unit/test_erp_role_isolation.py` | **101** | Phases 1–5: permission completeness; route isolation for seller/manager/accountant/cashier/inventory/hr/viewer (allowed → 200/302, denied → 403/404/302); cross-tenant blocks; per-role dashboard render; palette + quick-action URL absence for unpermitted modules; Master Key scoping; decorator fail-closed behavior. |
| Zero-trust | `tests/security/test_zero_trust_isolation.py` | 18 | Tenant immutability, owner cross-tenant read/insert semantics. |
| Remediation | `tests/unit/test_security_remediation.py` | — | Mixin fail-fast, `TENANT_STRICT` warn path, exact registry match. |
| Seed safety | `tests/unit/test_system_init_db_safety.py` | — | 19 expected permission codes; DB-safe seeding. |

## 6. Static security posture (Bandit)

**0 HIGH, 0 MEDIUM** (111 LOW only — style-level, non-gating). Resolutions:
- **B301** — `ai_knowledge/learning_system.py`: pickle persistence replaced with JSON (`patterns.json`);
  `import pickle` removed. Verified JSON round-trip incl. `defaultdict` reconstruction.
- **B704** — `app.py::_status_badge`: both badge class (allowlist map) and label pass through `escape()`.
- **B608** — `routes/owner.py`: DB-catalog loops re-checked against `get_allowed_table_names_safe()`;
  `validate_table_name()`-guarded sites annotated; owner SELECT-consoles documented as scoped admin tools
  (SELECT-only, single-statement, keyword blocklist, table allowlist, audited).
  `ai_knowledge/code_generator.py`: outputs are never-executed informational strings; values escaped anyway.
- **B104** — `HOST=0.0.0.0` is operator-controlled env for container/reverse-proxy multi-branch deployment.
- **B324** — MD5 usages are non-security cache/content hashes (`usedforsecurity=False`).

CI gate: `bandit -c .bandit.yml -r . -ll -ii` — fails only on real MEDIUM/HIGH findings
(plain `bandit` without `-ll -ii` counts LOW findings toward the exit code, so the flags are load-bearing).
`continue-on-error` removed from Bandit, pip-audit, Gitleaks, Trivy and the SARIF upload: security is a hard gate.

## 7. Residual risks / follow-ups

- Dashboard data sections (e.g. Recent Sales table) render for any authenticated role; only *actions* are gated.
  Tenant filtering still applies, but role-based data hiding beyond actions is a product decision, not yet specified.
- `developer` holds all permissions by seed; restrict in production if developers should not see finance data.
- LOW bandit findings (B110/B311/…) accepted; revisit if CI policy ever gates on LOW.
