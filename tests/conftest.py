"""
Shared test fixtures for the UAE-Sale ERP system.

Auto-detects PostgreSQL (CI) vs SQLite (local):
- PostgreSQL: uses flask db upgrade via Alembic for full schema
- SQLite: uses db.create_all() for fast in-memory tests
"""

import os
import pytest
from datetime import datetime, timezone
from decimal import Decimal

# Force test environment before importing app
os.environ.setdefault('APP_ENV', 'testing')
os.environ.setdefault('SECRET_KEY', 'test-secret-key-not-for-production')
os.environ.setdefault('OWNER_PASSWORD', 'TestOwner@1234567890123456!')
os.environ.setdefault('DEBUG', 'true')
os.environ.setdefault('WTF_CSRF_ENABLED', 'false')
os.environ.setdefault('RATELIMIT_ENABLED', 'false')
os.environ.setdefault('RATELIMIT_STORAGE_URI', 'memory://')
os.environ.setdefault('CACHE_TYPE', 'simple')

# If DATABASE_URL not set, default to SQLite for local development
if 'DATABASE_URL' not in os.environ:
    os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from app import create_app
from extensions import db as _db
from models import User, Role, Permission, Customer, Product, ProductCategory, Sale, SaleLine

IS_POSTGRES = os.environ.get('DATABASE_URL', '').startswith('postgresql')


@pytest.fixture(scope='session')
def app():
    """Create application for testing."""
    app = create_app()
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['SERVER_NAME'] = 'localhost'
    app.config['RATELIMIT_ENABLED'] = False
    app.config['RATELIMIT_DEFAULT'] = '10000 per day'
    app.config['RATELIMIT_STORAGE_URI'] = 'memory://'

    if not IS_POSTGRES:
        # SQLite: clear pool settings that SQLite doesn't support
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {}

    return app


@pytest.fixture(scope='function')
def db(app):
    """Create a fresh database for each test.

    PostgreSQL: creates all tables via SQLAlchemy metadata (fast).
    SQLite: in-memory, same approach.
    """
    with app.app_context():
        _db.create_all()
        yield _db
        _db.session.rollback()
        _db.drop_all()


@pytest.fixture(scope='function')
def client(app, db):
    """Create a test client with fresh DB."""
    with app.test_client() as client:
        with app.app_context():
            yield client


@pytest.fixture(scope='function')
def owner_user(db):
    """Create an owner user for testing."""
    perms = [
        Permission(code='manage_sales', name='Manage Sales', category='sales'),
        Permission(code='manage_customers', name='Manage Customers', category='customers'),
        Permission(code='manage_products', name='Manage Products', category='products'),
        Permission(code='manage_purchases', name='Manage Purchases', category='purchases'),
        Permission(code='manage_suppliers', name='Manage Suppliers', category='suppliers'),
        Permission(code='manage_users', name='Manage Users', category='users'),
        Permission(code='manage_payments', name='Manage Payments', category='payments'),
        Permission(code='manage_expenses', name='Manage Expenses', category='expenses'),
        Permission(code='manage_warehouse', name='Manage Warehouse', category='warehouse'),
        Permission(code='view_ledger', name='View Ledger', category='ledger'),
        Permission(code='view_reports', name='View Reports', category='reports'),
        Permission(code='manage_backups', name='Manage Backups', category='backups'),
    ]
    db.session.add_all(perms)
    db.session.flush()

    owner_role = Role(
        name='Owner', name_ar='المالك', slug='owner', permissions=perms
    )
    db.session.add(owner_role)
    db.session.flush()

    owner = User(
        username='testowner', email='owner@test.com', full_name='Test Owner',
        is_owner=True, is_active=True, role_id=owner_role.id,
    )
    owner.set_password('OwnerPass123!')
    db.session.add(owner)
    db.session.commit()
    return owner


