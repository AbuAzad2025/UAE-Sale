#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import time
from datetime import datetime, timedelta
from decimal import Decimal
from app import create_app
from extensions import db
from models import *
from models.product import ProductCategory
from models.expense import ExpenseCategory
from services.stock_service import StockService
from services.sale_service import SaleService

app = create_app()

def print_section(title):
    print("\n" + "="*80)
    print(f"  {title}")
    print("="*80)

def test_database_connection():
    print_section("TEST 1: DATABASE CONNECTION")
    with app.app_context():
        try:
            count = db.session.execute(db.text("SELECT COUNT(*) FROM users")).scalar()
            print(f"✓ Database connected: {count} users found")
            return True
        except Exception as e:
            print(f"✗ Database error: {e}")
            return False

def test_models_integrity():
    print_section("TEST 2: MODELS INTEGRITY")
    with app.app_context():
        tests_passed = 0
        tests_total = 0
        
        models_to_check = [
            (User, 'username'),
            (Warehouse, 'name'),
            (Product, 'name'),
            (ProductCategory, 'name'),
            (Customer, 'name'),
            (Supplier, 'name'),
            (Sale, 'sale_number'),
            (Purchase, 'purchase_number'),
            (StockMovement, 'product_id'),
            (ExpenseCategory, 'name'),
        ]
        
        for model, field in models_to_check:
            tests_total += 1
            try:
                count = model.query.count()
                has_field = hasattr(model, field)
                if has_field:
                    print(f"✓ {model.__name__}: {count} records, field '{field}' exists")
                    tests_passed += 1
                else:
                    print(f"✗ {model.__name__}: field '{field}' missing")
            except Exception as e:
                print(f"✗ {model.__name__}: {e}")
        
        print(f"\nResult: {tests_passed}/{tests_total} models OK")
        return tests_passed == tests_total

def test_warehouse_system():
    print_section("TEST 3: WAREHOUSE SYSTEM")
    with app.app_context():
        try:
            warehouses = Warehouse.query.all()
            print(f"✓ Total warehouses: {len(warehouses)}")
            
            for wh in warehouses:
                print(f"  • {wh.name_ar or wh.name} [{wh.code}]")
                print(f"    - Main: {wh.is_main}, Active: {wh.is_active}")
                if wh.parent:
                    print(f"    - Parent: {wh.parent.name_ar}")
            
            main_wh = Warehouse.query.filter_by(is_main=True).first()
            if main_wh:
                print(f"\n✓ Main warehouse: {main_wh.name_ar}")
                return True
            else:
                print("\n✗ No main warehouse found!")
                return False
        except Exception as e:
            print(f"✗ Error: {e}")
            return False

def test_categories():
    print_section("TEST 4: CATEGORIES")
    with app.app_context():
        try:
            product_cats = ProductCategory.query.count()
            expense_cats = ExpenseCategory.query.count()
            
            print(f"✓ Product Categories: {product_cats}")
            print(f"✓ Expense Categories: {expense_cats}")
            
            print("\nProduct Categories:")
            for cat in ProductCategory.query.order_by(ProductCategory.sort_order).limit(10):
                print(f"  • {cat.name_ar or cat.name}")
            
            print("\nExpense Categories:")
            for cat in ExpenseCategory.query.limit(10):
                print(f"  • {cat.name_ar or cat.name}")
            
            return product_cats > 0
        except Exception as e:
            print(f"✗ Error: {e}")
            return False

