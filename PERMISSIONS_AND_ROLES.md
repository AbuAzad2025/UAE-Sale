# 🔐 الصلاحيات والأدوار والمستخدمين (Permissions, Roles & Users) — UAE-Sale ERP

> هذا التقرير يحصي **جميع الصلاحيات** (26 صلاحية) و**الأدوار** (3 platform + 13 operational) و**ربطها منطقياً بالمستخدمين** حسب وظيفتهم في النظام. كل دور يحصل على مجموعة صلاحيات محددة، والمستخدمون الافتراضيون يُنشأون تلقائياً لكل تينانت.

---

## 1. جدول الصلاحيات (Permissions Catalog) — 27 صلاحية

### 1.1 المبيعات (Sales)

| # | Code | Name (AR) | الوصف | مستخدم في |
|---|------|-----------|-------|-----------|
| 1 | `manage_sales` | إدارة المبيعات | إنشاء/تعديل/حذف فواتير البيع، عروض الأسعار | `routes/sales.py`, `routes/erp_modules.py`, `routes/api_enhanced.py` |
| 2 | `view_products` | عرض المنتجات | عرض قائمة المنتجات (read-only) | `routes/ai.py` |

### 1.2 المنتجات (Products)

| # | Code | Name (AR) | الوصف | مستخدم في |
|---|------|-----------|-------|-----------|
| 3 | `manage_products` | إدارة المنتجات | إنشاء/تعديل/حذف منتجات، فئات، تعديل المخزون | `routes/products.py`, `routes/api_enhanced.py`, `routes/ai.py` |
| 4 | `view_costs` | عرض التكاليف | عرض cost_price/average_cost/stock_value (permission-driven) | `models/user.py::can_see_costs()` |

### 1.3 العملاء (Customers)

| # | Code | Name (AR) | الوصف | مستخدم في |
|---|------|-----------|-------|-----------|
| 5 | `manage_customers` | إدارة العملاء | إنشاء/تعديل/حذف عملاء، شركاء، تجار | `routes/customers.py`, `routes/api_enhanced.py`, `routes/ai.py` |

### 1.4 الموردين (Suppliers)

| # | Code | Name (AR) | الوصف | مستخدم في |
|---|------|-----------|-------|-----------|
| 6 | `manage_suppliers` | إدارة الموردين | إنشاء/تعديل/حذف موردين | `routes/suppliers.py` |

### 1.5 المشتريات (Purchases)

| # | Code | Name (AR) | الوصف | مستخدم في |
|---|------|-----------|-------|-----------|
| 7 | `manage_purchases` | إدارة المشتريات | فواتير شراء، أوامر شراء (PO)، استلام | `routes/purchases.py`, `routes/erp_modules.py` |

### 1.6 المدفوعات والمالية (Payments & Finance)

| # | Code | Name (AR) | الوصف | مستخدم في |
|---|------|-----------|-------|-----------|
| 8 | `manage_payments` | إدارة المدفوعات | تسجيل/عرض المدفوعات، الشيكات، payment vault | `routes/payments.py`, `routes/payment_vault.py` |
| 9 | `manage_expenses` | إدارة المصروفات | إنشاء/تعديل/حذف مصروفات | `routes/expenses.py` |
| 10 | `view_ledger` | عرض دفتر الأستاذ | عرض GL entries, trial balance | `routes/ledger.py`, `routes/advanced_ledger.py`, `routes/ai.py`, `routes/graphql.py` |
| 11 | `manage_ledger` | إدارة دفتر الأستاذ | ترحيل قيود، إقفال فترات | `routes/ledger.py`, `routes/advanced_ledger.py` |

### 1.7 التقارير (Reports)

| # | Code | Name (AR) | الوصف | مستخدم في |
|---|------|-----------|-------|-----------|
| 12 | `view_reports` | عرض التقارير | عرض جميع التقارير (مبيعات، مخزون، مالي، إلخ) | `routes/reports.py`, `routes/api_analytics.py`, `routes/ai.py`, `routes/graphql.py` |

### 1.8 المستودعات (Warehouse)

| # | Code | Name (AR) | الوصف | مستخدم في |
|---|------|-----------|-------|-----------|
| 13 | `manage_warehouse` | إدارة المستودعات | شحنات واردة، تعديلات مخزون، locations, bins | `routes/warehouse.py`, `routes/inbound_shipments.py`, `routes/shipments.py` |

### 1.9 الموارد البشرية (HR)

| # | Code | Name (AR) | الوصف | مستخدم في |
|---|------|-----------|-------|-----------|
| 14 | `manage_hr` | إدارة الموارد البشرية | موظفين، رواتب، إجازات | `routes/hr.py` |

### 1.10 الموافقات (Approvals)

