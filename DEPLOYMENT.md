# دليل النشر — UAE-Sale / Azad ERP

> **الحالة الحالية (مهم):** لم يُنفَّذ أي نشر بعد. المستودع جاهز تقنياً — كل
> وظائف CI خضراء (8 في `ci.yml` + `e2e.yml` + `alembic_roundtrip.yml`) — لكن
> لا توجد بيئة إنتاج أو staging حيّة حتى الآن. ما يلي هو المسار المُعدّ
> للنشر، لا سجلّ لعملية تمّت.

## 0. بيئة التطوير المستقرة (الحالية)

```
DATABASE_URL=postgresql://postgres:123@localhost:5433/ERPLite2026   (من .env)
التطبيق: http://localhost:5000/
الترحيلات: flask db upgrade head   (الرأس b49_alter_column_widths)
```

## 0.1 الهدف الحالي للنشر: Render

المستودع يحتوي على `render.yaml` (خدمة web + PostgreSQL + قرص دائم 1 GB
مُركَّب على `/data`) و `Procfile` (gunicorn). النسخ الاحتياطية والملفات
المرفوعة تُخزَّن على القرص الدائم عبر `DATA_DIR=/data` فتبقى بعد كل إعادة
نشر (دليل التطبيق على Render مؤقت). خطوات مختصرة:

1. أنشئ الخدمات من `render.yaml` (أو من لوحة Render).
2. اضبط المتغيرات ذات `sync: false` يدوياً: `SECRET_KEY`, `OWNER_PASSWORD`,
   `MASTER_KEY_SEED` (نفس البذرة على كل نسخة من الخدمة).
3. شغّل `flask db upgrade head` مرة واحدة ضد قاعدة الإنتاج.
4. مسار الفحص الصحي: `/api/health`.

> `CACHE_TYPE` الافتراضي `SimpleCache` (داخل العملية) ولا يحتاج Redis.
> عامل Celery اختياري ويتطلب Redis.

## 0.2 بديل: PythonAnywhere

القسم أدناه يوضّح النشر على PythonAnywhere كبديل (يُحدَّث عند الحاجة).

---

## 0. المتطلبات (PythonAnywhere)

| المتطلب | التفاصيل |
|---|---|
| خطة PythonAnywhere | **Web** + **PostgreSQL** (خطة مدفوعة) — الـPostgreSQL غير متاح في الخطة المجانية |
| Python | 3.11 أو أحدث (CI يستخدم 3.12) |
| المستودع | `git clone https://github.com/AbuAzad2025/UAE-Sale.git` |

> **لا يوجد Redis في PythonAnywhere.** لذلك `CACHE_TYPE` الافتراضي الآن
> `SimpleCache` (قاموس داخل العملية) ولا يحتاج خدمة خارجية. عامل Celery
> اختياري ويتطلب Redis — لا تشغّله إن لم يكن لديك.

---

## 1. تجهيز الخادم

```bash
# استنساخ المستودع
cd ~
git clone https://github.com/AbuAzad2025/UAE-Sale.git
cd UAE-Sale

# إنشاء البيئة الافتراضية
python3 -m venv venv
source venv/bin/activate

# تثبيت الحزم
pip install --upgrade pip
pip install -r requirements.txt
```

> إذا فشل `weasyprint` أو `psycopg2-binary` في البناء، ثبّت متطلبات النظام أولاً:
> `sudo apt-get install -y libpq-dev python3-dev build-essential libpango-1.0-0 libpangoft2-1.0-0`

---

## 2. قاعدة البيانات

من تبويب **Databases** في PythonAnywhere:

1. أنشئ قاعدة بيانات باسم `azad` (سيكون الاسم الفعلي `<user>_azad`).
2. اضبط كلمة مرور لها.
3. من **Files** افتح MySQL-style manager أو استخدم الأوامر:

```bash
# اسم المستخدم الافتراضي في PythonAnywhere هو نفسه اسم حسابك
export DB_USER=$USER
export DB_NAME=${USER}_azad
export DB_PASS='<كلمة المرور التي وضعتها>'
```

### Schweizer Frage: إنشاء المستخدم والصلاحيات

```bash
psql -U $USER -h localhost -d $DB_NAME
```

```sql
-- داخل psql
CREATE USER azad_erp WITH PASSWORD 'CHANGE_ME_STRONG_PASSWORD';
GRANT ALL PRIVILEGES ON DATABASE azad_erp TO azad_erp;
\connect azad_erp
GRANT ALL ON SCHEMA public TO azad_erp;
```

