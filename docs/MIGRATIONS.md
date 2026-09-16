# Migration Contract — عقد التهجيرات (FROZEN / ثابت)

> **ملخص عربي:** مجلد `migrations/` تاريخ ثابت (append-only) من 21 مراجعة مرتبة
> برأس واحد (`21_inbound_shipment`). ممنوع إعادة كتابته أو دمجه أو حذف ملفاته.
> أي تغيير في الموديل = مراجعة جديدة في آخر السلسلة فقط. هذا الملف هو المرجع
> الوحيد المعتمد، ولا يجوز لأي مهمة مستقبلية مخالفته.

## 1. Status (verified 2026-09-16 — inbound shipments + shipment expedition)

- **Revisions:** 21 files in `migrations/versions/`, UTF-8, no null bytes.
- **History:** single linear chain, exactly **ONE head**: `21_inbound_shipment`.
- **Database:** PostgreSQL 15+ only. No SQLite fallback anywhere in the chain.
- **Engine source:** `migrations/env.py` (stock Flask-Migrate) always uses the
  Flask app engine, therefore it always respects the `DATABASE_URL`
  environment variable. There is intentionally **no** `sqlalchemy.url`
  hardcoded in `migrations/alembic.ini`.
- **Health proofs (fresh PostgreSQL database):**
  - `flask db upgrade head` applies all 21 revisions cleanly (85 tables: 81 + shipments/shipment_lines + inbound_shipments/inbound_shipment_lines).
  - `flask db downgrade <head-1>` + `flask db upgrade head` round-trips cleanly.
  - App boot passes schema verification (`[OK] Schema verification passed:
    83 tables present`).
  - `bandit -c .bandit.yml -r . -ll -ii` reports no MEDIUM/HIGH issues.
  - GitHub **Alembic Round-Trip** workflow: SUCCESS.

## 2. The chain (oldest → newest, do not reorder)

| # | revision | one-line description |
|---|----------|----------------------|
| 1 | `1a6dadd0ddb4` | Initial unified schema |
| 2 | `2b_add_tenant_scoping` | `tenant_id` on all core business tables (row-level isolation) |
| 3 | `3_hr_module` | HR module tables |
| 4 | `4_erp_modules` | Extended ERP modules |
| 5 | `5_add_missing_indexes` | Performance indexes on HR/ERP tables |
| 6 | `6_rename_amount_base` | `*_aed` columns → `*_base` (base-currency semantics) |
| 7 | `7_cheque_gl_links` | Cheque ↔ GL journal linkage columns |
| 8 | `8_purchase_payment_tracking` | Purchase `paid_amount` / `payment_status` |
| 9 | `9_audit_cascade` | `journal_entry_audits.entry_id` ON DELETE CASCADE |
| 10 | `10_remove_depr_fk` | Remove `depreciation_schedules.journal_entry_id` FK |
| 11 | `11_f01_f03_f04_f05_invariants` | F-01/F-03/F-04/F-05 schema invariants |
| 12 | `12_decimal_indexes_currency_fix` | Decimal precision, missing FK indexes, currency default |
| 13 | `13_add_gl_line_tenant` | `tenant_id` on `gl_journal_lines` |
| 14 | `14_cost_permission_grant` | `view_costs` grant to cost-privileged roles |
| 15 | `15_approval_wf_recon` | Approval workflows, `base_salary` NOT NULL, 7 indexes |
| 16 | `16_drop_legacy_audit_fk` | Drop legacy audit FK left over by #9 |
| 17 | `17_audit_trail_survives` | Deletion audits survive their entry |
| 18 | `18_donation_method_flags` | Per-method donation switches (owner panel) |
| 19 | `19_error_log_table` | `error_logs` table for the centralized error journal |
| 20 | `20_shipment_module` | Field sales shipments — الإرسالية الميدانية (from warehouse to site, then sale→payment→invoice) |
| 21 | `21_inbound_shipment` *(HEAD)* | Inbound shipments — استقبال شحنات البضائع الواردة (in_transit→arrived→inspected→put_away→closed, stock movement on put_away) |

Each file's `down_revision` points to its exact predecessor above.
`alembic history` / `flask db history` must always render one straight line.

## 3. How migrations run (do not redesign this)

1. **App boot** (`app.py::create_app`): calls Alembic `upgrade(cfg, 'head')`
   with `migrations/alembic.ini`, then fail-fast verifies 14 critical tables
   exist. Boot refuses to run on an incomplete schema.
