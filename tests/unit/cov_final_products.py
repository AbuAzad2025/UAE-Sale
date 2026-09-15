"""Backend test coverage for routes/products.py"""
import pytest
from decimal import Decimal

from models import User, Role, Permission, Product, ProductCategory
from extensions import db as _db


@pytest.fixture(scope='function')
def owner_user_with_permissions(db):
    """Create an owner user with all standard permissions."""
    perms = [
        Permission(code='manage_products', name='Manage Products', category='products'),
        Permission(code='manage_inventory', name='Manage Inventory', category='inventory'),
        Permission(code='manage_purchases', name='Manage Purchases', category='purchases'),
        Permission(code='view_reports', name='View Reports', category='reports'),
    ]
    db.session.add_all(perms)
    db.session.flush()

    role = Role(
        name='Owner', name_ar='المالك', slug='owner',
        permissions=perms
    )
    db.session.add(role)
    db.session.flush()

    owner = User(
        username='testowner', email='owner@test.com', full_name='Test Owner',
        is_owner=True, is_active=True, role_id=role.id
    )
    owner.set_password('OwnerPass123!')
    db.session.add(owner)
    db.session.commit()
    return owner


@pytest.fixture(scope='function')
def category(db):
    """Create a test category."""
    cat = ProductCategory(name='Electronics', name_ar='إلكترونيات', is_active=True)
    db.session.add(cat)
    db.session.commit()
    return cat


@pytest.fixture(scope='function')
def product(db, category):
    """Create a test product."""
    prod = Product(
        name='Test Laptop', name_ar='لابتست اختباري',
        sku='SKU-LAPTOP-001', category_id=category.id,
        cost_price=Decimal('500.000'), regular_price=Decimal('1000.000'),
        current_stock=Decimal('50'), min_stock_alert=Decimal('5'),
        is_active=True,
    )
    db.session.add(prod)
    db.session.commit()
    return prod


class TestProductsRoutes:
    """Test products routes."""

    def test_products_page(self, client, owner_user_with_permissions):
        """Test products page loads."""
        client.post('/auth/login', data={
            'username': 'testowner', 'password': 'OwnerPass123!',
        }, follow_redirects=True)
        resp = client.get('/products/')
        assert resp.status_code == 200

    def test_product_detail_page(self, client, owner_user_with_permissions, product):
        """Test product detail page loads."""
        client.post('/auth/login', data={
            'username': 'testowner', 'password': 'OwnerPass123!',
        }, follow_redirects=True)
        resp = client.get(f'/products/{product.id}')
        assert resp.status_code == 200

    def test_products_api(self, client, owner_user_with_permissions):
        """Test products API search endpoint (exists at /products/api/search with type=products)."""
        client.post('/auth/login', data={
            'username': 'testowner', 'password': 'OwnerPass123!',
        }, follow_redirects=True)
        resp = client.get('/products/api/search', query_string={'q': 'Laptop', 'type': 'products'})
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)