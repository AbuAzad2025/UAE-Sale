"""
E2E tests for Products module - comprehensive coverage of all routes.

Route contract (routes/products.py):
  GET     /products/                     (login + manage_products)
  GET/POST /products/create              (login + manage_products) WTForms, requires warehouse_id
  GET     /products/<id>                 (login + manage_products)
  GET/POST /products/<id>/edit           (login + manage_products) WTForms
  POST    /products/<id>/delete          (login + manage_products) soft/hard delete
  GET     /products/api/search           (login + manage_products) JSON
  GET     /api/products/barcode/<code>   (login) JSON
  GET     /api/barcode/validate          (login) JSON
  GET     /products/categories           (login + manage_products)
  POST    /products/categories/create    (login + manage_products) JSON/form
  POST    /products/<id>/adjust-stock    (login + manage_products) JSON

Records seeded directly (Flask-Login binds current_user for app context lifetime).
"""

from decimal import Decimal

import pytest

from models.product import Product, ProductCategory
from models.sale import SaleLine
from models.purchase import PurchaseLine
from extensions import db


class TestProductsListAndView:
    def test_products_list_renders(self, client, login_as):
        login_as('owner')
        r = client.get('/products/')
        assert r.status_code == 200

    def test_product_view_requires_login(self, client, product):
        r = client.get(f'/products/{product.id}')
        assert r.status_code == 302
        assert '/auth/login' in r.headers.get('Location', '')

    def test_product_view_by_owner(self, client, login_as, product):
        login_as('owner')
        r = client.get(f'/products/{product.id}')
        assert r.status_code == 200

    def test_product_categories_list(self, client, login_as):
        login_as('owner')
        r = client.get('/products/categories')
        assert r.status_code == 200

    def test_create_page_renders(self, client, login_as):
        login_as('owner')
        r = client.get('/products/create')
        assert r.status_code == 200

    def test_edit_page_renders(self, client, login_as, product):
        login_as('owner')
        r = client.get(f'/products/{product.id}/edit')
        assert r.status_code == 200


class TestProductsCreate:
    def test_create_requires_warehouse(self, client, login_as, category):
        login_as('owner')
        r = client.post('/products/create', data={
            'name': 'Test Product',
            'category_id': str(category.id),
            'cost_price': '50',
            'regular_price': '100',
        })
        # missing warehouse_id -> form validation fails, re-renders
        assert r.status_code == 200

    def test_create_requires_login(self, client, category):
        r = client.post('/products/create', data={
            'name': 'Test',
            'category_id': str(category.id),
            'cost_price': '10',
            'regular_price': '20',
        })
        assert r.status_code == 302
        assert '/auth/login' in r.headers.get('Location', '')


class TestProductsEdit:
    def test_edit_page_requires_login(self, client, product):
        r = client.get(f'/products/{product.id}/edit')
        assert r.status_code == 302
        assert '/auth/login' in r.headers.get('Location', '')

    def test_edit_page_renders_for_owner(self, client, login_as, product):
        login_as('owner')
        r = client.get(f'/products/{product.id}/edit')
        assert r.status_code == 200


class TestProductsDelete:
    def test_delete_product_without_lines(self, client, login_as, category):
        login_as('owner')
        prod = Product(
            name='Deletable', name_ar='قابل للحذف',
            sku='DEL-001', cost_price=10, regular_price=20,
            category_id=category.id, current_stock=0,
            unit='piece', is_returnable=True,
        )
        db.session.add(prod)
        db.session.commit()

        r = client.post(f'/products/{prod.id}/delete')
        assert r.status_code in (302, 303)
        assert Product.query.get(prod.id) is None

    def test_delete_product_with_lines_soft_deletes(self, client, login_as, product_with_lines):
        login_as('owner')
        r = client.post(f'/products/{product_with_lines.id}/delete')
        assert r.status_code in (302, 303)
        reloaded = Product.query.get(product_with_lines.id)
        assert reloaded.is_active is False  # soft deleted


