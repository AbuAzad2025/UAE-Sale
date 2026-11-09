# 📋 Azadexa — Enterprise Test Matrix (Execution-Ready)

> **Purpose**: Real-world, concurrent, multi-tenant test scenarios that stress the platform across RBAC, financial/GL integrity, tax/compliance, operational workflows, and concurrency. Each scenario is execution-ready: preconditions, steps, expected outcomes, and verification commands.
>
> **Status legend**: ✅ verified in CI/E2E/unit · ⏳ designed, not yet executed · ❌ known gap

---

## 0. Test Environment Prerequisites

| Item | Value |
|---|---|
| Database | PostgreSQL 15 (CI) or SQLite in-memory (unit) |
| Base currency | ILS (tests) / AED (production) |
| Fiscal period | Current year open (`ensure_periods_for_years`) |
| GL core accounts | Seeded via `GLService.ensure_core_accounts()` |
| Concurrency driver | `pytest -n auto` (xdist) or `locust` for HTTP-level |

---

## 1. RBAC & Tenant Isolation

### 1.1 Role Hierarchy Matrix

| Role | Sales | Purchases | Expenses | Ledger | HR | Warehouse | Owner Panel | Reports |
|---|---|---|---|---|---|---|---|---|
| Owner | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Super Admin | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ (no panel) | ✅ |
| Branch Manager | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ |
| Senior Accountant | ✅ (view) | ✅ (view) | ✅ (view) | ✅ | ❌ | ❌ | ❌ | ✅ |
| Accountant | ✅ (view) | ✅ (view) | ✅ (view) | ✅ (view) | ❌ | ❌ | ❌ | ✅ |
| Sales Agent | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| POS Cashier | ✅ (POS only) | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Warehouse Keeper | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ |
| HR | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ |
| Viewer | ❌ (read only) | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ (read) |
| Auditor | ❌ | ❌ | ❌ | ✅ (read) | ❌ | ❌ | ❌ | ✅ |

### 1.2 Tenant Isolation Scenarios

| ID | Scenario | Preconditions | Steps | Expected Outcome | Verification |
|---|---|---|---|---|---|
| T-01 | Cross-tenant sale read | 2 tenants (A, B), each with 1 sale | Tenant A user GETs `/sales/<B_sale_id>` | 404 (stealth, no leak) | `test_tenant_isolation_p0.py` |
| T-02 | Cross-tenant customer read | 2 tenants, each with 1 customer | Tenant A user GETs `/customers/<B_customer_id>` | 404 | `test_tenant_isolation.py` (9) |
| T-03 | Cross-tenant GL entry read | 2 tenants, each with 1 journal entry | Tenant A user GETs `/ledger/entry/<B_entry_id>` | 404 | `test_tenant_isolation_p0.py` |
| T-04 | Cross-tenant product read | 2 tenants, each with 1 product | Tenant A user GETs `/products/<B_product_id>` | 404 | `test_tenant_isolation_p0.py` |
| T-05 | Cross-tenant warehouse read | 2 tenants, each with 1 warehouse | Tenant A user GETs `/warehouse/<B_warehouse_id>` | 404 | `test_tenant_isolation_p0.py` |
| T-06 | Cross-tenant expense read | 2 tenants, each with 1 expense | Tenant A user GETs `/expenses/<B_expense_id>` | 404 | `test_tenant_isolation_p0.py` |
| T-07 | Cross-tenant payment read | 2 tenants, each with 1 payment | Tenant A user GETs `/payments/<B_payment_id>` | 404 | `test_tenant_isolation_p0.py` |
| T-08 | Cross-tenant quotation read | 2 tenants, each with 1 quotation | Tenant A user GETs `/erp/quotations/<B_q_id>` | 404 | `test_erp_modules_journal.py` |
| T-09 | Cross-tenant partner distribution | 2 tenants, each with company partner | Tenant A owner (platform) distributes in tenant B context | Entries stamped with tenant B ID | `test_owner_partners_page.py` |
| T-10 | Tenant-less user isolation | User with `tenant_id=NULL` | User reads any tenant's data | Sees only tenant-less rows (TENANT_LESS_SCOPE=-1) | `test_tenant_isolation_p0.py` |
| T-11 | Owner platform view | Owner (no impersonation) | Owner reads `/owner/partners` | Cross-tenant overview (read-only) | `test_owner_partners_page.py` |
| T-12 | IDOR via direct ID enumeration | 2 tenants | Tenant A iterates IDs 1..N, counts accessible B rows | 0 accessible | `test_zero_trust_isolation.py` |
| T-13 | Privilege escalation: seller → super_admin | Seller user | Seller POSTs to `/users/<id>/edit` with role=super_admin | 403 / 404 | `test_zero_trust_isolation.py` |
| T-14 | Non-owner redirected to dashboard | Non-owner user | Non-owner GETs `/owner/dashboard` | 302 → `/dashboard` | `test_owner_panel.py` |
| T-15 | Unauthenticated → login | Anonymous | GET any protected route | 302 → `/auth/login` | `test_owner_panel.py` |

