"""
Comprehensive Seed — بذور شاملة لكل مكونات النظام (عشرات، ليس آلاف)

- منفصل تماماً عن `init_dev.py` و `utils/system_init.py` (لا يُستدعى تلقائياً)
- Idempotent: كل كيان يُفحص بـ unique قبل الإنشاء — إعادة التشغيل لا تكرر
- العدد: عشرات فقط (3 tenants / 8 warehouses / 20 products / 15 customers / 10 suppliers / 12 sales / 8 purchases / 10 payments / ...)

الاستخدام (لا يُطبق تلقائياً):
    python scripts/seed_comprehensive.py
    # أو
    flask seed-comprehensive  (إن سُجل كـ CLI)

يتطلب قاعدة نظيفة على 21_inbound_shipment (85 جدول) و owner موجود.
"""

import os
import sys
import random
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal

# Ensure project root on path when run as `python scripts/seed_comprehensive.py`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('APP_ENV', 'development')
os.environ.setdefault('SECRET_KEY', os.environ.get('SECRET_KEY', 'dev-seed-secret'))
os.environ.setdefault('OWNER_PASSWORD', os.environ.get('OWNER_PASSWORD', 'TestOwner1234567890123456'))

from app import create_app
from extensions import db

# ---------------------------------------------------------------------------
# Helpers — get_or_create
# ---------------------------------------------------------------------------

def get_or_create(model, defaults=None, **kwargs):
    inst = model.query.filter_by(**kwargs).first()
    if inst:
        return inst, False
    params = dict(kwargs)
    if defaults:
        params.update(defaults)
    inst = model(**params)
    db.session.add(inst)
    db.session.flush()
    return inst, True


def log(msg):
    print(f"[seed] {msg}")


# ---------------------------------------------------------------------------
# Seeders
# ---------------------------------------------------------------------------

def seed_tenants():
    from models.tenant import Tenant
    tenants_data = [
        dict(name='Azad Central', name_ar='أزاد المركزي', slug='azad-central', city='Dubai', country='UAE', default_currency='AED'),
        dict(name='Azad Branch Al Ain', name_ar='فرع العين', slug='azad-alain', city='Al Ain', country='UAE', default_currency='AED'),
        dict(name='Azad Branch Sharjah', name_ar='فرع الشارقة', slug='azad-sharjah', city='Sharjah', country='UAE', default_currency='AED'),
    ]
    out = []
    for d in tenants_data:
        t, created = get_or_create(Tenant, **d)
        out.append(t)
        log(f"Tenant {t.slug}: {'created' if created else 'exists'}")
    db.session.commit()
    return out


def seed_warehouses(tenants):
    from models.warehouse import Warehouse
    wh_names = [
        ('WH-Main-DXB', 'المستودع الرئيسي دبي', tenants[0].id),
        ('WH-AbuDhabi', 'مستودع أبوظبي', tenants[0].id),
        ('WH-AlAin', 'مستودع العين', tenants[1].id),
        ('WH-Sharjah', 'مستودع الشارقة', tenants[2].id),
        ('WH-Spare-1', 'مستودع قطع غيار 1', tenants[0].id),
        ('WH-Spare-2', 'مستودع قطع غيار 2', tenants[0].id),
        ('WH-Returns', 'مستودع المرتجعات', tenants[0].id),
        ('WH-Transit', 'مستودع عابر', tenants[0].id),
    ]
    out = []
    for code, name_ar, tid in wh_names:
        w, created = get_or_create(Warehouse, dict(name=name_ar, tenant_id=tid, is_active=True, code=code), code=code)
        out.append(w)
        log(f"Warehouse {code}: {'created' if created else 'exists'}")
    db.session.commit()
    return out


def seed_departments():
    from models.hr import Department
    deps = [('Sales', 'المبيعات', 'SALES'), ('Warehouse', 'المستودع', 'WH'), ('Accounting', 'المحاسبة', 'ACC'), ('HR', 'الموارد', 'HR')]
    out = []
    for name, name_ar, code in deps:
        d, created = get_or_create(Department, dict(name_ar=name_ar, is_active=True), name=name)
        if created:
            d.code = code
        out.append(d)
        log(f"Department {name}: {'created' if created else 'exists'}")
    db.session.commit()
    return out


