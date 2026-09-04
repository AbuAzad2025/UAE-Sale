from datetime import datetime, timezone
from extensions import db


def _number(model, attr, prefix):
    from utils.helpers import generate_number
    return generate_number(prefix, model, attr)


def create_customer(name, phone=None, address=None):
    from models.customer import Customer
    customer = Customer(
        name=name,
        name_ar=name,
        phone=phone,
        address=address,
        customer_type='regular',
        balance=0,
        is_active=True,
    )
    db.session.add(customer)
    db.session.commit()
    return customer


def create_product(name, part_number=None, regular_price=0, current_stock=0):
    from models.product import Product
    product = Product(
        name=name,
        name_ar=name,
        part_number=part_number,
        regular_price=regular_price,
        current_stock=current_stock,
        unit='قطعة',
        is_active=True,
    )
    db.session.add(product)
    db.session.commit()
    return product


def create_sale(customer_id, product_id, quantity, seller_id):
    from models.sale import Sale, SaleLine
    from models.product import Product

    product = Product.query.get(product_id)
    if product is None:
        raise ValueError('المنتج غير موجود')

    total = product.regular_price * quantity

    sale = Sale(
        sale_number=_number(Sale, 'sale_number', 'INV'),
        customer_id=customer_id,
        seller_id=seller_id,
        total_amount=total,
        amount_base=total,
        subtotal=total,
        paid_amount=0,
        paid_amount_base=0,
        balance_due=total,
        currency='AED',
        exchange_rate=1,
        payment_status='unpaid',
        status='confirmed',
        is_active=True,
    )
    db.session.add(sale)
    db.session.flush()

    line = SaleLine(
        sale_id=sale.id,
        product_id=product_id,
        quantity=quantity,
        unit_price=product.regular_price,
        line_total=total,
    )
    db.session.add(line)

    product.current_stock -= quantity
    db.session.commit()
    return sale


def record_payment(customer_id, amount, method, direction, user_id, payment_type):
    from models.payment import Payment

    sign = -1 if direction == 'outgoing' else 1
    amount = abs(amount)

    payment = Payment(
        payment_number=_number(Payment, 'payment_number', 'PAY'),
        payment_type=payment_type,
        direction=direction,
        customer_id=customer_id,
        amount=amount,
        amount_base=sign * amount,
        currency='AED',
        exchange_rate=1,
        payment_method=method,
        payment_date=datetime.now(timezone.utc),
        user_id=user_id,
        payment_confirmed=True,
    )
    db.session.add(payment)
    db.session.commit()
    return payment


def _default_expense_category():
    from models.expense import ExpenseCategory
    category = ExpenseCategory.query.filter_by(is_active=True).first()
    if category is None:
        category = ExpenseCategory(name='عام', name_ar='عام', is_active=True)
        db.session.add(category)
        db.session.flush()
    return category


def create_expense(description, amount, user_id):
    from models.expense import Expense

    amount = abs(amount)
    category = _default_expense_category()

    expense = Expense(
        expense_number=_number(Expense, 'expense_number', 'EXP'),
        description=description,
        description_ar=description,
        amount=amount,
        amount_base=amount,
        category_id=category.id,
        payment_method='cash',
        user_id=user_id,
    )
    db.session.add(expense)
    db.session.commit()
    return expense


def create_supplier(name, phone=None, email=None, address=None, tax_number=None):
    from models.supplier import Supplier
    supplier = Supplier(
        name=name,
        name_ar=name,
        phone=phone,
        email=email,
        address=address,
        tax_number=tax_number,
        is_active=True,
    )
    db.session.add(supplier)
    db.session.commit()
    return supplier


def create_purchase(supplier_id, product_id, quantity, unit_cost, user_id):
    from models.purchase import Purchase, PurchaseLine
    from models.product import Product
    from models.supplier import Supplier

    product = Product.query.get(product_id)
    if product is None:
        raise ValueError('المنتج غير موجود')

    supplier = Supplier.query.get(supplier_id)
    total = unit_cost * quantity

    purchase = Purchase(
        purchase_number=_number(Purchase, 'purchase_number', 'PUR'),
        supplier_id=supplier_id,
        supplier_name=supplier.name if supplier else None,
        total_amount=total,
        amount_base=total,
        user_id=user_id,
        status='confirmed',
    )
    db.session.add(purchase)
    db.session.flush()

    item = PurchaseLine(
        purchase_id=purchase.id,
        product_id=product_id,
        quantity=quantity,
        unit_cost=unit_cost,
        line_total=total,
    )
    db.session.add(item)

    product.current_stock += quantity
    db.session.commit()
    return purchase


def create_cheque(cheque_number, amount, due_date, cheque_type, user_id):
    from datetime import date
    from models.cheque import Cheque
    cheque = Cheque(
        cheque_number=cheque_number,
        cheque_bank_number=cheque_number,
        bank_name='بنك افتراضي',
        amount=amount,
        issue_date=date.today(),
        due_date=due_date,
        cheque_type=cheque_type,
        status='pending',
        user_id=user_id,
        is_active=True,
    )
    db.session.add(cheque)
    db.session.commit()
    return cheque


def create_user(username, password, role_slug, email=None, full_name=None):
    from models.user import User
    from models import Role

    role = Role.query.filter_by(slug=role_slug).first()
    if role is None:
        raise ValueError('الدور غير صحيح')

    user = User(
        username=username,
        email=email or f"{username}@system.local",
        full_name=full_name or username,
        role_id=role.id,
        is_owner=False,
        is_active=True,
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user
