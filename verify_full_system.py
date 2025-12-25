
import os
import sys
from decimal import Decimal
from datetime import datetime, date, timedelta
from flask import Flask
from config import Config
from extensions import db
from services.gl_service import GLService
from services.stock_service import StockService
from services.advanced_analytics import AdvancedFinancialAnalytics

# Setup Flask App for Testing
class TestConfig(Config):
    db_path = os.path.join(os.getcwd(), 'test_full_system.db')
    SQLALCHEMY_DATABASE_URI = f'sqlite:///{db_path}'
    TESTING = True
    SQLALCHEMY_ENGINE_OPTIONS = {}
    SECRET_KEY = 'test-secret'

app = Flask(__name__)
app.config.from_object(TestConfig)
db.init_app(app)

def setup_database():
    with app.app_context():
        db.create_all()
        # Ensure GL Accounts exist
        GLService.ensure_core_accounts()
        print("✅ Database setup complete.")

def create_mock_data():
    from models import User, Role, Customer, Supplier, Product, ProductCategory, Warehouse, ExpenseCategory, GLAccount
    
    # 0. Role
    role = Role.query.filter_by(slug='admin').first()
    if not role:
        role = Role(name='Admin', slug='admin', description='Administrator')
        db.session.add(role)
        db.session.flush() # Get ID

    # 1. User
    user = User.query.first()
    if not user:
        user = User(username='admin', email='admin@test.com', role_id=role.id)
        user.set_password('password')
        db.session.add(user)
        db.session.commit()
    
    # 2. Warehouse
    warehouse = Warehouse.query.first()
    if not warehouse:
        warehouse = Warehouse(name='Main Warehouse', is_active=True, is_main=True)
        db.session.add(warehouse)
    
    # 3. Customer
    customer = Customer.query.filter_by(name='Test Customer').first()
    if not customer:
        customer = Customer(name='Test Customer', balance=0)
        db.session.add(customer)
    
    # 4. Supplier
    supplier = Supplier.query.filter_by(name='Test Supplier').first()
    if not supplier:
        supplier = Supplier(name='Test Supplier', total_purchases_aed=0, total_paid_aed=0)
        db.session.add(supplier)
        
    # 5. Product Category
    category = ProductCategory.query.filter_by(name='General').first()
    if not category:
        category = ProductCategory(name='General')
        db.session.add(category)
    db.session.commit() # Commit to get ID
    
    # 6. Product
    product = Product.query.filter_by(sku='TEST-001').first()
    if not product:
        product = Product(
            name='Test Product',
            sku='TEST-001',
            regular_price=150, # Selling Price
            cost_price=100,    # Cost Price
            category_id=category.id,
            current_stock=0
        )
        db.session.add(product)
        
    # 7. Expense Category
    exp_cat = ExpenseCategory.query.filter_by(name='Rent').first()
    if not exp_cat:
        exp_cat = ExpenseCategory(name='Rent', gl_account_code='6200') # 6200 is Rent
        db.session.add(exp_cat)

    db.session.commit()
    print("✅ Mock data created.")
    return user, customer, supplier, product, warehouse, exp_cat

def simulate_purchase(supplier, product, warehouse, quantity=10, cost=100):
    """
    Simulates a purchase:
    1. Update Stock (Increase)
    2. GL Entry: Debit Inventory (1140), Credit AP (2110)
    3. Update Supplier Balance
    """
    print(f"\n--- Simulating Purchase of {quantity} units @ {cost} AED ---")
    
    from models import Purchase, PurchaseLine, User
    
    user = User.query.first()
    total_amount = Decimal(quantity) * Decimal(cost)
    
    # 1. Create Purchase Record
    purchase = Purchase(
                purchase_number=f'PUR-{datetime.now().strftime("%H%M%S")}',
                supplier_id=supplier.id,
                supplier_name=supplier.name,
                total_amount=total_amount,
                amount_aed=total_amount,
                currency='AED',
                exchange_rate=1,
                status='confirmed',
                warehouse_id=warehouse.id,
                purchase_date=datetime.now(),
                user_id=user.id
            )
    db.session.add(purchase)
    db.session.flush()
    
    line = PurchaseLine(
        purchase_id=purchase.id,
        product_id=product.id,
        quantity=quantity,
        unit_cost=cost,
        line_total=total_amount
    )
    db.session.add(line)
    db.session.flush()
    
    # 2. Process Stock (Increase)
    StockService.process_purchase_lines(purchase)
    
    # 3. Post GL Entry
    lines = [
        {'account': '1140', 'debit': total_amount, 'description': f'Purchase Stock {product.name}'}, # Inventory
        {'account': '2110', 'credit': total_amount, 'description': f'Payable to {supplier.name}'}   # AP
    ]
    GLService.post_entry(lines, description=f'Purchase {purchase.purchase_number}', reference_type='Purchase', reference_id=purchase.id)
    
    # 4. Update Supplier Stats
    supplier.total_purchases_aed += total_amount
    
    db.session.commit()
    print("✅ Purchase processed.")

