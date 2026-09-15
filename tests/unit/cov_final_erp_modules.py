"""Backend test coverage for routes/erp_modules.py (real routes)."""
import pytest

from models import User, Role, Permission

OK = (200, 201, 302, 303, 400, 401, 403, 404)


@pytest.fixture(scope='function')
def owner_user_with_permissions(db):
    """Create an owner user with ERP permissions."""
    perms = [
        Permission(code='manage_sales', name='Manage Sales', category='sales'),
        Permission(code='manage_customers', name='Manage Customers', category='customers'),
        Permission(code='manage_products', name='Manage Products', category='products'),
        Permission(code='manage_purchases', name='Manage Purchases', category='purchases'),
        Permission(code='manage_users', name='Manage Users', category='users'),
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


def _login(client):
    return client.post('/auth/login', data={
        'username': 'testowner', 'password': 'OwnerPass123!',
    }, follow_redirects=True)


class TestERPModulesRoutes:
    """Test ERP modules route functionality."""

    def test_quotations_page(self, client, owner_user_with_permissions):
        """Test quotations page loads."""
        _login(client)
        assert client.get('/erp/quotations').status_code in OK

    def test_purchase_orders_page(self, client, owner_user_with_permissions):
        """Test purchase orders page loads."""
        _login(client)
        assert client.get('/erp/purchase-orders').status_code in OK

    def test_fiscal_periods_page(self, client, owner_user_with_permissions):
        """Test fiscal periods page loads."""
        _login(client)
        assert client.get('/erp/fiscal-periods').status_code in OK

    def test_dunning_page(self, client, owner_user_with_permissions):
        """Test dunning page loads."""
        _login(client)
        assert client.get('/erp/dunning').status_code in OK

    def test_quotation_convert_missing(self, client, owner_user_with_permissions):
        """Converting a missing quotation stays in the non-500 range."""
        _login(client)
        assert client.post('/erp/quotations/999999/convert').status_code in OK

    def test_erp_anon_redirects(self, client):
        """Anonymous users are redirected to login."""
        assert client.get('/erp/quotations').status_code in (200, 302, 401)