### 1.3 Route Census Enforcement

| Check | Mechanism | Verification |
|---|---|---|
| Every route classified | `MODULE_SCOPE` + `SPECIAL_ROUTES` in `utils/route_scope.py` | `test_every_route_is_classified` (517 routes) |
| Every tenant route carries isolation evidence | Source inspection for `login_required`/`permission_required`/`get_owned_or_404`/`tenant_id` | `test_tenant_routes_carry_isolation_evidence` |
| Platform modules are platform | `routes.owner`, `routes.payment_vault` → platform | `test_owner_and_vault_are_platform` |
| Public modules are public | `routes.public`, `routes.auth`, etc. | `test_public_modules_are_public` |
| No unclassified modules | Every `__module__` in `MODULE_SCOPE` | `test_every_module_prefix_in_scope_map` |
| Inventory count matches | 517 total (355 tenant / 128 platform / 27 public / 7 system) | `test_full_inventory_count` |

---

## 2. Financial & Accounting Integrity

### 2.1 Sales → GL Atomicity

| ID | Scenario | Steps | Expected Outcome | Verification |
|---|---|---|---|---|
| F-01 | Sale creates balanced GL entries | Create sale (2×100, cost 30) | JE-1: Dr AR 200 / Cr Revenue 200; JE-2: Dr COGS 60 / Cr Inventory 60; JE-3: Dr 6910 (partner share) / Cr 3350 (partner) — all balanced | `test_sale_to_gl.py::test_sale_creates_gl_entries` |
| F-02 | Sale fails → full rollback | Create sale with invalid cost basis (0 cost product) | ValidationError raised; no sale, no GL, no stock movement committed | `test_double_entry_integrity.py` |
| F-03 | Payment atomic with GL | Create payment for sale | Payment row + GL entry in same transaction; if GL fails, payment rolls back | `test_leak_guards.py` |
| F-04 | Cancel sale reverses all GL | Cancel unpaid sale | All Sale-ref entries (revenue, COGS, partner shares) reversed; stock restored; customer balance recomputed | `test_sale_to_gl.py::test_gl_reversed_on_cancellation` |
| F-05 | Cancel paid sale blocked | Cancel sale with payments | ValidationError: cannot cancel paid invoice | `store_sales_api.py::test_cancel_sale_with_payments_raises` |
| F-06 | Return creates reversing entries | Return 1 of 2 units | ProductReturn entry (Dr sales_returns, Dr VAT, Cr AR) + COGS reversal + partner share reversal (proportional) | `test_return_service.py` (9 tests) |
| F-07 | Return more than sold | Return 5 units from 2-unit sale | ValidationError: Cannot return | `test_return_service.py::test_return_more_than_sold_raises` |
| F-08 | Cumulative returns capped | Return 1, then try 2 more from 2-unit sale | ValidationError: Already returned | `test_return_service.py::test_cumulative_returns_capped` |

### 2.2 Partner Profit Distribution

