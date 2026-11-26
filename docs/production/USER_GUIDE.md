# دليل المستخدم الشامل — Azad ERP
# Complete User Guide — Azad ERP

> نسخة عربية succinct + English quick reference. محدَّث 2026-11-18 ومطابق للكود.
> الملفان اللذان يقرأهما مساعد AI: `FULL_USER_GUIDE.md` (عام) و`OWNER_USER_GUIDE.md` (مالك).

---

## 1. البدء / Getting Started

**عربي**
1. افتح `http://localhost:5000/auth/login` (أو عنوان النشر).
2. سجّل الدخول باسم المستخدم وكلمة المرور. المالك يستخدم المفتاح اليومي
   `<seed>@YYYY@MM@DD` (UTC) بدل كلمة مرور ثابتة.
3. عند أول دخول، غيّر كلمة المرور عندما يُطلب ذلك.
4. من اللوحة `main.dashboard` اختر الوحدة حسب صلاحيتك.

**English**
1. Open `http://localhost:5000/auth/login` (or your deployed URL).
2. Sign in with username/password. The owner signs in with the daily master key
   `<seed>@YYYY@MM@DD` (UTC) instead of a fixed password.
3. On first login you'll be asked to change your password.
4. Use the dashboard to pick a module based on your role.

> **Roles / الأدوار:** owner, super_admin, developer, manager, accountant, seller,
> cashier, viewer, and maintenance-specific roles. Each role sees only its scope.

---

## 2. المبيعات / Sales

**عربي**
- المسار `routes/sales.py`. أنشئ فاتورة: `/sales/create` — اختر العميل والمستودع،
  أضف الأصناف والكميات والأسعار، حدّد العملة/سعر الصرف، ثم احفظ.
- النظام يتحقق من المخزون والائتمان، يخصم المخزون، ويرحّل قيدَي الإيراد وCOGS تلقائياً.
- الطباعة `/sales/<id>/print`؛ المرتجع `/returns/api/create`؛ الإلغاء `/sales/<id>/cancel`.
- **مهم:** القيود تُنشأ بالعملة الأساس؛ `amount_base = amount × exchange_rate`.

**English**
- Module `routes/sales.py`. Create an invoice at `/sales/create`: pick customer and
  warehouse, add product lines, set currency/FX if non-base, then save.
- The app checks stock & credit, deducts inventory, and auto-posts the revenue and
  COGS journal entries. Print at `/sales/<id>/print`; return via `/returns/api/create`;
  cancel at `/sales/<id>/cancel`.
- All postings are balanced in base currency (`amount_base = amount × rate`).

---

## 3. المشتريات والدفعات / Purchases & Payments

**عربي**
- `/purchases/create`: المورد، الأصناف، الضريبة (قابلة للاسترداد / عكس الشحن).
  الاستلام يرحّل قيد المخزون والضريبة والدائنين.
- `/payments/create_from_sale/<sale_id>` للتحصيل، `/payments/receipts` لسندات القبض،
  `/payments/voucher/create` لسندات الصرف.
- `/cheques`: شيكات واردة/صادرة — استلام، إيداع، صرف، ارتداد، إلغاء؛ كلها بقيود متوازنة.

**English**
- `/purchases/create`: supplier, lines, VAT (recoverable / reverse-charge). Receipt
  auto-posts inventory/VAT/payables.
- `/payments/create_from_sale/<sale_id>` to collect; `/payments/receipts` for receipts;
  `/payments/voucher/create` for payment vouchers.
- `/cheques`: incoming/outgoing cheques with receive/deposit/clear/bounce/cancel —
  each produces a balanced journal entry.

---

## 4. المخزون / Inventory

**عربي**: `/products` و`/warehouse` — أصناف، تصنيفات، مستودعات، تحركات، جرد،
وتنبيهات نقص. التكلفة بالمتوسط المتحرك المرجّح.

**English**: `/products` and `/warehouse` — products, categories, warehouses,
stock movements, stock takes, low-stock alerts. Moving-weighted-average costing.

---

## 5. المحاسبة والتقارير / Accounting & Reports

**عربي**
- `/ledger`: دليل الحسابات، ميزان المراجعة، قائمة الدخل، الميزانية العمومية،
  كشف الحساب، القيود اليدوية والعكس.
- `/reports`: تقارير المبيعات/المشتريات، الذمم، المخزون، تقييم المخزون، كشف الشريك.
- الأرصدة تُحسب من القيود **المُرحَّلة فقط** بعملة الأساس — لا تظهر المسودات.

**English**
- `/ledger`: chart of accounts, trial balance, income statement, balance sheet,
  account statement, manual entries & reversals.
- `/reports`: sales/purchases, receivables/payables, inventory valuation, partner statement.
- Balances use **posted entries only** in base currency — drafts never appear.

---

## 6. الصيانة / Maintenance

**عربي** (يتطلب `enable_maintenance` وصلاحيات `maintenance_*`)
`/maintenance`: استقبال، قطع بالتكلفة الفعلية، خدمات، حالات، خصم، ضمان، فاتورة،
سند قبض، مرتجع، إشعار دائن، طباعة، تقرير تكلفة.

**English** (requires `enable_maintenance` + `maintenance_*` permissions)
`/maintenance`: reception, parts at actual cost, services, statuses, discounts,
warranty, invoice, receipt, return, credit note, printing, cost report.

---

## 7. الرواتب / Payroll

**عربي**: `/hr` — أقسام، موظفون، إجازات، كشوفات رواتب. صرف الكشف
`/hr/payroll/<id>/pay` يرحّل قيد الرواتب تلقائياً.

**English**: `/hr` — departments, employees, leave, payslips. Paying a payslip at
`/hr/payroll/<id>/pay` auto-posts the salary journal entry.

---

## 8. بوابات الميزات / Feature Gates

| وحدة / Module | الحاجة / Requires | افتراضي / Default |
|---|---|---|
| `/api/*`, `/api/v2/*`, `/graphql` | `enable_api` | **False** (معطّل) |
| `/ai` | `enable_ai` | True |
| `/ledger` | `enable_gl` | True |
| `/reports` | `enable_reports` | True |
| `/maintenance` | `enable_maintenance` | True |

عند تعطيل الميزة تُرفض الطلبات بـ **403**؛ وعند تعذّر التحقق بـ **503**.
نقاط البنية التحتية (`/api/health`, `/api/healthz`, `/api/version`,
`/monitoring/health`, `/monitoring/metrics`) معفاة.
Disabled feature → **403**; verification failure → **503**. Infrastructure
health endpoints are exempt.

---

## 9. المالك / Owner (fit in `OWNER_USER_GUIDE.md`)

`/owner/dashboard`, `/owner/tenants`, `/owner/roles-permissions`,
`/owner/backup-now`. المالك يتجاوز البوابات (عرض المنصة). تسجيل الدخول بالمفتاح
اليومي فقط. The owner bypasses gates and signs in with the daily master key only.

---

*للتفاصيل التقنية راجع الكود المصدري واختبارات المشروع. For technical details,
refer to the source code and the project test suites.*
