"""
اختبار القيد اليدوي مع تسجيل دخول
"""
import requests
from datetime import date
import re

BASE_URL = "http://127.0.0.1:8080"

# بيانات الدخول
USERNAME = "owner"
PASSWORD = "REDACTED-PASSWORD"

session = requests.Session()

def login():
    """تسجيل الدخول"""
    print("="*80)
    print("🔐 تسجيل الدخول")
    print("="*80)
    
    # 1. GET login page
    print("\n1️⃣ الحصول على صفحة تسجيل الدخول...")
    response = session.get(f"{BASE_URL}/auth/login")
    print(f"   Status: {response.status_code}")
    
    # استخراج CSRF token
    csrf_match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
    csrf_token = csrf_match.group(1) if csrf_match else None
    
    if not csrf_token:
        print("   ❌ لم يتم العثور على CSRF token")
        return False
    
    print(f"   ✅ CSRF Token: {csrf_token[:30]}...")
    
    # 2. POST login
    print("\n2️⃣ إرسال بيانات تسجيل الدخول...")
    login_data = {
        'csrf_token': csrf_token,
        'username': USERNAME,
        'password': PASSWORD,
        'remember': 'y'
    }
    
    response = session.post(
        f"{BASE_URL}/auth/login",
        data=login_data,
        allow_redirects=False
    )
    
    print(f"   Status: {response.status_code}")
    
    if response.status_code == 302:
        print(f"   ✅ تم تسجيل الدخول بنجاح!")
        print(f"   Redirect: {response.headers.get('Location')}")
        return True
    else:
        print(f"   ❌ فشل تسجيل الدخول")
        
        # البحث عن رسالة خطأ
        if 'alert-danger' in response.text:
            error_match = re.search(r'alert-danger[^>]*>([^<]+)', response.text)
            if error_match:
                print(f"   ❌ {error_match.group(1).strip()}")
        
        return False

def test_manual_entry():
    """اختبار إنشاء قيد يدوي"""
    print("\n" + "="*80)
    print("📝 اختبار القيد اليدوي")
    print("="*80)
    
    # 1. GET manual entry page
    print("\n1️⃣ الحصول على صفحة القيد اليدوي...")
    response = session.get(f"{BASE_URL}/ledger/manual-entry")
    print(f"   Status: {response.status_code}")
    
    if response.status_code != 200:
        print(f"   ❌ لم يتم الوصول للصفحة")
        return False
    
    # استخراج CSRF token
    csrf_match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
    csrf_token = csrf_match.group(1) if csrf_match else None
    
    if not csrf_token:
        print("   ❌ لم يتم العثور على CSRF token")
        return False
    
    print(f"   ✅ CSRF Token: {csrf_token[:30]}...")
    
    # 2. POST manual entry
    print("\n2️⃣ إرسال قيد يدوي...")
    
    data = {
        'csrf_token': csrf_token,
        'description': 'قيد اختبار من السكريبت',
        'entry_date': '2025-10-27',
        'notes': 'هذا قيد تجريبي',
        
        # السطر الأول
        'line_0_account': '1110',
        'line_0_description': 'إيداع صندوق',
        'line_0_debit': '2500',
        'line_0_credit': '0',
        
        # السطر الثاني
        'line_1_account': '4100',
        'line_1_description': 'مبيعات نقدية',
        'line_1_debit': '0',
        'line_1_credit': '2500'
    }
    
    print(f"   📝 البيانات:")
    for key, value in data.items():
        if not key.startswith('csrf'):
            print(f"      {key}: {value}")
    
    response = session.post(
        f"{BASE_URL}/ledger/manual-entry",
        data=data,
        allow_redirects=True  # نتبع التوجيه
    )
    
    print(f"\n   📡 Status: {response.status_code}")
    print(f"   URL النهائي: {response.url}")
    
    # فحص النتيجة
    if 'alert-success' in response.text:
        success_match = re.search(r'alert-success[^>]*>\s*([^<]+)', response.text)
        if success_match:
            print(f"   ✅ {success_match.group(1).strip()}")
            return True
    
    if 'alert-danger' in response.text:
        error_match = re.search(r'alert-danger[^>]*>\s*([^<]+)', response.text)
        if error_match:
            print(f"   ❌ {error_match.group(1).strip()}")
    
    # فحص إذا تم إنشاء القيد
    if '/entry/' in response.url:
        entry_id = response.url.split('/entry/')[-1]
        print(f"   ✅ تم إنشاء القيد! ID: {entry_id}")
        return True
    
    print(f"   ⚠️ لم يتم التأكد من نجاح الحفظ")
    return False

if __name__ == '__main__':
    import time
    print("\n⏱️ انتظر 2 ثانية لتشغيل الخادم...")
    time.sleep(2)
    
    # تسجيل الدخول
    if login():
        # اختبار القيد اليدوي
        result = test_manual_entry()
        
        if result:
            print("\n" + "="*80)
            print("🎉 نجح! القيد اليدوي يعمل بشكل ممتاز!")
            print("="*80)
        else:
            print("\n" + "="*80)
            print("❌ فشل في حفظ القيد - راجع الأخطاء أعلاه")
            print("="*80)
    else:
        print("\n❌ فشل في تسجيل الدخول - لا يمكن اختبار القيد")