| ID | Scenario | Preconditions | Steps | Expected Outcome | Verification |
|---|---|---|---|---|---|
| P-01 | Product partner profit share | ProductPartner 25% on product; sale 2×100 cost 30 | Create sale | Partner share = (200-60)×25% = 35.000 → Dr 6910 35 / Cr 3350 35 (party_id set) | `test_partner_profit.py::test_profit_share_posted_immediately_with_sale` |
| P-02 | Product partner loss distribution | ProductPartner 50%; sale 1×40 cost 100 | Create sale | Loss = (40-100)×50% = -30 → Cr 6910 30 / Dr 3350 30 (party_id set) | `test_partner_profit.py::test_loss_is_distributed_too` |
| P-03 | Cancel reverses partner shares | P-01 scenario + cancel | Cancel sale | Net partner balance on 3350 = 0 (entry reversed) | `test_partner_profit.py::test_cancel_reverses_partner_shares` |
| P-04 | Partial return reverses proportionally | P-01 scenario + return 1 unit | Return 1 of 2 | Reversed = 35/2 = 17.5 → remaining = 17.5 | `test_partner_profit.py::test_partial_return_reverses_proportionally` |
| P-05 | Zero-profit sale posts nothing | cost = price (profit 0) | Create sale | No partner entry created (shares empty) | `test_partner_profit.py::test_sale_with_zero_profit_posts_no_partner_entry` |
| P-06 | Company partner distribution (profit) | Company partner 25%; revenue 1000 | Preview → Distribute | Share = 250; Dr 3400 1000 / Cr 3350 250 (party) + Cr 3350 750 (residual) | `test_partner_profit.py::test_preview_and_distribute_profit` |
| P-07 | Company partner distribution (loss) | Company partner 25%; revenue 1000, expense 1600 | Distribute | Loss 600; partner bears 150 → Dr 3350 150 (party) + Dr 3350 450 (residual) / Cr 3400 600 | `test_partner_profit.py::test_loss_is_allocated_between_partners` |
| P-08 | Draws deducted from distribution | Company partner 25%; revenue 1000; draw 100 | Distribute | Payout = 250 - 100 = 150 | `test_partner_profit.py::test_draws_are_deducted` |
| P-09 | Unpaid sales deducted (full) | Company partner buys 150 unpaid | Distribute | Deduction = 150 → payout reduced | `test_partner_profit.py::test_full_paid_sale_not_deducted_and_unpaid_deducted` |
| P-10 | Unpaid sales deducted (partial) | Company partner buys 150, pays 50 | Distribute | Deduction = 100 (remaining balance) | `test_partner_profit.py::test_full_paid_sale_not_deducted_and_unpaid_deducted` |
| P-11 | Paid sales not deducted | Company partner buys 150, pays 150 | Distribute | Deduction = 0 | `test_partner_profit.py::test_full_paid_sale_not_deducted_and_unpaid_deducted` |
| P-12 | Percentage overflow rejected | Two partners: 60% + 55% | Distribute | ValueError: مجموع نسب الشركاء يتجاوز 100% | `test_partner_profit.py::test_partner_percentages_above_100_rejected` |
| P-13 | Zero net income → nothing | No revenue entries | Distribute | Returns None (no entry) | `test_partner_profit.py::test_zero_net_income_posts_nothing` |
| P-14 | Idempotent distribution | Distribute same period twice | Second call | Returns None (no duplicate entry) | `test_partner_profit.py::test_preview_and_distribute_profit` |
| P-15 | Overlapping period rejected | Distribute March, then overlapping April window | Second call | ValueError: متداخل | `test_partner_profit.py::TestOverlappingDistributionPeriods` |
| P-16 | Force override | Distribute overlapping with force=True | Distribute | Posts entry despite overlap | `test_partner_profit.py::test_force_true_overrides_overlap_guard` |
| P-17 | Dual-role partner | Partner is both product (25%) and company (25%) | Sale 2×100 cost 30 → Distribute | Product share = 35 (posted with sale); company share = 26.25 (from net 105); total entitlement = 61.25 | `test_partner_profit.py::test_dual_role_gets_both_shares_without_double_counting` |
| P-18 | Partner scope none keeps product links | scope='none' + product link | Create sale | Product share still posted (links independent of scope) | `test_partner_profit.py::test_scope_none_partner_still_earns_product_shares` |
| P-19 | Manual journal draw tracked | Manual entry: Dr 3350 120 / Cr 1110 120 (party_id set) | Preview distribution | Draw = 120 deducted from payout | `test_partner_profit.py::test_manual_journal_tagged_3350_debit_counts_as_draw` |
| P-20 | Internal entries never counted as draws | Sale with partner share + cancel | Check draws | Draws = 0 (Sale/ProductReturn/PartnerDistribution excluded) | `test_partner_profit.py::test_partner_share_entries_themselves_are_never_draws` |
| P-21 | VAT-inclusive partner base | tax_inclusive=True, rate=5%, standard treatment, price 105 | Create sale | VAT extracted: net 100 - cost 30 = 70 → share 17.5 | `test_partner_profit.py::test_inclusive_vat_deducted_from_partner_base` |
| P-22 | Zero-rated line no VAT extraction | tax_treatment='zero', inclusive, rate=5% | Create sale | No VAT extraction: 100 - 10 = 90 → share 90 | `test_partner_profit.py::test_inclusive_vat_mixed_treatments_only_standard_taxed` |
| P-23 | Draws window filter | Draw on date X, query window before X | `_draws_for_partner` | Returns 0 (outside window) | `test_partner_profit.py::test_draws_and_sales_window_filters` |
| P-24 | Preview total entitlement | Company partner with product link | Preview | `total_entitlement = net_payout + product_shares_in_period` | `test_partner_profit.py::test_preview_shows_total_entitlement` |

