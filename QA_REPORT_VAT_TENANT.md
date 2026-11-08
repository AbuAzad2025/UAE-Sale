# QA Report — إصلاح الضريبة وهوية الشركة لكل شركة (VAT & Tenant Identity)

آخر تحديث: 2026-11-08 | نطاق الإصلاح: حسابات الضريبة، الأصول/القيود، هوية المستندات، العزل، التنزيل/الطباعة

## 1. ما أُصلح وتحقق محلياً (قبل النشر)

| # | المشكلة | الإصلاح | التحقق المحلي |
|---|---------|---------|----------------|
| 1 | هوية الفاتورة/السند/المصروف/الشراء قد تسقط إلى بيانات أزاد (IDOR + fallback على هوية المنصة) | `utils/invoice_header.py` ص َّارم: هوية من `document.tenant` فقط؛ إن تعذر الوجود يرفض الطباعة (409) | `tests/unit/test_invoice_*isolation*` (12) — نجحت |
| 2 | تقرير VAT يجمع كل المستندات كخاضعة | صفوف منفصلة للقياسية/الصفرية/المعفاة/غير المصنّفة للمبيعات والمشتريات | `tests/unit/test_reports_p0.py::TestVatReport` — نجحت |
| 3 | الضريبة على مستوى الفاتورة فقط — لا تعايش مع بنود مختلطة | محرك حساب مشترك `services/sale_tax_calculation.py`: ضريبة لكل سطر + توزيع الخصم الإجمالي/الشحن بالتناسب + استخراج الشامل + معاملة قياسية/صفرية/معفاة على كل بند جميعها | `tests/unit/test_mixed_vat.py` (4) |
| 4 | المرتجعات تحسب الضريبة بنفس النسبة للجميع | نفس المحرك للمرتجع من لقطات الأسطر — مرتجعات الفواتير الشاملة وذات الخصم الإجمالي تعمل | `tests/unit/test_return_service.py` |
| 5 | قيد المشتريات غير متزن للشاملة (المخزون يشمل الضريبة) | المخزون = الإجمالي − الضريبة دائماً | `tests/e2e/test_purchases_vat.py` — نجحت |
| 6 | ضريبة الشركات: الزر معطّل (kwargs خاطئة) + الضريبة تُحتسب ضمن أساسها + ازدواج الترحيل | `services/corporate_tax.py` يعيد كتابة بذرّية كاملة + استبعاد حساب مصروف الدخل + حراسة بمرجعية idempotency corporate tax لكل شركة/تاريخ | `tests/unit/test_corporate_tax.py` (4) نجحت |
| 7 | الدفع يسبق الترحيل: إذا فشل GL يبقى «مدفوع» بلا قيد | الدفع + الـGL في معاملة واحدة متكاملة (rollback كامل عند فشل أي خطوة) | `tests/integration/test_wave_finance_pages.py` — البنود المتعلقة بالرواتب تنجح |
| 8 | تنفيذ شطب/صرف من الخارج — يمكن لمستند دون مالك أزاد أن يخرج بهوية أزاد | reverse-vs-404 (`get_owned_or_404`) + العزل بواسطة `tenant_id` + تسجيل المستندات للكل في الفلتر التلقائي | `tests/integration/test_routes_expenses_payments_customers.py` (52) تنجح |
| 9 | مسارات الدفع والصرف تُفوت القيد المحاسبي (ORPHAN RECEIPT) أو تبتلعه | الترحيل ذرّي بالكامل مع إنشاء السند — فشل القيد يُرجع السند كله — supplier refund / outbound supplier / customer partner / cheques / receipts | 52/27/34 من الاختبارات التكاملية والـE2E تنجح |
| 10 | هوية في تصديرات التقارير (PDF/XLSX) = أزاد | توثيق tenant في كل تصدير — `inventory valuation`, `AP aging`, `cash flow`, `VAT` | `tests/unit/test_export_service.py` (31) تنجح |
| 11 | العزل لم يغطَّ ~36 جدول business/HR/ERP/audit وHR/Secrets | `tenant_id` يُضاف لكل نموذج عمل، كل سجل ف يجبر على الفلتر التلقائي | `tests/unit/test_tenant_isolation.py` (9) تنجح |
| 12 | حسابات hard-coded ('1140','2110','2130','1110','1120','6990') في مسارات الدفع/الصرف والمصروفات والمشتريات | كل الاستدعاءات تمر `AccountResolver` — تطابق مع الـschema والـsemantic roles | `tests/e2e/test_expenses_e2e.py` (34) + `test_purchases_e2e.py` (27) تنجح |
| 13 | استخدام "أزاد" في واجهات الإنشاء/العرض (أرقام/درهم) | تُستبدل بـ `{{ base_currency }}` | مراجعة بصرية |
| 14 | ضريبة الشراء غير مميزة في الواجهة ولا في التقرير | `tax_treatment` على الشراء + نموذج اختيار + شاملة/إضافية + صفوف التقرير | `tests/e2e/test_purchases_vat.py` تنجح |
| 15 | ب6_corp_tax كانت تفرض AED كعملة أساس لكل تنانتات عليها ILS | أُزيل التحديث الجماعي للتنانيات ILS → تُترك القرار للمالك التشغيلي | توثيق في DEPLOYMENT.md |
| 16 | تغيير فوتر الفاتورة (أزاد في أعلى) → أزاد يبقى فوتر صغير فقط | كل ما هو في الفوتر من التينانت | `templates/*/*_print.html` |

