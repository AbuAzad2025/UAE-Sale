# UAE-Sale | Enterprise Warehouse Management System

<div align="center">

[![Version](https://img.shields.io/badge/version-2.0.0-blue.svg)](https://github.com/AbuAzad2025/UAE-Sale/releases)
[![Python](https://img.shields.io/badge/python-3.13-brightgreen.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/flask-3.0-orange.svg)](https://flask.palletsprojects.com/)
[![Status](https://img.shields.io/badge/status-Production-success.svg)](https://uaesale-azad.pythonanywhere.com/)
[![License](https://img.shields.io/badge/license-Proprietary-red.svg)](LICENSE)
[![Code Size](https://img.shields.io/github/languages/code-size/AbuAzad2025/UAE-Sale)](https://github.com/AbuAzad2025/UAE-Sale)
[![Last Commit](https://img.shields.io/github/last-commit/AbuAzad2025/UAE-Sale)](https://github.com/AbuAzad2025/UAE-Sale/commits/main)

**Professional warehouse and sales management system for enterprises**

🌐 **[Live Demo](https://uaesale-azad.pythonanywhere.com/)** • [Docs](AZAD_SYSTEM_COMPLETE_GUIDE.md) • [API](API.md) • [Architecture](ARCHITECTURE.md) • [Changelog](CHANGELOG.md) • [Security](SECURITY.md)

---

### 🚀 Quick Links

| Resource | Link |
|----------|------|
| 🌐 **Live System** | [uaesale-azad.pythonanywhere.com](https://uaesale-azad.pythonanywhere.com/) |
| 🏢 **Company** | [azad.pythonanywhere.com](https://azad.pythonanywhere.com/) |
| 📂 **Repository** | [github.com/AbuAzad2025/UAE-Sale](https://github.com/AbuAzad2025/UAE-Sale) |
| 📧 **Email** | rafideen.ahmadghannam@gmail.com |
| 📱 **Phone** | +970-598-953-362 |

</div>

---

## 📋 Table of Contents

- [Overview](#-overview---نظرة-عامة)
- [Tech Stack](#-tech-stack)
- [Features](#-المميزات)
- [Installation](#-التثبيت)
- [Docker Deployment](#-docker-deployment)
- [API Documentation](#-api-documentation)
- [System Architecture](#-system-architecture)
- [Documentation](#-التوثيق)
- [Legal Notice](#-legal-notice---إشعار-قانوني)
- [Support](#-support-our-work---ادعم-عملنا)
- [License](#-license---الترخيص)

---

## 📋 Overview - نظرة عامة

**UAE-Sale** is a comprehensive enterprise resource planning (ERP) system specifically designed for warehouse and sales management. Built with modern technologies and intelligent automation, it provides businesses with the tools needed to efficiently manage inventory, sales, customers, and financial operations.

### Core Capabilities

- 📦 **Inventory Management** - Real-time tracking with automated alerts
- 💰 **Sales Management** - Professional invoicing with multiple templates
- 🧾 **Receipt System** - Comprehensive payment documentation
- 👥 **Customer & Supplier CRM** - Complete relationship management
- 💳 **Payment Processing** - Multiple payment method support
- 🏦 **Check Management** - Full check lifecycle tracking
- 💱 **Multi-Currency** - Automatic exchange rate conversion
- 📊 **Advanced Analytics** - Business intelligence and reporting
- 🤖 **AI Assistant** - Intelligent automation and insights

---

## 🛠 Tech Stack

### Backend
- **Framework:** Flask 3.0 (Python 3.13)
- **Database:** SQLite / PostgreSQL
- **ORM:** SQLAlchemy 2.0
- **Cache:** Redis
- **Task Queue:** Celery

### Frontend
- **UI Framework:** AdminLTE 3
- **CSS:** Bootstrap 4
- **JavaScript:** jQuery, Chart.js
- **Components:** Select2, DataTables, SweetAlert2

### AI & ML
- **Neural Networks:** scikit-learn (10 models)
- **NLP:** Custom semantic matching
- **Data Analysis:** pandas, numpy
- **Providers:** Groq, Google Gemini, OpenAI

### Security
- **Authentication:** Flask-Login
- **Authorization:** Role-based access control (RBAC)
- **Encryption:** bcrypt password hashing
- **Protection:** CSRF, SQL injection prevention, XSS protection

---

## ✨ **المميزات**

### 🎯 **الربط التلقائي الذكي**
```
فاتورة بيع → خصم مخزون → سند قبض → تحديث ذمم (تلقائياً!)
```

### 💱 **نظام عملات متطور (3 مستويات)**
1. **يدوي** - المستخدم يدخل السعر
2. **API** - جلب تلقائي من الإنترنت
3. **طلب** - تنبيه للمستخدم إذا فشل

### 👥 **3 أنواع زبائن**
- 🙂 **عادي** - السعر الكامل
- 🏪 **تاجر** - خصم 5-15%
- 🤝 **شريك** - خصم 15-30%

### 🤖 **المساعد الذكي - أزاد**
- **18 محرك ذكي** متكامل
- **فهم سياقي** متقدم
- **نظام أمان** ذكي (مالك/مستخدم)
- **تعلم ذاتي** مستمر
- **معرفة شاملة** (ضرائب، جمارك، قطع غيار)

### 🔐 **3 مستويات صلاحيات**
- 🔴 **Owner** - كل شيء + معلومات سرية
- 🟡 **Manager** - عمليات + مالية
- 🟢 **Seller** - بيع وقبض فقط

### 🎨 **4 قوالب للفواتير والسندات**
- **عصري** - ملون وحديث
- **كلاسيكي** - تقليدي أنيق
- **بسيط** - واضح ومباشر
- **خليجي** - ذهبي فاخر

### 🔍 **بحث ذكي شامل**
- Select2 مع AJAX
- فلترة فورية
- دعم عربي كامل (RTL)

### 🏦 **نظام شيكات محترف**
- 5 حالات (معلق/مودع/مؤكد/مرتد/ملغي)
- محاسبة دقيقة
- تتبع كامل

### 📱 **تصميم متجاوب**
- AdminLTE 3
- Bootstrap 4
- دعم جميع الأجهزة

---

## 🛠️ **التثبيت**

### **المتطلبات:**
- Python 3.13+
- SQLite (مدمج) أو PostgreSQL
- Redis (اختياري - للأداء)

### **الخطوات:**

```bash
# 1. تثبيت المتطلبات
pip install -r requirements.txt

# 2. تشغيل النظام
python app.py
```

الموقع: `http://localhost:8080`  
**المستخدم الافتراضي:** admin / admin123

---

## 🐳 Docker Deployment

### Quick Start with Docker

```bash
# Build and run
docker-compose up -d

# Access
http://localhost:8080
```

### Manual Docker Build

```bash
# Build image
docker build -t uae-sale:latest .

# Run container
docker run -d -p 8080:8080 --name uae-sale uae-sale:latest
```

### Production Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for detailed production deployment guide.

---

## 📡 API Documentation

REST API endpoints available for integration.

**Full API Reference:** [API.md](API.md)

### Quick Example

```python
import requests

# Login
session = requests.Session()
session.post('http://localhost:8080/login', data={
    'username': 'admin',
    'password': 'admin123'
})

# Get sales
response = session.get('http://localhost:8080/api/sales/list')
print(response.json())
```

---

## 🏗 System Architecture

**Detailed Architecture:** [ARCHITECTURE.md](ARCHITECTURE.md)

### High-Level Overview

```
Web Interface → Flask App → Services → Models → Database
                    ↓
              AI Engines → External APIs
```

### Key Components
- **Backend:** Flask 3.0 + SQLAlchemy
- **Frontend:** AdminLTE 3 + Bootstrap 4
- **AI/ML:** Custom engines + External providers
- **Database:** SQLite/PostgreSQL + Redis
- **Deployment:** Docker + WSGI

---

## 🧠 **الذكاء الاصطناعي**

### **🎯 ذكاء حقيقي - ليس تلقين!**

**المحركات (5 محركات):**
1. **Neural Engine** - 10 نماذج شبكات عصبية
2. **Reasoning Engine** - استنتاج منطقي
3. **Data Analyzer** - تحليل بيانات حقيقية
4. **Memory System** - ذاكرة طويلة المدى
5. **Semantic Matcher** - 35 نية، 500+ مثال

**نظام التعاون:**
```
المحلي (بيانات + تحليل) ← → Groq/Gemini (تحسين)
                 ↓
         رد متكامل ذكي
```

**الميزة الفريدة:**
- ✅ يحلل بياناتك الحقيقية من DB
- ✅ يتنبأ بالمستقبل (Neural Networks)
- ✅ يتعاون: محلي + سحابي
- ✅ يتذكر المحادثات
- ✅ يتعلم ويتحسن

**المزودون:**
- Groq (مجاني - 14K/يوم) ✅
- Google Gemini (مجاني)
- OpenAI GPT-4 (مدفوع)

**تحديث يومي:**
```
/ai/config → جيب مفتاح جديد → حدّث (30 ثانية)
```

---

## 📚 **التوثيق**

**📖 الدليل الشامل:** [AZAD_SYSTEM_COMPLETE_GUIDE.md](AZAD_SYSTEM_COMPLETE_GUIDE.md)

**محتوياته:**
- معلومات النظام الكاملة
- الهيكل التقني التفصيلي
- نظام الذكاء الاصطناعي (شرح كامل)
- قاعدة البيانات والجداول
- المستخدمون والصلاحيات
- التشغيل والصيانة
- الأداء والتحسينات
- حل المشاكل الشائعة

**📖 دليل المستخدم:** [USER_MANUAL.md](USER_MANUAL.md)

---

## 🗃️ **بنية المشروع**

```
garage_simple/
├── app.py                    # التطبيق الرئيسي
├── config.py                 # الإعدادات
├── extensions.py             # الامتدادات
├── requirements.txt          # المتطلبات
│
├── models/                   # 📊 النماذج (15+ نموذج)
│   ├── user.py              # المستخدمين
│   ├── customer.py          # العملاء
│   ├── product.py           # المنتجات
│   ├── sale.py              # المبيعات
│   ├── payment.py           # الدفعات والمقبوضات
│   ├── cheque.py            # الشيكات
│   └── ...
│
├── routes/                   # 🛣️ المسارات (12+ مسار)
│   ├── auth.py              # المصادقة
│   ├── customers.py         # العملاء
│   ├── sales.py             # المبيعات
│   ├── payments.py          # الدفعات
│   ├── cheques.py           # الشيكات
│   ├── owner.py             # إعدادات المالك
│   ├── ai.py                # المساعد الذكي
│   └── ...
│
├── services/                 # ⚙️ الخدمات (8+ خدمة)
│   ├── ai_service.py        # خدمة AI الرئيسية
│   ├── sale_service.py      # خدمة المبيعات
│   ├── payment_service.py   # خدمة الدفعات
│   └── ...
│
├── ai_knowledge/             # 🤖 محركات AI (27 ملف)
│   ├── azad_responses.py    # الردود الذكية
│   ├── context_engine.py    # محرك السياق
│   ├── analytics_predictions.py
│   ├── data_analyzer.py
│   ├── system_integration.py
│   ├── learning_system.py
│   └── ... (21 محرك آخر)
│
├── templates/                # 🎨 القوالب
│   ├── invoices/            # 4 قوالب فواتير
│   ├── receipts/            # 4 قوالب سندات
│   ├── ai/                  # المساعد الذكي
│   └── ...
│
├── static/                   # 📁 الملفات الثابتة
│   ├── js/                  # JavaScript
│   │   ├── customer-select.js
│   │   ├── azad-app.js
│   │   └── ...
│   └── css/                 # Stylesheets
│
└── instance/                 # 💾 البيانات
    ├── garage.db            # قاعدة البيانات
    └── backups/             # النسخ الاحتياطية
```

---

## 🚀 **البدء السريع**

### **1. الإعدادات الأولية:**
```
1. افتح: http://localhost:8080
2. تسجيل الدخول: admin / admin123
3. اذهب لـ: الإعدادات → إعدادات الفواتير
4. املأ معلومات الشركة
5. اختر القالب المفضل
6. احفظ الإعدادات
```

### **2. إضافة البيانات:**
```
1. العملاء → إضافة عميل
2. المنتجات → إضافة منتج
3. المبيعات → فاتورة جديدة
4. الدفعات → سند قبض جديد
```

### **3. استخدام المساعد:**
```
1. اضغط على أيقونة 🤖 في النافبار
2. اسأل أي سؤال:
   • "حلل المبيعات"
   • "كم عدد العملاء؟"
   • "ما هو البستم؟"
   • (مالك) "كلمات مرور"
```

---

---

## ⚠️ **LEGAL NOTICE - إشعار قانوني**

### 🔒 **Proprietary Software - برمجية محمية**

**This software is PROPRIETARY and CONFIDENTIAL.**  
**هذه البرمجية محمية بحقوق الملكية وسرية.**

#### ❌ **STRICTLY PROHIBITED - ممنوع تماماً:**
- Unauthorized copying or distribution | النسخ أو التوزيع بدون إذن
- Commercial use without license | الاستخدام التجاري بدون ترخيص
- Reverse engineering | الهندسة العكسية
- Code modification | تعديل الكود
- Reselling or sublicensing | إعادة البيع أو الترخيص

#### ⚖️ **Legal Consequences - العواقب القانونية:**
Violations will result in:
- Immediate legal action | إجراءات قانونية فورية
- Criminal prosecution | محاكمة جنائية
- Claims for damages | مطالبات بالتعويضات

#### ✅ **Authorized Use Only - للاستخدام المصرح فقط:**
Contact us for licensing: rafideen.ahmadghannam@gmail.com

---

## 📞 **Contact - الاتصال**

**Azad Smart Systems - شركة أزاد للأنظمة الذكية**

- 🌐 **Website:** https://azad.pythonanywhere.com/
- 📧 **Email:** rafideen.ahmadghannam@gmail.com
- 📱 **Mobile:** +970-598-953-362
- 📍 **Location:** Palestine - Ramallah | فلسطين - رام الله 🇵🇸

**Developer:** Eng. Ahmad Ghannam  
**Company:** Azad Smart Systems

---

## 📝 **License - الترخيص**

**Copyright © 2025 Azad Smart Systems. ALL RIGHTS RESERVED.**  
**جميع الحقوق محفوظة © 2025 شركة أزاد للأنظمة الذكية**

This software is protected by copyright law and international treaties.  
Unauthorized reproduction or distribution may result in severe civil and  
criminal penalties, and will be prosecuted to the maximum extent possible  
under the law.

See [LICENSE](LICENSE) file for full terms and conditions.

---

## 💝 **Support Our Work - ادعم عملنا**

**Like this project? Help us continue developing! 🚀**  
**أعجبك المشروع؟ ساعدنا على الاستمرار! 🚀**

### Ways to Support:

1. **⭐ Star this repository** - Show your appreciation
2. **🛍️ Become a client** - Purchase a license
3. **💼 Hire us** - Custom development services
4. **📢 Spread the word** - Share with others

**Contact for licensing & support:**  
📧 rafideen.ahmadghannam@gmail.com  
📱 +970-598-953-362  
🌐 https://azad.pythonanywhere.com/

**Your support helps Palestinian developers! 🇵🇸**

👉 **[Learn more about supporting us](SUPPORT.md)**

---

## 🎉 **الخلاصة**

**نظام احترافي متكامل:**
- ✅ ذكاء حقيقي (5 محركات + 35 نية)
- ✅ بيانات حقيقية من DB
- ✅ تعاون محلي + سحابي
- ✅ 47 ملف معرفة
- ✅ 21 مستمع ذكي
- ✅ تحديث يومي سهل (30 ثانية)
- ✅ بصمة أزاد احترافية

**التقييم:** ⭐⭐⭐⭐⭐ (25/25)

---

<div align="center">

**🇵🇸 صُنع بفخر في فلسطين**

![Made with Love](https://img.shields.io/badge/Made%20with-❤️-red.svg)
![Palestine](https://img.shields.io/badge/Made%20in-Palestine%20🇵🇸-green.svg)
![AI Powered](https://img.shields.io/badge/AI-Real%20Intelligence-purple.svg)

**© 2025 شركة أزاد للأنظمة الذكية - جميع الحقوق محفوظة**

**Azad Smart Systems | م. أحمد غنام**

</div>