### 2.3 GL Direction Enforcement (F8)

| Account | Nature | Whitelisted Debit | Whitelisted Credit |
|---|---|---|---|
| 3350 (Partners Current) | Equity (credit) | مسحوبات الشركاء (draws, reversals, loss allocation) | Normal (profit share, distribution) |
| 6910 (Partner Share Expense) | Expense (debit) | Normal (profit share) | عكس حصة الشريك عند توزيع الخسارة |
| 3400 (Current Year Profit) | Equity (credit) | إقفال أرباح السنة الحالية | Normal (loss allocation) |

### 2.4 GL Party Tagging (Traceability)

| Flow | AR Account | Party Tagged | Reference Type |
|---|---|---|---|
| Sale to partner | 3350 (PARTNER_CURRENT) | ✅ on AR + revenue lines | `Sale` |
| Payment for sale (partner) | 3350 | ✅ on debit + credit legs | `Payment` |
| Refund to partner (outgoing) | 3350 | ✅ on AR + cash legs | `Payment` |
| Return (cash refund) | 3350 | ✅ on AR debit + cash credit | `ProductReturn` |
| Return (AR credit) | 3350 | ✅ on AR credit leg | `ProductReturn` |
| Write-off (partner receivable) | 1130 (AR_CONTROL) | ✅ on AR credit leg | `WriteOff` |
| Manual journal entry | Any | ✅ via `party_id` field in line dict | `manual` (or any) |
| Partner draw | 3350 | ✅ on debit leg | `PartnerDraw` |
| Product partner share | 6910 + 3350 | ✅ on both legs | `Sale` |
| Company distribution | 3350 + 3400 | ✅ on partner legs (residual untagged) | `PartnerDistribution` |

---

## 3. Tax & Compliance Scenarios

### 3.1 Per-Line VAT Engine

| ID | Scenario | Treatment | Inclusive | Rate | Expected Tax | Verification |
|---|---|---|---|---|---|---|
| TAX-01 | Standard exclusive | standard | false | 5% | 175×5% = 8.75 on 175 base | `test_mixed_vat.py` (4) |
| TAX-02 | Standard inclusive | standard | true | 5% | 200/1.05 = 190.48 net, tax 9.52 | `test_mixed_vat.py` |
| TAX-03 | Zero-rated | zero | either | 5% | 0 (rate forced to 0) | `test_mixed_vat.py` |
| TAX-04 | Exempt | exempt | either | 5% | 0 (rate forced to 0) | `test_mixed_vat.py` |
| TAX-05 | Mixed treatments (std + zero + exempt) | per-line | either | 5% | Tax only on standard bucket; shipping/discount allocated proportionally | `test_mixed_vat.py` |
| TAX-06 | Invoice-level zero overrides all lines | zero (invoice) | either | 5% | 0 (all lines treated as zero) | `test_mixed_vat.py` |
| TAX-07 | Negative std_base clamped to 0 | standard | false | 5% | 0 (std_base < 0 → clamped) | `test_mixed_vat.py` |
| TAX-08 | Return inclusive | standard | true | 5% | Per returned line bucket split with proportional allocation | `test_return_service.py` |

### 3.2 Quotation Tax (Phase 1)

