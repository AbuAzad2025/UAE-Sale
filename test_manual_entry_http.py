"""
اختبار إنشاء قيد يدوي مباشرة عبر HTTP
"""
import requests
from datetime import date

BASE_URL = "http://127.0.0.1:8080"

def test_manual_entry():
    """اختبار إنشاء قيد يدوي"""
    print("="*80)
    print("🔥 اختبار القيد اليدوي المباشر")
    print("="*80)
    
    # 1. الحصول على الصفحة أولاً للحصول على CSRF token
    print("\n1️⃣ الحصول على صفحة القيد اليدوي...")
    try:
        response = requests.get(f"{BASE_URL}/ledger/manual-entry")
        print(f"   ✅ Status: {response.status_code}")
        
        # استخراج CSRF token من HTML
        import re
        csrf_match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
        csrf_token = csrf_match.group(1) if csrf_match else None
        
        if csrf_token:
            print(f"   ✅ CSRF Token: {csrf_token[:20]}...")
        else:
            print("   ⚠️ لم يتم العثور على CSRF Token")
        
        # استخراج session cookie
        session_cookie = response.cookies.get('session')
        cookies = {'session': session_cookie} if session_cookie else {}
        
    except Exception as e:
        print(f"   ❌ خطأ: {e}")
        return False
    
    # 2. إرسال القيد اليدوي
    print("\n2️⃣ إرسال قيد يدوي اختباري...")
    
    # بيانات القيد
    data = {
        'csrf_token': csrf_token,
        'description': 'قيد اختبار تلقائي',
        'entry_date': date.today().strftime('%Y-%m-%d'),
        'notes': 'هذا قيد تم إنشاؤه تلقائياً للاختبار',
        'line_count': '2',
        
        # السطر الأول: مدين صندوق
        'line_0_account': '1110',
        'line_0_description': 'صندوق - اختبار',
        'line_0_debit': '1000',
        'line_0_credit': '0',
        
        # السطر الثاني: دائن مبيعات
        'line_1_account': '4100',
        'line_1_description': 'مبيعات - اختبار',
        'line_1_debit': '0',
        'line_1_credit': '1000'
    }
    
    print(f"   📝 البيانات المرسلة:")
    print(f"      - الوصف: {data['description']}")
    print(f"      - التاريخ: {data['entry_date']}")
    print(f"      - السطر 1: حساب {data['line_0_account']} - مدين {data['line_0_debit']}")
    print(f"      - السطر 2: حساب {data['line_1_account']} - دائن {data['line_1_credit']}")
    
    try:
        response = requests.post(
            f"{BASE_URL}/ledger/manual-entry",
            data=data,
            cookies=cookies,
            allow_redirects=False
        )
        
        print(f"\n   📡 Response Status: {response.status_code}")
        
        if response.status_code == 302:
            # تم التوجيه - نجح
            redirect_url = response.headers.get('Location', '')
            print(f"   ✅ تم إنشاء القيد بنجاح!")
            print(f"   🔗 تم التوجيه إلى: {redirect_url}")
            
            # محاولة الحصول على رقم القيد من URL
            if 'entry/' in redirect_url:
                entry_id = redirect_url.split('entry/')[-1].split('/')[0]
                print(f"   📋 معرف القيد: {entry_id}")
            
            return True
            
        elif response.status_code == 200:
            # الصفحة نفسها - قد يكون هناك خطأ
            print(f"   ⚠️ لم يتم التوجيه - قد يكون هناك خطأ في النموذج")
            
            # البحث عن رسائل الخطأ
            if 'alert-danger' in response.text:
                import re
                error_match = re.search(r'alert-danger[^>]*>([^<]+)', response.text)
                if error_match:
                    print(f"   ❌ رسالة الخطأ: {error_match.group(1)}")
            
            # البحث عن رسائل النجاح
            if 'alert-success' in response.text:
                print(f"   ✅ يوجد رسالة نجاح!")
            
            return False
            
        else:
            print(f"   ❌ Status Code غير متوقع: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"   ❌ خطأ في الإرسال: {e}")
        return False

if __name__ == '__main__':
    import time
    print("\n⏱️ انتظر 3 ثوانٍ لتشغيل الخادم...")
    time.sleep(3)
    
    result = test_manual_entry()
    
    if result:
        print("\n" + "="*80)
        print("🎉 نجح الاختبار - القيد اليدوي يعمل بشكل صحيح!")
        print("="*80)
    else:
        print("\n" + "="*80)
        print("❌ فشل الاختبار - هناك مشكلة في حفظ القيد")
        print("="*80)