def simulate_sale(customer, product, warehouse, quantity=5, price=150):
    """
    Simulates a sale:
    1. Update Stock (Decrease)
    2. GL Entry: Debit AR (1130), Credit Sales (4100)
    3. GL Entry: Debit COGS (5100), Credit Inventory (1140)
    4. Update Customer Balance
    """
    print(f"\n--- Simulating Sale of {quantity} units @ {price} AED ---")
    
    from models import Sale, SaleLine, User
    
    user = User.query.first()
    total_amount = Decimal(quantity) * Decimal(price)
    cost_amount = Decimal(quantity) * Decimal(product.cost_price)
    
    # 1. Create Sale Record
    sale = Sale(
        sale_number=f'SALE-{datetime.now().strftime("%H%M%S")}',
        customer_id=customer.id,
        seller_id=user.id,
        total_amount=total_amount,
        amount_aed=total_amount,
        currency='AED',
        exchange_rate=1,
        status='confirmed',
        warehouse_id=warehouse.id,
        sale_date=datetime.now()
    )
    db.session.add(sale)
    db.session.flush()
    
    line = SaleLine(
        sale_id=sale.id,
        product_id=product.id,
        quantity=quantity,
        unit_price=price,
        line_total=total_amount
    )
    db.session.add(line)
    db.session.flush()
    
    # 2. Process Stock (Decrease)
    StockService.process_sale_lines(sale)
    
    # 3. Post GL Entry (Revenue)
    lines_rev = [
        {'account': '1130', 'debit': total_amount, 'description': f'Receivable from {customer.name}'}, # AR
        {'account': '4100', 'credit': total_amount, 'description': f'Sales Revenue {product.name}'}   # Revenue
    ]
    GLService.post_entry(lines_rev, description=f'Sale {sale.sale_number}', reference_type='Sale', reference_id=sale.id)
    
    # 4. Post GL Entry (COGS)
    lines_cogs = [
        {'account': '5100', 'debit': cost_amount, 'description': f'COGS {product.name}'}, # COGS
        {'account': '1140', 'credit': cost_amount, 'description': f'Inventory Decrease {product.name}'} # Inventory
    ]
    GLService.post_entry(lines_cogs, description=f'COGS {sale.sale_number}', reference_type='Sale', reference_id=sale.id)
    
    db.session.commit()
    print("✅ Sale processed.")

def simulate_expense(category, amount=500):
    """
    Simulates an expense:
    1. GL Entry: Debit Expense Account, Credit Cash/Bank
    """
    print(f"\n--- Simulating Expense {category.name} of {amount} AED ---")
    
    from models import Expense, User
    
    user = User.query.first()
    
    # 1. Create Expense Record
    expense = Expense(
        expense_number=f'EXP-{datetime.now().strftime("%H%M%S")}',
        category_id=category.id,
        description='Monthly Rent',
        amount=amount,
        amount_aed=amount,
        payment_method='cash',
        user_id=user.id
    )
    db.session.add(expense)
    db.session.flush()
    
    # 2. Post GL Entry
    lines = [
        {'account': category.gl_account_code, 'debit': amount, 'description': f'{category.name} Expense'}, # Expense
        {'account': '1110', 'credit': amount, 'description': 'Cash Payment'}   # Cash
    ]
    GLService.post_entry(lines, description=f'Expense {expense.expense_number}', reference_type='Expense', reference_id=expense.id)
    
    db.session.commit()
    print("✅ Expense processed.")

