# 📋 دليل مستخدم لوحة مالك المنصة (Owner Dashboard)

## نظرة عامة

لوحة مالك المنصة (Owner Dashboard) هي مركز التحكم (God Mode) للنظام. توفر تحكمًا كاملاً في:
- المستخدمين والأدوار والصلاحيات
- التينانتات (Multi-tenant management)
- إعدادات النظام (Config, Branding, Integrations)
- التدقيق (Audit, Logs, Security)
- النسخ الاحتياطي (Backups)
- التحليلات (Analytics, Forecasting)
- صحة النظام (Health, Performance)

**الوصول:** `/owner/dashboard` (للمالك فقط)

---

## 1. لوحة التحكم (Dashboard)

### `/owner/dashboard`
إحصائيات النظام: إجمالي المستخدمين، العملاء، المبيعات، الإيرادات.

---

## 2. إدارة المستخدمين (Users & Roles)

### `/owner/roles-permissions`
إدارة الأدوار والصلاحيات (RBAC).

---

## 3. إدارة التينانتات (Tenants)

### `/owner/tenants` — قائمة التينانتات
### `/owner/tenants/new` — إنشاء تينانت
### `/owner/tenants/<id>` — تفاصيل تينانت
### `/owner/tenants/<id>/edit` — تعديل تينانت
### `/owner/tenants/<id>/suspend` — تعليق تينانت
### `/owner/tenants/<id>/activate` — تفعيل تينانت

---

## 4. إعدادات الشركة (Company Info)

### `/owner/company-info`
تعديل معلومات الشركة (اسم، عنوان، هاتف، شعار، ألوان).

### إعدادات الضريبة وكل شركة (Tenant)
- `tax_country` (AE/SA/…), `default_tax_rate`, `enable_tax`, `tax_inclusive` (شامل/إضافي)
- ضريبة الشركات (`corp_tax_*`) — **تقديرية وليست إقراراً ضريبياً**، والمسؤولية القانونية على الشركة ومحاسبها
- كل مستند يحتفظ بلقطته (النسبة/الشمول/المعاملة) وقت الإصدار — تعديل الإعدادات لاحقاً لا يغيّر الفواتير القديمة
- قائمة VAT لكل شركة (المخرجات/المدخلات/المرتجعات) تُصدَّر من `view_reports` وتُطابَق مع الشاشة؛ لا تعتبر توصية قانونية للتقديم

---

## 5. إعدادات النظام (System Config)

### `/owner/system-config`
### `/owner/config`
### `/owner/tax-settings`
### `/owner/currency-settings`
### `/owner/payment-gateways`
### `/owner/email-settings`
### `/owner/sms-settings`
### `/owner/whatsapp-settings`
### `/owner/notification-templates`

---

## 6. ثوابت النظام (Constants)

### `/owner/constants`
### `/owner/constants/<group>`
### `/owner/constants/<group>/add`
### `/owner/constants/<group>/label`
### `/owner/constants/<group>/visibility`

---

## 7. إعدادات الفواتير (Invoice Settings)

### `/owner/invoice-settings`
### `/owner/preview-invoice/<template>`
### `/owner/preview-receipt/<template>`

---

## 8. التدقيق (Audit & Logs)

### `/owner/audit-logs`
### `/owner/error-logs`
### `/owner/error-logs/<id>/resolve`
### `/owner/login-history`
### `/owner/activity-monitor`
### `/owner/security-alerts`
### `/owner/security-alerts/<id>/resolve`
### `/owner/ip-whitelist`
### `/owner/ip-whitelist/<index>/delete`
### `/owner/api-keys`
### `/owner/api-keys/<id>/toggle`

---

## 9. النسخ الاحتياطي (Backups)

### `/owner/database-tools`
### `/owner/backup-now`
### `/owner/backups/list`
### `/owner/backups/verify/<filename>`
### `/owner/backups/restore/<filename>`
### `/owner/backups/custom-restore/<filename>`
### `/owner/backups/delete`
### `/owner/backups/download/<filename>`
### `/owner/scheduled-backups`
### `/owner/verify-backups`
### `/owner/database-optimize`

---

## 10. تقارير (Reports)

### `/owner/reports`
### `/owner/financial-overview`
### `/owner/financial-dashboard-advanced`

---

## 11. تحليلات (Analytics)

### `/owner/sales-insights`
### `/owner/customer-insights`
### `/owner/product-performance`
### `/owner/forecasting`

---

## 12. صحة النظام (System Health)

### `/owner/system-health`
### `/owner/performance-metrics`

---

## 13. إدارة البيانات (Data Management)

### `/owner/data-cleanup`
### `/owner/import-export-tools`
### `/owner/export-excel/<table_name>`
### `/owner/archived`
### `/owner/clear-cache`
### `/owner/truncate-table`
### `/owner/browse-table/<table_name>`
### `/owner/edit-table-data/<table_name>`
### `/owner/export-database`
### `/owner/convert-database`

---

## 14. التكامل (Integrations)

### `/owner/integrations`
### `/owner/integrations/update/<service>`

---

## 15. بطاقات (Cards Vault)

### `/owner/cards-vault`
### `/owner/cards-vault/<id>/view`

---

## 16. تقييم FX (FX Revaluation)

### `/owner/fx-revaluation/`

---

---

## 17. توزيع أرباح الشركاء (`/owner/partners`)

**يتطلب دخول سياق شركة عبر مبدّل Companies في لوحة المالك** (impersonate_tenant_id). بلا سياق: عرض تجميعي للقراءة فقط لكل شركة.

### شريك منتج (ProductPartner)
- يُدار من شاشة المنتج (تعديل منتج → قسم الشركاء) — نسبة لكل شريك.
- عند إنشاء الفاتورة: يُرحَّل قيد فوري (Dr 6910 / Cr 3350 مع party_id).
- المرتجع: عكس تناسبي بالكمية المرتجعة.
- الإلغاء: عكس كامل (عبر reverse_sale_gl_entries).

### شريك شركة (Customer.partner_scope='company')
- نسبة من صافي نتيجة الشركة بالكامل — تُحسب دوريًا (لا لحظيًا).
- المعاينة (`preview_partner_distributions`) تخصم:
  - **المسحوبات** (قيود `PartnerDraw` بطرفه — يدويًا أو عبر قيد يدوي موسوم).
  - **مبيعات غير مسددة له** (`balance_due x exchange_rate`).
- الخسارة تُحمَّل على الشركاء بنسبتهم؛ الملاك المتبقون يأخذون الباقي.
- **منع التوزيع المزدوج** لنفس الفترة (idempotent عبر علامة في notes).
- **حظر تداخل الفترات** — الربح لا يُوزَّع مرتين.
- **شريك ذو دورين** (منتج + شركة) يحصل على الحصتين — كل أساس مستقل.

### الإعداد
- `/owner/partners` (GET): معاينة + قائمة شركاء + روابط منتج + رصيد جاري (3350).
- POST actions: `set_scope` (none/product/company + نسبة)، `record_draw` (cash/bank)، `distribute` (مع period from/to).
- **لا تُعدَّل any بيانات без سياق الشركة** (refused with flash).

### القيود
- 6910 (حصص الشركاء في الأرباح) — مُبذَر تلقائيًا.
- 3350 (جاري الشركاء) + 3400 (أرباح السنة الحالية) — F8 direction whitelisted.

---

**هل تريد أن أساعدك في أي فئة بالتفصيل؟**