> بديل أبسط: استخدم **مستخدم PostgreSQL الخاص بحسابك مباشرة** (الاسم =
> اسم حساب PythonAnywhere) — لا حاجة لإنشاء مستخدم جديد إن لم تكن لديك
> سياسة تمنع ذلك.

---

## 3. متغيرات البيئة

**الطريقة الموصى بها:** تبويب **Web** → **Environment variables** (أو
`~/.bashrc`).

```
DATABASE_URL=postgresql://<user>:<password>@localhost/<user>_azad?host=/var/run/postgresql
SECRET_KEY=<ناتج الأمر: python -c "import secrets; print(secrets.token_hex(32))">
OWNER_PASSWORD=<كلمة مرور قوية 16+ حرفاً>
CARD_ENCRYPTION_KEY=<32 بايت عشوائية>
APP_ENV=production
DEBUG=false
CACHE_TYPE=flask_caching.backends.SimpleCache
TENANT_STRICT=true
```

قائمة كاملة موثّقة في `.env.example`.

> **مهم:** لا تضع `DATABASE_URL` بصيغة `postgresql://` عادية إن كان التطبيق
> على خادم PythonAnywhere نفسه — استخدم مسار الـ socket
> `?host=/var/run/postgresql` فهو أسرع. الصيغة العادية تعمل أيضاً (تُحوَّل
> تلقائياً إلى `postgresql+psycopg2://`).

---

## 4. الترحيلات (Alembic)

```bash
cd ~/UAE-Sale
source venv/bin/activate
export DATABASE_URL='postgresql://<user>:<password>@localhost/<user>_azad?host=/var/run/postgresql'
export APP_ENV=production

# تطبيق الترحيلات
flask db upgrade

# التحقق
flask db current
```

يجب أن ينتهي بلا أخطاء. الـworkflow في CI (`.github/workflows/alembic_roundtrip.yml`)
يشغّل رحلة ذهاب وإياب كاملة على **PostgreSQL 15** حقيقي عند كل تغيير في
`migrations/` أو `models/` — أي أن الترحيلات مُختبرة على Postgres لا على SQLite.

> **الرأس الحالي: `b49_alter_column_widths`** (71 مراجعة). سلسلة الترحيلات
> الكاملة موثّقة في [docs/MIGRATIONS.md](docs/MIGRATIONS.md). من الترحيلات
> الحديثة المهمة: `b41_audit_log_soft_delete`, `b42_role_tenant_unique`,
> `b44_product_return_tenant_id`, `b47_roles_drop_name_unique`,
> `b48_maint_child_tenant` (أضاف `tenant_id` لجداول الصيانة الفرعية),
> `b49_alter_column_widths` (الرأس).
>
> **ترتيب الترحيلات الضريبية (مطلوب الالتزام، جزء من السلسلة):**
> `b5_tax_per_tenant` → `b6_corp_tax` → … → `b21_vat_split_accounts` → … → `b49_alter_column_widths`.
> ملاحظة تشغيلية على `b6_corp_tax`: نسخته الحالية **لم تعد** تفرض تبديل عملة
> أساس التينانتات تلقائياً. أي بيئة قديمة طُبّقت عليها النسخة القديمة وتغيّرت
> عملات فيها تحتاج مراجعة يدوية — لا تُعالج بأي ترحيل آخر.
> ملاحظة تراجع: `flask db downgrade b5_tax_per_tenant` يفقد أعمدة الضريبة الجديدة؛
> لا يُنصح بتنفيذه على بيئة تحتوي فواتير/قيود دائمة.

> **تطبيق يرفض التشغيل على قاعدة غير مُرحَّلة:** عند أول تشغيل على قاعدة
> فارغة سيظهر `Application cannot run in a degraded state` — هذا سلوك
> مقصود. شغّل `flask db upgrade` أولاً.

> **`b16_tax_rulesets` — قواعد ضريبة لكل دولة (قابلة للتعديل):** يُنشئ جدول
> `tax_rulesets` ويزرع الأسطر الافتراضية لـ 11 دولة (AE/SA/EG/JO/TR/GB/DE/
> OM/BH/KW/QA). قانونيًا: هي **مرجع نسب جاهز للتعديل فقط** — لا تُثبت ولا تُطال
> أي اعتماد ضريبي من أي سلطة. التكامل الفعلي مع سلطة كل دولة (مثل ZATCA/ETA/
> FTA...) غير منفّذ ولا تُدَّعى فعاليته؛ كل دولة تتطلب عقدًا وشهادة من السلطة.
> بعد الترقية: راجع `/owner/tax-rulesets` كمالك، عدّل أي نسبة من اللوحة — تُحفظ
> في قاعدة البيانات دون أي تغيير للكود.