def simulate_asset_purchase(name, cost=5000):
    """
    Simulates asset purchase:
    1. GL Entry: Debit Fixed Asset, Credit Cash
    """
    print(f"\n--- Simulating Asset Purchase: {name} @ {cost} AED ---")
    
    from models import FixedAsset, GLAccount
    
    # Ensure asset accounts exist (1200 Fixed Assets -> 1240 Equipment)
    # Using 1240 for generic equipment
    
    asset_acc = GLAccount.query.filter_by(code='1240').first()
    if not asset_acc:
        print("⚠️ Asset account 1240 not found, using 1200")
        asset_acc = GLAccount.query.filter_by(code='1200').first()

    asset = FixedAsset(
        asset_number=f'AST-{datetime.now().strftime("%H%M%S")}',
        name_ar=name,
        category='equipment',
        asset_account_id=asset_acc.id,
        purchase_date=date.today(),
        purchase_price=cost,
        useful_life_years=5
    )
    db.session.add(asset)
    db.session.flush()
    
    # GL Entry
    lines = [
        {'account': asset_acc.code, 'debit': cost, 'description': f'Asset Purchase {name}'},
        {'account': '1110', 'credit': cost, 'description': 'Cash Payment for Asset'}
    ]
    GLService.post_entry(lines, description=f'Asset Purchase {asset.asset_number}', reference_type='FixedAsset', reference_id=asset.id)
    
    db.session.commit()
    print("✅ Asset processed.")

def simulate_payment_to_supplier(supplier, purchase, amount=500):
    """
    Simulates a payment to supplier:
    1. Create Payment Record
    2. Update Purchase (paid_amount, status)
    3. Update Supplier Statistics
    4. GL Entry: Debit AP (2110), Credit Cash (1110)
    """
    print(f"\n--- Simulating Payment to Supplier {supplier.name}: {amount} AED ---")
    
    from models import Payment, Cheque
    from services.gl_service import GLService
    
    # 1. Create Payment
    payment = Payment(
        payment_number=f'PAY-{datetime.now().strftime("%H%M%S")}',
        supplier_id=supplier.id,
        supplier_name=supplier.name,
        amount=Decimal(amount),
        amount_aed=Decimal(amount),
        currency='AED',
        exchange_rate=1,
        payment_method='cash',
        direction='outgoing',
        payment_type='supplier_payment',
        notes='Partial Payment for Purchase',
        payment_confirmed=True # Important for statistics
    )
    db.session.add(payment)
    db.session.flush()
    
    # 2. Update Supplier Stats
    supplier.update_statistics()
    
    # 3. GL Entry
    # Debit AP (2110), Credit Cash (1110)
    lines = [
        {'account': '2110', 'debit': Decimal(amount), 'credit': 0, 'description': f'Payment to {supplier.name}'},
        {'account': '1110', 'debit': 0, 'credit': Decimal(amount), 'description': f'Cash Payment {payment.payment_number}'}
    ]
    
    GLService.post_entry(
        lines=lines,
        description=f'Payment {payment.payment_number}',
        reference_type='Payment',
        reference_id=payment.id
    )
    
    db.session.commit()
    print("✅ Payment processed.")


