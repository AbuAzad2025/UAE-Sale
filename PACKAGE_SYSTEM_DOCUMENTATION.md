# 📦 نظام إدارة الباقات والمشتريات - التوثيق الكامل

## 🎯 نظرة عامة

نظام متكامل لإدارة باقات النظام، المشتريات، والتبرعات - محمي بالكامل داخل **Payment Vault** مع كلمة مرور إضافية.

---

## 📂 الهيكل

```
routes/
├── auth.py ..................... صفحة الدعم العامة فقط
└── payment_vault.py ............ كل شيء محمي هنا

models/
├── package.py .................. Package + PackagePurchase
└── donation.py ................. Donation (موجود مسبقاً)

templates/
├── support.html ................ Landing Page (عامة)
└── payment_vault/
    ├── packages.html ........... إدارة الباقات
    ├── purchases.html .......... عرض المشتريات
    └── purchase_detail.html .... تفاصيل شراء واحد
```

---

## 🔐 نظام الحماية

### المستويات:
1. **Level 1**: تسجيل دخول عادي (Owner فقط)
2. **Level 2**: كلمة مرور الخزينة (Payment Vault)
3. **Level 3**: تسجيل كل عملية في Audit Log

### الوصول:
```
/payment-vault/packages-management  ← Owner + Vault Password
/payment-vault/purchases            ← Owner + Vault Password
/payment-vault/api/purchase         ← Public (rate limited: 10/min)
/payment-vault/api/donation         ← Public (rate limited: 10/min)
/auth/support                       ← Public (للجميع)
```

---

## 📊 نماذج البيانات

### 1. Package (الباقة)
```python
{
    id: Integer
    name_ar: "الباقة الأساسية"
    name_en: "Basic Package"
    slug: "basic"
    icon: "📦"
    price: 299.00
    currency: "USD"
    features: ["ميزة 1", "ميزة 2", ...]  # JSON Array
    is_active: True
    is_featured: True
    badge_text: "الأكثر شعبية"
    badge_color: "success"
    sort_order: 1
    support_duration_months: 3
    max_users: 5
    max_branches: 1
    has_ai: False
    has_whatsapp: False
    has_pos: False
    # ... المزيد من الخصائص
}
```

### 2. PackagePurchase (عملية الشراء)
```python
{
    id: Integer
    package_id: Integer → FK(packages.id)
    customer_name: "أحمد محمد"
    customer_email: "ahmad@example.com"
    customer_phone: "+970599123456"
    company_name: "شركة ABC"
    payment_method: "crypto|card|paypal|bank"
    payment_status: "pending|completed|failed|refunded"
    amount_paid: 599.00
    currency: "USD"
    transaction_id: "CRYPTO_1234567890"
    payment_details: {...}  # JSON
    activation_status: "pending|activated|expired"
    activation_date: DateTime
    expiry_date: DateTime
    notes: Text
    created_at: DateTime
    updated_at: DateTime
}
```

### 3. Donation (التبرع)
```python
{
    id: Integer
    amount_usd: 50.00
    payment_method: "crypto"
    crypto_type: "btc"
    transaction_type: "donation|purchase"
    donor_name: "محمد أحمد"
    donor_email: "mohammad@example.com"
    donor_message: "شكراً"
    status: "pending|confirmed|completed|failed"
    transaction_hash: "BTC_TX_987654"
    # ... معلومات إضافية
}
```

---

## 🔄 سيناريو الشراء الكامل

### الخطوة 1: المستخدم على Landing Page
```
URL: /auth/support
العرض:
  ✅ قائمة الباقات (ديناميكية من DB)
  ✅ أزرار "شراء النظام" و "دعم المشروع"
  ✅ نماذج الدفع
```

### الخطوة 2: اختيار الباقة
```javascript
// عند الضغط على باقة
function selectPackage(slug, price, event) {
    selectedPackage = slug;
    selectedAmount = price;
    // تفعيل البطاقة
    event.currentTarget.classList.add('active');
    // عرض طرق الدفع
    document.getElementById('purchase-payment-methods').style.display = 'grid';
}
```

