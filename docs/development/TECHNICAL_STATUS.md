# التقرير التقني المعتمد — Azad ERP / UAE-Sale

> **المرجع الوحيد المعتمد** للحالة التقنية الحالية.
> **آخر تحديث/تحقق:** 2026-11-23 (مطابق للكود، 52 اختباراً مركّزاً ناجحاً).
> هذا التقرير يلغي ويستبدل كل التقارير السابقة المتفرقة (البنية، العزل، الأدوار،
> المسارات، تدقيق الكود، حالة الصيانة). أي تعارض بينه وبين مستند قديم يُعمل بهذا.

---

## 1. بطاقة النظام

| المؤشر | القيمة | المصدر |
|---|---|---|
| الإصدار المُبلَّغ | `APP_VERSION` (افتراضي `1.0.0`) | `config.py` |
| الواجهة | Flask 3.1+ / Python 3.11+ | `requirements.txt` |
| ORM / قاعدة البيانات | SQLAlchemy 2.0 / PostgreSQL 15+ | `requirements.txt` |
| قاعدة التطوير المستقرة | `postgresql://…@localhost:5433/ERPLite2026` | `.env` |
| عنوان التطوير | `http://localhost:5000/` | `config.py` |
| Blueprints | 37 | `app.py` |
| النماذج | ~103 classes | `models/` |
| الترحيلات | 71 مراجعة — الرأس `b49_alter_column_widths` | `migrations/versions/` |
| الجداول المشمولة بالعزل | ~79 (78 مسجَّلة + `users` مدمج) | `models/tenant_scope.py`, `models/__init__.py` |
| الصلاحيات المزروعة | ~27 | `utils/system_init.py` |
| المسارات المصنَّفة | ≥545 | `test_route_isolation_census.py` |
| بوابات الميزات | 8 blueprints | `utils/feature_guards.py` |

---

## 2. بنية التطبيق

- `create_app()` (`app.py`) يُهيّئ config → مجلدات التشغيل → فحص سلامة الإنتاج →
  سجلات منقّاة (`RequestIdFilter` + `SanitizeFilter`) → db/migrate/login/csrf/cache/limiter
  → يسجّل 37 blueprint → يثبّت عزل المستأجرين → يستدعي `ensure_system_integrity`.
- `before_request`: request_id، ضبط سياق المستأجر من المستخدم، مهلة خمول 30 دقيقة،
  بوابة تغيير كلمة المرور عند أول دخول. `after_request`: رؤوس أمان CSP/HSTS.
- خيوط النسخ الاحتياطي/الموافقة تعمل تحت `python app.py` فقط؛ الإنتاج يستخدم
  gunicorn (`Procfile`) مع Celery اختياري.
- تخزين الملفات والنسخ الاحتياطية على مجلد دائم (`DATA_DIR`، على Render = `/data`).

---

## 3. عزل المستأجرين (Tenant Isolation)

**الآلية الحالية (مُثبتة بمصدر):**

1. **التحميل (قراءة) — الأساس:** `install_tenant_loader_criteria()` ينصّب حدث
   `do_orm_execute` يطبّق `with_loader_criteria(...)` على كل كيان مشمول، ويغطّي:
   الاستعلامات العادية، `session.get()` / `db.get_or_404()`، تحميل العلاقات،
   الأسماء المستعارة (aliases)، والاستعلامات المقسّمة (LIMIT/OFFSET).
2. **الكتابة:** `before_flush` (`_before_flush_tenant_guard`) يختم `tenant_id` على
   الصفوف الجديدة ويمنع تغييره/الإدخال عبر مستأجر آخر (المالك معفى).
3. **سياق بلا مستأجر:** `TENANT_LESS_SCOPE = -1` يقصر الصفوف على `tenant_id IS NULL`؛
   `None` = عرض المنصة غير المفلتر (المالك).
4. **صفوف المنصة العامة:** `roles` / `tax_rulesets` / `fiscal_periods` تبقى مرئية عبر
   `(tenant_id == current OR tenant_id IS NULL)`.