def create_test_data():
    print_section("TEST 5: CREATING TEST DATA")
    with app.app_context():
        try:
            main_wh = Warehouse.query.filter_by(is_main=True).first()
            if not main_wh:
                print("✗ No main warehouse - creating one...")
                main_wh = Warehouse(
                    name='Main Warehouse',
                    name_ar='المستودع الرئيسي',
                    code='WH-MAIN',
                    location='المقر الرئيسي',
                    is_main=True,
                    is_active=True
                )
                db.session.add(main_wh)
                db.session.commit()
                print("✓ Main warehouse created")
            
            print("\n1. Creating Suppliers...")
            suppliers_data = [
                {'name': 'Global Auto Parts', 'name_ar': 'قطع غيار عالمية', 'phone': '0501234567'},
                {'name': 'Heavy Equipment Co', 'name_ar': 'شركة المعدات الثقيلة', 'phone': '0507654321'},
            ]
            suppliers = []
            for sup_data in suppliers_data:
                existing = Supplier.query.filter_by(name=sup_data['name']).first()
                if not existing:
                    supplier = Supplier(**sup_data, is_active=True)
                    db.session.add(supplier)
                    suppliers.append(supplier)
                    print(f"  ✓ {sup_data['name_ar']}")
                else:
                    suppliers.append(existing)
                    print(f"  ⊙ {sup_data['name_ar']} (exists)")
            
            print("\n2. Creating Customers...")
            customers_data = [
                {'name': 'Ahmed Construction', 'name_ar': 'أحمد للمقاولات', 'phone': '0509876543'},
                {'name': 'Dubai Transport LLC', 'name_ar': 'دبي للنقليات', 'phone': '0501122334'},
            ]
            customers = []
            for cust_data in customers_data:
                existing = Customer.query.filter_by(name=cust_data['name']).first()
                if not existing:
                    customer = Customer(**cust_data, is_active=True)
                    db.session.add(customer)
                    customers.append(customer)
                    print(f"  ✓ {cust_data['name_ar']}")
                else:
                    customers.append(existing)
                    print(f"  ⊙ {cust_data['name_ar']} (exists)")
            
            db.session.commit()
            
            print("\n3. Creating Products...")
            cat1 = ProductCategory.query.first()
            if not cat1:
                print("  ✗ No categories found!")
                return False
            
            products_data = [
                {
                    'name': 'Engine Oil 5W30',
                    'name_ar': 'زيت محرك 5W30',
                    'sku': 'OIL-5W30-001',
                    'category_id': cat1.id,
                    'cost_price': Decimal('25.00'),
                    'regular_price': Decimal('35.00'),
                    'current_stock': 0,
                    'min_stock_alert': 10,
                    'unit': 'لتر'
                },
                {
                    'name': 'Air Filter Heavy Duty',
                    'name_ar': 'فلتر هواء للمعدات الثقيلة',
                    'sku': 'FILTER-HD-001',
                    'category_id': cat1.id,
                    'cost_price': Decimal('45.00'),
                    'regular_price': Decimal('65.00'),
                    'current_stock': 0,
                    'min_stock_alert': 5,
                    'unit': 'قطعة'
                },
            ]
            
            products = []
            for prod_data in products_data:
                existing = Product.query.filter_by(sku=prod_data['sku']).first()
                if not existing:
                    product = Product(**prod_data, is_active=True)
                    db.session.add(product)
                    products.append(product)
                    print(f"  ✓ {prod_data['name_ar']}")
                else:
                    products.append(existing)
                    print(f"  ⊙ {prod_data['name_ar']} (exists)")
            
            db.session.commit()
            
            print("\n✓ Test data created successfully!")
            return True
            
        except Exception as e:
            db.session.rollback()
            print(f"✗ Error: {e}")
            import traceback
            traceback.print_exc()
            return False