def verify_system():
    print("\n\n=== SYSTEM VERIFICATION ===")
    
    from models import GLAccount, Customer, Supplier, Product, GLJournalEntry, StockMovement
    
    # DEBUG: Print all GL Entries
    print("\n--- All GL Entries ---")
    entries = GLJournalEntry.query.all()
    for entry in entries:
        print(f"Entry: {entry.entry_number} | Date: {entry.entry_date} | Type: {entry.entry_type}")
        for line in entry.lines:
             print(f"  - {line.account.code}: {line.debit} Dr / {line.credit} Cr | AED: {line.amount_aed}")
    print("----------------------\n")
    
    # DEBUG: Print all Stock Movements
    print("\n--- Stock Movements History ---")
    movements = StockMovement.query.order_by(StockMovement.created_at).all()
    calculated_stock = Decimal('0')
    for mov in movements:
        print(f"ID: {mov.id} | Type: {mov.movement_type} | Qty: {mov.quantity} | Ref: {mov.reference_type} #{mov.reference_id} | Time: {mov.created_at}")
        calculated_stock += Decimal(str(mov.quantity))
    
    print(f"Calculated Stock from Movements: {calculated_stock}")
    print("----------------------\n")

    # 1. Verify Inventory Balance (1140)
    # Purchase: +10 * 100 = +1000
    # Sale: -5 * 100 = -500 (Cost)
    # Net Inventory Value should be 500
    inventory_acc = GLAccount.query.filter_by(code='1140').first()
    inventory_bal = inventory_acc.get_balance()
    print(f"📦 Inventory GL Balance (1140): {inventory_bal} (Expected: 500.000)")
    
    product = Product.query.filter_by(sku='TEST-001').first()
    print(f"📦 Physical Stock Count: {product.current_stock} (Expected: 5.000)")
    
    if abs(inventory_bal - 500) < 0.01 and abs(product.current_stock - 5) < 0.01:
        if abs(calculated_stock - product.current_stock) < 0.01:
             print("✅ Inventory Verification PASSED (GL + Physical + Movements)")
        else:
             print(f"❌ Stock Mismatch: Physical {product.current_stock} != Calculated {calculated_stock}")
    else:
        print("❌ Inventory Verification FAILED")

    # 2. Verify Profit
    # Revenue: 5 * 150 = 750
    # COGS: 5 * 100 = 500
    # Gross Profit: 250
    # Expense: 500
    # Net Profit: 250 - 500 = -250 (Loss)
    
    ratios = AdvancedFinancialAnalytics.get_financial_ratios(date_to=date.today() + timedelta(days=1))
    net_profit = ratios['base_data']['net_profit']
    revenue = ratios['base_data']['revenue']
    expenses = ratios['base_data']['expenses'] # Should include COGS + Rent = 500 + 500 = 1000
    
    print(f"💰 Revenue: {revenue} (Expected: 750.0)")
    print(f"💸 Expenses: {expenses} (Expected: 1000.0) [COGS 500 + Rent 500]")
    print(f"📉 Net Profit: {net_profit} (Expected: -250.0)")
    
    if abs(net_profit - (-250)) < 0.01:
        print("✅ Profit Verification PASSED")
    else:
        print("❌ Profit Verification FAILED")
    
    # 3. Verify Assets
    # Inventory: 500
    # AR: 750
    # Fixed Assets: 5000
    # Cash: -500 (Rent) - 5000 (Asset) - 500 (Supplier Payment) = -6000
    # Total Assets: 500 + 750 + 5000 - 6000 = 250
    
    total_assets = ratios['base_data']['total_assets']
    print(f"🏛️ Total Assets: {total_assets} (Expected: 250.0)")
    
    if abs(total_assets - 250) < 0.01:
        print("✅ Assets Verification PASSED")
    else:
        print(f"❌ Assets Verification FAILED (Got {total_assets})")
        
    # 4. Verify Parties Balance
    customer_bal = Customer.query.first().get_balance()
    supplier_bal = Supplier.query.first().get_balance_aed()
    
    print(f"👤 Customer Balance: {customer_bal} (Expected: 750.000)")
    print(f"🏭 Supplier Balance: {supplier_bal} (Expected: 500.000)")
    
    if abs(customer_bal - 750) < 0.01 and abs(supplier_bal - 500) < 0.01:
        print("✅ Parties Balance Verification PASSED")
    else:
        print("❌ Parties Balance Verification FAILED")

if __name__ == '__main__':
    db_path = os.path.join(os.getcwd(), 'test_full_system.db')
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
            print(f"🗑️ Deleted existing DB: {db_path}")
        except PermissionError:
            print(f"⚠️ Could not delete {db_path}, it might be in use.")

    with app.app_context():
        setup_database()
        user, customer, supplier, product, warehouse, exp_cat = create_mock_data()
        
        simulate_purchase(supplier, product, warehouse, quantity=10, cost=100) # +1000 Inv, +1000 AP
        simulate_sale(customer, product, warehouse, quantity=5, price=150)     # -500 Inv, +500 COGS, +750 AR, +750 Rev
        simulate_expense(exp_cat, amount=500)                                  # +500 Exp, -500 Cash
        simulate_asset_purchase("New Laptop", cost=5000)                       # +5000 Asset, -5000 Cash

        from models import Purchase
        purchase = Purchase.query.filter_by(supplier_id=supplier.id).first()
        simulate_payment_to_supplier(supplier, purchase, amount=500)
        
        verify_system()
