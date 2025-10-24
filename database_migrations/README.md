# 🔧 دليل التهجير الآمن - Safe Migration Guide

## 📋 الملفات المتوفرة للتهجير

### ✅ ملفات التهجير الآمنة (تحافظ على البيانات):

```
1. migrate_payment_vault.py  - تهجير جدول payment_vault
2. check_db.py               - فحص قاعدة البيانات
3. migrations/versions/      - جميع ملفات الـ migration
```

---

## 🚀 خطوات التهجير على PythonAnywhere

### **الطريقة 1: تهجير يدوي آمن (موصى به)**

```bash
# 1. الانتقال لمجلد المشروع
cd ~/UAE-Sale

# 2. سحب آخر التحديثات
git pull origin main

# 3. عمل نسخة احتياطية من قاعدة البيانات
cp instance/garage.db instance/garage.db.backup_$(date +%Y%m%d_%H%M%S)

# 4. تشغيل سكريبت التهجير الآمن
python migrate_payment_vault.py

# 5. فحص قاعدة البيانات للتأكد
python check_db.py

# 6. إعادة تحميل التطبيق
touch /var/www/uaesale_azad_pythonanywhere_com_wsgi.py
```

---

### **الطريقة 2: باستخدام Flask-Migrate (إذا كنت تستخدمه)**

```bash
cd ~/UAE-Sale
git pull origin main

# نسخة احتياطية
cp instance/garage.db instance/garage.db.backup_$(date +%Y%m%d)

# تطبيق التهجير
flask db upgrade

# إعادة تحميل
touch /var/www/uaesale_azad_pythonanywhere_com_wsgi.py
```

---

## ⚠️ تحذيرات مهمة

### ❌ **لا تفعل هذا أبداً في الإنتاج:**
```bash
# ❌ خطر! يحذف كل البيانات
rm instance/garage.db

# ❌ خطر! يعيد إنشاء الجداول
flask db init
```

### ✅ **افعل هذا دائماً:**
```bash
# ✅ آمن - نسخة احتياطية أولاً
cp instance/garage.db instance/garage.db.backup

# ✅ آمن - فحص قبل التطبيق
python check_db.py

# ✅ آمن - تهجير تدريجي
python migrate_payment_vault.py
```

---

## 📊 التحقق من نجاح التهجير

### بعد تشغيل `migrate_payment_vault.py` يجب أن ترى:

```
═══════════════════════════════════════════════════════════════
✅ اكتمل التهجير بنجاح!
🚀 يمكنك الآن تشغيل النظام
═══════════════════════════════════════════════════════════════
```

### بعد تشغيل `check_db.py` يجب أن ترى:

```
✅ عدد الأعمدة: 38

✅ التحقق من الأعمدة الجديدة:
  ✅ paypal_client_id: موجود
  ✅ paypal_client_secret: موجود
  ✅ bank_name: موجود
  ✅ stripe_publishable_key: موجود
```

---

## 🔄 سيناريوهات التهجير

### **السيناريو 1: نظام جديد (لا توجد بيانات)**

```bash
cd ~/UAE-Sale
git pull origin main
python migrate_payment_vault.py
touch /var/www/uaesale_azad_pythonanywhere_com_wsgi.py
```
**النتيجة:** ✅ سيتم إنشاء الجدول من الصفر

---

### **السيناريو 2: نظام موجود (توجد بيانات قديمة)**

```bash
cd ~/UAE-Sale

# 1. نسخة احتياطية
cp instance/garage.db instance/garage.db.backup

# 2. سحب التحديثات
git pull origin main

# 3. فحص الوضع الحالي
python check_db.py

# 4. تهجير آمن
python migrate_payment_vault.py

# 5. فحص بعد التهجير
python check_db.py

# 6. إعادة تحميل
touch /var/www/uaesale_azad_pythonanywhere_com_wsgi.py
```
**النتيجة:** ✅ سيتم إضافة الأعمدة الجديدة فقط + الحفاظ على البيانات

---

### **السيناريو 3: استعادة من نسخة احتياطية**

```bash
cd ~/UAE-Sale/instance

# 1. عرض النسخ الاحتياطية المتوفرة
ls -lh *.backup*

# 2. استعادة من نسخة محددة
cp garage.db.backup_20251024 garage.db

# 3. إعادة تحميل
touch /var/www/uaesale_azad_pythonanywhere_com_wsgi.py
```

---

## 📁 بنية الملفات

