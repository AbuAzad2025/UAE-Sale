"""
E2E tests for Products module - comprehensive coverage of all routes.
Tests cover: list, create, view, edit, delete, adjust-stock, categories, api endpoints.
"""

from decimal import Decimal

import pytest

from models.product import Product, ProductCategory
from tests.e2e.harness import (
    product_adjust_form, snapshot_entry_ids,
    assert_product_stock, assert_stock_movement, q3,
)


class TestProductsListAndView:
    def test_products_list_renders(self, client, login_as):
        login_as('owner')
        r = client.get('/products/')
        assert r.status_code == 200

    def test_products_create_renders(self, client, login_as):
        login_as('owner')
        r = client.get('/products/create')
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


class TestProductsCreate:
    def test_create_product_basic(self, client, login_as, category):
        login_as('owner')
        r = client.post('/products/create', data={
            'name': 'Test Product',
            'name_ar': 'منتج اختبار',
            'sku': 'TEST-001',
            'barcode': '1234567890123',
            'category_id': str(category.id),
            'cost_price': '50',
            'regular_price': '100',
            'merchant_price': '80',
            'partner_price': '70',
            'unit': 'pcs',
            'min_stock_alert': '10',
            'country_of_origin': 'AE',
            'is_returnable': 'on',
        })
        assert r.status_code in (302, 303)
        pid = r.headers.get('Location', '').split('/')[-1]
        assert pid.isdigit()
        prod = Product.query.get(int(pid))
        assert prod is not None
        assert prod.sku == 'TEST-001'

    def test_create_product_with_discount_prices(self, client, login_as, category):
        login_as('owner')
        r = client.post('/products/create', data={
            'name': 'Discounted Product',
            'name_ar': 'منتج مخفض',
            'sku': 'DISC-001',
            'category_id': str(category.id),
            'cost_price': '40',
            'regular_price': '100',
            'merchant_price': '80',
            'partner_price': '70',
            'unit': 'pcs',
            'min_stock_alert': '5',
        })
        assert r.status_code in (302, 303)
        pid = r.headers.get('Location', '').split('/')[-1]
        prod = Product.query.get(int(pid))
        assert prod.merchant_price == Decimal('80.000')
        assert prod.partner_price == Decimal('70.000')

    def test_create_product_duplicate_sku_rejected(self, client, login_as, product):
        login_as('owner')
        before = Product.query.count()
        r = client.post('/products/create', data={
            'name': 'Duplicate',
            'name_ar': 'مكرر',
            'sku': product.sku,  # duplicate
            'category_id': str(product.category_id),
            'cost_price': '10',
            'regular_price': '20',
        })
        assert r.status_code == 200  # re-renders form
        assert Product.query.count() == before

    def test_create_product_invalid_cost_price_rejected(self, client, login_as, category):
        login_as('owner')
        r = client.post('/products/create', data={
            'name': 'Invalid',
            'name_ar': 'غير صالح',
            'sku': 'INV-001',
            'category_id': str(category.id),
            'cost_price': '-10',
            'regular_price': '20',
        })
        assert r.status_code == 200  # re-renders form


class TestProductsEdit:
    def test_edit_product_updates_fields(self, client, login_as, product):
        login_as('owner')
        r = client.post(f'/products/{product.id}/edit', data={
            'name': 'Updated Product',
            'name_ar': 'منتج محدث',
            'sku': product.sku,
            'category_id': str(product.category_id),
            'cost_price': '60',
            'regular_price': '120',
        })
        assert r.status_code in (302, 303)
        product.refresh()
        assert product.name == 'Updated Product'

    def test_edit_product_not_found(self, client, login_as):
        login_as('owner')
        r = client.post('/products/999999/edit', data={})
        assert r.status_code == 404


class TestProductsDelete:
    def test_delete_product_without_sales(self, client, login_as, category):
        login_as('owner')
        # Create a product with no sales
        prod = Product(
            name='Deletable', name_ar='قابل للحذف',
            sku='DEL-001', cost_price=10, regular_price=20,
            category_id=category.id
        )
        from extensions import db
        db.session.add(prod)
        db.session.commit()
        
        r = client.post(f'/products/{prod.id}/delete')
        assert r.status_code in (302, 303)
        assert Product.query.get(prod.id) is None

    def test_delete_product_with_sales_is_blocked(self, client, login_as, product):
        login_as('owner')
        r = client.post(f'/products/{product.id}/delete')
        assert r.status_code == 200  # re-renders with error
        assert 'cannot delete' in r.get_data(as_text=True).lower()


class TestProductsAdjustStock:
    def test_adjust_stock_add(self, client, login_as, product):
        login_as('owner')
        r = client.post(f'/products/{product.id}/adjust-stock', data={
            'adjustment_type': 'add',
            'quantity': '25',
            'reason': 'receiving',
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data['success'] is True
        assert data['new_stock'] == 125

    def test_adjust_stock_subtract(self, client, login_as, product):
        login_as('owner')
        r = client.post(f'/products/{product.id}/adjust-stock', data={
            'adjustment_type': 'subtract',
            'quantity': '20',
            'reason': 'damaged',
        })
        data = r.get_json()
        assert data['success'] is True
        assert data['new_stock'] == 80

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
        assert data['new_stock'] == 50

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
            'description': 'Test',
        })
        assert r.status_code in (302, 303)
        cat = ProductCategory.query.filter_by(name='New Category').first()
        assert cat is not None

    def test_edit_category(self, client, login_as, category):
        login_as('owner')
        r = client.post(f'/products/categories/{category.id}/edit', data={
            'name': 'Updated Category',
            'name_ar': 'فئة محدثة',
        })
        assert r.status_code in (302, 303)
        category.refresh()
        assert category.name == 'Updated Category'


class TestProductsApi:
    def test_api_search(self, client, login_as, product):
        login_as('owner')
        r = client.get(f'/products/api/search?q={product.sku[:3]}')
        assert r.status_code == 200
        data = r.get_json()
        assert len(data['products']) >= 1

    def test_api_barcode_lookup(self, client, login_as, product):
        login_as('owner')
        r = client.get(f'/api/products/barcode/{product.barcode}')
        assert r.status_code == 200
        data = r.get_json()
        assert data['product']['id'] == product.id

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
        ('warehouse_keeper', True),
        ('pos_cashier', False),
        ('senior_accountant', False),
    ])
    def test_manage_products_gates_product_creation(
            self, client, db, users, login_as, category, role, allowed):
        login_as(role)
        before = Product.query.count()
        r = client.post('/products/create', data={
            'name': 'Test', 'name_ar': 'اختبار', 'sku': 'RBAC-001',
            'category_id': str(category.id), 'cost_price': '10', 'regular_price': '20',
        })
        if allowed:
            assert r.status_code in (302, 303)
        else:
            assert r.status_code == 403
            assert Product.query.count() == before


# Fixtures for this test module
@pytest.fixture
def category(db):
    cat = ProductCategory(name='E2E Parts', name_ar='قطع غيار', is_active=True)
    db.session.add(cat)
    db.session.commit()
    return cat