### الخطوة 3: اختيار طريقة الدفع
```javascript
// عند اختيار Crypto
function generateCryptoPayment() {
    // جمع البيانات
    const packageCard = document.querySelector('.package-card.active');
    const packageId = packageCard.getAttribute('data-package-id');
    
    // طلب بيانات العميل
    const customerData = {
        customer_name: prompt('اسمك الكامل:'),
        customer_email: prompt('بريدك الإلكتروني:'),
        customer_phone: prompt('رقم الجوال:'),
        company_name: prompt('اسم الشركة (اختياري):')
    };
}
```

### الخطوة 4: إرسال الطلب
```javascript
// POST /payment-vault/api/purchase
fetch('/payment-vault/api/purchase', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
        package_id: parseInt(packageId),
        customer_name: customerData.customer_name,
        customer_email: customerData.customer_email,
        customer_phone: customerData.customer_phone,
        company_name: customerData.company_name,
        payment_method: 'crypto',
        amount_paid: selectedAmount,
        currency: 'USD',
        transaction_id: 'CRYPTO_' + Date.now(),
        payment_details: {
            crypto_type: cryptoType,
            amount: selectedAmount
        }
    })
})
```

### الخطوة 5: معالجة الخادم
```python
@payment_vault_bp.route('/api/purchase', methods=['POST'])
@limiter.limit("10 per minute")
def api_create_purchase():
    # 1. التحقق من البيانات المطلوبة
    if not all(request.json.get(f) for f in required_fields):
        return error_response
    
    # 2. التحقق من الباقة
    package = Package.query.get(package_id)
    if not package.is_active:
        return error_response
    
    # 3. التحقق من المبلغ
    if amount_paid < package.price:
        return error_response
    
    # 4. إنشاء PackagePurchase
    purchase = PackagePurchase(...)
    db.session.add(purchase)
    
    # 5. إنشاء Donation (للتوافق)
    donation = Donation(transaction_type='purchase', ...)
    db.session.add(donation)
    
    # 6. Commit
    db.session.commit()
    
    # 7. Audit Log
    create_audit_log(...)
    
    return jsonify({
        'success': True,
        'purchase_id': purchase.id
    })
```

### الخطوة 6: الرد للمستخدم
```javascript
// عرض رسالة نجاح
Swal.fire({
    icon: 'success',
    title: 'تم إنشاء الطلب بنجاح!',
    html: `
        <p>رقم الطلب: #${purchase_id}</p>
        <p>المبلغ: $${amount}</p>
        <p>سنتواصل معك قريباً</p>
    `
})
```

### الخطوة 7: المالك في الخزينة
```
1. يفتح /payment-vault
2. يدخل كلمة مرور الخزينة
3. يذهب إلى /payment-vault/purchases
4. يشاهد:
   - إجمالي: 15 مشترية
   - معلقة: 3
   - مكتملة: 12
   - الإيرادات: $7,485
5. يضغط على "✓" لتفعيل الشراء
6. POST /payment-vault/purchase/123/activate
7. النظام:
   ✅ payment_status → completed
   ✅ activation_status → activated
   ✅ activation_date → now
   ✅ يحدث Donation المرتبط
   ✅ يسجل في Audit Log
```

---

## 💝 سيناريو التبرع الكامل

### الفرق عن الشراء:
```
❌ لا يوجد باقة
❌ لا يوجد package_id
✅ مبلغ حر (>= $1)
✅ بيانات اختيارية
✅ يحفظ في Donation فقط
```

### الكود:
```javascript
// POST /payment-vault/api/donation
fetch('/payment-vault/api/donation', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
        amount: customAmount,
        payment_method: 'crypto',
        crypto_type: 'btc',
        donor_name: donorName || null,      // اختياري
        donor_email: donorEmail || null,    // اختياري
        message: donorMessage || null,      // اختياري
        transaction_id: 'DONATION_' + Date.now()
    })
})
```

---

## ✅ الحقول المتطابقة

### API Request → Database Fields

