# 🚀 دليل النشر على PythonAnywhere

## 📋 الخطوات الكاملة

### 1️⃣ الإعداد الأولي (مرة واحدة فقط)

```bash
# إنشاء المجلد
cd ~
git clone git@github.com:AbuAzad2025/UAE-Sale.git
cd UAE-Sale

# إنشاء Virtual Environment
mkvirtualenv --python=/usr/bin/python3.10 uaesale-env

# تثبيت المكتبات
pip install -r requirements.txt

# إنشاء مجلدات ضرورية
mkdir -p instance/backups
mkdir -p logs
mkdir -p static/uploads

# إعداد قاعدة البيانات
flask db upgrade
python init_db.py
```

---

### 2️⃣ تحديث النظام (كل مرة)

**استخدم السكريبت:**
```bash
cd ~/UAE-Sale
bash DEPLOY_TO_PYTHONANYWHERE.sh
```

**أو يدوياً:**
```bash
cd ~/UAE-Sale
git remote set-url origin git@github.com:AbuAzad2025/UAE-Sale.git
ssh-keyscan github.com >> ~/.ssh/known_hosts
GIT_SSH_COMMAND='ssh -i ~/.ssh/pythonanywhere_deploy -o IdentitiesOnly=yes' git pull origin main
flask db upgrade
touch /var/www/uaesale_azad_pythonanywhere_com_wsgi.py
```

---

### 3️⃣ إعدادات WSGI

**ملف:** `/var/www/uaesale_azad_pythonanywhere_com_wsgi.py`

```python
import sys
import os

project_folder = '/home/azad/UAE-Sale'
if project_folder not in sys.path:
    sys.path.insert(0, project_folder)

from app import create_app
application = create_app()
```

---

### 4️⃣ متغيرات البيئة

**في PythonAnywhere Web Tab → Environment variables:**

```
FLASK_ENV=production
SECRET_KEY=<your-strong-secret-key>
DATABASE_URL=sqlite:////home/azad/UAE-Sale/instance/app.db
```

---

### 5️⃣ Static Files

**في PythonAnywhere Web Tab → Static files:**

```
URL: /static/
Directory: /home/azad/UAE-Sale/static
```

---

### 6️⃣ الفحص

```bash
# فحص الـ logs
tail -f /var/log/uaesale.azad.pythonanywhere.com.error.log

# فحص قاعدة البيانات
cd ~/UAE-Sale
python -c "from app import create_app, db; app = create_app(); print('OK')"

# فحص التطبيق
curl https://uaesale.azad.pythonanywhere.com/
```

---

### 7️⃣ Scheduled Tasks (للنسخ الاحتياطية)

**في PythonAnywhere → Tasks:**

```
# يومياً الساعة 2:00 AM
cd ~/UAE-Sale && /home/azad/.virtualenvs/uaesale-env/bin/python -c "from services.backup_service import BackupService; BackupService.create_backup(manual=False)"
```

---

## 🔧 Troubleshooting

### مشكلة: 500 Error
```bash
# فحص logs
tail -100 /var/log/uaesale.azad.pythonanywhere.com.error.log

# إعادة تحميل
touch /var/www/uaesale_azad_pythonanywhere_com_wsgi.py
```

### مشكلة: Database locked
```bash
# إيقاف العمليات
cd ~/UAE-Sale
rm instance/app.db-shm instance/app.db-wal
touch /var/www/uaesale_azad_pythonanywhere_com_wsgi.py
```

### مشكلة: Import Error
```bash
# التأكد من Virtual Environment
workon uaesale-env
pip install -r requirements.txt
```

---

## ✅ Checklist قبل النشر

```
☑ requirements.txt - محدثة
☑ .gitignore - يتجاهل instance/ و logs/
☑ migrations - كلها موجودة
☑ static files - موجودة
☑ templates - 193 template
☑ SECRET_KEY - قوي وسري
☑ Database - تم upgrade
```

---

## 🌐 الوصول

**URL:** https://uaesale.azad.pythonanywhere.com

**Admin Login:**
- Username: owner
- Password: (كلمة المرور الخاصة بك)

---

**بالتوفيق! 🚀**