```
UAE-Sale/
├── migrate_payment_vault.py    ← سكريبت التهجير الآمن ⭐
├── check_db.py                  ← فحص قاعدة البيانات ⭐
├── MIGRATION_GUIDE.md          ← هذا الدليل ⭐
├── migrations/
│   └── versions/
│       ├── add_payment_vault_columns.py
│       ├── add_payment_vault_indexes.py
│       └── add_packages.py
└── instance/
    ├── garage.db                ← قاعدة البيانات الرئيسية
    └── garage.db.backup*        ← النسخ الاحتياطية
```

---

## 🧪 اختبار التهجير محلياً (قبل الإنتاج)

### على جهازك المحلي:

```bash
# 1. نسخ قاعدة بيانات الإنتاج
scp username@ssh.pythonanywhere.com:~/UAE-Sale/instance/garage.db instance/garage_prod.db

# 2. اختبار التهجير على النسخة
python migrate_payment_vault.py

# 3. فحص النتيجة
python check_db.py

# 4. إذا نجح، طبقه على الإنتاج
```

---

## 📊 ما يفعله `migrate_payment_vault.py`

### ✅ **آمن تماماً:**

1. **يتحقق من وجود الجدول**
   - إذا غير موجود → ينشئه
   - إذا موجود → يحدثه

2. **يضيف الأعمدة المفقودة فقط**
   - لا يحذف أي عمود
   - لا يعدل بيانات موجودة
   - لا يمسح الجدول

3. **يحافظ على جميع البيانات**
   - كل السجلات تبقى
   - كل القيم تبقى
   - كل العلاقات تبقى

4. **يعطي تقرير مفصل**
   - عدد الأعمدة المضافة
   - الأعمدة الموجودة بالفعل
   - أي أخطاء حدثت

---

## 🆘 حل المشاكل

### **المشكلة 1: "no such column: payment_vault.XXX"**

**السبب:** لم يتم تشغيل التهجير

**الحل:**
```bash
cd ~/UAE-Sale
python migrate_payment_vault.py
touch /var/www/uaesale_azad_pythonanywhere_com_wsgi.py
```

---

### **المشكلة 2: "table payment_vault already exists"**

**السبب:** الجدول موجود لكن ينقصه أعمدة

**الحل:**
```bash
# التهجير سيكتشف ذلك ويضيف الأعمدة المفقودة فقط
python migrate_payment_vault.py
```

---

### **المشكلة 3: "Permission denied"**

**السبب:** صلاحيات ملف قاعدة البيانات

**الحل:**
```bash
chmod 664 instance/garage.db
chmod 775 instance/
```

---

### **المشكلة 4: "Database is locked"**

**السبب:** التطبيق يعمل ويستخدم قاعدة البيانات

**الحل:**
```bash
# أوقف التطبيق مؤقتاً على PythonAnywhere Web tab
# ثم شغل التهجير
python migrate_payment_vault.py
# ثم أعد تشغيل التطبيق
```

---

## 📝 سجل التغييرات

### **نسخة 2025-10-24:**
```
✅ إضافة 15 عمود جديد لـ payment_vault:
   - paypal_client_id, paypal_client_secret
   - paypal_business_email, paypal_mode
   - bank_name, bank_account_name, bank_account_number
   - bank_iban, bank_swift_code, bank_branch
   - bank_country, bank_currency
   - stripe_publishable_key, stripe_secret_key
   - stripe_webhook_secret
```

---

## 🎯 الخلاصة

### ✅ **ملفات آمنة للاستخدام في الإنتاج:**
- ✅ `migrate_payment_vault.py`
- ✅ `check_db.py`

### ❌ **ملفات خطرة - لا تستخدمها في الإنتاج:**
- ❌ `rm instance/garage.db`
- ❌ `flask db init` (إلا للمرة الأولى فقط)
- ❌ `db.drop_all()`

### 📞 **للدعم:**
راجع الأخطاء في:
- PythonAnywhere Error Log
- `instance/logs/` (إن وجدت)

---

## 🚀 البدء السريع

```bash
# على PythonAnywhere (ريبو خاص) - نسخ ولصق:

cd ~/UAE-Sale
git remote set-url origin git@github.com:AbuAzad2025/UAE-Sale.git
ssh-keyscan github.com >> ~/.ssh/known_hosts
GIT_SSH_COMMAND='ssh -i ~/.ssh/pythonanywhere_deploy -o IdentitiesOnly=yes' git pull origin main
cp instance/app.db instance/app.db.backup_$(date +%Y%m%d_%H%M%S)
python database_migrations/migrate_payment_vault.py
python database_migrations/check_db.py
flask db upgrade
touch /var/www/uaesale_azad_pythonanywhere_com_wsgi.py

echo "✅ اكتمل التهجير!"
```

**هذا الأمر يفعل كل شيء بأمان! 🎉**

