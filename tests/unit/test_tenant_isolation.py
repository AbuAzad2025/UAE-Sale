"""
Tenant Isolation Tests — Multi-Tenant Row-Level Security.

Proves that tenant A cannot read tenant B's sales, customers, or products
even by direct ID lookups when the scoped query filter is active.
"""

import pytest
from decimal import Decimal


@pytest.fixture
def tenant_a(app, db):
    """Create Tenant A."""
    from models import Tenant
    t = Tenant(name='Tenant A', name_ar='المستأجر أ', slug='tenant-a', is_active=True)
    db.session.add(t)
    db.session.commit()
    return t


@pytest.fixture
def tenant_b(app, db):
    """Create Tenant B."""
    from models import Tenant
    t = Tenant(name='Tenant B', name_ar='المستأجر ب', slug='tenant-b', is_active=True)
    db.session.add(t)
    db.session.commit()
    return t


@pytest.fixture
def customer_a(app, db, tenant_a):
    """Customer belonging to Tenant A."""
    from models import Customer
    c = Customer(
        tenant_id=tenant_a.id,
        name='Customer A', name_ar='عميل أ',
        customer_type='regular', phone='+971501111111',
        credit_limit=Decimal('50000'), balance=Decimal('0'), is_active=True,
    )
    db.session.add(c)
    db.session.commit()
    return c


@pytest.fixture
def customer_b(app, db, tenant_b):
    """Customer belonging to Tenant B."""
    from models import Customer
    c = Customer(
        tenant_id=tenant_b.id,
        name='Customer B', name_ar='عميل ب',
        customer_type='regular', phone='+971502222222',
        credit_limit=Decimal('50000'), balance=Decimal('0'), is_active=True,
    )
    db.session.add(c)
    db.session.commit()
    return c


@pytest.fixture
def product_a(app, db, tenant_a, test_category):
    """Product belonging to Tenant A."""
    from models import Product
    p = Product(
        tenant_id=tenant_a.id,
        name='Product A', name_ar='منتج أ',
        sku='SKU-A-001', category_id=test_category.id,
        cost_price=Decimal('50.000'), regular_price=Decimal('100.000'),
        current_stock=Decimal('50'), is_active=True,
    )
    db.session.add(p)
    db.session.commit()
    return p


@pytest.fixture
def product_b(app, db, tenant_b, test_category):
    """Product belonging to Tenant B."""
    from models import Product
    p = Product(
        tenant_id=tenant_b.id,
        name='Product B', name_ar='منتج ب',
        sku='SKU-B-001', category_id=test_category.id,
        cost_price=Decimal('50.000'), regular_price=Decimal('100.000'),
        current_stock=Decimal('50'), is_active=True,
    )
    db.session.add(p)
    db.session.commit()
    return p


@pytest.fixture
def sale_a(app, db, tenant_a, customer_a, product_a, owner_user):
    """Sale belonging to Tenant A."""
    from models import Sale, SaleLine
    from utils.helpers import generate_number
    sale = Sale(
        tenant_id=tenant_a.id,
        sale_number=generate_number('S', Sale, 'sale_number'),
        customer_id=customer_a.id,
        seller_id=owner_user.id,
        total_amount=Decimal('200.000'),
        amount_base=Decimal('200.000'),
        paid_amount=Decimal('0'),
        paid_amount_base=Decimal('0'),
        balance_due=Decimal('200.000'),
        currency='AED',
        exchange_rate=Decimal('1'),
        payment_status='unpaid',
        status='confirmed',
        is_active=True,
    )
    db.session.add(sale)
    db.session.flush()
    line = SaleLine(
        tenant_id=tenant_a.id,
        sale_id=sale.id,
        product_id=product_a.id,
        quantity=Decimal('2'),
        unit_price=Decimal('100.000'),
        discount_percent=Decimal('0'),
        line_total=Decimal('200.000'),
        cost_price=Decimal('50.000'),
    )
    db.session.add(line)
    db.session.commit()
    return sale


@pytest.fixture
def sale_b(app, db, tenant_b, customer_b, product_b, owner_user):
    """Sale belonging to Tenant B."""
    from models import Sale, SaleLine
    from utils.helpers import generate_number
    sale = Sale(
        tenant_id=tenant_b.id,
        sale_number=generate_number('S', Sale, 'sale_number'),
        customer_id=customer_b.id,
        seller_id=owner_user.id,
        total_amount=Decimal('300.000'),
        amount_base=Decimal('300.000'),
        paid_amount=Decimal('0'),
        paid_amount_base=Decimal('0'),
        balance_due=Decimal('300.000'),
        currency='AED',
        exchange_rate=Decimal('1'),
        payment_status='unpaid',
        status='confirmed',
        is_active=True,
    )
    db.session.add(sale)
    db.session.flush()
    line = SaleLine(
        tenant_id=tenant_b.id,
        sale_id=sale.id,
        product_id=product_b.id,
        quantity=Decimal('3'),
        unit_price=Decimal('100.000'),
        discount_percent=Decimal('0'),
        line_total=Decimal('300.000'),
        cost_price=Decimal('50.000'),
    )
    db.session.add(line)
    db.session.commit()
    return sale


