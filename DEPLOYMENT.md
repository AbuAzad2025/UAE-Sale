# دليل النشر على PythonAnywhere — UAE-Sale / Azad ERP

خطوات عملية لنشر التطبيق على PythonAnywhere مع PostgreSQL.
كل الأوامر تُنفَّذ في **Bash console** الخاص بحسابك على PythonAnywhere
(أو عبر SSH).

---

## 0. المتطلبات

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

> **تطبيق يرفض التشغيل على قاعدة غير مُرحَّلة:** عند أول تشغيل على قاعدة
> فارغة سيظهر `Application cannot run in a degraded state` — هذا سلوك
> مقصود. شغّل `flask db upgrade` أولاً.

---

## 5. إنشاء حساب المالك

يُنشأ المالك تلقائياً عند أول تشغيل باستخدام `OWNER_PASSWORD`:

```bash
flask shell
>>> from utils.system_init import ensure_system_integrity
>>> from app import create_app
>>> app = create_app()
>>> with app.app_context():
...     ensure_system_integrity(app)
>>> exit
```

تحقق:

```bash
flask shell -c "from models import User; print([(u.username, u.is_owner) for u in User.query.filter_by(is_owner=True).all()])"
```

---

## 6. إعداد الويب (Web tab)

| الحقل | القيمة |
|---|---|
| **Source code** | `/home/<user>/UAE-Sale` |
| **Working directory** | `/home/<user>/UAE-Sale` |
| **Virtualenv** | `/home/<user>/UAE-Sale/venv` |
| **WSGI configuration file** | `/home/<user>/UAE-Sale/wsgi.py` |

اضغط **Reload** ثم افتح النطاق.

---

## 7. التحقق بعد النشر

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
flask db upgrade
flask shell -c "from app import create_app; from utils.system_init import ensure_system_integrity; a=create_app(); ctx=a.app_context(); ctx.push(); ensure_system_integrity(a)"
# ثم: Web tab -> WSGI file = ~/UAE-Sale/wsgi.py -> Reload
curl -s https://<domain>/api/healthz
```
