"""
اختبار شامل للنظام المحاسبي الإداري
Test all admin ledger functionalities
"""

import requests
import json
from datetime import datetime, date

BASE_URL = "http://127.0.0.1:8080"

def test_endpoint(url, name, method='GET', data=None):
    """اختبار endpoint محدد"""
    try:
        full_url = f"{BASE_URL}{url}"
        print(f"\n{'='*60}")
        print(f"🔍 اختبار: {name}")
        print(f"📍 URL: {url}")
        print(f"🔧 Method: {method}")
        
        if method == 'GET':
            response = requests.get(full_url, timeout=5)
        elif method == 'POST':
            response = requests.post(full_url, data=data, timeout=5)
        
        status = response.status_code
        
        if status == 200:
            print(f"✅ نجح - Status Code: {status}")
            return True
        elif status == 302:
            print(f"🔄 إعادة توجيه - Status Code: {status}")
            print(f"   Location: {response.headers.get('Location', 'N/A')}")
            return True
        elif status == 401:
            print(f"🔐 يتطلب تسجيل دخول - Status Code: {status}")
            return True  # هذا متوقع للصفحات المحمية
        elif status == 404:
            print(f"❌ غير موجود - Status Code: {status}")
            return False
        elif status == 500:
            print(f"❌ خطأ في الخادم - Status Code: {status}")
            return False
        else:
            print(f"⚠️ Status Code: {status}")
            return False
            
    except requests.exceptions.ConnectionError:
        print(f"❌ فشل الاتصال - الخادم غير متاح")
        return False
    except requests.exceptions.Timeout:
        print(f"⏱️ انتهى الوقت")
        return False
    except Exception as e:
        print(f"❌ خطأ: {str(e)}")
        return False

def main():
    print("="*60)
    print("🚀 اختبار شامل للنظام المحاسبي الإداري")
    print("="*60)
    
    results = {
        'passed': 0,
        'failed': 0,
        'total': 0
    }
    
    # قائمة الاختبارات
    tests = [
        # الصفحات الأساسية
        ('/', 'الصفحة الرئيسية'),
        ('/login', 'صفحة تسجيل الدخول'),
        
        # دفتر الأستاذ الأساسي
        ('/ledger/', 'لوحة تحكم دفتر الأستاذ'),
        ('/ledger/accounts-tree', 'شجرة الحسابات'),
        ('/ledger/journal-entries', 'القيود اليومية'),
        ('/ledger/manual-entry', 'إضافة قيد يدوي'),
        ('/ledger/trial-balance', 'ميزان المراجعة'),
        ('/ledger/income-statement', 'قائمة الدخل'),
        ('/ledger/balance-sheet', 'الميزانية العمومية'),
        ('/ledger/cash-flow', 'قائمة التدفقات النقدية'),
        ('/ledger/aging-analysis?type=receivables', 'تحليل عمر الذمم المدينة'),
        ('/ledger/aging-analysis?type=payables', 'تحليل عمر الذمم الدائنة'),
        
        # لوحة التحكم الإدارية الجديدة
        ('/ledger/admin-dashboard', 'لوحة التحكم الإدارية'),
        ('/ledger/admin-accounts', 'إدارة الحسابات المحاسبية'),
        ('/ledger/admin-accounts/add', 'إضافة حساب جديد'),
        ('/ledger/admin-vaults', 'إدارة الصناديق والمحافظ'),
        ('/ledger/admin-journals', 'إدارة القيود المحاسبية'),
        ('/ledger/admin-reports', 'التقارير المالية المتقدمة'),
        ('/ledger/admin-trial-balance', 'ميزان المراجعة (إداري)'),
        ('/ledger/admin-balance-sheet', 'الميزانية العمومية (إداري)'),
        ('/ledger/admin-income-statement', 'قائمة الدخل (إداري)'),
        ('/ledger/admin-settings', 'إعدادات النظام المحاسبي'),
        
        # API Endpoints
        ('/ledger/api/accounts/search', 'API - البحث عن الحسابات'),
        
        # الوحدات الأخرى
        ('/customers', 'إدارة العملاء'),
        ('/suppliers', 'إدارة الموردين'),
        ('/products', 'إدارة المنتجات'),
        ('/sales', 'إدارة المبيعات'),
        ('/purchases', 'إدارة المشتريات'),
        ('/expenses', 'إدارة المصروفات'),
        ('/payment-vault/dashboard', 'لوحة تحكم المحفظة'),
    ]
    
    for url, name in tests:
        results['total'] += 1
        if test_endpoint(url, name):
            results['passed'] += 1
        else:
            results['failed'] += 1
    
    # ملخص النتائج
    print("\n" + "="*60)
    print("📊 ملخص الاختبارات")
    print("="*60)
    print(f"✅ نجح: {results['passed']}/{results['total']}")
    print(f"❌ فشل: {results['failed']}/{results['total']}")
    print(f"📈 النسبة: {(results['passed']/results['total']*100):.1f}%")
    print("="*60)
    
    if results['failed'] == 0:
        print("🎉 جميع الاختبارات نجحت!")
    else:
        print(f"⚠️ هناك {results['failed']} اختبار فشل")
    
    return results

if __name__ == '__main__':
    print("\n⏱️ انتظر 5 ثوانٍ لبدء الخادم...")
    import time
    time.sleep(5)
    
    results = main()
    
    print("\n✅ اكتمل الاختبار!")

