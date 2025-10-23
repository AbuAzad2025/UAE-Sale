#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
اختبار مباشر لإضافة منتج عبر Flask Shell
Direct test for adding product via Flask Shell
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import after adding to path
from extensions import db
from flask import Flask

# Create app instance
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///instance/app.db'
app.config['SECRET_KEY'] = 'dev-secret-key'
db.init_app(app)
from models.product import Product, ProductCategory
from models.user import User
from utils.audit import create_audit_log
import random

def test_add_product():
    """اختبار إضافة منتج مباشرة"""
    with app.app_context():
        print("="*70)
        print("🧪 اختبار إضافة منتج مباشر")
        print("="*70)
        
        # Check if admin user exists
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            print("❌ المستخدم admin غير موجود")
            return False
        
        print(f"✅ تم العثور على المستخدم: {admin.username}")
        
        # Generate unique SKU
        sku = f"TEST-{random.randint(1000, 9999)}"
        
        # Create product
        print(f"\n📦 جاري إنشاء منتج بـ SKU: {sku}")
        
        try:
            product = Product(
                name=f"منتج تجريبي {sku}",
                name_ar=f"منتج تجريبي {sku}",
                sku=sku,
                barcode=f"123456789{random.randint(1000, 9999)}",
                category_id=None,
                regular_price=100.00,
                merchant_price=90.00,
                partner_price=85.00,
                cost_price=75.00,
                current_stock=50,
                min_stock_alert=10,
                unit='piece',
                location='A1-TEST',
                description='منتج تجريبي للاختبار',
                notes='تم إضافته بواسطة test_product_direct.py'
            )
            
            print(f"\n📋 بيانات المنتج:")
            print(f"   - الاسم: {product.name}")
            print(f"   - SKU: {product.sku}")
            print(f"   - السعر العادي: {product.regular_price} AED")
            print(f"   - الكمية: {product.current_stock}")
            
            db.session.add(product)
            db.session.commit()
            
            print(f"\n✅ تم حفظ المنتج بنجاح!")
            print(f"   - ID: {product.id}")
            print(f"   - تاريخ الإنشاء: {product.created_at}")
            
            # Create audit log
            create_audit_log('create', 'products', product.id, user_id=admin.id)
            print(f"   - تم إنشاء سجل التدقيق")
            
            # Verify product exists
            saved_product = Product.query.get(product.id)
            if saved_product:
                print(f"\n✅ تم التحقق: المنتج موجود في قاعدة البيانات")
                print(f"   - الاسم المحفوظ: {saved_product.name}")
                print(f"   - SKU المحفوظ: {saved_product.sku}")
                return True
            else:
                print(f"\n❌ خطأ: المنتج غير موجود بعد الحفظ!")
                return False
                
        except Exception as e:
            db.session.rollback()
            print(f"\n❌ حدث خطأ أثناء إضافة المنتج:")
            print(f"   - {str(e)}")
            import traceback
            traceback.print_exc()
            return False

if __name__ == "__main__":
    try:
        success = test_add_product()
        print("\n" + "="*70)
        if success:
            print("✅ الاختبار نجح - المنتج تم إضافته وحفظه")
        else:
            print("❌ الاختبار فشل")
        print("="*70)
    except Exception as e:
        print(f"\n❌ خطأ عام: {str(e)}")
        import traceback
        traceback.print_exc()