5. `before_compile` (`_apply_query_loader_criteria`) محتفظ به كحل ثانوي فقط؛ لا يحمي
   `session.get()` وحده.

**التسجيل:** ~79 جدولاً (78 في حلقة `models/__init__.py` + `users` عبر
`_BUILTIN_SCOPED_TABLES`). `User` و`ProductReturn` (b44) و`TaxRuleset` و`Role` و`FiscalPeriod`
مشمولة. `b48` أضاف `tenant_id` لثمانية جداول صيانة فرعية
(`_items`, `_services`, `_status_log`, `receipts`, `invoices`, `returns`, `return_lines`, `credit_notes`).

> التفاصيل والبراهين: اختبارات `tests/unit/test_tenant_isolation.py`،
> `tests/security/test_zero_trust_isolation.py`، `tests/unit/test_schema_parity.py`.

---

## 4. الصلاحيات وبوابات الميزات

- ~27 صلاحية مزروعة؛ أدوار: owner، super_admin، developer، manager، accountant،
  seller، cashier، viewer، إلخ. المالك/الـsuper admin يتجاوزان الفحص.
- **تسجيل دخول المالك:** المفتاح الرئيسي اليومي `<seed>@YYYY@MM@DD` (بتوقيت UTC)،
  حيث البذرة من `MASTER_KEY_SEED` → `instance/master_seed` → مولّدة تلقائياً.
  `OWNER_PASSWORD` مهمل لتسجيل الدخول؛ كلمة مرور المالك عشوائية.
- إجبار تغيير كلمة المرور عند أول دخول لكل مستخدم (`must_change_password`).

**بوابات الميزات (تحكم حقيقي، لا عرض):**

| البلوبرنت | الميزة |
|---|---|
| `api`, `api_enhanced`, `api_analytics`, `graphql` | `api` (افتراضه **False**) |
| `ai` | `ai` |
| `ledger` | `gl` |
| `reports` | `reports` |
| `maintenance` | `maintenance` |

- ميزة معطّلة → **403**؛ فشل التحقق → **503** (fail-closed)؛
  نقاط البنية التحتية (`api.health`, `healthz`, `version`, `client_errors`, `csrf_token`,
  `monitoring.health`, `monitoring.metrics`) معفاة؛ سياقات `None`/`TENANT_LESS_SCOPE`
  تتجاوز البوابة ويقررها مستوى الصلاحيات.
- مُثبت بـ `tests/unit/test_feature_gates.py`.

---

## 5. السلامة المالية (Accounting Integrity)

- الترحيل **طبقة خدمة** (`GLService`: `post_entry` / `create_journal_entry` /
  `create_manual_entry`) — لا مستمعات أحداث GL. يستخدم `flush()` فقط، يفرض التوازن
  قبل الكتابة، ويحسب `amount_base = (debit − credit) × exchange_rate`.
- الأرصدة/kشوف الحساب/الميزانية/مراكز التكلفة/المطابقات تقرأ **المُرحَّل فقط**
  (`is_posted`) بعملة الأساس.
- ترقيم القيود عبر `next_global_entry_number` بقفل عام + قيد UNIQUE.
- عكس القيد ينشئ معكوساً بربط ثنائي؛ سجلات التدقيق مُلحقة فقط (append-only) مع
  حذف ناعم (`b41`, `is_archived`).
- **توحيد الدقة (2026-11-23):** `utils/money.py` هو المصدر الوحيد للتقريب
  (2dp نقود، 3dp كميات، 6dp تكلفة وحدة/صرف، HALF_UP). `average_cost` مُخزَّن
  الآن بـ 6 خانات (`c07`)، ورصيد حساب الضبط يُقرَّب بنفس الدالة. فَرق التقييم
  التاريخي (1.44 ILS) سُوّي بقيد موثّق `JE-2026-0050`
  (`InventoryRoundingAdjustment`, idempotent) — رصيد المخزون = التقييم = 403,170.39
  وفرق المطابقة `0.00`. مطابقتا AR/AP متوازنتان (حصة الشريك 3350 بند تسوية صريح).