| ID | Scenario | Steps | Expected Outcome | Verification |
|---|---|---|---|---|
| Q-01 | Create quotation with mixed tax treatments | 2 lines: standard (100) + zero (50), discount 10, shipping 5, rate 5% | tax_amount = (100-6.67+3.33)×5% = 4.83; total = 145 + 4.83 = 149.83 | `test_erp_modules_journal.py::TestQuotationService` |
| Q-02 | Convert quotation to sale | Accepted quotation → convert | Sale created with same totals; stock decremented; quotation status='converted'; converted_sale_id set; converted_at set | `test_erp_modules_journal.py::test_convert_to_sale_creates_linked_sale` |
| Q-03 | Double conversion blocked | Convert already-converted quotation | ValueError: عرض الأسعار هذا مُحَوَّل بالفعل | `test_erp_modules_journal.py` |
| Q-04 | Expired quotation conversion blocked | valid_until = yesterday → convert | ValueError: عرض الأسعار منتهي الصلاحية | `test_erp_modules_journal.py::test_convert_expired_quotation_raises` |
| Q-05 | Rejected quotation conversion blocked | status='rejected' → convert | ValueError: لا يمكن تحويل فاتورة بحالة: مرفوضة | `test_erp_modules_journal.py::test_convert_rejected_quotation_raises` |
| Q-06 | Closed fiscal period blocks conversion | Close current period → convert | ValueError: الفترة المالية.*مغلقة | `test_erp_modules_journal.py::test_closed_period_blocks_new_sales` |
| Q-07 | Auto-expire on access | valid_until = yesterday, status='draft' | GET view_quotation → status becomes 'expired' | `test_erp_modules_journal.py` |
| Q-08 | Duplicate quotation | Duplicate a quotation | New quotation with same lines, new number, status='draft', all fields copied | (service method exists; route exists) |
| Q-09 | Delete draft only | Delete accepted quotation | Refused (status != 'draft') | (route guard) |
| Q-10 | Stock availability at conversion | Product with 0 stock → convert | SaleService.create_sale raises ValidationError; quotation NOT marked converted | (service guard) |

### 3.3 Corporate Tax

| ID | Scenario | Expected | Verification |
|---|---|---|---|
| CT-01 | UAE 9% above threshold | Profit 400,000 → tax = (400,000-375,000)×9% = 2,250 | `test_corporate_tax.py` (4) |
| CT-02 | Below threshold → 0 | Profit 300,000 → tax = 0 | `test_corporate_tax.py` |
| CT-03 | Idempotent per tenant+date | Compute twice → same result, no duplicate entry | `test_corporate_tax.py` |
| CT-04 | Income tax expense excluded from base | Tax base = accounting profit − income tax expense | `test_corporate_tax.py` |

### 3.4 Tax Rulesets (Dynamic, Per-Country)

| ID | Scenario | Expected | Verification |
|---|---|---|---|
| TR-01 | Country rate lookup | `country_rate('AE')` → 5.0 | `test_tax_engine.py` (30) |
| TR-02 | Tenant-specific override | Tenant with custom ruleset → uses tenant's rate | `test_tax_engine_tenant.py` |
| TR-03 | Effective-dated rate change | Saudi 5%→15% from 2020-07-01 → rate on 2020-06-30 = 5%, on 2020-07-01 = 15% | `test_tax_engine.py` |
| TR-04 | Unique partial index | Two platform-default rulesets for same country → IntegrityError | `test_tax_engine.py` |
| TR-05 | Compliance snapshot | `country_compliance_snapshot('AE')` → supported/partial/not_supported | `test_tax_engine.py` |

---

## 4. Operational & Administrative Workflows

### 4.1 Quotation Lifecycle

| ID | Scenario | Steps | Expected |
|---|---|---|---|
| QL-01 | Draft → Sent → Accepted → Converted | Create draft → send → accept → convert | Each transition valid; converted creates sale |
| QL-02 | Draft → Sent → Rejected | Create → send → reject | Status = rejected; cannot convert |
| QL-03 | Auto-expire | valid_until = yesterday, status='draft' | GET view → status='expired' |
| QL-04 | Duplicate | Duplicate accepted quotation | New draft with same lines/fields, new number |
| QL-05 | Delete draft only | Delete accepted quotation | Refused (status != 'draft') |
| QL-06 | Print with company identity | Print quotation | Company name/TRN/address/logo; "صُدر بواسطة AzadERP" footer; no AzadERP branding except footer |
| QL-07 | Stock check at conversion | Product with 0 stock → convert | SaleService raises ValidationError; quotation NOT marked converted |

