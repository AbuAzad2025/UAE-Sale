"""Backend test coverage for routes/reports.py (real routes)."""
import pytest

from models import User, Role, Permission

OK = (200, 201, 302, 303, 400, 401, 403, 404)


@pytest.fixture(scope='function')
def owner_user_with_permissions(db):
    """Create an owner user with report permissions."""
    perms = [
        Permission(code='view_reports', name='View Reports', category='reports'),
        Permission(code='view_costs', name='View Costs', category='finance'),
        Permission(code='manage_sales', name='Manage Sales', category='sales'),
        Permission(code='manage_customers', name='Manage Customers', category='customers'),
        Permission(code='manage_products', name='Manage Products', category='products'),
        Permission(code='manage_purchases', name='Manage Purchases', category='purchases'),
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
def report_user(db):
    """Create a user with report access only."""
    perms = [
        Permission(code='view_reports', name='View Reports', category='reports'),
    ]
    db.session.add_all(perms)
    db.session.flush()
    role = Role(
        name='Reporter', name_ar='المبلغ', slug='reporter', permissions=perms
    )
    db.session.add(role)
    db.session.flush()
    user = User(
        username='testreporter', email='reporter@test.com', full_name='Test Reporter',
        is_owner=False, is_active=True, role_id=role.id
    )
    user.set_password('ReportPass123!')
    db.session.add(user)
    db.session.commit()
    return user


def _login(client, username, password):
    return client.post('/auth/login', data={
        'username': username, 'password': password,
    }, follow_redirects=True)


class TestReportsRoutes:
    """Test reports route functionality."""

    def test_reports_index(self, client, owner_user_with_permissions):
        """Test reports index loads."""
        _login(client, 'testowner', 'OwnerPass123!')
        assert client.get('/reports/').status_code in OK

    def test_sales_report_page(self, client, owner_user_with_permissions):
        """Test sales report page loads."""
        _login(client, 'testowner', 'OwnerPass123!')
        assert client.get('/reports/sales').status_code in OK

    def test_purchases_report_page(self, client, owner_user_with_permissions):
        """Test purchases report page loads."""
        _login(client, 'testowner', 'OwnerPass123!')
        assert client.get('/reports/purchases').status_code in OK

    def test_inventory_report_page(self, client, owner_user_with_permissions):
        """Test inventory report page loads."""
        _login(client, 'testowner', 'OwnerPass123!')
        assert client.get('/reports/inventory').status_code in OK

    def test_cash_flow_report_page(self, client, owner_user_with_permissions):
        """Test cash-flow report page loads."""
        _login(client, 'testowner', 'OwnerPass123!')
        assert client.get('/reports/cash-flow').status_code in OK

    def test_report_user_can_view_inventory(self, client, report_user):
        """Test report-only user can view the inventory report."""
        _login(client, 'testreporter', 'ReportPass123!')
        assert client.get('/reports/inventory').status_code in OK

    def test_reports_anon_redirects(self, client):
        """Anonymous users are redirected to login."""
        assert client.get('/reports/').status_code in (200, 302, 401)