| # | Code | Name (AR) | الوصف | مستخدم في |
|---|------|-----------|-------|-----------|
| 15 | `manage_approvals` | إدارة الموافقات | سير عمل الموافقات (workflows) | `routes/approvals.py` |

### 1.11 الإعدادات والنسخ الاحتياطي (Settings & Backups)

| # | Code | Name (AR) | الوصف | مستخدم في |
|---|------|-----------|-------|-----------|
| 16 | `manage_settings` | إدارة الإعدادات | إعدادات النظام، lookups، currencies | `routes/settings.py` |
| 17 | `manage_backups` | إدارة النسخ الاحتياطي | إنشاء/استعادة نسخ احتياطية | `routes/owner.py`, `routes/settings.py` |

### 1.12 المستخدمين (Users)

| # | Code | Name (AR) | الوصف | مستخدم في |
|---|------|-----------|-------|-----------|
| 18 | `manage_users` | إدارة المستخدمين | إنشاء/تعديل/حذف مستخدمين، تعيين أدوار | `routes/users.py` |

### 1.13 الصيانة (Maintenance) — 8 صلاحيات

| # | Code | Name (AR) | الوصف | مستخدم في |
|---|------|-----------|-------|-----------|
| 19 | `maintenance_view` | عرض الصيانة | عرض أوامر الصيانة، التقارير | `routes/maintenance.py` |
| 20 | `maintenance_receive` | استقبال الصيانة | استقبال مركبات، إنشاء أوامر صيانة | `routes/maintenance.py` |
| 21 | `maintenance_cashier` | تحصيل صيانة | تحصيل مدفوعات، سندات قبض | `routes/maintenance.py` |
| 22 | `maintenance_purchase` | شراء قطع الصيانة | شراء/استلام قطع غيار للصيانة | `routes/maintenance.py` |
| 23 | `maintenance_work` | أعمال الصيانة | إضافة قطع/خدمات، تشخيص، إصلاح | `routes/maintenance.py` |
| 24 | `maintenance_close` | إنهاء الصيانة | إغلاق أوامر الصيانة، تسليم | `routes/maintenance.py` |
| 25 | `maintenance_discount` | خصم الصيانة | تطبيق خصومات على أوامر الصيانة | `routes/maintenance.py` |
| 26 | `maintenance_settings` | إعدادات الصيانة | إعدادات وحدة الصيانة | `routes/maintenance.py` |

### 1.14 صلاحيات غير مستخدمة (Orphan)

| # | Code | Name (AR) | ملاحظة |
|---|------|-----------|--------|
*(تمت إزالة صلاحية `admin` (orphan) من seeding — admin_required يستخدم flags is_owner/is_super_admin)*

---

## 2. الأدوار (Roles) — 3 Platform + 13 Operational

### 2.1 أدوار المنصة (Platform Roles) — Full Access

| Role | Slug | الوصف | الصلاحيات | المستخدم الافتراضي |
|------|------|-------|-----------|-------------------|
| **Owner** (المالك) | `owner` | وصول كامل (Master Key) | **ALL 27** | `owner` (env: OWNER_USERNAME, OWNER_PASSWORD) |
| **Super Admin** (مدير عام) | `super_admin` | وصول كامل (except Owner Panel) | **ALL 27** | يُنشأ يدوياً (Owner Panel) |
| **Developer** (مطوّر) | `developer` | وصول كامل (maintenance) | **ALL 27** | يُنشأ يدوياً (Owner Panel) |

### 2.2 أدوار تشغيلية (Operational Roles) — Tenant-Scoped

هذه الأدوار تُنشأ تلقائياً لكل تينانت (tenant) عند إنشائه (إذا `enable_maintenance=True`، تُنشأ أيضاً أدوار الصيانة).

| Role | Slug | Name (AR) | الصلاحيات (Permissions) |
|------|------|-----------|------------------------|
| **Manager** (مدير فرع) | `manager` | مدير فرع | `manage_sales`, `manage_customers`, `manage_products`, `manage_purchases`, `manage_suppliers`, `manage_payments`, `manage_expenses`, `manage_warehouse`, `manage_users`, `view_ledger`, `view_reports`, `view_costs`, `maintenance_view`, `maintenance_receive`, `maintenance_work`, `maintenance_close`, `maintenance_discount`, `maintenance_settings`, `maintenance_purchase` |
| **Seller** (بائع) | `seller` | بائع | `manage_sales`, `manage_customers`, `manage_products` |
| **Accountant** (محاسب) | `accountant` | محاسب | `view_ledger`, `manage_ledger`, `view_reports`, `view_costs`, `manage_payments`, `manage_expenses`, `maintenance_view` |
| **Cashier** (كاشير) | `cashier` | كاشير | `manage_sales`, `manage_payments`, `maintenance_view`, `maintenance_cashier` |
| **HR** (موارد بشرية) | `hr` | موارد بشرية | `manage_hr` |
| **Inventory** (أمين مخزون) | `inventory` | أمين مخزون | `manage_warehouse`, `manage_products`, `view_products`, `maintenance_view`, `maintenance_work`, `maintenance_purchase` |
| **Viewer** (مشاهد) | `viewer` | مشاهد | `view_reports`, `view_ledger` |

