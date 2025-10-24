# 🧪 دليل اختبار ميزات الخزينة السرية - Vault Testing Guide

## 🎯 النظام يعمل الآن في وضع Debug المتقدم

---

## 🔐 1. اختبار تسجيل الدخول والوصول للخزينة

### الخطوات:
```
1. افتح: http://localhost:8080/
2. سجل دخول بحساب المالك:
   👤 Username: owner
   🔑 Password: REDACTED-PASSWORD
3. انتقل إلى: http://localhost:8080/payment-vault
4. أدخل كلمة مرور الخزينة (إذا لم تكن مفتوحة)
```

### ما يجب ملاحظته:
- ✅ تسجيل دخول سلس
- ✅ رسالة ترحيب
- ✅ فتح الخزينة بنجاح

---

## 📊 2. اختبار Dashboard المحسن

### افتح:
```
http://localhost:8080/payment-vault/dashboard
```

### الميزات للفحص:
- ✅ **الإحصائيات الأربعة الرئيسية:**
  - 📦 إجمالي المشتريات
  - ❤️ إجمالي التبرعات
  - 💰 إجمالي الإيرادات
  - ⏰ قيد الانتظار

- ✅ **بطاقة حالة الأمان:**
  - 🛡️ مستوى الأمان (عالي/متوسط/منخفض)
  - 🚫 عدد IPs المحظورة
  - ⚠️ عدد المحاولات الفاشلة

- ✅ **بطاقة تحليل العملاء:**
  - 👥 إجمالي العملاء
  - 🔄 عملاء متكررون
  - ⭐ عملاء VIP

- ✅ **الرسم البياني:**
  - 📈 إيرادات آخر 6 أشهر
  - 📊 خط للمشتريات
  - 📊 خط للتبرعات

### اختبار التحديث المباشر:
1. افتح Developer Tools (F12)
2. انتقل إلى Console
3. انتظر 30 ثانية
4. يجب أن ترى: `📊 Live stats updated`

---

## 🔍 3. اختبار Pagination

### افتح:
```
http://localhost:8080/payment-vault/purchases
```

### الميزات للفحص:
- ✅ عرض 20 عنصر في الصفحة
- ✅ أزرار التنقل (السابق/التالي)
- ✅ أرقام الصفحات
- ✅ عداد العناصر (عرض X - Y من Z)
- ✅ Filter حسب الحالة

### اختبر:
```
1. انقر على "التالي" → يجب أن تنتقل للصفحة 2
2. انقر على رقم صفحة → يجب أن تذهب مباشرة
3. Filter حسب الحالة → يجب أن تتحدث النتائج
```

---

## 📥 4. اختبار التصدير

### CSV - المشتريات:
```
http://localhost:8080/payment-vault/export/purchases
```
**المتوقع:** تحميل ملف `purchases_YYYYMMDD.csv`

### CSV - التبرعات:
```
http://localhost:8080/payment-vault/export/donations
```
**المتوقع:** تحميل ملف `donations_YYYYMMDD.csv`

### CSV - البطاقات:
```
http://localhost:8080/payment-vault/export/cards
```
**المتوقع:** تحميل ملف `cards_YYYYMMDD.csv`

### PDF - التقرير الشامل:
```
http://localhost:8080/payment-vault/export/report-pdf
```
**المتوقع:** عرض HTML للطباعة (Ctrl+P للطباعة كـ PDF)

### التحقق من الملف:
1. افتح الملف CSV في Excel
2. تحقق من الترميز العربي (يجب أن يظهر صحيحاً)
3. تحقق من البيانات

---

## 🏥 5. اختبار Health Check

### افتح:
```
http://localhost:8080/payment-vault/health
```

### المتوقع (JSON):
```json
{
  "overall_status": "healthy",
  "checks": {
    "database": {"status": "healthy"},
    "nowpayments": {"status": "healthy" أو "warning"},
    "encryption": {"status": "healthy"},
    "system": {
      "status": "healthy",
      "cpu_percent": XX.X,
      "memory_percent": XX.X,
      "disk_percent": XX.X
    }
  },
  "timestamp": "2025-10-24T..."
}
```

### التحقق:
- ✅ overall_status = "healthy"
- ✅ جميع checks ناجحة
- ✅ CPU < 90%
- ✅ Memory < 90%
- ✅ Disk < 90%

---

## 📊 6. اختبار Metrics

### افتح (يجب تسجيل الدخول):
```
http://localhost:8080/payment-vault/metrics
```

### المتوقع (JSON):
```json
{
  "database": {
    "total_donations": XX,
    "total_purchases": XX,
    "total_cards": XX
  },
  "process": {
    "memory_mb": XX.XX,
    "cpu_percent": X.X,
    "threads": XX,
    "uptime_seconds": XXXX
  },
  "timestamp": "..."
}
```

