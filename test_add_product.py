#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
سكريبت اختبار إضافة منتج
Test script for adding a product
"""

import requests
from bs4 import BeautifulSoup

BASE_URL = "http://localhost:8080"

def login():
    """تسجيل الدخول"""
    session = requests.Session()
    
    # GET login page to get CSRF token
    print("📝 جاري تسجيل الدخول...")
    response = session.get(f"{BASE_URL}/auth/login")
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Find CSRF token
    csrf_token = soup.find('input', {'name': 'csrf_token'})
    if csrf_token:
        csrf_token = csrf_token.get('value')
    
    # Login
    login_data = {
        'username': 'admin',
        'password': 'admin123',
        'csrf_token': csrf_token,
        'remember': 'on'
    }
    
    response = session.post(f"{BASE_URL}/auth/login", data=login_data, allow_redirects=True)
    
    print(f"Status: {response.status_code}, URL: {response.url}")
    
    if (response.status_code == 200 or response.status_code == 302) and ('dashboard' in response.url or 'admin' in response.url):
        print("✅ تم تسجيل الدخول بنجاح")
        return session
    else:
        print(f"❌ فشل تسجيل الدخول - Status: {response.status_code}")
        print(f"URL: {response.url}")
        return None

def get_csrf_token(session, url):
    """الحصول على CSRF token من الصفحة"""
    response = session.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    csrf_token = soup.find('input', {'name': 'csrf_token'})
    if csrf_token:
        return csrf_token.get('value')
    return None

def add_product(session):
    """إضافة منتج جديد"""
    print("\n📦 جاري إضافة منتج جديد...")
    
    # Get create product page and CSRF token
    create_url = f"{BASE_URL}/products/create"
    csrf_token = get_csrf_token(session, create_url)
    
    if not csrf_token:
        print("❌ لم يتم العثور على CSRF token")
        return False
    
    print(f"🔑 CSRF Token: {csrf_token[:20]}...")
    
    # Product data
    product_data = {
        'csrf_token': csrf_token,
        'name': 'منتج تجريبي - Test Product',
        'name_ar': 'منتج تجريبي',
        'sku': 'TEST-001',
        'barcode': '1234567890123',
        'category_id': 0,  # بدون تصنيف
        'regular_price': 100.00,
        'merchant_price': 90.00,
        'partner_price': 85.00,
        'cost_price': 75.00,
        'current_stock': 50,
        'min_stock_alert': 10,
        'unit': 'piece',
        'location': 'A1',
        'description': 'هذا منتج تجريبي للاختبار',
        'notes': 'تم إضافته بواسطة سكريبت الاختبار'
    }
    
    print("\n📋 بيانات المنتج:")
    for key, value in product_data.items():
        if key != 'csrf_token':
            print(f"   - {key}: {value}")
    
    # Submit the form
    print("\n📤 جاري إرسال البيانات...")
    response = session.post(create_url, data=product_data, allow_redirects=True)
    
    print(f"\n📊 النتيجة:")
    print(f"   - Status Code: {response.status_code}")
    print(f"   - Final URL: {response.url}")
    
    # Check if success
    if response.status_code == 200:
        if 'products' in response.url and 'create' not in response.url:
            print("✅ تم إضافة المنتج بنجاح!")
            print(f"   - تم التوجيه إلى: {response.url}")
            return True
        elif 'create' in response.url:
            print("⚠️ ما زلنا في صفحة الإضافة - قد يكون هناك خطأ في التحقق")
            
            # Check for error messages in response
            soup = BeautifulSoup(response.text, 'html.parser')
            alerts = soup.find_all('div', class_=['alert', 'alert-danger', 'alert-warning'])
            
            if alerts:
                print("\n❌ رسائل الخطأ:")
                for alert in alerts:
                    print(f"   - {alert.get_text(strip=True)}")
            
            return False
    else:
        print(f"❌ فشلت العملية - Status Code: {response.status_code}")
        return False

def main():
    """Main function"""
    print("="*70)
    print("🧪 سكريبت اختبار إضافة منتج")
    print("   Test Script for Adding Product")
    print("="*70)
    
    # Login
    session = login()
    if not session:
        print("\n❌ فشل تسجيل الدخول - إنهاء الاختبار")
        return
    
    # Add product
    success = add_product(session)
    
    # Summary
    print("\n" + "="*70)
    if success:
        print("✅ الاختبار نجح - تم إضافة المنتج")
    else:
        print("❌ الاختبار فشل - لم يتم إضافة المنتج")
    print("="*70)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ حدث خطأ: {str(e)}")
        import traceback
        traceback.print_exc()