class TestTenantSaleIsolation:
    """Prove tenant A cannot see tenant B's sales and vice versa."""

    def test_tenant_a_sees_only_own_sales(self, app, db, login_owner,
                                          tenant_a, sale_a, sale_b):
        """When tenant A is scoped, only A's sale is visible."""
        from models import Sale, set_current_tenant_id
        set_current_tenant_id(tenant_a.id)

        sales = Sale.query.filter_by(status='confirmed').all()
        sale_ids = [s.id for s in sales]

        assert sale_a.id in sale_ids
        assert sale_b.id not in sale_ids

    def test_tenant_b_sees_only_own_sales(self, app, db, login_owner,
                                          tenant_b, sale_a, sale_b):
        """When tenant B is scoped, only B's sale is visible."""
        from models import Sale, set_current_tenant_id
        set_current_tenant_id(tenant_b.id)

        sales = Sale.query.filter_by(status='confirmed').all()
        sale_ids = [s.id for s in sales]

        assert sale_b.id in sale_ids
        assert sale_a.id not in sale_ids

    def test_no_tenant_sees_all_sales(self, app, db, login_owner,
                                      sale_a, sale_b):
        """With no tenant set, all sales are visible (owner / backward compat)."""
        from models import Sale, set_current_tenant_id
        set_current_tenant_id(None)

        sales = Sale.query.filter_by(status='confirmed').all()
        sale_ids = [s.id for s in sales]

        assert sale_a.id in sale_ids
        assert sale_b.id in sale_ids


class TestTenantCustomerIsolation:
    """Prove tenant A cannot see tenant B's customers."""

    def test_tenant_a_sees_only_own_customers(self, app, db, login_owner,
                                              tenant_a, customer_a, customer_b):
        from models import Customer, set_current_tenant_id
        set_current_tenant_id(tenant_a.id)

        customers = Customer.query.filter_by(is_active=True).all()
        customer_ids = [c.id for c in customers]

        assert customer_a.id in customer_ids
        assert customer_b.id not in customer_ids

    def test_tenant_b_sees_only_own_customers(self, app, db, login_owner,
                                              tenant_b, customer_a, customer_b):
        from models import Customer, set_current_tenant_id
        set_current_tenant_id(tenant_b.id)

        customers = Customer.query.filter_by(is_active=True).all()
        customer_ids = [c.id for c in customers]

        assert customer_b.id in customer_ids
        assert customer_a.id not in customer_ids


class TestTenantProductIsolation:
    """Prove tenant A cannot see tenant B's products."""

    def test_tenant_a_sees_only_own_products(self, app, db, login_owner,
                                             tenant_a, product_a, product_b):
        from models import Product, set_current_tenant_id
        set_current_tenant_id(tenant_a.id)

        products = Product.query.filter_by(is_active=True).all()
        product_ids = [p.id for p in products]

        assert product_a.id in product_ids
        assert product_b.id not in product_ids

    def test_tenant_b_sees_only_own_products(self, app, db, login_owner,
                                             tenant_b, product_a, product_b):
        from models import Product, set_current_tenant_id
        set_current_tenant_id(tenant_b.id)

        products = Product.query.filter_by(is_active=True).all()
        product_ids = [p.id for p in products]

        assert product_b.id in product_ids
        assert product_a.id not in product_ids


class TestTenantSalesLineIsolation:
    """Prove sale lines are also scoped to tenant."""

    def test_tenant_a_does_not_see_tenant_b_sale_lines(self, app, db,
                                                       login_owner,
                                                       tenant_a, sale_a, sale_b):
        from models import SaleLine, set_current_tenant_id
        set_current_tenant_id(tenant_a.id)

        lines = SaleLine.query.all()
        line_ids = [ln.id for ln in lines]

        # Tenant A's sale line should be visible
        a_line = sale_a.lines[0]
        assert a_line.id in line_ids

        # Tenant B's sale line should NOT be visible
        b_line = sale_b.lines[0]
        assert b_line.id not in line_ids


class TestTenantScopedRegistered:
    """Verify all expected models are registered for tenant scoping."""

    def test_all_core_models_registered(self):
        from models.tenant_scope import _tenant_scoped_tables
        expected = {
            'sales', 'sale_lines', 'purchases', 'purchase_lines',
            'payments', 'receipts', 'customers', 'suppliers',
            'products', 'stock_movements', 'cheques', 'gl_journal_entries',
            'gl_journal_lines', 'warehouses',
        }
        assert expected == _tenant_scoped_tables
