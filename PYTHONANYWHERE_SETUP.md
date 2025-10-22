# 🚀 دليل النشر على PythonAnywhere

## خطوات التثبيت السريعة

### 1️⃣ استنساخ المشروع
```bash
git clone https://github.com/YOUR-USERNAME/YOUR-REPO.git
cd YOUR-REPO
```

### 2️⃣ إنشاء البيئة الافتراضية
```bash
python3.10 -m venv .venv
source .venv/bin/activate
```

### 3️⃣ تثبيت المتطلبات
```bash
pip install -r requirements.txt
```

### 4️⃣ إنشاء ملف `.env`
```bash
nano .env
```

انسخ المحتوى التالي وعدّل حسب الحاجة:
```env
FLASK_APP=app:create_app
FLASK_ENV=production
DEBUG=False
HOST=0.0.0.0
PORT=8080

SECRET_KEY=YOUR-RANDOM-SECRET-KEY-HERE

DEFAULT_CURRENCY=AED
CURRENCY_API_PROVIDER=exchangerate-api
CURRENCY_API_KEY=
CURRENCY_CACHE_TIMEOUT=3600

COMPANY_NAME=Your Company Name
COMPANY_NAME_AR=اسم شركتك
COMPANY_ADDRESS=Your Address
COMPANY_PHONE=+1234567890
COMPANY_EMAIL=info@yourcompany.com

GROQ_API_KEY=your-groq-api-key

MAX_LOGIN_ATTEMPTS=5
LOGIN_BLOCK_DURATION_MINUTES=15
ITEMS_PER_PAGE=20
LOG_LEVEL=INFO
```

### 5️⃣ تهيئة قاعدة البيانات
```bash
python init_db.py
```

سيعرض:
- ✅ Database created
- ✅ Owner user created
- Username: `owner`
- Password: `REDACTED-PASSWORD`

### 6️⃣ إعداد WSGI على PythonAnywhere

في Web tab:
- **Source code:** `/home/yourusername/YOUR-REPO`
- **Working directory:** `/home/yourusername/YOUR-REPO`
- **Virtualenv:** `/home/yourusername/YOUR-REPO/.venv`

في WSGI configuration file:
```python
import sys
import os

project_folder = '/home/yourusername/YOUR-REPO'
if project_folder not in sys.path:
    sys.path.insert(0, project_folder)

from app import create_app
application = create_app()
```

### 7️⃣ إعادة التحميل
اضغط **Reload** في Web tab

---

## 🔐 الأمان

### ملفات محمية (لن ترفع لـ Git):
- ✅ `.env` - إعداداتك الخاصة
- ✅ `instance/` - قاعدة البيانات
- ✅ `logs/` - ملفات اللوج
- ✅ `__pycache__/` - ملفات مؤقتة

### بعد أول تسجيل دخول:
⚠️ **غيّر كلمة سر المالك فوراً!**

---

## 📞 الدعم الفني

**المطور:** م. أحمد غنام  
**الشركة:** شركة أزاد للأنظمة الذكية  
**البريد:** rafideen.ahmadghannam@gmail.com  
**الهاتف:** +970592800646