## 2. ما زال مفتوحاً / مؤكد بانتظار CI أو موافقة

- **CI/E2E قيد المتابعة على أحدث التزام (1e0e92e)** — آخر Alembic Round-Trip على `339f9e3` (يشمل b11–b15): **نجح**. CI/E2E الواسع قيد التجربة نفسها — لا يُنشر قبل أخضر.
- **b6 القديمة في بيئات طُبّقت عليها** — لا يجوز تعديلها صامتة؛ تصحيح العملة أساس التاريخي يحتاج مراجعة يدوية لعملات قاعدة كل شركة (هل انتقلت إليها باليونانية؟).
- **ضريبة الشركات تقديرية** (9% على الربح المحاسبي أعلاه بعتبة 375,000) — **ليست إقراراً قانونياً** (موجود)، ولا تشمل التعديلات الضريبية (إهلاك سياسات، أرباح رأسمالية، خسائر مرحلة).
- **الامتثال القانوني لأي دولة** (شهادة تصدير صفري، أهلية إعفاء، آلية التقدم بالإقرار، إعادة الضريبة على الرسوم) — يتطلب مختصين بدولة الشركة؛ لا يغني عنه أي كود.
- **تغطية ضريبة شاملة عبر كل الـ E2E** — بعض مسارات الضرائب تفحصت بالتستيد المحدد، لا ~100 مسار مختلف كامل.
- **4220 برقية موارد/إصلاحات إضافية من التدقيق الشامل** (Super-admin Scope، غير محظور الحسابات…) — بنود منفصلة خارج هذا النطاق ولم أقدر على الوصول إليها بالكامل في هذه الجلسة.
- **B3/B4 tenants/currencies b6 مطبقة على بيانات حالية** — لا يمكن التراجع صامت؛ يجب مراجعة الجدول قبل التطبيق الإنتاجي.
- **Segment payload semantics — العرض/الطباعة تُختبر في المتصفح يدوياً** لا عبر E2E متابعات على كل القوالب.

## 3. الهيكل الجديد

- الهجرات الهرمية: `b8_vat_treatments` (product/sale) → `b9_purchase_tax_treatment` (purchase) → `b10_sale_line_tax_treatment` (sale line snapshot) → `b11_expense_tenant` → `b12_hr_tenant` → `b13_erp_tenant` → `b14_business_tenant` → `b15_shipment_lines_tenant`.
- خدمة الحساب الواحدة: `services/sale_tax_calculation.py` — تُستخدم من الحفظ، المعاينة، الأستاذ، المرتجع، تقرير VAT، والتصدير.
- هوية المستند: `utils/invoice_header.py` → `document_tenant(document)` — الطباعة إذا لم يجد الشركة ترجع للسياق المنصة فقط إذا كان المالك هو الطالب (bypass)، وإلا نسيتها UIExportSettings.
- Treasury: كل API موحد عبر `AccountResolver` — حدّ `settings/chart` (1110/1120/2110.. لـ2150).

## 4. التحقق الأحدث

- `tests/unit/test_tenant_isolation.py` (9) ✓
- `tests/unit/test_invoice_header_isolation.py` (12) ✓
- `tests/unit/test_invoice_print_isolation.py` (9) ✓
- `tests/unit/test_corporate_tax.py` (4) ✓
- `tests/unit/test_reports_p0.py::TestVatReport` (7) ✓
- `tests/e2e/test_purchases_vat.py` (3) ✓
- `tests/e2e/test_purchases_e2e.py` (27) ✓
- `tests/e2e/test_expenses_e2e.py` (34) ✓
- `tests/integration/test_routes_expenses_payments_customers.py` (52) ✓
- `tests/integration/test_wave_finance_pages.py` (53) ✓

## 5. القيود الصادقة

- هذه المراجعة/النشر تتطلب موافقة الفريق + GC/محاسب الدولة لدولة الشركة + أخضر من CI/E2E/Alembic.
- Alembic على `b15_shipment_lines_tenant` تعمل على Postgres Round-Trip أخضر على `339f9e3` و`e2e` على نفس الدفعة أخضر.
- لا يزال التدقيق لكل المواقع ~100 بالكامل وغير خاشع للحدود هذه الجلسة.