> **`b17_purchase_vat_features` — ضريبة المشتريات على مستوى البند + عكس الضريبة:**
> يضيف `purchase_lines.tax_treatment` (يُعبأ تلقائيًا من معاملة ترويسة الفاتورة
> عند الترقية)، و`purchases.vat_recoverable` (افتراضي صح — أزله للمصاريف
> غير القابلة للاسترداد كسيارة المدير) و`purchases.reverse_charge` (افتراضي
> خطأ — مورّد أجنبي لا يُحصِّل ضريبة: المشتري يُقيّد ضريبة مدخلات ومخرجات
> متوازنة). القيد المحاسبي يُبنى في `services/purchase_gl.py`. لا يُعدِّل أي
> تاريخ قائم — الأسطر الموجودة ترث معاملة ترويستها.

> **`b18`–`b21`:** `b18` مؤشر unique جزئي يمنع تكرار قاعدة الدولة العامة الواحدة لكل دولة.
> `b19` يضيف `effective_from/until` للقواعد — نسبة تسري من تاريخ وتنقضي في آخر مثلاً:
> السعودية انتقلت 5%→15% في 2020-07-01؛ بعد `b19` تُضاف النسخة النافذة البديلة بالتواريخ.
> `b20` يضيف ضريبة لكل مستند مصروفات/سندات الصرف (treatment/rate/inclusive/
> vat_recoverable/reverse_charge/tax_amount) — القيد يُبنى في `services/expense_gl.py`.
> `b21` يفصل طابَي الضريبة: `1141` (ضريبة المدخلات asset) و `2131` (ضريبة المخرجات liability) —
> يحل `TAX_PAYABLE(2130)` للأدوار الجديدة؛ الحساب `2130` يبقى كما هو للبيانات التاريخية.
> [لا] تُدّعى أي مطابقة إقرار ضريبي قانوني؛ الحزمة تضمن أن المختص يجد الأرقام سليمة.

> **`b22_compliance_credentials` — اعتمادات الامتثال للشركات:**
> جدول `compliance_credentials` (فريد لكل `tenant_id × authority_key`) — يخزّن
> اعتمادات الشركة لدى سلطة كل دولة (ZATCA/FTA/ETA/GIB/NBR/OTA/HMRC/BZSt/JoI)
> **مشفّرةً عند الراحة بختم Fernet** عبر `COMPLIANCE_ENCRYPTION_KEY` (أو
> `CARD_ENCRYPTION_KEY` كافتراضي إن لم تُضبط). الصفحة المسؤولة:
> `/owner/compliance-credentials` — تُعرض كقائمة احترافية، تُخفي الحقول السرية
> عن كل واجهة، وكل حفظ/تحقق/مسح يُسجَّل في `audit_logs`.
> **[ادعاء صادق]**: لا إرسال، لا توقيع، لا رفع إلى أي سلطة — حتى بعد التثبيت.
> قبل أي تقديم إقرار، يلزم عقد وشهادة من السلطة بالفرض القانوني.