def seed_employees(departments):
    from models.hr import Employee
    emps = [
        ('EMP-001', 'Ahmad Saleh', departments[0].id),
        ('EMP-002', 'Sara Khalid', departments[0].id),
        ('EMP-003', 'Omar Warehouse', departments[1].id),
        ('EMP-004', 'Layla Accounts', departments[2].id),
        ('EMP-005', 'Hassan HR', departments[3].id),
        ('EMP-006', 'Khaled Driver', departments[1].id),
    ]
    out = []
    for num, name, dep_id in emps:
        e, created = get_or_create(Employee, dict(full_name=name, department_id=dep_id, hire_date=date.today() - timedelta(days=random.randint(30, 400)), employment_status='active', is_active=True), employee_number=num)
        out.append(e)
        log(f"Employee {num}: {'created' if created else 'exists'}")
    db.session.commit()
    return out


def seed_users(tenants):
    from models.user import User, Role
    # Roles are already seeded by system_init; ensure they exist
    roles = {r.slug: r for r in Role.query.all()}
    users_data = [
        ('manager_dxb', 'manager@azad.local', 'Manager DXB', roles.get('manager'), tenants[0].id),
        ('seller_alain', 'seller.alain@azad.local', 'Seller Al Ain', roles.get('seller'), tenants[1].id),
        ('seller_shj', 'seller.shj@azad.local', 'Seller Sharjah', roles.get('seller'), tenants[2].id),
        ('accountant1', 'acc1@azad.local', 'Accountant One', roles.get('accountant'), tenants[0].id),
        ('cashier1', 'cashier1@azad.local', 'Cashier One', roles.get('cashier'), tenants[0].id),
        ('inventory1', 'inv1@azad.local', 'Inventory Keeper', roles.get('inventory'), tenants[0].id),
        ('hr1', 'hr1@azad.local', 'HR One', roles.get('hr'), tenants[0].id),
        ('viewer1', 'viewer1@azad.local', 'Viewer One', roles.get('viewer'), tenants[0].id),
        ('seller2', 'seller2@azad.local', 'Seller Two', roles.get('seller'), tenants[0].id),
        ('manager_shj', 'manager.shj@azad.local', 'Manager Sharjah', roles.get('manager'), tenants[2].id),
    ]
    out = []
    for username, email, full_name, role, tid in users_data:
        if not role:
            log(f"Skip user {username}: role missing")
            continue
        u, created = get_or_create(User, dict(email=email, full_name=full_name, role_id=role.id, tenant_id=tid, is_owner=False, is_active=True, email_verified=True), username=username)
        if created:
            u.set_password('Azad123!')
            log(f"User {username}: created")
        else:
            log(f"User {username}: exists")
        out.append(u)
    db.session.commit()
    return out


def seed_categories():
    from models.product import ProductCategory
    cats = ['قطع غيار محرك', 'تكييف', 'فرامل', 'كهرباء', 'إطارات']
    out = []
    for name in cats:
        c, created = get_or_create(ProductCategory, dict(is_active=True), name=name)
        out.append(c)
        log(f"Category {name}: {'created' if created else 'exists'}")
    db.session.commit()
    return out


