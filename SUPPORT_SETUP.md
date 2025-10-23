# دعم المشروع - Project Support Setup

## إعداد نظام الدعم مع NOWPayments

### 1. الحصول على API Key من NOWPayments

1. **سجل في NOWPayments:**
   - اذهب إلى: https://account.nowpayments.io/signup
   - استخدم أي إيميل شخصي (Gmail, Yahoo, Outlook)
   - أكمل التسجيل وتفعيل الحساب

2. **احصل على API Key:**
   - ادخل إلى Dashboard
   - اذهب إلى **Settings → API Keys**
   - اضغط **Create API Key**
   - **انسخ المفتاح** واحفظه

3. **أضف Payout Wallet:**
   - اذهب إلى **Settings → Payout Settings**
   - أضف عنوان محفظة Bitcoin الخاصة بك
   - (هنا سيتم إرسال التبرعات)

### 2. إعداد متغيرات البيئة

أضف هذه المتغيرات إلى ملف `.env`:

```env
# NOWPayments Integration
NOWPAYMENTS_API_KEY=your-api-key-here
NOWPAYMENTS_IPN_SECRET=your-ipn-secret-here
BASE_URL=https://your-domain.com
```

### 3. إعداد IPN Callback

1. **في NOWPayments Dashboard:**
   - اذهب إلى **Settings → IPN Settings**
   - أضف URL: `https://your-domain.com/auth/payment/callback`
   - احفظ الـ IPN Secret

2. **في ملف .env:**
   ```env
   NOWPAYMENTS_IPN_SECRET=your-ipn-secret-from-dashboard
   ```

### 4. اختبار النظام

1. **تشغيل الخادم:**
   ```bash
   python app.py
   ```

2. **اختبار صفحة الدعم:**
   - اذهب إلى: `http://localhost:5000/auth/support`
   - جرب إنشاء تبرع بـ $10
   - تحقق من إنشاء عنوان الدفع

3. **اختبار الدفع:**
   - استخدم عنوان Bitcoin المعروض
   - أرسل مبلغ صغير للاختبار
   - تحقق من تحديث الحالة

### 5. الميزات المتاحة

#### ✅ **مكتمل:**
- ✅ صفحة دعم جميلة ومتجاوبة
- ✅ دعم العملات الرقمية (Bitcoin, Ethereum, USDT, USDC, BNB)
- ✅ تكامل مع NOWPayments API
- ✅ إنشاء عناوين دفع فورية
- ✅ QR Code للدفع السريع
- ✅ صفحة شكر بعد الدفع
- ✅ تتبع حالة الدفع
- ✅ الحد الأدنى $10
- ✅ أمان كامل مع تشفير

#### 🔄 **قيد التطوير:**
- 🔄 دفع بالبطاقات البنكية
- 🔄 دفع عبر PayPal
- 🔄 إشعارات WhatsApp
- 🔄 تقارير التبرعات

### 6. استكشاف الأخطاء

#### **خطأ "API Key غير صحيح":**
- تأكد من صحة API Key
- تحقق من تفعيل الحساب

#### **خطأ "IPN Callback فشل":**
- تأكد من صحة BASE_URL
- تحقق من إعدادات IPN في NOWPayments

#### **خطأ "الحد الأدنى $10":**
- هذا طبيعي، الحد الأدنى للتبرع $10

### 7. الأمان

- ✅ جميع المعاملات مشفرة
- ✅ لا نحتفظ بمعلومات شخصية
- ✅ IPN محمي بالتوقيع
- ✅ Rate limiting على API
- ✅ تحقق من صحة البيانات

### 8. الدعم الفني

للحصول على المساعدة:
- **Email:** support@azadsystems.com
- **WhatsApp:** +970 592 800 646
- **GitHub Issues:** [إنشاء issue جديد]

---

## 🎉 **جاهز للاستخدام!**

بعد إكمال الإعداد، سيكون لديك نظام دعم كامل وآمن للتبرعات بالعملات الرقمية!