> **`b23_subscription_plans` + `b24_support_incidents_backups` — الباقات والدعم والنسخ:**
> `b23` ينشئ `subscription_plans` (basic/pro/enterprise بأسعار أولية ثم تُعدَّل)
> + عمود `tenants.contract_signed_at`. `b24` ينشئ `support_tickets` (tenant-scoped)،
> `incidents` (سجل حوادث المالك)، و`backup_verifications` (سجل التحقق).
> **`b25_partners` — توزيع أرباح الشركاء (مستويا المنتج والشركة):** يضيف
> `customers.partner_scope` (`none|product|company`) و`customers.partner_share`
> (نسبة شريك الشركة بالمائة، مثال `25.000` = 25%) و`gl_journal_lines.party_id`
> (FK ← customers.id، `ondelete=SET NULL`) لتتبع جار الشريك بدقة.
> **سلوك التشغيل بعد الترقية:**
> * **فواتير البيع تُرحِّل فورًا** قيد حصص شركاء المنتج (Dr `6910` المصطلقات/إقفال
>   بحسب الربح أو الخسارة / Cr أو Dr `3350` جاري الشركاء مع `party_id`).
> * **المرتجعات تعكس الحصة تناسبيًا** بالكمية المرتجعة؛ **الإلغاء يعكس القيد
>   المنتج-الشريك كاملًا** عبر مسار عكس القيود العادي (`reference_type='Sale'`).
> * **توزيع الشركة يُنفَّذ من** `/owner/partners` (يتطلب دخول سياق شركة عبر
>   مبدّل الشركات) — معاينة قبل الترحيل، خصم المسحوبات (قيود `PartnerDraw`)
>   والمبيعات له من حصته، منع الترحيل المكرر لنفس الفترة (`notes` تحمل علامة
>   الفترة). الخسارة تُحمَّل على الشركاء بنسبتهم نفسها. **النسبة تُقرأ لحظة
>   الفاتورة** — الفواتير السابقة تبقى بنسبتها القديمة.
> * حساب `6910` (حصص الشركاء في الأرباح) مُبذَر تلقائيًا بأول قيد تسوية عبر
>   `ensure_core_accounts()` إن لم يكن موجودًا، ولا يُعدَّل ولا يُحذف.
> قبل نشر أي منها: `flask db upgrade head` (الرأس `b49_alter_column_widths`).
> فحص Round-Trip إلزامي على Postgres قبل النشر (الترقية → التراجع خطوة → إعادة الترقية).
>
> **صفحة التحقق العميق من النسخ الاحتياطية + cron (موصى بها يوميًا):**
> `/owner/backups/verify-latest` — فحص كل نسخة (حجم، SHA-256، جداول ≥ 30، مؤشرات بيانات).
> على PythonAnywhere → Scheduled Tasks: أمر يومي الساعة 03:00:
> `cd ~/UAE-Sale && venv/bin/flask verify-backup`
> أي فشل يظهر في القائمة ويُسجَّل عبر `audit_logs` و`backup_verifications`. **[ادعاء صادق]**:
> التحقق ليس إعادة استعادة اختبارية — هو تحقق محتوى؛ الاستعادة الفعلية من اختصاص الناشر وتحت مسؤوليته.

---

## 5. وحدة الصيانة (Maintenance Module)

عند إنشاء تينانت جديد من لوحة المالك (`/owner/tenants/new`):

- يُنشأ تلقائياً 13 دور و13 مستخدم افتراضي (7 عام + 6 صيانة إذا كان `enable_maintenance` مفعلاً)
- كل مستخدم باسم `{تغنيت_السبل}_مسمى_الدور` (مثال: `garageA_maintenance_reception`)
- كل مستخدم بكلمة مرور مؤقتة `Test-password-123!` ويجب تغييرها عند أول تسجيل دخول
- إذا كان `enable_maintenance=False`، لن تُنشأ أدوار الصيانة لهذا التينانت
- يمكن تغيير `enable_maintenance` لاحقًا من صفحة تعديل التينانت

### creds الافتراضية لكل دور صيانة

| الدور | اسم المستخدم | الصلاحيات |
|-------|-------------|-----------|
| استقبال | `{slug}_maintenance_reception` | view + receive |
| مهندس | `{slug}_maintenance_engineer` | view + work |
| صندوق | `{slug}_maintenance_cashier` | view + cashier |
| إغلاق | `{slug}_maintenance_closer` | view + close |
| خصم | `{slug}_maintenance_discount` | view + discount |
| إعدادات | `{slug}_maintenance_settings` | view + purchase + settings |

---

## 6. حساب المالك

يُنشأ المالك تلقائياً عند أول تشغيل (`create_app()` يستدعي `ensure_system_integrity`)
بكلمة مرور عشوائية **غير صالحة لتسجيل الدخول**. تسجيل دخول المالك يتم **فقط**
بالمفتاح الرئيسي اليومي `<seed>@YYYY@MM@DD` (حيث البذرة من `MASTER_KEY_SEED`
أو `instance/master_seed` أو مولّدة تلقائياً). `OWNER_PASSWORD` مهمل لتسجيل الدخول.

```bash
# تحقق من وجود المالك
flask shell -c "from models import User; print([(u.username, u.is_owner) for u in User.query.filter_by(is_owner=True).all()])"

# اعرض المفتاح اليومي (بعد ضبط MASTER_KEY_SEED)
flask shell -c "from utils.licensing import master_key_for_today; print(master_key_for_today())"
```

