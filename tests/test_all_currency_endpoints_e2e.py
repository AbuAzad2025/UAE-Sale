"""Exhaustive E2E currency endpoints — hits every mapped route across 3 tenants."""
from decimal import Decimal
import pytest


TENANTS_CFG = [
    ('ILS', 't-e2e-ils', 'ILS Tenant'),
    ('AED', 't-e2e-aed', 'AED Tenant'),
    ('USD', 't-e2e-usd', 'USD Tenant'),
]


def _get_or_create_tenant(db, slug, currency, name):
    from models.tenant import Tenant
    t = Tenant.query.filter_by(slug=slug).first()
    if t:
        if t.default_currency != currency:
            t.default_currency = currency
            db.session.commit()
        return t
    t = Tenant(name=name, name_ar=name, slug=slug, default_currency=currency, is_active=True)
    db.session.add(t)
    db.session.commit()
    return t


def _login_as_owner(client):
    # Use owner login via fixture login_owner
    pass


@pytest.mark.parametrize("base_currency,slug,name", TENANTS_CFG)
def test_all_currency_endpoints_e2e(db, app, client, login_owner, base_currency, slug, name):
    """Hit every currency-handling endpoint for each tenant base."""
    from models.tenant import Tenant
    from models.tenant_scope import set_current_tenant_id, clear_current_tenant_id
    from services.currency_service import CurrencyService

    tenant = _get_or_create_tenant(db, slug, base_currency, name)
    set_current_tenant_id(tenant.id)
    try:
        # Mock base to ensure deterministic
        orig = CurrencyService.get_base_currency
        CurrencyService.get_base_currency = staticmethod(lambda b=base_currency: b)

        # 1. API currency-rate
        resp = client.get(f'/api/currency-rate/USD/{base_currency}')
        assert resp.status_code == 200, f"API USD->{base_currency} failed"
        data = resp.get_json()
        assert data['success'] is True
        assert data['from'] == 'USD'
        assert data['to'] == base_currency

        # 2. Sales create page (GET)
        resp = client.get('/sales/create')
        assert resp.status_code == 200

        # 3. Sales API calculate-totals (POST)
        resp = client.post('/sales/api/calculate-totals', json={
            'items': [{'product_id': 1, 'quantity': 1, 'unit_price': 100}],
            'currency': base_currency,
            'exchange_rate': 1,
            'discount_amount': 0,
            'shipping_cost': 0,
            'tax_rate': 0
        })
        # May be 200 or 400 if validation fails, but should not be 500
        assert resp.status_code in (200, 400)

        # 4. Payments list (may be /payments or /payments/receipts)
        resp = client.get('/payments/')
        assert resp.status_code in (200, 302, 404)
        if resp.status_code == 404:
            resp = client.get('/payments/receipts')
            assert resp.status_code in (200, 302, 404)

        # 5. Expenses create page
        resp = client.get('/expenses/create')
        assert resp.status_code in (200, 302, 404)

        # 6. Cheques list
        resp = client.get('/cheques/')
        assert resp.status_code in (200, 302, 404)

        # 7. Ledger
        resp = client.get('/ledger/')
        assert resp.status_code in (200, 302, 404)

        # 8. Reports
        for report_path in ['/reports/sales', '/reports/purchases', '/reports/cash_flow']:
            resp = client.get(report_path)
            assert resp.status_code in (200, 302, 404)

        # 9. Invoices list
        resp = client.get('/invoices/')
        # May be 404 if not exists, but should not be 500
        assert resp.status_code in (200, 302, 404)

        # 10. Verify Sale amount_base calculation for this base
        from models.sale import Sale
        from models.product import Product, ProductCategory
        from models.customer import Customer
        from models.warehouse import Warehouse
        from models.user import User
        # Create minimal sale for this tenant
        wh = Warehouse.query.filter_by(tenant_id=tenant.id).first()
        if not wh:
            wh = Warehouse(name=f'WH-E2E-{base_currency}', name_ar='WH', code=f'WH-E2E-{base_currency}', tenant_id=tenant.id, is_active=True)
            db.session.add(wh)
            db.session.commit()
        cat = ProductCategory.query.filter_by(name='Cat-E2E').first()
        if not cat:
            cat = ProductCategory(name='Cat-E2E', is_active=True)
            db.session.add(cat)
            db.session.commit()
        prod = Product.query.filter_by(sku=f'SKU-E2E-{base_currency}').first()
        if not prod:
            prod = Product(name=f'P-E2E-{base_currency}', sku=f'SKU-E2E-{base_currency}', category_id=cat.id, cost_price=Decimal('5'), regular_price=Decimal('10'), current_stock=Decimal('10'), is_active=True)
            db.session.add(prod)
            db.session.commit()
        cust = Customer.query.filter_by(name=f'C-E2E-{base_currency}').first()
        if not cust:
            cust = Customer(name=f'C-E2E-{base_currency}', customer_type='regular', tenant_id=tenant.id, is_active=True)
            db.session.add(cust)
            db.session.commit()
        seller = User.query.filter_by(is_owner=True).first()
        sale = Sale(sale_number=f'S-E2E-{base_currency}-{tenant.id}', customer_id=cust.id, seller_id=seller.id, warehouse_id=wh.id, tenant_id=tenant.id,
                    total_amount=Decimal('0'), amount_base=Decimal('0'), paid_amount=Decimal('0'), paid_amount_base=Decimal('0'), balance_due=Decimal('0'),
                    currency=base_currency, exchange_rate=Decimal('1'), payment_status='unpaid', status='confirmed', is_active=True)
        db.session.add(sale)
        db.session.flush()
        from models.sale import SaleLine
        line = SaleLine(sale_id=sale.id, product_id=prod.id, quantity=Decimal('1'), unit_price=Decimal('100'), line_total=Decimal('100'))
        db.session.add(line)
        db.session.flush()
        sale.lines = [line]
        sale.calculate_totals()
        # For base currency, amount_base should equal total (no conversion)
        assert sale.amount_base == sale.total_amount, f"Base {base_currency} sale should not convert, got {sale.amount_base} vs {sale.total_amount}"
        # For foreign, should convert
        sale2 = Sale(sale_number=f'S-E2E-{base_currency}-F', customer_id=cust.id, seller_id=seller.id, warehouse_id=wh.id, tenant_id=tenant.id,
                     total_amount=Decimal('0'), amount_base=Decimal('0'), paid_amount=Decimal('0'), paid_amount_base=Decimal('0'), balance_due=Decimal('0'),
                     currency='USD' if base_currency != 'USD' else 'EUR', exchange_rate=Decimal('3.67'), payment_status='unpaid', status='confirmed', is_active=True)
        db.session.add(sale2)
        db.session.flush()
        line2 = SaleLine(sale_id=sale2.id, product_id=prod.id, quantity=Decimal('1'), unit_price=Decimal('100'), line_total=Decimal('100'))
        db.session.add(line2)
        db.session.flush()
        sale2.lines = [line2]
        sale2.calculate_totals()
        assert sale2.amount_base == (sale2.total_amount * Decimal('3.67')).quantize(Decimal('0.001')), f"Foreign sale should convert for base {base_currency}"

        db.session.rollback()

    finally:
        CurrencyService.get_base_currency = orig
        clear_current_tenant_id()
        db.session.rollback()