def seed_products(categories, warehouses):
    from models.product import Product
    products_data = [
        ('فلتر زيت', 'OIL-F-001', 'BC-OIL-001', categories[0].id, Decimal('15'), Decimal('35')),
        ('فلتر هواء', 'AIR-F-002', 'BC-AIR-002', categories[0].id, Decimal('12'), Decimal('28')),
        ('كمبريسر تكييف', 'AC-COMP-003', 'BC-AC-003', categories[1].id, Decimal('180'), Decimal('420')),
        ('فحمات فرامل أمامي', 'BRAKE-F-004', 'BC-BRK-004', categories[2].id, Decimal('45'), Decimal('95')),
        ('فحمات فرامل خلفي', 'BRAKE-R-005', 'BC-BRK-005', categories[2].id, Decimal('40'), Decimal('85')),
        ('بطارية 12V', 'BATT-006', 'BC-BAT-006', categories[3].id, Decimal('110'), Decimal('220')),
        ('دينمو', 'ALT-007', 'BC-ALT-007', categories[3].id, Decimal('95'), Decimal('210')),
        ('إطار 225/60R17', 'TIRE-008', 'BC-TIRE-008', categories[4].id, Decimal('140'), Decimal('290')),
        ('إطار 195/65R15', 'TIRE-009', 'BC-TIRE-009', categories[4].id, Decimal('110'), Decimal('230')),
        ('طرمبة ماء', 'PUMP-010', 'BC-PUMP-010', categories[0].id, Decimal('55'), Decimal('125')),
        ('سير تايمن', 'BELT-011', 'BC-BELT-011', categories[0].id, Decimal('22'), Decimal('55')),
        ('بواجي طقم', 'SPARK-012', 'BC-SPARK-012', categories[0].id, Decimal('18'), Decimal('45')),
        ('مقص أمامي', 'ARM-013', 'BC-ARM-013', categories[2].id, Decimal('70'), Decimal('155')),
        ('مساعد أمامي', 'SHOCK-014', 'BC-SHOCK-014', categories[2].id, Decimal('85'), Decimal('175')),
        ('كولر زيت', 'COOLER-015', 'BC-COOLER-015', categories[0].id, Decimal('60'), Decimal('135')),
        ('فيوز طقم', 'FUSE-016', 'BC-FUSE-016', categories[3].id, Decimal('8'), Decimal('22')),
        ('لمبة أمامية', 'LAMP-017', 'BC-LAMP-017', categories[3].id, Decimal('25'), Decimal('60')),
        ('مروحة رديتر', 'FAN-018', 'BC-FAN-018', categories[0].id, Decimal('48'), Decimal('110')),
        ('رديتر', 'RAD-019', 'BC-RAD-019', categories[0].id, Decimal('130'), Decimal('280')),
        ('سلف', 'STARTER-020', 'BC-STARTER-020', categories[3].id, Decimal('105'), Decimal('235')),
    ]
    out = []
    for name, sku, barcode, cat_id, cost, price in products_data:
        p, created = get_or_create(Product, dict(name=name, category_id=cat_id, cost_price=cost, regular_price=price, current_stock=Decimal(str(random.randint(20, 80))), min_stock_alert=Decimal('5'), barcode=barcode, is_active=True), sku=sku)
        out.append(p)
        log(f"Product {sku}: {'created' if created else 'exists'}")
    db.session.commit()
    return out


def seed_customers(tenants):
    from models.customer import Customer
    customers = [
        ('شركة النور للسيارات', '0501234567', tenants[0].id),
        ('كراج الواحة', '0502345678', tenants[0].id),
        ('مركز الخليج', '0503456789', tenants[1].id),
        ('ورشة الاتحاد', '0504567890', tenants[2].id),
        ('شركة السرعة', '0505678901', tenants[0].id),
        ('كراج المدينة', '0506789012', tenants[0].id),
        ('مركز الصيانة السريعة', '0507890123', tenants[1].id),
        ('شركة التقنية', '0508901234', tenants[0].id),
        ('ورشة الأمانة', '0509012345', tenants[2].id),
        ('كراج النخيل', '0510123456', tenants[0].id),
        ('شركة الفهد', '0511234567', tenants[0].id),
        ('مركز الإمارات', '0512345678', tenants[1].id),
        ('ورشة الصقر', '0513456789', tenants[0].id),
        ('شركة المدار', '0514567890', tenants[2].id),
        ('كراج التعاون', '0515678901', tenants[0].id),
    ]
    out = []
    for name, phone, tid in customers:
        c, created = get_or_create(Customer, dict(phone=phone, tenant_id=tid, customer_type='regular', is_active=True), name=name)
        out.append(c)
        log(f"Customer {name}: {'created' if created else 'exists'}")
    db.session.commit()
    return out


def seed_suppliers(tenants):
    from models.supplier import Supplier
    suppliers = [
        ('المورد المتحدة للقطع', '0551112222', tenants[0].id),
        ('شركة الخليج للتجارة', '0552223333', tenants[0].id),
        ('مورد أبوظبي', '0553334444', tenants[1].id),
        ('مورد الشارقة', '0554445555', tenants[2].id),
        ('العالمية للسيارات', '0555556666', tenants[0].id),
        ('شركة النور للتوريد', '0556667777', tenants[0].id),
        ('مؤسسة الفهد', '0557778888', tenants[0].id),
        ('شركة السرعة للقطع', '0558889999', tenants[1].id),
        ('المورد السريع', '0559990000', tenants[0].id),
        ('شركة الإمارات للقطع', '0550001111', tenants[2].id),
    ]
    out = []
    for name, phone, tid in suppliers:
        s, created = get_or_create(Supplier, dict(phone=phone, tenant_id=tid, is_active=True), name=name)
        out.append(s)
        log(f"Supplier {name}: {'created' if created else 'exists'}")
    db.session.commit()
    return out