#### للشراء:
```
package_id        → PackagePurchase.package_id
customer_name     → PackagePurchase.customer_name
customer_email    → PackagePurchase.customer_email
customer_phone    → PackagePurchase.customer_phone
company_name      → PackagePurchase.company_name
payment_method    → PackagePurchase.payment_method
amount_paid       → PackagePurchase.amount_paid
currency          → PackagePurchase.currency
transaction_id    → PackagePurchase.transaction_id
payment_details   → PackagePurchase.payment_details
```

#### للتبرع:
```
amount           → Donation.amount_usd
payment_method   → Donation.payment_method
crypto_type      → Donation.crypto_type
donor_name       → Donation.donor_name
donor_email      → Donation.donor_email
message          → Donation.donor_message
transaction_id   → Donation.transaction_hash
```

---

## 🔒 الأمان

### 1. Rate Limiting
```python
@limiter.limit("10 per minute")  # 10 طلبات فقط في الدقيقة
```

### 2. Validation
```python
# التحقق من جميع الحقول المطلوبة
# التحقق من صحة البريد الإلكتروني
# التحقق من المبلغ
# التحقق من وجود الباقة ونشاطها
```

### 3. Audit Log
```python
create_audit_log(
    action='purchase_created',
    description=f'طلب شراء: {package.name_ar} - ${amount}',
    user_id=None,
    ip_address=request.remote_addr
)
```

### 4. الخزينة المحمية
```python
# جميع routes الإدارة محمية
if not current_user.is_owner:
    return redirect('/')

vault = PaymentVault.query.first()
if not vault or vault.is_locked:
    return redirect('/unlock')
```

---

## 📈 التقارير والإحصائيات

### في Dashboard:
```python
stats = {
    'total_purchases': PackagePurchase.query.count(),
    'pending': PackagePurchase.query.filter_by(payment_status='pending').count(),
    'completed': PackagePurchase.query.filter_by(payment_status='completed').count(),
    'revenue': db.session.query(func.sum(PackagePurchase.amount_paid))
                .filter_by(payment_status='completed').scalar(),
    'total_donations': Donation.query.filter_by(transaction_type='donation').count(),
    'donation_amount': db.session.query(func.sum(Donation.amount_usd))
                        .filter_by(transaction_type='donation', status='completed').scalar()
}
```

---

## 🧪 الاختبار

### 1. اختبار الشراء:
```bash
# محلياً
http://localhost:8080/auth/support
1. اختر باقة
2. اختر crypto
3. أدخل البيانات
4. تحقق من DB: SELECT * FROM package_purchases;
```

### 2. اختبار التبرع:
```bash
# محلياً
http://localhost:8080/auth/support
1. تبويب "دعم المشروع"
2. اختر crypto
3. أدخل مبلغ
4. تحقق من DB: SELECT * FROM donations WHERE transaction_type='donation';
```

### 3. اختبار الخزينة:
```bash
http://localhost:8080/payment-vault
1. ادخل كلمة المرور
2. اذهب لـ Purchases
3. فعّل شراء
4. تحقق: activation_status = 'activated'
```

---

## 🚀 النشر

```bash
# 1. Git
git add -A
git commit -m "نظام الباقات الكامل"
git push origin main

# 2. PythonAnywhere
cd ~/UAE-Sale
git pull origin main
flask db upgrade
touch /var/www/uaesale_azad_pythonanywhere_com_wsgi.py
```

---

## ✨ الميزات

✅ نظام باقات ديناميكي من DB
✅ إدارة كاملة للباقات
✅ تتبع كامل للمشتريات
✅ نظام تبرعات مستقل
✅ حماية متعددة المستويات
✅ Audit Log لكل عملية
✅ Rate Limiting للحماية
✅ واجهة Landing Page احترافية
✅ لوحة تحكم محمية
✅ إحصائيات وتقارير
✅ تفعيل يدوي للمشتريات
✅ دعم عملات متعددة
✅ مرن وقابل للتوسع

---

**🎯 النظام جاهز للإنتاج! 🚀**

