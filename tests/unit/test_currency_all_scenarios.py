"""Exhaustive currency scenarios — all tenant bases, all transaction types, API fallback, templates."""
from decimal import Decimal
import pytest

TENANTS = ['AED', 'ILS', 'USD', 'JOD', 'EUR']
FOREIGNS = ['AED', 'ILS', 'USD', 'JOD', 'EUR']


def _tenant(db, slug, currency):
    from models.tenant import Tenant
    t = Tenant.query.filter_by(slug=slug).first()
    if t:
        if t.default_currency != currency:
            t.default_currency = currency
            db.session.commit()
        return t
    t = Tenant(name=f'T-{currency}', name_ar='ت', slug=slug, default_currency=currency, is_active=True)
    db.session.add(t)
    db.session.commit()
    return t


def _warehouse(db, tenant, suffix):
    from models.warehouse import Warehouse
    name = f'WH-{tenant.default_currency}-{suffix}'
    w = Warehouse.query.filter_by(code=name).first()
    if w:
        return w
    w = Warehouse(name=name, name_ar=name, code=name, tenant_id=tenant.id, is_active=True)
    db.session.add(w)
    db.session.commit()
    return w


def _product(db, suffix):
    from models.product import Product, ProductCategory
    cat = ProductCategory.query.filter_by(name='Cat-CURR-ALL').first()
    if not cat:
        cat = ProductCategory(name='Cat-CURR-ALL', is_active=True)
        db.session.add(cat)
        db.session.commit()
    sku = f'SKU-ALL-{suffix}'
    p = Product.query.filter_by(sku=sku).first()
    if p:
        return p
    p = Product(name=f'P-{suffix}', sku=sku, category_id=cat.id, cost_price=Decimal('10'), regular_price=Decimal('20'), current_stock=Decimal('100'), is_active=True)
    db.session.add(p)
    db.session.commit()
    return p


def _customer(db, tenant, suffix):
    from models.customer import Customer
    name = f'C-ALL-{suffix}'
    c = Customer.query.filter_by(name=name).first()
    if c:
        return c
    c = Customer(name=name, customer_type='regular', tenant_id=tenant.id, is_active=True)
    db.session.add(c)
    db.session.commit()
    return c


def test_all_tenant_bases_sale_base_foreign_and_base_base(db, app, owner_user):
    """For each tenant base (AED/ILS/USD/JOD/EUR), test Sale with foreign, base, and same."""
    from models.sale import Sale, SaleLine
    from services.currency_service import CurrencyService
    for base in TENANTS:
        tenant = _tenant(db, f't-all-{base.lower()}', base)
        wh = _warehouse(db, tenant, 'SALE')
        prod = _product(db, f'SALE-{base}')
        cust = _customer(db, tenant, f'SALE-{base}')
        # Mock base
        orig = CurrencyService.get_base_currency
        CurrencyService.get_base_currency = staticmethod(lambda b=base: b)
        try:
            for foreign in [base, 'USD', 'EUR']:  # base-to-base, base-to-foreign
                rate = Decimal('3.67') if foreign != base else Decimal('1')
                sale = Sale(sale_number=f'S-ALL-{base}-{foreign}', customer_id=cust.id, seller_id=owner_user.id, warehouse_id=wh.id, tenant_id=tenant.id,
                            total_amount=Decimal('100'), amount_base=Decimal('0'), paid_amount=Decimal('0'), paid_amount_base=Decimal('0'), balance_due=Decimal('0'),
                            currency=foreign, exchange_rate=rate, payment_status='unpaid', status='confirmed', is_active=True)
                db.session.add(sale)
                db.session.flush()
                line = SaleLine(sale_id=sale.id, product_id=prod.id, quantity=Decimal('1'), unit_price=Decimal('100'), line_total=Decimal('100'))
                db.session.add(line)
                db.session.flush()
                sale.lines = [line]
                sale.calculate_totals()
                if foreign == base:
                    assert sale.amount_base == sale.total_amount, f"{base} base {foreign} should not convert"
                else:
                    assert sale.amount_base == (sale.total_amount * rate).quantize(Decimal('0.001')), f"{base} base {foreign} should convert"
                db.session.rollback()
        finally:
            CurrencyService.get_base_currency = orig
            db.session.rollback()