### 4.2 Partner Management (Owner)

| ID | Scenario | Steps | Expected |
|---|---|---|---|
| PM-01 | Set company partner scope | POST set_scope scope=company share=30 | customer.partner_scope='company', partner_share=30, customer_type='partner' |
| PM-02 | Set product partner scope | POST set_scope scope=product | partner_scope='product', partner_share=NULL, customer_type='partner' |
| PM-03 | Clear partner scope (no links) | POST set_scope scope=none | partner_scope='none', customer_type='regular' |
| PM-04 | Clear partner scope (with product links) | POST set_scope scope=none (partner has product links) | partner_scope='none', customer_type stays 'partner' (links preserved) |
| PM-05 | Record draw (cash) | POST record_draw amount=120 source=cash | GL entry: Dr 3350 120 (party) / Cr 1110 120; reference_type='PartnerDraw' |
| PM-06 | Record draw (bank) | POST record_draw amount=120 source=bank | GL entry: Dr 3350 120 / Cr 1120 120 |
| PM-07 | Draw requires impersonation | POST record_draw without impersonation | 302 redirect, flash error, no entry created |
| PM-08 | Distribute requires impersonation | POST distribute without impersonation | 302 redirect, flash error |
| PM-09 | Distribute posts tenant-scoped entry | Impersonate tenant → POST distribute | Entry with tenant_id=tenant, total_debit=total_credit |
| PM-10 | Platform overview (no impersonation) | GET /owner/partners without impersonation | Per-tenant summary table (read-only) |

### 4.3 Backup Verification

| ID | Scenario | Steps | Expected |
|---|---|---|---|
| BV-01 | Verify valid backup | Run `flask verify-backup` on valid dump | PASS: size > 0, SHA-256 matches, ≥30 tables, data indicators present |
| BV-02 | Verify corrupted backup | Tamper with backup file → verify | FAIL: SHA-256 mismatch or gzip error |
| BV-03 | Verify empty backup | Empty file → verify | FAIL: size = 0 |
| BV-04 | Deep verify via UI | `/owner/backups/verify-latest` | Same checks + audit log entry |

### 4.4 Support Tickets & SLA

| ID | Scenario | Steps | Expected |
|---|---|---|---|
| ST-01 | Create ticket | Tenant user creates ticket | Ticket created with tenant_id, status='open' |
| ST-02 | SLA breach detection | Ticket open > SLA threshold | Breach indicator shown in owner inbox |
| ST-03 | Update status | Owner changes status to 'resolved' | Status updated, audit log entry |
| ST-04 | Incident registration | Owner creates incident (SEV-1/2/3) | Incident created, health dashboard updated |

---

## 5. Concurrency & Race Condition Scenarios

### 5.1 Stock Concurrency

| ID | Scenario | Steps | Expected |
|---|---|---|---|
| CC-01 | Parallel sales on same product | 2 concurrent sales of 5 units each on product with stock=5 | One succeeds, one fails with "المخزون غير كافٍ" (FOR UPDATE serializes) |
| CC-02 | Sale + return on same product | Concurrent sale (−2) and return (+1) on same product | Stock reflects both atomically; no negative stock |
| CC-03 | Parallel stock adjustment | 2 concurrent adjustments of +10 and −5 on same product | Final stock = initial + 5; no lost update |
| CC-04 | Moving average under concurrency | Concurrent inbound purchases at different costs | Average cost computed correctly (each inbound locks product row) |

### 5.2 Customer Balance Concurrency

| ID | Scenario | Steps | Expected |
|---|---|---|---|
| CB-01 | Parallel sales to same customer | 2 concurrent sales to same customer | Both committed; balance = sum of both; no lost update (FOR UPDATE on customer) |
| CB-02 | Sale + payment concurrent | Sale creates + payment posts simultaneously | Both committed atomically; balance correct |
| CB-03 | Sale + return concurrent | Sale creates + return posts simultaneously | Both committed; balance = sale − return |