- **الشيكات:** إلغاء الشيك يُقيَّد الآن بـ `tenant_id` صحيح؛ المدير يملك الصلاحية
  مع توثيق كامل. الشيكات لا تعدّل `total_purchases_aed` (مُشتق من المشتريات).

**اختبارات السلامة الدائمة (تعمل في `alembic-smoke` على PostgreSQL):**

| الاختبار | المجالات |
|---|---|
| `test_financial_seed_integrity.py` | بيع، دفع، شراء+ضريبة، مرتجع، شطب ديون |
| `test_financial_domains_integrity.py` | شيكات، عملات متعددة/FX، صيانة، رواتب |
| `test_financial_gaps_integrity.py` | أصول ثابتة/إهلاك، أنواع الصيانة الفرعية، حصص الشركاء، فرق الصرف |

كل مستند يُمرَّر عبر الخدمة الحقيقية ويُتحقق أن `sum(amount_base)==0` و
`total_debit==total_credit`، مع عدم وجود سطور عابرة للمستأجر.

---

## 6. الترحيلات

- 71 مراجعة، سلسلة خطية برأس واحد: **`b49_alter_column_widths`**.
- محطات مهمة: `b13` (عزل ERP)، `b41` (حذف ناعم للتدقيق)، `b42` (تفرد الدور لكل مستأجر)،
  `b44` (عزل المرتجعات)، `b45` (`must_change_password`)، `b47` (إسقاط تفرد `roles.name`)،
  `b48` (`tenant_id` لجداول الصيانة الفرعية)، `b49` (الرأس).
- بوابة الانحراف `tests/unit/test_schema_parity.py` تمنع أي اختلاف model/migration.
- الرجوع: `flask db upgrade head`. القائمة الكاملة لأسماء الملفات في `migrations/versions/`.

---

## 7. الاختبارات و CI

| السويت | العدد (تقريباً) |
|---|---|
|.unit | 3,577 |
| security | 80 |
| integration (PostgreSQL) | 507 |
| e2e vertical slice | 305 |
| e2e combinatorial matrix | 28,350 |

**كل الوظائف خضراء:**
- `ci.yml` — 8 وظائف: lint، security-scan، verify-boot، frontend، test، integration،
  repo-security، alembic-smoke.
- `e2e.yml` — شريحة رأسية + مصفوفة 30 نطاقاً × shardين.
- `alembic_roundtrip.yml` — رحلة ذهاب/إياب للترحيلات على PostgreSQL.

فحوص الأمان: Gitleaks، Bandit، pip-audit، Trivy.

> التشغيل المحلي المتسلسل الطويل لوحدة `unit` قد يُظهر إخفاقات تلوّط حالة
> (SQLite in-memory + إعادة استخدام PK + تسلسل `/auth/login`) لا تظهر في وظائف CI
> المعزولة. المعتمد هو نتيجة CI.

---

## 8. النشر

- **لم يُنفَّذ أي نشر حتى الآن** — لا بيئة إنتاج ولا staging حيّة.
- الأصول المُعدّة: `render.yaml` (خدمة web + PostgreSQL + قرص دائم 1 GB على `/data`)
  و`Procfile` (gunicorn). النسخ الاحتياطية والملفات المرفوعة على القرص الدائم.
- المتغيرات ذات `sync: false` (`SECRET_KEY`, `OWNER_PASSWORD`, `MASTER_KEY_SEED`)
  تُضبط يدوياً. التفاصيل: [DEPLOYMENT.md](../production/DEPLOYMENT.md).

---

## 9. ما أُزيل من المستندات

وحّدت هذه المرجع كل التقارير القديمة وألغيتها: تقارير البنية/العزل/الأدوار/المسارات/
تدقيق الكود/حالة الصيانة. كما حُذفت أدلة المستخدم غير المستخدمة وخطة الشحنات
القديمة (منفّذة). المراجع العملية المعتمدة: [README.md](../README.md)،
[DEPLOYMENT.md](../production/DEPLOYMENT.md)، [MIGRATIONS.md](MIGRATIONS.md)،
[CHANGELOG.md](CHANGELOG.md)، وهذا التقرير.