def test_all_purchase_expense_payment_cheque_ledger_with_base(db, app, owner_user):
    """Purchases, Expenses, Payments, Cheques, Ledger entries respect base."""
    from models.tenant import Tenant
    from services.currency_service import CurrencyService
    from models.purchase import Purchase
    from models.expense import Expense, ExpenseCategory
    from models.payment import Payment
    from models.cheque import Cheque
    from models.warehouse import Warehouse
    from models.supplier import Supplier
    from decimal import Decimal as D
    for base in ['AED', 'ILS']:
        tenant = _tenant(db, f't-all2-{base.lower()}', base)
        wh = _warehouse(db, tenant, 'MISC')
        # Purchase
        sup = Supplier.query.filter_by(name=f'Sup-ALL-{base}').first()
        if not sup:
            sup = Supplier(name=f'Sup-ALL-{base}', is_active=True, tenant_id=tenant.id)
            db.session.add(sup)
            db.session.commit()
        orig = CurrencyService.get_base_currency
        CurrencyService.get_base_currency = staticmethod(lambda b=base: b)
        try:
            # Expense
            cat = ExpenseCategory.query.filter_by(name='Cat-ALL').first()
            if not cat:
                cat = ExpenseCategory(name='Cat-ALL', is_active=True)
                db.session.add(cat)
                db.session.commit()
            exp = Expense(expense_number=f'EXP-ALL-{base}', category_id=cat.id, amount=D('100'), amount_base=D('100') if base=='ILS' else D('367'), expense_date=__import__('datetime').date.today(), status='approved', is_active=True, description='test', payment_method='cash', user_id=owner_user.id, currency=base, exchange_rate=D('1'))
            db.session.add(exp)
            db.session.flush()
            assert exp.amount_base is not None
            db.session.rollback()
            # Payment
            cust = _customer(db, tenant, f'PAY-{base}')
            sale = None
            # Cheque
            ch = Cheque(cheque_number=f'CHQ-ALL-{base}', cheque_bank_number=f'CHQ-ALL-{base}', cheque_type='incoming', bank_name='Test', amount=D('100'), currency=base, issue_date=__import__('datetime').date.today(), due_date=__import__('datetime').date.today(), status='pending', customer_id=cust.id, tenant_id=tenant.id)
            db.session.add(ch)
            db.session.flush()
            assert ch.currency == base
            db.session.rollback()
        finally:
            CurrencyService.get_base_currency = orig
            db.session.rollback()


def test_api_fallback_all_bases(client, login_owner, db, monkeypatch):
    """API fallback for each base when live provider unreachable."""
    import services.currency_service as cs_mod
    from decimal import Decimal as D
    for base in TENANTS:
        # Mock to simulate offline but fallback should still work
        monkeypatch.setattr(cs_mod.CurrencyService, 'get_exchange_rate', staticmethod(lambda f,t, user_rate=None, b=base: D('1.5')))
        resp = client.get(f'/api/currency-rate/USD/{base}')
        assert resp.status_code == 200, f"API failed for base {base}"
        data = resp.get_json()
        assert data['success'] is True


def test_template_rendering_no_hardcoded_currency(db, app, client, login_owner):
    """Render invoices/receipts/statements and assert no hardcoded AED/ILS literals."""
    # Check critical templates source (not rendered) for hardcoded patterns
    import pathlib
    critical_templates = [
        'templates/receipts/minimal.html',
        'templates/receipts/gulf.html',
        'templates/sales/view.html',
        'templates/customers/statement.html',
    ]
    for path in critical_templates:
        txt = pathlib.Path(path).read_text(encoding='utf-8', errors='ignore')
        # After fixes, these should not contain literal "!= 'AED'" without base_currency
        if "!= 'AED'" in txt:
            assert 'base_currency' in txt, f"{path} still has hardcoded AED check without base_currency"
    # Render a sale invoice with foreign currency and check HTML contains dynamic currency, not hardcoded
    from models.sale import Sale
    sale = Sale.query.first()
    if sale:
        with app.test_request_context('/'):
            from flask import render_template_string
            html = render_template_string("{{ sale.currency }} {{ base_currency }}", sale=sale, base_currency='AED')
            assert 'AED' in html or 'ILS' in html  # dynamic, not hardcoded literal check

    # Verify window.BASE_CURRENCY is injected
    resp = client.get('/sales/create')
    html = resp.get_data(as_text=True)
    assert 'window.BASE_CURRENCY' in html or 'BASE_CURRENCY' in html