---

## 🔔 7. اختبار API v2

### Stats API:
```
http://localhost:8080/payment-vault/api/v2/stats
```

**المتوقع:** JSON شامل بجميع الإحصائيات

### Purchases API:
```
http://localhost:8080/payment-vault/api/v2/purchases?page=1&per_page=5
```

**المتوقع:** 
```json
{
  "version": "2.0",
  "success": true,
  "data": [...],
  "pagination": {
    "page": 1,
    "per_page": 5,
    "total": XX,
    "pages": XX,
    "has_next": true/false,
    "has_prev": false
  }
}
```

### Donations API:
```
http://localhost:8080/payment-vault/api/v2/donations?page=1&status=pending
```

**المتوقع:** تبرعات مفلترة حسب الحالة

### Live Stats API:
```
http://localhost:8080/payment-vault/api/live-stats
```

**المتوقع:**
```json
{
  "success": true,
  "daily_revenue": XX.XX,
  "daily_transactions": XX,
  "pending_count": XX,
  "security_level": "high",
  "timestamp": "..."
}
```

---

## 🚨 8. اختبار نظام الأمان

### كشف النشاط المشبوه:
**لا تختبر هذا يدوياً** - يعمل تلقائياً

### مراقبة Logs في Console:
افتح Developer Tools → Console وراقب:
- ✅ رسائل تحديث الإحصائيات
- ✅ رسائل جلب الإشعارات
- ✅ رسائل تحميل Dashboard

---

## 💰 9. اختبار صفحة الدعم (Landing Page)

### افتح:
```
http://localhost:8080/auth/support
```

### الميزات للفحص:
- ✅ عرض الباقات الثلاثة
- ✅ أزرار "شراء"
- ✅ التبديل بين "شراء النظام" و "دعم المشروع"
- ✅ نماذج الدفع (Crypto, Card, PayPal, Bank)
- ✅ مؤشر التقدم (3 خطوات)

### اختبر تدفق الشراء:
1. انقر "شراء" على باقة
2. يجب أن يظهر السعر تلقائياً
3. اختر طريقة دفع
4. يجب أن يظهر النموذج المناسب

### اختبر تدفق التبرع:
1. انقر "دعم المشروع"
2. أدخل مبلغ يدوياً (>= $15)
3. اختر طريقة دفع
4. يجب أن يظهر النموذج

---

## 🔧 10. اختبار الإجراءات الإدارية

### إدارة الباقات:
```
http://localhost:8080/payment-vault/packages-management
```
- ✅ عرض جميع الباقات
- ✅ أزرار التحرير
- ✅ أزرار الإحصائيات
- ✅ تفعيل/تعطيل الباقة

### إدارة المشتريات:
```
http://localhost:8080/payment-vault/purchases
```
- ✅ عرض جميع المشتريات
- ✅ Pagination
- ✅ تفاصيل المشترية
- ✅ زر التفعيل

### إدارة التبرعات:
```
http://localhost:8080/payment-vault/donations
```
- ✅ عرض جميع التبرعات
- ✅ أزرار القبول/الرفض
- ✅ إرسال شكر بالإيميل

### البطاقات المشفرة:
```
http://localhost:8080/payment-vault/cards
```
- ✅ عرض البطاقات (مشفرة)
- ✅ زر فك التشفير (للمالك فقط)
- ✅ إحصائيات البطاقات

---

## 📝 سجل الاختبارات

### ✅ اختبرت:
```
☐ تسجيل الدخول
☐ Dashboard محسن
☐ إحصائيات مباشرة
☐ تحليل الأمان
☐ تحليل العملاء
☐ Pagination
☐ Export CSV
☐ Export PDF
☐ Health Check
☐ Metrics
☐ API v2 Stats
☐ API v2 Purchases
☐ API v2 Donations
☐ Live Stats API
☐ صفحة الدعم
☐ إدارة الباقات
☐ إدارة المشتريات
☐ إدارة التبرعات
☐ البطاقات المشفرة
```

---

## 🐛 تقرير المشاكل

إذا وجدت أي مشاكل، اذكر:
1. **الصفحة/Endpoint:** 
2. **الخطوات:**
3. **المتوقع:**
4. **الفعلي:**
5. **رسالة الخطأ (إن وجدت):**
6. **Screenshot (اختياري):**

---

## 🎊 ملاحظات

- 🔍 راقب Console للأخطاء
- 📊 راقب Network tab للـ API calls
- ⚡ لاحظ سرعة التحميل
- 🎨 تحقق من التصميم
- 📱 جرب على أحجام شاشات مختلفة

**استمتع بالاختبار! 🚀**