def seed_sales(customers, products, warehouses, seller):
    from models.sale import Sale, SaleLine
    from utils.helpers import generate_number
    out = []
    for i in range(12):
        cust = random.choice(customers)
        wh = random.choice(warehouses)
        # check existence by sale_number pattern
        sale_number = f"S-SEED-{i+1:03d}"
        existing = Sale.query.filter_by(sale_number=sale_number).first()
        if existing:
            log(f"Sale {sale_number}: exists")
            out.append(existing)
            continue
        sale = Sale(
            sale_number=sale_number,
            customer_id=cust.id, seller_id=seller.id, warehouse_id=wh.id, tenant_id=cust.tenant_id,
            total_amount=Decimal('0'), amount_base=Decimal('0'), paid_amount=Decimal('0'), paid_amount_base=Decimal('0'), balance_due=Decimal('0'),
            currency='AED', exchange_rate=Decimal('1'), payment_status='unpaid', status='confirmed', is_active=True
        )
        db.session.add(sale)
        db.session.flush()
        # 2-3 lines per sale
        chosen = random.sample(products, k=random.randint(2, 3))
        for p in chosen:
            qty = Decimal(str(random.randint(1, 4)))
            price = p.regular_price
            line = SaleLine(sale_id=sale.id, product_id=p.id, quantity=qty, unit_price=price, line_total=qty*price, cost_price=p.cost_price)
            db.session.add(line)
        sale.calculate_totals()
        # minimal: mark half as paid
        if i % 2 == 0:
            sale.paid_amount = sale.total_amount
            sale.paid_amount_base = sale.amount_base
            sale.balance_due = Decimal('0')
            sale.payment_status = 'paid'
        db.session.commit()
        log(f"Sale {sale_number}: created ({len(chosen)} lines)")
        out.append(sale)
    return out


def seed_purchases(suppliers, products, warehouses, user):
    from models.purchase import Purchase, PurchaseLine
    out = []
    for i in range(8):
        sup = random.choice(suppliers)
        wh = random.choice(warehouses)
        num = f"P-SEED-{i+1:03d}"
        existing = Purchase.query.filter_by(purchase_number=num).first()
        if existing:
            log(f"Purchase {num}: exists")
            out.append(existing)
            continue
        pur = Purchase(purchase_number=num, supplier_id=sup.id, warehouse_id=wh.id, tenant_id=sup.tenant_id, total_amount=Decimal('0'), amount_base=Decimal('0'), status='confirmed', is_active=True)
        db.session.add(pur)
        db.session.flush()
        chosen = random.sample(products, k=random.randint(2, 3))
        for p in chosen:
            qty = Decimal(str(random.randint(5, 15)))
            cost = p.cost_price
            line = PurchaseLine(purchase_id=pur.id, product_id=p.id, quantity=qty, unit_cost=cost, line_total=qty*cost)
            db.session.add(line)
        pur.calculate_totals()
        db.session.commit()
        log(f"Purchase {num}: created")
        out.append(pur)
    return out


def seed_payments(sales, customers):
    from models.payment import Payment
    # create 10 payments for first 10 sales
    for idx, sale in enumerate(sales[:10]):
        num = f"PAY-SEED-{idx+1:03d}"
        existing = Payment.query.filter_by(payment_number=num).first()
        if existing:
            log(f"Payment {num}: exists")
            continue
        cust = sale.customer
        pay = Payment(
            payment_number=num, payment_type='sale_payment', direction='incoming',
            sale_id=sale.id, customer_id=cust.id, tenant_id=sale.tenant_id,
            amount=sale.total_amount, amount_base=sale.amount_base, currency='AED', exchange_rate=Decimal('1'),
            payment_method=random.choice(['cash','bank_transfer','card'])
        )
        db.session.add(pay)
        log(f"Payment {num}: created")
    db.session.commit()


def seed_cheques(customers):
    from models.cheque import Cheque
    for i in range(5):
        num = f"CHQ-SEED-{i+1:03d}"
        existing = Cheque.query.filter_by(cheque_number=num).first()
        if existing:
            log(f"Cheque {num}: exists")
            continue
        cust = random.choice(customers)
        ch = Cheque(cheque_number=num, customer_id=cust.id, amount=Decimal(str(random.randint(500, 2000))), cheque_date=date.today() + timedelta(days=random.randint(10, 60)), status='pending', cheque_type='incoming', is_active=True, tenant_id=cust.tenant_id)
        db.session.add(ch)
        log(f"Cheque {num}: created")
    db.session.commit()