2. **CLI / CI**: `flask db upgrade head` (Flask-Migrate → same `env.py`,
   same chain, engine taken from the Flask app = `DATABASE_URL`).
3. **CI gates** (`.github/workflows/`):
   - `ci.yml` → `verify-boot` (app boots on fresh `azad_test`),
     `alembic-smoke` (`flask db upgrade head` on fresh DB),
     `integration` (migrate + integration tests).
   - `alembic_roundtrip.yml` → upgrade to head, downgrade **one** revision,
     re-upgrade to head (reversibility gate).

## 4. Golden rules (binding on every future task)

1. **APPEND-ONLY.** Never edit, squash, reorder, or delete an applied
   revision. A past mistake is fixed by a *new* revision on top, never by
   rewriting history. (A 2026-09 squash attempt broke all migration CI jobs;
   it was reverted — do not repeat it.)
2. **ONE HEAD, ALWAYS.** Before adding a revision, confirm the current head
   (`flask db heads` → exactly one). New file's `down_revision` = that head.
3. **NO HARDCODED DB URL.** `migrations/alembic.ini` must not contain
   `sqlalchemy.url`; `env.py` must keep using the Flask app engine so
   `DATABASE_URL` (CI: `azad_test`, local dev: `uae_sale`) is always honored.
4. **KEEP `env.py` STOCK.** It is the standard Flask-Migrate template
   (app engine + SQLite `render_as_batch` guard for unit tests). Do not
   replace it with a standalone-Alembic variant.
5. **NO CREDENTIALS IN REPO.** Never commit debug scripts containing
   connection strings/passwords — Bandit (`B106`) and secret scanners will
   fail the build.
6. **REVIEW AUTOGENERATE NOISE.** Autogenerate reports index/FK *renames*
   and model-level check constraints as diffs even when every table and
   column exists. Renames are cosmetic: only migrate them in a deliberate,
   reviewed revision — never as drive-by edits, never by touching old files.

## 5. Adding a new revision (the only allowed change)

```bash
# 1. Confirm single head
python -m flask db heads        # exactly one line
# 2. Change models in models/, then generate
python -m flask db migrate -m "short_description"
# 3. READ the generated file: keep needed ops, drop rename-only noise
#    unless a rename is the explicit goal of this revision
# 4. Fresh-database proof (use a scratch DB, never dev data):
python -m flask db upgrade head
python -m flask db downgrade <previous_head>
python -m flask db upgrade head
python -m flask db current      # new revision (head)
# 5. Boot proof + security proof
python -c "from app import create_app; app = create_app()"
python -m bandit -c .bandit.yml -r . -ll -ii
```

Required env for the above: `DATABASE_URL`, `SECRET_KEY`, `OWNER_PASSWORD`,
`APP_ENV=testing` (see `ci.yml` for exact CI values).

## 6. Completeness gate (no missing field/column)

After `flask db upgrade head` on a fresh database:

```bash
python -m flask db migrate -m "drift_probe"
```

- **Zero `Detected added table` / zero new-column ops** = every model
  table/column the application needs physically exists. ✅
  (Verified 2026-09-16: 81/81 tables, all columns present.)
- Remaining diffs, if any, are *naming* drift (index/FK names, model-level
  check constraints) — see rule 6. They prove nothing is missing, and they
  must not trigger history edits.
- **Delete the probe file** if one is generated; it must never be committed
  (it would create a second head).

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Can't locate revision identified by 'X'` | Local `alembic_version` points at a deleted/renamed revision | `flask db stamp head` (dev DB only, when schema already matches), or rebuild scratch DB |
| `Missing critical tables after migration` at boot | App connected to the wrong database | Check `DATABASE_URL` (local dev uses `uae_sale`; CI uses `azad_test`) |
| `source code string cannot contain null bytes` | A version file saved with UTF-16/BOM | Rewrite that file as plain UTF-8 (then see rule 1: prefer revert over repair) |
| CI `alembic-*` red, local green | Hardcoded URL or non-Flask engine in `env.py` | Restore stock `env.py` (rule 3–4), re-run §5 proofs |

## 8. Local databases (reference)

- `uae_sale` — local dev database, stamped at `19_error_log_table`.
- `azad_test` / scratch DBs (`ci_sim`, …) — disposable; create fresh for
  every proof in §5–§6, drop afterwards. Never store real data in them.