def test_purchase_flow():
    print_section("TEST 6: PURCHASE FLOW")
    with app.app_context():
        try:
            main_wh = Warehouse.query.filter_by(is_main=True).first()
            supplier = Supplier.query.first()
            products = Product.query.limit(2).all()
            
            if not main_wh or not supplier or len(products) < 1:
                print("✗ Missing required data")
                return False
            
            print(f"✓ Warehouse: {main_wh.name_ar}")
            print(f"✓ Supplier: {supplier.name_ar}")
            print(f"✓ Products: {len(products)}")
            
            purchase_number = f"PUR-TEST-{int(time.time())}"
            
            purchase = Purchase(
                purchase_number=purchase_number,
                supplier_id=supplier.id,
                warehouse_id=main_wh.id,
                purchase_date=datetime.now(),
                total_amount=0,
                status='completed'
            )
            db.session.add(purchase)
            db.session.flush()
            
            total = Decimal('0')
            for i, product in enumerate(products[:2], 1):
                quantity = 10
                price = Decimal(str(product.cost_price))
                line_total = quantity * price
                total += line_total
                
                line = PurchaseLine(
                    purchase_id=purchase.id,
                    product_id=product.id,
                    quantity=quantity,
                    unit_price=price,
                    total=line_total
                )
                db.session.add(line)
                
                movement = StockMovement(
                    product_id=product.id,
                    warehouse_id=main_wh.id,
                    quantity=quantity,
                    movement_type='purchase',
                    reference_type='purchase',
                    reference_id=purchase.id,
                    notes=f'Purchase {purchase_number}'
                )
                db.session.add(movement)
                
                product.current_stock += quantity
                
                print(f"  ✓ Line {i}: {product.name_ar} x{quantity} = {line_total} AED")
            
            purchase.total_amount = total
            db.session.commit()
            
            print(f"\n✓ Purchase created: {purchase_number}")
            print(f"✓ Total: {total} AED")
            print(f"✓ Stock updated for {len(products)} products")
            
            return True
            
        except Exception as e:
            db.session.rollback()
            print(f"✗ Error: {e}")
            import traceback
            traceback.print_exc()
            return False

def test_sale_flow():
    print_section("TEST 7: SALE FLOW")
    with app.app_context():
        try:
            main_wh = Warehouse.query.filter_by(is_main=True).first()
            customer = Customer.query.first()
            user = User.query.first()
            products = Product.query.filter(Product.current_stock > 0).limit(2).all()
            
            if not main_wh or not customer or not user or len(products) < 1:
                print("✗ Missing required data")
                return False
            
            print(f"✓ Warehouse: {main_wh.name_ar}")
            print(f"✓ Customer: {customer.name_ar}")
            print(f"✓ Products in stock: {len(products)}")
            
            sale_number = f"SALE-TEST-{int(time.time())}"
            
            sale = Sale(
                sale_number=sale_number,
                customer_id=customer.id,
                warehouse_id=main_wh.id,
                seller_id=user.id,
                sale_date=datetime.now(),
                total_amount=0,
                status='completed',
                payment_status='paid'
            )
            db.session.add(sale)
            db.session.flush()
            
            total = Decimal('0')
            for i, product in enumerate(products[:2], 1):
                quantity = min(2, int(product.current_stock))
                if quantity <= 0:
                    continue
                    
                price = Decimal(str(product.regular_price))
                line_total = quantity * price
                total += line_total
                
                line = SaleLine(
                    sale_id=sale.id,
                    product_id=product.id,
                    quantity=quantity,
                    unit_price=price,
                    total=line_total
                )
                db.session.add(line)
                
                movement = StockMovement(
                    product_id=product.id,
                    warehouse_id=main_wh.id,
                    quantity=-quantity,
                    movement_type='sale',
                    reference_type='sale',
                    reference_id=sale.id,
                    notes=f'Sale {sale_number}'
                )
                db.session.add(movement)
                
                product.current_stock -= quantity
                
                print(f"  ✓ Line {i}: {product.name_ar} x{quantity} = {line_total} AED")
            
            sale.total_amount = total
            db.session.commit()
            
            print(f"\n✓ Sale created: {sale_number}")
            print(f"✓ Total: {total} AED")
            print(f"✓ Stock deducted")
            
            return True
            
        except Exception as e:
            db.session.rollback()
            print(f"✗ Error: {e}")
            import traceback
            traceback.print_exc()
            return False

def test_stock_movements():
    print_section("TEST 8: STOCK MOVEMENTS")
    with app.app_context():
        try:
            movements = StockMovement.query.order_by(StockMovement.created_at.desc()).limit(10).all()
            print(f"✓ Total movements: {StockMovement.query.count()}")
            
            print("\nRecent 10 movements:")
            for mov in movements:
                product = mov.product
                warehouse = mov.warehouse
                sign = "+" if mov.quantity > 0 else ""
                print(f"  • {product.name_ar}: {sign}{mov.quantity} @ {warehouse.name_ar}")
                print(f"    Type: {mov.movement_type}, Date: {mov.created_at.strftime('%Y-%m-%d %H:%M')}")
            
            return True
        except Exception as e:
            print(f"✗ Error: {e}")
            return False

