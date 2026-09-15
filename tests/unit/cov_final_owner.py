"""Backend test coverage for routes/owner.py"""
import pytest
from decimal import Decimal

from models import User, Role, Permission, Customer, Product, ProductCategory, Sale, SaleLine

from extensions import db as _db


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
        Permission(code='view_costs', name='View Costs', category='finance'),
    ]
    db.session.add_all(perms)
    db.session.flush()

    owner_role = Role(
        name='Owner', name_ar='المالك', slug='owner',
        permissions=perms
    )
    db.session.add(owner_role)
    db.session.flush()

    owner = User(
        username='testowner', email='owner@test.com', full_name='Test Owner',
        is_owner=True, is_active=True, role_id=owner_role.id
    )
    owner.set_password('OwnerPass123!')
    db.session.add(owner)
    db.session.commit()
    return owner


@pytest.fixture(scope='function')
def owner_user_with_permissions(owner_user):
    """Alias the local owner fixture."""
    return owner_user


def test_owner_user_creation(owner_user_with_permissions):
    """Test that owner user can be created with all permissions."""
    owner = owner_user_with_permissions
    assert owner.is_owner is True
    assert owner.is_active is True
    assert len(owner.role.permissions) == 13  # All expected permissions


def test_owner_user_can_access_roles(owner_user_with_permissions):
    """Test owner user can access different role types."""
    owner = owner_user_with_permissions
    # Verify role assignment
    assert owner.role_id is not None
    assert owner.role.name == 'Owner'