class TestProductsAdjustStock:
    def test_adjust_stock_add(self, client, login_as, product):
        login_as('owner')
        old_stock = product.current_stock
        r = client.post(f'/products/{product.id}/adjust-stock', data={
            'adjustment_type': 'add',
            'quantity': '25',
            'reason': 'receiving',
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data['success'] is True
        assert data['new_stock'] == float(old_stock + 25)

    def test_adjust_stock_subtract(self, client, login_as, product):
        login_as('owner')
        old_stock = product.current_stock
        r = client.post(f'/products/{product.id}/adjust-stock', data={
            'adjustment_type': 'subtract',
            'quantity': '20',
            'reason': 'damaged',
        })
        data = r.get_json()
        assert data['success'] is True
        assert data['new_stock'] == float(old_stock - 20)

    def test_adjust_stock_subtract_beyond_stock(self, client, login_as, product):
        login_as('owner')
        r = client.post(f'/products/{product.id}/adjust-stock', data={
            'adjustment_type': 'subtract',
            'quantity': '5000',
            'reason': 'test',
        })
        data = r.get_json()
        assert data['success'] is False

    def test_adjust_stock_set(self, client, login_as, product):
        login_as('owner')
        r = client.post(f'/products/{product.id}/adjust-stock', data={
            'adjustment_type': 'set',
            'quantity': '50',
            'reason': 'inventory count',
        })
        data = r.get_json()
        assert data['success'] is True
        assert data['new_stock'] == 50.0

    def test_adjust_stock_unknown_type_rejected(self, client, login_as, product):
        login_as('owner')
        r = client.post(f'/products/{product.id}/adjust-stock', data={
            'adjustment_type': 'teleport',
            'quantity': '10',
        })
        data = r.get_json()
        assert data['success'] is False


class TestProductsCategories:
    def test_create_category(self, client, login_as):
        login_as('owner')
        r = client.post('/products/categories/create', data={
            'name': 'New Category',
            'name_ar': 'فئة جديدة',
        })
        assert r.status_code in (302, 303)
        cat = ProductCategory.query.filter_by(name='New Category').first()
        assert cat is not None

    def test_create_category_duplicate_rejected(self, client, login_as, category):
        login_as('owner')
        r = client.post('/products/categories/create', data={
            'name': category.name,
        })
        assert r.status_code in (302, 303)
        assert ProductCategory.query.filter_by(name=category.name).count() == 1


class TestProductsApi:
    def test_api_search(self, client, login_as, product):
        login_as('owner')
        r = client.get(f'/products/api/search?q={product.sku[:3]}')
        assert r.status_code == 200
        data = r.get_json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_api_barcode_lookup(self, client, login_as, product):
        login_as('owner')
        r = client.get(f'/api/products/barcode/{product.barcode}')
        assert r.status_code == 200
        data = r.get_json()
        assert data['id'] == product.id

    def test_api_barcode_validate(self, client, login_as):
        login_as('owner')
        r = client.get('/api/barcode/validate?code=1234567890123')
        assert r.status_code == 200
        data = r.get_json()
        assert 'valid' in data


class TestProductsRbac:
    @pytest.mark.parametrize('role,allowed', [
        ('owner', True),
        ('branch_manager', True),
        ('warehouse_keeper', False),  # manage_warehouse + view_products, NOT manage_products
        ('manager', True),
        ('pos_cashier', False),
        ('senior_accountant', False),
        ('accountant', False),
        ('viewer', False),
        ('hr', False),
    ])
    def test_manage_products_gates_create_page(self, client, login_as, role, allowed):
        """Test GET /products/create - permission gate on the page."""
        login_as(role)
        r = client.get('/products/create')
        if allowed:
            assert r.status_code == 200
        else:
            assert r.status_code == 403

    @pytest.mark.parametrize('role,allowed', [
        ('owner', True),
        ('branch_manager', True),
        ('warehouse_keeper', False),
        ('manager', True),
        ('pos_cashier', False),
        ('senior_accountant', False),
        ('accountant', False),
        ('viewer', False),
        ('hr', False),
    ])
    def test_manage_products_gates_adjust_stock(self, client, login_as, product, role, allowed):
        login_as(role)
        r = client.post(f'/products/{product.id}/adjust-stock', data={
            'adjustment_type': 'add', 'quantity': '1', 'reason': 'test'
        })
        if allowed:
            assert r.status_code == 200
        else:
            assert r.status_code == 403


# Fixtures for this test module
@pytest.fixture
def category(db):
    cat = ProductCategory(name='E2E Parts', name_ar='قطع غيار', is_active=True)
    db.session.add(cat)
    db.session.commit()
    return cat


@pytest.fixture
def product(db, category, e2e_tenant):
    """Seed a product directly (no sale/purchase lines -> hard delete)."""
    prod = Product(
        name='E2E Product', name_ar='منتج E2E',
        sku='E2E-PROD-001', barcode='1234567890123',
        cost_price=Decimal('50.000'), regular_price=Decimal('100.000'),
        merchant_price=Decimal('80.000'), partner_price=Decimal('70.000'),
        category_id=category.id, current_stock=Decimal('100.000'),
        unit='piece', is_returnable=True,
        min_stock_alert=10,
    )
    prod.tenant_id = e2e_tenant.id
    db.session.add(prod)
    db.session.commit()
    return prod


@pytest.fixture
def product_with_lines(db, product, customer, owner, e2e_tenant, warehouse):
    """Seed a product WITH sale lines (so delete soft-deletes)."""
    from models.sale import Sale
    sale = Sale(
        sale_number='S-E2E-LINE', customer_id=customer.id,
        warehouse_id=warehouse.id, currency='ILS', exchange_rate=Decimal('1'),
        subtotal=Decimal('100'), tax_amount=Decimal('0'), total_amount=Decimal('100'),
        amount_base=Decimal('100'), status='confirmed', seller_id=owner.id,
    )
    sale.tenant_id = e2e_tenant.id
    db.session.add(sale)
    db.session.flush()
    db.session.add(SaleLine(
        sale_id=sale.id, product_id=product.id, quantity=Decimal('1'),
        unit_price=Decimal('100'), line_total=Decimal('100'),
    ))
    db.session.commit()
    return product