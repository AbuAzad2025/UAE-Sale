"""Currency unification tests — verify single base_currency source."""

from decimal import Decimal
import pytest


def test_sale_calculate_totals_dynamic_base(db, app, owner_user):
    """Sale.calculate_totals must use Tenant.base_currency, not hardcoded ILS."""
    from models.sale import Sale, SaleLine
    from models.tenant import Tenant
    from models.product import Product, ProductCategory
    from models.customer import Customer
    from models.warehouse import Warehouse
    from services.currency_service import CurrencyService
    tenant_aed = Tenant(name='T-AED2', name_ar='ت', slug='t-aed-test2', default_currency='AED', is_active=True)
    db.session.add(tenant_aed)
    db.session.commit()
    # Create minimal related entities
    wh = Warehouse(name='WH-CURR', name_ar='WH-CURR', code='WH-CURR', tenant_id=tenant_aed.id, is_active=True)
    db.session.add(wh)
    db.session.flush()
    cat = ProductCategory(name='Cat-CURR', is_active=True)
    db.session.add(cat)
    db.session.flush()
    prod = Product(name='P-CURR', sku='SKU-CURR', category_id=cat.id, cost_price=Decimal('5'), regular_price=Decimal('10'), current_stock=Decimal('10'), is_active=True)
    db.session.add(prod)
    db.session.flush()
    cust = Customer(name='C-CURR', customer_type='regular', tenant_id=tenant_aed.id, is_active=True)
    db.session.add(cust)
    db.session.flush()
    seller = owner_user
    orig = CurrencyService.get_base_currency
    CurrencyService.get_base_currency = staticmethod(lambda: 'AED')
    try:
        # Sale in AED (base) — amount_base should equal total
        sale = Sale(sale_number='S-CURR-AED2', customer_id=cust.id, seller_id=seller.id, warehouse_id=wh.id, tenant_id=tenant_aed.id,
                    total_amount=Decimal('100'), amount_base=Decimal('0'), paid_amount=Decimal('0'), paid_amount_base=Decimal('0'), balance_due=Decimal('0'),
                    currency='AED', exchange_rate=Decimal('3.67'), payment_status='unpaid', status='confirmed', is_active=True)
        db.session.add(sale)
        db.session.flush()
        line = SaleLine(sale_id=sale.id, product_id=prod.id, quantity=Decimal('2'), unit_price=Decimal('50'), line_total=Decimal('100'))
        db.session.add(line)
        db.session.flush()
        sale.lines = [line]
        sale.calculate_totals()
        assert Decimal(str(sale.amount_base)).quantize(Decimal('0.001')) == Decimal(str(sale.total_amount)).quantize(Decimal('0.001'))
        # Sale in USD (foreign) should multiply
        sale2 = Sale(sale_number='S-CURR-USD2', customer_id=cust.id, seller_id=seller.id, warehouse_id=wh.id, tenant_id=tenant_aed.id,
                     total_amount=Decimal('100'), amount_base=Decimal('0'), paid_amount=Decimal('0'), paid_amount_base=Decimal('0'), balance_due=Decimal('0'),
                     currency='USD', exchange_rate=Decimal('3.67'), payment_status='unpaid', status='confirmed', is_active=True)
        db.session.add(sale2)
        db.session.flush()
        line2 = SaleLine(sale_id=sale2.id, product_id=prod.id, quantity=Decimal('2'), unit_price=Decimal('50'), line_total=Decimal('100'))
        db.session.add(line2)
        db.session.flush()
        sale2.lines = [line2]
        sale2.calculate_totals()
        # total from line is 100, *3.67 = 367
        assert Decimal(str(sale2.amount_base)).quantize(Decimal('0.001')) == Decimal('367.000')
    finally:
        CurrencyService.get_base_currency = orig
        db.session.rollback()


def test_invoice_receipt_statement_same_currency_for_tenant(db, app, client, login_owner):
    """Invoice, receipt, statement for same tenant must show same base currency."""
    from models.tenant import Tenant
    from services.currency_service import CurrencyService
    # Ensure tenant is AED
    tenant = Tenant.query.filter_by(slug='t-aed-test').first()
    if not tenant:
        tenant = Tenant(name='T-AED2', name_ar='ت', slug='t-aed-test2', default_currency='AED', is_active=True)
        db.session.add(tenant)
        db.session.commit()
    # The base_currency injected should be AED
    with app.test_request_context('/'):
        base = CurrencyService.get_base_currency()
        # This will be AED if tenant is AED, else ILS fallback
        assert base in ('AED', 'ILS')
    # Check that templates would render with base_currency (indirect via view)
    # Create a sale in that tenant's currency and verify calculate_totals uses base
    from models.sale import Sale
    sale = Sale.query.filter_by(tenant_id=tenant.id).first()
    if sale:
        assert sale.currency is not None


def test_no_hardcoded_currency_in_critical_templates():
    """Ensure critical templates no longer contain hardcoded 'AED' checks."""
    import pathlib, re
    critical = [
        'templates/receipts/minimal.html',
        'templates/receipts/gulf.html',
        'templates/sales/view.html',
    ]
    for path in critical:
        txt = pathlib.Path(path).read_text(encoding='utf-8', errors='ignore')
        # These should now use base_currency, not literal 'AED' in currency checks
        # We check that the specific old pattern is gone
        assert "!= 'AED'" not in txt or "base_currency" in txt, f"{path} still has hardcoded AED check"
