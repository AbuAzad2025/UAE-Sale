"""
اختبار مباشر للقيد اليدوي مع طباعة التفاصيل الكاملة
"""
import requests
from datetime import date
from bs4 import BeautifulSoup

BASE_URL = "http://127.0.0.1:8080"

# إنشاء session للحفاظ على cookies
session = requests.Session()

print("="*80)
print("🔍 اختبار القيد اليدوي - تحليل مفصل")
print("="*80)

# 1. GET request
print("\n1️⃣ GET /ledger/manual-entry")
response = session.get(f"{BASE_URL}/ledger/manual-entry")
print(f"   Status: {response.status_code}")

if response.status_code == 200:
    # استخراج CSRF token
    import re
    csrf_match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
    csrf_token = csrf_match.group(1) if csrf_match else None
    print(f"   CSRF Token: {csrf_token[:30] if csrf_token else 'NOT FOUND'}...")
    
    # 2. POST request
    print("\n2️⃣ POST /ledger/manual-entry")
    
    data = {
        'csrf_token': csrf_token,
        'description': 'قيد اختبار HTTP',
        'entry_date': '2025-10-27',
        'notes': 'اختبار',
        'line_0_account': '1110',
        'line_0_description': 'صندوق',
        'line_0_debit': '500',
        'line_0_credit': '0',
        'line_1_account': '4100',
        'line_1_description': 'مبيعات',
        'line_1_debit': '0',
        'line_1_credit': '500'
    }
    
    print(f"   📝 إرسال البيانات...")
    response = session.post(
        f"{BASE_URL}/ledger/manual-entry",
        data=data,
        allow_redirects=False
    )
    
    print(f"   📡 Status: {response.status_code}")
    
    if response.status_code == 302:
        print(f"   ✅ نجح! Redirect to: {response.headers.get('Location')}")
    elif response.status_code == 400:
        print(f"   ❌ Bad Request - فحص التفاصيل:")
        print(f"   Response Length: {len(response.text)} bytes")
        
        # البحث عن أخطاء
        if 'error' in response.text.lower():
            print("   🔍 يوجد رسالة خطأ في الاستجابة")
        
        # طباعة أول 500 حرف
        print(f"\n   Response Preview:")
        print(response.text[:500])
    else:
        print(f"   Status: {response.status_code}")
        
        # البحث عن رسائل Flash
        if 'alert-success' in response.text:
            success_match = re.search(r'alert-success[^>]*>([^<]+)', response.text)
            if success_match:
                print(f"   ✅ {success_match.group(1)}")
        
        if 'alert-danger' in response.text:
            error_match = re.search(r'alert-danger[^>]*>([^<]+)', response.text)
            if error_match:
                print(f"   ❌ {error_match.group(1)}")

if __name__ == '__main__':
    import time
    print("\n⏱️ انتظر 2 ثانية...")
    time.sleep(2)
    test_manual_entry()
    print("\n✅ اكتمل الاختبار!")