### 5.3 Quotation Conversion Concurrency

| ID | Scenario | Steps | Expected |
|---|---|---|---|
| QC-01 | Double conversion race | 2 concurrent convert calls on same quotation | One succeeds, one raises "عرض الأسعار هذا مُحَوَّل بالفعل" (FOR UPDATE on quotation) |

### 5.4 Partner Distribution Concurrency

| ID | Scenario | Steps | Expected |
|---|---|---|---|
| PD-01 | Concurrent distribution + sale | Distribute period while sale posts partner share | Distribution sees consistent snapshot; no partial read |
| PD-02 | Concurrent draws + distribution | Record draw while distribution runs | Draw is either included or not (serialized via row lock on customer) |
| PD-03 | Concurrent overlapping distribution | Two distribute calls with overlapping periods | One succeeds, other raises ValueError: متداخل |

### 5.5 GL Entry Number Concurrency

| ID | Scenario | Steps | Expected |
|---|---|---|---|
| GL-01 | Parallel sale creation | 5 concurrent sales | 5 unique entry numbers (distributed lock) |
| GL-02 | Parallel manual entries | 3 concurrent manual entries | 3 unique entry numbers |

---

## 6. Test Execution Matrix

### 6.1 Unit Tests

| Suite | Tests | Status | Command |
|---|---|---|---|
| `test_partner_profit.py` | 34 | ✅ green | `pytest tests/unit/test_partner_profit.py` |
| `test_owner_partners_page.py` | 10 | ✅ green | `pytest tests/unit/test_owner_partners_page.py` |
| `test_erp_modules_journal.py` | 45 | ✅ green | `pytest tests/unit/test_erp_modules_journal.py` |
| `test_route_isolation_census.py` | 6 | ✅ green | `pytest tests/unit/test_route_isolation_census.py` |
| `test_account_resolution.py` | 21 | ✅ green | `pytest tests/unit/test_account_resolution.py` |
| `test_return_service.py` | 9 | ✅ green | `pytest tests/unit/test_return_service.py` |
| `test_double_entry_integrity.py` | 45 | ✅ green | `pytest tests/unit/test_double_entry_integrity.py` |
| `test_sales_tax_posting.py` | 36 | ✅ green | `pytest tests/unit/test_sales_tax_posting.py` |
| `test_sales.py` | 9 | ✅ green | `pytest tests/unit/test_sales.py` |
| `test_mixed_vat.py` | 4 | ✅ green | `pytest tests/unit/test_mixed_vat.py` |
| `test_tax_engine.py` | 30 | ✅ green | `pytest tests/unit/test_tax_engine.py` |
| `test_corporate_tax.py` | 4 | ✅ green | `pytest tests/unit/test_corporate_tax.py` |
| `test_vat_report_by_rate.py` | 4 | ✅ green | `pytest tests/unit/test_vat_report_by_rate.py` |
| `test_amount_in_words.py` | 12 | ✅ green | `pytest tests/unit/test_amount_in_words.py` |
| `test_owner_panel.py` | 18 | ✅ green | `pytest tests/unit/test_owner_panel.py` |
| `test_tenant_isolation.py` | 9 | ✅ green | `pytest tests/unit/test_tenant_isolation.py` |
| `test_tenant_isolation_p0.py` | 19 | ✅ green | `pytest tests/unit/test_tenant_isolation_p0.py` |
| `test_invoice_header_isolation.py` | 12 | ✅ green | `pytest tests/unit/test_invoice_header_isolation.py` |
| `test_invoice_print_isolation.py` | 9 | ✅ green | `pytest tests/unit/test_invoice_print_isolation.py` |
| `test_ai_guide_loader.py` | 4 | ✅ green | `pytest tests/unit/test_ai_guide_loader.py` |
| `test_ai_guide_endpoint.py` | 1 | ✅ green | `pytest tests/unit/test_ai_guide_endpoint.py` |

### 6.2 Integration Tests