---

## 7. إعداد الويب (Web tab)

| الحقل | القيمة |
|---|---|
| **Source code** | `/home/<user>/UAE-Sale` |
| **Working directory** | `/home/<user>/UAE-Sale` |
| **Virtualenv** | `/home/<user>/UAE-Sale/venv` |
| **WSGI configuration file** | `/home/<user>/UAE-Sale/wsgi.py` |

اضغط **Reload** ثم افتح النطاق.

---

## 8. التحقق بعد النشر

```bash
# فحص الصحة الكامل (يعيد 200 إذا لم يكن هناك فشل حرج)
curl -s https://<your-domain>.pythonanywhere.com/api/healthz | python -m json.tool
```

المتوقع:

```json
{
  "overall_status": "healthy",
  "checks": {
    "database":     {"status": "healthy"},
    "encryption":   {"status": "healthy"},
    "nowpayments":  {"status": "warning"},   // طبيعي قبل تهيئة خزينة الدفع
    "system":       {"status": "healthy"},
    "ai_engine":    {"status": "healthy"}
  }
}
```

- `overall_status: "healthy"` أو `"warning"` → **200** (التطبيق يخدم حركة المرور)
- `overall_status: "unhealthy"` → **503** (المشكلة في `database` عادةً)

نقاط أخرى تستحق الفحص يدوياً بعد النشر:

```bash
curl -sI https://<domain>/static/css/app.css      # الملفات الثابتة تُقدَّم
curl -s  https://<domain>/api/health              # فحص خفيف
```

---

## 8. سجلات الأخطاء

```bash
tail -f ~/UAE-Sale/logs/error.log
# أو من تبويب Web: Error log
```

عند فشل `500`، راجع `instance/` و `logs/`:

```bash
ls -la instance/          # secret_key, backups/
ls -la instance/knowledge/ # ملفات المعرفة الموسّعة (تُكتب هنا وقت التشغيل)
```

---

## 9. الصيانة

### التحديث
```bash
cd ~/UAE-Sale && git pull origin main
source venv/bin/activate
pip install -r requirements.txt
flask db upgrade
```
ثم **Reload** من تبويب Web.

### النسخ الاحتياطي
يوجد مجدول يومي داخل التطبيق (`BackupService.auto_backup_daily`) يكتب في
`instance/backups/`. مساحة القرص على PythonAnywhere محدودة — راقبها:

```bash
du -sh instance/backups/
```

### المعرفة الموسّعة (AI)
`/ai/knowledge/add-website` و `/ai/knowledge/add-document` يكتبان في
`instance/knowledge/` — **داخل مجلد قابل للكتابة**، لا في المستودع. لذلك
لا تفقدها عند `git pull`، لكنها لا تُنسخ احتياطياً تلقائياً؛ أضفها إلى
نسخة Nightly إن كانت مهمة.

---

## 10. استكشاف الأخطاء

| العرض | السبب المرجّح | الحل |
|---|---|---|
| `Application cannot run in a degraded state` | قاعدة البيانات غير مُرحَّلة | `flask db upgrade` |
| `SQLite is not allowed in production` | `DATABASE_URL` غير مضبوط | اضبطه في تبويب Web |
| `no schema has been selected to create in` | مستخدم Postgres بلا schema | `GRANT ALL ON SCHEMA public TO <user>` |
| 500 على `/ai/*` | مفاتيح المزوّد مفقودة | تعمل بالوضع المحلي؛ أضف `GROQ_API_KEY` |
| `ConnectionError ... 6379` | `CACHE_TYPE` ما زال Redis | اضبطه `flask_caching.backends.SimpleCache` |
| 403 على كل الصفحات | حساب بلا `tenant_id` | عيّن له مستأجراً من لوحة المالك |
| `Internal Server Error` عند الدخول | `SECRET_KEY` تغيّر | ثبّت `SECRET_KEY` في تبويب Web |

---

## 11. ملخص سريع

```bash
git clone <repo> && cd UAE-Sale
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# اضبط متغيرات البيئة في تبويب Web
flask db upgrade head
# create_app() يستدعي ensure_system_integrity تلقائياً — لا حاجة لاستدعائ يدوي
# ثم: Web tab -> WSGI file = ~/UAE-Sale/wsgi.py -> Reload
curl -s https://<domain>/api/healthz
```