### 2.3 أدوار الصيانة (Maintenance Roles) — Tenant-Scoped (enable_maintenance=True only)

| Role | Slug | Name (AR) | الصلاحيات (Permissions) | الوظيفة |
|------|------|-----------|------------------------|---------|
| **Maintenance Reception** | `maintenance_reception` | استقبال صيانة | `maintenance_view`, `maintenance_receive` | استقبال مركبات، إنشاء أوامر صيانة |
| **Maintenance Engineer** | `maintenance_engineer` | مهندس صيانة | `maintenance_view`, `maintenance_work` | تشخيص، إصلاح، إضافة قطع/خدمات |
| **Maintenance Cashier** | `maintenance_cashier` | صندوق صيانة | `maintenance_view`, `maintenance_cashier` | تحصيل مدفوعات، سندات قبض |
| **Maintenance Closer** | `maintenance_closer` | إنهاء صيانة | `maintenance_view`, `maintenance_close` | إغلاق أوامر، تسليم مركبات |
| **Maintenance Discount** | `maintenance_discount` | خصم صيانة | `maintenance_view`, `maintenance_discount` | تطبيق خصومات |
| **Maintenance Settings** | `maintenance_settings` | إعدادات صيانة | `maintenance_view`, `maintenance_settings`, `maintenance_purchase` | إعدادات وحدة الصيانة، شراء قطع |

---

## 3. ربط المستخدمين (User → Role → Permissions)

### 3.1 Platform Users (مستخدمو المنصة)

| Username | Role | Permissions | ملاحظة |
|----------|------|-------------|--------|
| `owner` (env: OWNER_USERNAME) | Owner | ALL 27 | Master Key — يُنشأ عند `ensure_system_integrity()` |
| `super_admin` | Super Admin | ALL 27 | يُنشأ يدوياً (Owner Panel) |
| `developer` | Developer | ALL 27 | يُنشأ يدوياً (Owner Panel) |

### 3.2 Tenant Default Users (مستخدمو التينانت الافتراضيون)

عند إنشاء تينانت جديد (`routes/owner.py` → `_ensure_operational_roles_for_tenant`), تُنشأ **أدوار + مستخدمون** تلقائياً:

| Username Pattern | Role | Password | must_change_password | الصلاحيات |
|-----------------|------|----------|---------------------|-----------|
| `{tenant_slug}_manager` | Manager | `Test-password-123!` | ✅ True | 19 صلاحية (full operational + maintenance) |
| `{tenant_slug}_seller` | Seller | `Test-password-123!` | ✅ True | 3 صلاحيات (sales, customers, products) |
| `{tenant_slug}_accountant` | Accountant | `Test-password-123!` | ✅ True | 7 صلاحيات (ledger, reports, payments, expenses, maintenance_view) |
| `{tenant_slug}_cashier` | Cashier | `Test-password-123!` | ✅ True | 4 صلاحيات (sales, payments, maintenance_view, maintenance_cashier) |
| `{tenant_slug}_hr` | HR | `Test-password-123!` | ✅ True | 1 صلاحية (manage_hr) |
| `{tenant_slug}_inventory` | Inventory | `Test-password-123!` | ✅ True | 6 صلاحيات (warehouse, products, view_products, maintenance_view, maintenance_work, maintenance_purchase) |
| `{tenant_slug}_viewer` | Viewer | `Test-password-123!` | ✅ True | 2 صلاحيات (view_reports, view_ledger) |

**Maintenance roles (only if `enable_maintenance=True`):**

| Username Pattern | Role | Password | must_change_password | الصلاحيات |
|-----------------|------|----------|---------------------|-----------|
| `{tenant_slug}_maintenance_reception` | Maintenance Reception | `Test-password-123!` | ✅ True | 2 صلاحيات (maintenance_view, maintenance_receive) |
| `{tenant_slug}_maintenance_engineer` | Maintenance Engineer | `Test-password-123!` | ✅ True | 2 صلاحيات (maintenance_view, maintenance_work) |
| `{tenant_slug}_maintenance_cashier` | Maintenance Cashier | `Test-password-123!` | ✅ True | 2 صلاحيات (maintenance_view, maintenance_cashier) |
| `{tenant_slug}_maintenance_closer` | Maintenance Closer | `Test-password-123!` | ✅ True | 2 صلاحيات (maintenance_view, maintenance_close) |
| `{tenant_slug}_maintenance_discount` | Maintenance Discount | `Test-password-123!` | ✅ True | 2 صلاحيات (maintenance_view, maintenance_discount) |
| `{tenant_slug}_maintenance_settings` | Maintenance Settings | `Test-password-123!` | ✅ True | 3 صلاحيات (maintenance_view, maintenance_settings, maintenance_purchase) |