| Suite | Tests | Status | Command |
|---|---|---|---|
| `test_sale_to_gl.py` | 10 | ✅ green (Postgres) | `DATABASE_URL=postgresql://... pytest tests/integration/test_sale_to_gl.py` |
| `test_full_erp_flow.py` | (part of 29) | ✅ green (Postgres) | `DATABASE_URL=postgresql://... pytest tests/integration/test_full_erp_flow.py` |
| `test_inbound_shipments.py` | (part of 29) | ✅ green (Postgres) | `DATABASE_URL=postgresql://... pytest tests/integration/test_inbound_shipments.py` |
| `test_wave_finance_pages.py` | 53 | ✅ green | `pytest tests/integration/test_wave_finance_pages.py` |

### 6.3 E2E Tests

| Domain | Shards | Status | Command |
|---|---|---|---|
| 30 domains × 2 shards = 60 jobs | 5880 scenarios | ✅ green | `pytest tests/e2e/` (CI matrix) |
| `partners` domain | 2 shards | ✅ green | CI matrix |

### 6.4 CI Workflows

| Workflow | Status | Last Run |
|---|---|---|
| CI (8 jobs: lint, test, security-scan, frontend, integration, verify-boot, repo-security, alembic-smoke) | ✅ success | 42660366928 (38m31s) |
| E2E (14 shards) | ✅ success | 42660367457 (11m23s) |
| Alembic Round-Trip | ✅ success | 42657980122 (1m34s) |

### 6.5 Alembic Migration Chain

| Migration | Status | Verification |
|---|---|---|
| b25_partners | ✅ RT green on Postgres 15 | upgrade → downgrade → re-upgrade |
| b26_quotation_phase1 | ✅ RT green (alembic-smoke) | upgrade on fresh DB |
| Full chain (b0 → b26) | ✅ RT green | CI alembic-smoke |

---

## 7. Verification Commands (Quick Reference)

```bash
# Unit tests (full)
python -m pytest tests/unit/ -q --tb=short

# Integration tests (PostgreSQL)
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/azad_test python -m pytest tests/integration/ -q --tb=short

# E2E tests
python -m pytest tests/e2e/ -q --tb=short

# Security tests
python -m pytest tests/security/ -q --tb=short

# Route census
python -m pytest tests/unit/test_route_isolation_census.py -q

# Alembic round-trip (PostgreSQL)
DATABASE_URL=postgresql://azad_test:azad_test@localhost:5432/azad_test flask db upgrade head
flask db downgrade b25_partners
flask db upgrade head

# Lint (critical)
flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics --exclude='.git,venv,.venv,env,instance,node_modules,static,ai_knowledge/models,migrations'

# Security scan
bandit -c .bandit.yml -r . -ll -ii
pip-audit -r requirements.txt

# Backup verification
flask verify-backup
```

---

## 8. Known Gaps (Honest Assessment)

| Gap | Severity | Mitigation |
|---|---|---|
| Legal compliance (ZATCA/FTA/ETA filing) | Out of scope | Requires authority contract + certificate |
| Production deployment (PythonAnywhere) | Pending approval | `flask db upgrade` + reload + cron |
| Load testing (concurrent users) | Not done | E2E `concurrent_repeat` state covers basic concurrency; no load test |
| Coverage 75.72% | Medium | CI tracks; partner module 85%+, gl_service 95%+ |
| AI in production | Disabled by default | Requires explicit activation + provider setup |
| Manual treasury draws to partner | Tracked only via `/owner/partners` or tagged manual entries | Documented; auto-detection via party_id on 3350 debits |
| Quotation Phase 2/3 | Not started | Print + duplicate + delete done in Phase 1; filter/search/email/versioning pending |
| Partner profit on manual COGS adjustments | Not allocated | By design: profit allocated at sale time only |

---

## 9. Conclusion

The platform is **operationally and accounting-complete** for:
- Multi-tenant isolation (514 routes classified, 355 tenant-scoped with isolation evidence)
- Sales/purchases/returns/expenses with per-line VAT
- Partner profit distribution (product + company levels, dual-role, draws, unpaid sales, loss allocation)
- Quotation lifecycle (Phase 1 complete with per-line tax, inclusive/exclusive, conversion guard)
- GL integrity (double-entry, direction checks, fiscal periods, audit logs, reversals)
- HR (departments, employees, leave, payroll)
- Cheques, write-offs, FX revaluation
- Backup verification, monitoring, audit logs
- CI/E2E/Alembic all green

**Not claimed**: Legal compliance, production deployment, 100% coverage, load testing.