@pytest.fixture(scope='function')
def seller_user(db, owner_user):
    """Create a seller user for testing."""
    seller_perms = [
        Permission.query.filter_by(code='manage_sales').first(),
        Permission.query.filter_by(code='manage_customers').first(),
        Permission.query.filter_by(code='manage_products').first(),
    ]
    seller_perms = [p for p in seller_perms if p is not None]

    seller_role = Role(
        name='Seller', name_ar='بائع', slug='seller', permissions=seller_perms
    )
    db.session.add(seller_role)
    db.session.flush()

    seller = User(
        username='testseller', email='seller@test.com', full_name='Test Seller',
        is_owner=False, is_active=True, role_id=seller_role.id,
    )
    seller.set_password('SellerPass123!')
    db.session.add(seller)
    db.session.commit()
    return seller


@pytest.fixture(scope='function')
def manager_user(db, owner_user):
    """Create a manager user for testing."""
    manager_perms = [
        Permission.query.filter_by(code='manage_sales').first(),
        Permission.query.filter_by(code='manage_customers').first(),
        Permission.query.filter_by(code='manage_products').first(),
        Permission.query.filter_by(code='manage_purchases').first(),
        Permission.query.filter_by(code='manage_payments').first(),
        Permission.query.filter_by(code='view_reports').first(),
    ]
    manager_perms = [p for p in manager_perms if p is not None]

    manager_role = Role(
        name='Manager', name_ar='مدير', slug='manager', permissions=manager_perms
    )
    db.session.add(manager_role)
    db.session.flush()

    manager = User(
        username='testmanager', email='manager@test.com', full_name='Test Manager',
        is_owner=False, is_active=True, role_id=manager_role.id,
    )
    manager.set_password('ManagerPass123!')
    db.session.add(manager)
    db.session.commit()
    return manager


@pytest.fixture(scope='function')
def test_customer(db):
    """Create a test customer."""
    customer = Customer(
        name='Test Customer', name_ar='زبون تجريبي',
        customer_type='regular', phone='+971501234567', email='customer@test.com',
        credit_limit=Decimal('50000'), balance=Decimal('0'), is_active=True,
    )
    db.session.add(customer)
    db.session.commit()
    return customer


@pytest.fixture(scope='function')
def test_category(db):
    """Create a test product category."""
    category = ProductCategory(
        name='Spare Parts', name_ar='قطع غيار', is_active=True,
    )
    db.session.add(category)
    db.session.commit()
    return category


@pytest.fixture(scope='function')
def test_product(db, test_category):
    """Create a test product."""
    product = Product(
        name='Test Brake Pad', name_ar='صยา فرامل تجريبي',
        sku='SKU-TEST-001', category_id=test_category.id,
        cost_price=Decimal('50.000'), regular_price=Decimal('100.000'),
        current_stock=Decimal('100'), min_stock_alert=Decimal('10'),
        is_active=True,
    )
    db.session.add(product)
    db.session.commit()
    return product


@pytest.fixture(scope='function')
def test_sale(db, owner_user, test_customer, test_product):
    """Create a test sale with one line item."""
    from utils.helpers import generate_number

    sale_number = generate_number('S', Sale, 'sale_number')
    sale = Sale(
        sale_number=sale_number,
        customer_id=test_customer.id, seller_id=owner_user.id,
        total_amount=Decimal('100.000'), amount_aed=Decimal('100.000'),
        paid_amount=Decimal('0'), paid_amount_aed=Decimal('0'),
        balance_due=Decimal('100.000'), currency='AED',
        exchange_rate=Decimal('1'), payment_status='unpaid',
        status='confirmed', is_active=True,
    )
    db.session.add(sale)
    db.session.flush()

    line = SaleLine(
        sale_id=sale.id, product_id=test_product.id,
        quantity=Decimal('2'), unit_price=Decimal('50.000'),
        discount_percent=Decimal('0'), line_total=Decimal('100.000'),
        cost_price=Decimal('25.000'),
    )
    db.session.add(line)
    db.session.commit()
    return sale


@pytest.fixture
def login_owner(client, owner_user):
    """Helper to log in as owner."""
    client.post('/auth/login', data={
        'username': 'testowner', 'password': 'OwnerPass123!',
    }, follow_redirects=True)


@pytest.fixture
def login_seller(client, seller_user):
    """Helper to log in as seller."""
    client.post('/auth/login', data={
        'username': 'testseller', 'password': 'SellerPass123!',
    }, follow_redirects=True)