def seed_expenses():
    from models.expense import Expense, ExpenseCategory
    cat, _ = get_or_create(ExpenseCategory, dict(is_active=True), name='مصاريف تشغيلية')
    for i in range(6):
        num = f"EXP-SEED-{i+1:03d}"
        existing = Expense.query.filter_by(expense_number=num).first()
        if existing:
            log(f"Expense {num}: exists")
            continue
        exp = Expense(expense_number=num, category_id=cat.id, amount=Decimal(str(random.randint(200, 1500))), expense_date=date.today() - timedelta(days=random.randint(1, 30)), status='approved', is_active=True, description=f'مصروف تجريبي {i+1}')
        db.session.add(exp)
        log(f"Expense {num}: created")
    db.session.commit()


def seed_shipments_and_inbound(warehouses, products):
    from services.shipment_service import ShipmentService
    from services.inbound_shipment_service import InboundShipmentService
    # 3 outbound shipments
    for i in range(3):
        wh = random.choice(warehouses)
        dest = random.choice(['موقع العين الميداني', 'موقع الشارقة المتنقل', 'موقع دبي الصناعية'])
        # check by shipment_number pattern (service generates SH-...)
        # we create via service which generates unique number, so idempotent by counting existing
        existing_count = __import__('models.shipment', fromlist=['Shipment']).Shipment.query.count()
        if existing_count >= 3:
            log("Outbound shipments: already 3+ exists, skip")
            break
        p = random.choice(products)
        ShipmentService.create_shipment(from_warehouse_id=wh.id, destination_name=dest, lines_data=[{'product_id': p.id, 'quantity': random.randint(2, 5), 'unit_cost': float(p.cost_price or 5)}])
        log(f"Outbound shipment {i+1}: created")
    # 3 inbound shipments
    for i in range(3):
        wh = random.choice(warehouses)
        from models.inbound_shipment import InboundShipment
        if InboundShipment.query.count() >= 3:
            log("Inbound shipments: already 3+ exists, skip")
            break
        p = random.choice(products)
        InboundShipmentService.create_shipment(warehouse_id=wh.id, lines_data=[{'product_id': p.id, 'quantity_expected': random.randint(5, 15), 'unit_cost': float(p.cost_price or 5)}])
        log(f"Inbound shipment {i+1}: created")
    db.session.commit()


def main():
    app = create_app()
    with app.app_context():
        log("Starting comprehensive seed (idempotent, dozens only)...")
        # Ensure base roles/permissions/owner exist (system_init already did, but ensure)
        from utils.system_init import ensure_system_integrity
        os.environ['SYSTEM_INTEGRITY_FORCE'] = '1'
        ensure_system_integrity(app)
        os.environ.pop('SYSTEM_INTEGRITY_FORCE', None)

        tenants = seed_tenants()
        warehouses = seed_warehouses(tenants)
        deps = seed_departments()
        seed_employees(deps)
        users = seed_users(tenants)
        cats = seed_categories()
        products = seed_products(cats, warehouses)
        customers = seed_customers(tenants)
        suppliers = seed_suppliers(tenants)

        # Pick a seller for sales (first seller)
        from models.user import User
        seller = User.query.filter(User.username.like('seller%')).first() or User.query.filter_by(is_owner=True).first()
        sales = seed_sales(customers, products, warehouses, seller)
        purchases = seed_purchases(suppliers, products, warehouses, seller)
        seed_payments(sales, customers)
        seed_cheques(customers)
        seed_expenses()
        seed_shipments_and_inbound(warehouses, products)

        log("Seed complete — counts:")
        from models import Tenant, Customer, Supplier, Product, Sale, Purchase, Payment
        from models.warehouse import Warehouse
        from models.shipment import Shipment
        from models.inbound_shipment import InboundShipment
        log(f"  Tenants: {Tenant.query.count()}, Warehouses: {Warehouse.query.count()}, Products: {Product.query.count()}")
        log(f"  Customers: {Customer.query.count()}, Suppliers: {Supplier.query.count()}")
        log(f"  Sales: {Sale.query.count()}, Purchases: {Purchase.query.count()}, Payments: {Payment.query.count()}")
        log(f"  Shipments: {Shipment.query.count()}, Inbound: {InboundShipment.query.count()}")
        log("Done. Re-running is safe (idempotent).")


if __name__ == '__main__':
    main()