def test_stock_accuracy():
    print_section("TEST 9: STOCK ACCURACY")
    with app.app_context():
        try:
            products = Product.query.limit(5).all()
            all_accurate = True
            
            for product in products:
                movements_sum = db.session.query(
                    db.func.sum(StockMovement.quantity)
                ).filter(
                    StockMovement.product_id == product.id
                ).scalar() or 0
                
                diff = abs(float(movements_sum) - float(product.current_stock))
                
                if diff < 0.01:
                    print(f"✓ {product.name_ar}: Stock={product.current_stock}, Movements={movements_sum}")
                else:
                    print(f"✗ {product.name_ar}: MISMATCH! Stock={product.current_stock}, Movements={movements_sum}")
                    all_accurate = False
            
            return all_accurate
        except Exception as e:
            print(f"✗ Error: {e}")
            return False

def generate_final_report():
    print_section("FINAL SYSTEM REPORT")
    with app.app_context():
        print("\n📊 DATABASE STATISTICS:")
        print("─" * 80)
        
        stats = {
            'Users': User.query.count(),
            'Warehouses': Warehouse.query.count(),
            'Product Categories': ProductCategory.query.count(),
            'Products': Product.query.count(),
            'Customers': Customer.query.count(),
            'Suppliers': Supplier.query.count(),
            'Purchases': Purchase.query.count(),
            'Sales': Sale.query.count(),
            'Stock Movements': StockMovement.query.count(),
            'Expense Categories': ExpenseCategory.query.count(),
        }
        
        for key, value in stats.items():
            print(f"  {key:.<35} {value:>5}")
        
        total_stock_value = db.session.query(
            db.func.sum(Product.current_stock * Product.cost_price)
        ).filter(Product.is_active == True).scalar() or 0
        
        print(f"\n  {'Total Stock Value':.<35} {float(total_stock_value):>10,.2f} AED")
        
        print("\n📦 WAREHOUSE BREAKDOWN:")
        print("─" * 80)
        
        for wh in Warehouse.query.filter_by(is_active=True).all():
            purchases = Purchase.query.filter_by(warehouse_id=wh.id).count()
            sales = Sale.query.filter_by(warehouse_id=wh.id).count()
            movements = StockMovement.query.filter_by(warehouse_id=wh.id).count()
            
            icon = "⭐" if wh.is_main else "📦"
            print(f"  {icon} {wh.name_ar or wh.name}")
            print(f"     Purchases: {purchases}, Sales: {sales}, Movements: {movements}")

def main():
    print("\n" + "="*80)
    print("  COMPREHENSIVE SYSTEM TEST - LOCAL SERVER")
    print("  URL: http://127.0.0.1:8080")
    print("="*80)
    
    tests = [
        ("Database Connection", test_database_connection),
        ("Models Integrity", test_models_integrity),
        ("Warehouse System", test_warehouse_system),
        ("Categories", test_categories),
        ("Test Data Creation", create_test_data),
        ("Purchase Flow", test_purchase_flow),
        ("Sale Flow", test_sale_flow),
        ("Stock Movements", test_stock_movements),
        ("Stock Accuracy", test_stock_accuracy),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
            time.sleep(0.5)
        except Exception as e:
            print(f"\n✗ Test '{name}' crashed: {e}")
            results.append((name, False))
    
    generate_final_report()
    
    print("\n" + "="*80)
    print("  TEST RESULTS SUMMARY")
    print("="*80)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {status}: {name}")
    
    print(f"\n{'='*80}")
    print(f"  Score: {passed}/{total} ({passed*100//total if total > 0 else 0}%)")
    
    if passed == total:
        print("  ✅ ALL TESTS PASSED - SYSTEM FULLY OPERATIONAL!")
    else:
        print(f"  ⚠️  {total - passed} TEST(S) FAILED")
    
    print("="*80 + "\n")
    
    return 0 if passed == total else 1

if __name__ == '__main__':
    sys.exit(main())

