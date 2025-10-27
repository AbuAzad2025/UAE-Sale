"""
اختبار الحسابات في الـ Backend
"""
import requests
import json
import time

BASE_URL = "http://127.0.0.1:8080"

def test_sales_calculation():
    """اختبار حساب إجماليات المبيعات"""
    print("\n" + "="*70)
    print("🔵 اختبار حساب إجماليات المبيعات (Sales)")
    print("="*70)
    
    # تسجيل الدخول أولاً
    session = requests.Session()
    
    # تجربة الـ API مباشرة
    data = {
        "lines": [
            {"quantity": 2, "unit_price": 100, "discount_percent": 10},
            {"quantity": 1, "unit_price": 50, "discount_percent": 0}
        ],
        "discount_amount": 20,
        "shipping_cost": 15,
        "tax_rate": 5
    }
    
    try:
        response = session.post(
            f"{BASE_URL}/sales/api/calculate-totals",
            json=data
        )
        
        print(f"   📡 Status Code: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"   ✅ الاستجابة:")
            print(f"      • المجموع الفرعي: {result.get('subtotal', 0):.2f} AED")
            print(f"      • الخصم: {result.get('discount', 0):.2f} AED")
            print(f"      • الشحن: {result.get('shipping', 0):.2f} AED")
            print(f"      • الضريبة ({result.get('tax_rate', 0)}%): {result.get('tax_amount', 0):.2f} AED")
            print(f"      • الإجمالي: {result.get('total', 0):.2f} AED")
            print(f"      • عدد السطور: {result.get('line_count', 0)}")
            
            # التحقق من الحسابات
            expected_subtotal = (2 * 100 * 0.9) + (1 * 50)  # 230
            expected_after_discount = 230 - 20 + 15  # 225
            expected_tax = 225 * 0.05  # 11.25
            expected_total = 225 + 11.25  # 236.25
            
            if abs(result['total'] - expected_total) < 0.01:
                print(f"\n   ✅ الحسابات صحيحة! (متوقع: {expected_total:.2f})")
                return True
            else:
                print(f"\n   ❌ خطأ في الحسابات! (متوقع: {expected_total:.2f}, فعلي: {result['total']:.2f})")
                return False
        else:
            print(f"   ❌ فشل الطلب: {response.text[:200]}")
            return False
            
    except Exception as e:
        print(f"   ❌ خطأ: {str(e)}")
        return False


def test_purchases_calculation():
    """اختبار حساب إجماليات المشتريات"""
    print("\n" + "="*70)
    print("🔵 اختبار حساب إجماليات المشتريات (Purchases)")
    print("="*70)
    
    session = requests.Session()
    
    data = {
        "lines": [
            {"quantity": 5, "unit_cost": 80, "discount_percent": 5},
            {"quantity": 3, "unit_cost": 120, "discount_percent": 0}
        ],
        "tax_rate": 5
    }
    
    try:
        response = session.post(
            f"{BASE_URL}/purchases/api/calculate-totals",
            json=data
        )
        
        print(f"   📡 Status Code: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"   ✅ الاستجابة:")
            print(f"      • المجموع الفرعي: {result.get('subtotal', 0):.2f} AED")
            print(f"      • الضريبة ({result.get('tax_rate', 0)}%): {result.get('tax_amount', 0):.2f} AED")
            print(f"      • الإجمالي: {result.get('total', 0):.2f} AED")
            print(f"      • عدد السطور: {result.get('line_count', 0)}")
            
            # التحقق
            expected_subtotal = (5 * 80 * 0.95) + (3 * 120)  # 380 + 360 = 740
            expected_tax = 740 * 0.05  # 37
            expected_total = 740 + 37  # 777
            
            if abs(result['total'] - expected_total) < 0.01:
                print(f"\n   ✅ الحسابات صحيحة! (متوقع: {expected_total:.2f})")
                return True
            else:
                print(f"\n   ❌ خطأ في الحسابات! (متوقع: {expected_total:.2f}, فعلي: {result['total']:.2f})")
                return False
        else:
            print(f"   ❌ فشل الطلب: {response.text[:200]}")
            return False
            
    except Exception as e:
        print(f"   ❌ خطأ: {str(e)}")
        return False


def test_ledger_calculation():
    """اختبار حساب توازن القيد اليدوي"""
    print("\n" + "="*70)
    print("🔵 اختبار حساب توازن القيد اليدوي (Ledger)")
    print("="*70)
    
    session = requests.Session()
    
    data = {
        "lines": [
            {"debit": 1000, "credit": 0},
            {"debit": 0, "credit": 1000}
        ]
    }
    
    try:
        response = session.post(
            f"{BASE_URL}/ledger/api/calculate-journal-balance",
            json=data
        )
        
        print(f"   📡 Status Code: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"   ✅ الاستجابة:")
            print(f"      • إجمالي المدين: {result.get('total_debit', 0):.2f} AED")
            print(f"      • إجمالي الدائن: {result.get('total_credit', 0):.2f} AED")
            print(f"      • الفرق: {result.get('difference', 0):.2f} AED")
            print(f"      • متوازن: {'✅ نعم' if result.get('is_balanced') else '❌ لا'}")
            
            if result.get('is_balanced'):
                print(f"\n   ✅ القيد متوازن!")
                return True
            else:
                print(f"\n   ❌ القيد غير متوازن!")
                return False
        else:
            print(f"   ❌ فشل الطلب: {response.text[:200]}")
            return False
            
    except Exception as e:
        print(f"   ❌ خطأ: {str(e)}")
        return False


if __name__ == '__main__':
    print("\n╔═══════════════════════════════════════════════════════════════╗")
    print("║        🧪 اختبار شامل للحسابات في الـ Backend               ║")
    print("╚═══════════════════════════════════════════════════════════════╝")
    
    time.sleep(2)  # انتظار تشغيل السيرفر
    
    results = []
    
    # اختبار المبيعات
    results.append(("Sales", test_sales_calculation()))
    
    # اختبار المشتريات
    results.append(("Purchases", test_purchases_calculation()))
    
    # اختبار دفتر الأستاذ
    results.append(("Ledger", test_ledger_calculation()))
    
    # النتيجة النهائية
    print("\n" + "="*70)
    print("📊 ملخص الاختبارات")
    print("="*70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ نجح" if result else "❌ فشل"
        print(f"   {name:15} : {status}")
    
    print("\n" + "="*70)
    print(f"   النتيجة: {passed}/{total} اختبار نجح ({passed/total*100:.0f}%)")
    print("="*70)
    
    if passed == total:
        print("\n🎉 جميع الاختبارات نجحت! النظام يعمل بشكل صحيح!")
    else:
        print(f"\n⚠️ هناك {total - passed} اختبار فشل!")