---

## 4. مصفوفة الصلاحيات × الأدوار (Permission × Role Matrix)

| Permission | Owner | Super Admin | Developer | Manager | Seller | Accountant | Cashier | HR | Inventory | Viewer | Maint. Reception | Maint. Engineer | Maint. Cashier | Maint. Closer | Maint. Discount | Maint. Settings |
|-----------|-------|-------------|-----------|---------|--------|------------|---------|-----|-----------|--------|------------------|-----------------|----------------|---------------|-----------------|-----------------|
| `manage_sales` | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `manage_purchases` | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `manage_products` | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `manage_customers` | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `manage_suppliers` | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `manage_payments` | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `manage_expenses` | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `view_reports` | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `manage_users` | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `manage_warehouse` | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `view_ledger` | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `manage_ledger` | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
*(تمت إزالة صلاحية `admin` orphan)*
| `manage_backups` | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `manage_hr` | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `manage_approvals` | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `manage_settings` | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `view_products` | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `view_costs` | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `maintenance_view` | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `maintenance_receive` | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `maintenance_cashier` | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ |
| `maintenance_purchase` | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| `maintenance_work` | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ |
| `maintenance_close` | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ |
| `maintenance_discount` | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ |
| `maintenance_settings` | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |

---

## 5. منطق الربط (Logic Summary)

### 5.1 Platform (منصة)
- **Owner/Super Admin/Developer** → ALL 27 permissions (full access).
- `admin_required` decorator checks `is_owner or is_super_admin()` flags (not the `admin` permission).
- `view_costs` permission is permission-driven (`models.User.can_see_costs()`).

### 5.2 Tenant (مستأجر)
- عند إنشاء تينانت (`routes/owner.py` → `_ensure_operational_roles_for_tenant`):
  - **Core roles** (manager, seller, accountant, cashier, hr, inventory, viewer) → always created.
  - **Maintenance roles** (maintenance_*) → only if `enable_maintenance=True`.
  - **Default users** → `{tenant_slug}_{role_slug}` with password `Test-password-123!`, `must_change_password=True`.
- **No auto-grant** to existing roles (role assignment is manual via Owner Panel).

### 5.3 Maintenance Isolation
- Engineers (`maintenance_engineer`) **cannot close orders or collect money** (only `maintenance_work`).
- Cashiers (`maintenance_cashier`) can collect (`maintenance_cashier`) but cannot work/close.
- Closers (`maintenance_closer`) can close (`maintenance_close`) but cannot work/collect.
- Only `manager` has full maintenance access (receive, work, close, discount, settings, purchase).

### 5.4 RBAC Enforcement
- `@permission_required('code')` decorator on routes.
- `current_user.has_permission('code')` in templates/services.
- `current_user.can_see_costs()` checks `view_costs` permission.
- Tenant isolation via `TenantScopedMixin` (auto-filters queries by tenant_id).

---

## 6. ملاحظات (Notes)

1. **`admin` permission** is seeded but **unused** in production code (orphan). Consider removing in future cleanup.
2. **`manage_auctions`** and **`nonexistent_perm`** appear only in tests (not production).
3. **Cost visibility** is permission-driven: only `owner`, `super_admin`, `developer`, `manager`, `accountant` have `view_costs`.
4. **Maintenance roles** are created **only when `enable_maintenance=True`** for the tenant.
5. **Default password** `Test-password-123!` with `must_change_password=True` — enforced on first login (`routes/auth.py`).
6. **No tenant selector on login** — tenant is derived from user's `tenant_id`.

---

## 7. ملفات مرجعية (Key Files)

| Purpose | File |
|---------|------|
| Permission seeding | `utils/system_init.py::_ensure_permissions` |
| Owner role | `utils/system_init.py::_ensure_owner_role` |
| Operational roles | `utils/system_init.py::OPERATIONAL_ROLES` |
| Tenant role provisioning | `utils/system_init.py::_ensure_operational_roles_for_tenant` |
| Tenant creation flow | `routes/owner.py` (calls `_ensure_operational_roles_for_tenant`) |
| Login + password change | `routes/auth.py`, `services/user_service.py::change_own_password` |
| Permission decorator | `utils/decorators.py::permission_required` |
| User model (can_see_costs) | `models/user.py` |
| Cost permission grants | `utils/system_init.py::_ensure_cost_permission_grants` |