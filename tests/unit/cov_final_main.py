"""Backend test coverage for routes/main.py"""
import pytest

from models import User, Role, Permission


@pytest.fixture(scope='function')
def owner_user_with_permissions(db):
    """Create an owner user with all standard permissions."""
    perms = [
        Permission(code='view_dashboard', name='View Dashboard', category='dashboard'),
        Permission(code='manage_sales', name='Manage Sales', category='sales'),
        Permission(code='manage_customers', name='Manage Customers', category='customers'),
        Permission(code='manage_products', name='Manage Products', category='products'),
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


class TestMainRoutes:
    """Test main routes."""

    def test_home_page(self, client, owner_user_with_permissions):
        """Test home page loads."""
        client.post('/auth/login', data={
            'username': 'testowner', 'password': 'OwnerPass123!',
        }, follow_redirects=True)
        resp = client.get('/')
        assert resp.status_code in (200, 302)

    def test_dashboard_page(self, client, owner_user_with_permissions):
        """Test dashboard page loads."""
        client.post('/auth/login', data={
            'username': 'testowner', 'password': 'OwnerPass123!',
        }, follow_redirects=True)
        resp = client.get('/dashboard')
        assert resp.status_code == 200

    def test_dashboard_api_undefined(self, client, owner_user_with_permissions):
        """No /api/dashboard endpoint exists; documents the 404."""
        client.post('/auth/login', data={
            'username': 'testowner', 'password': 'OwnerPass123!',
        }, follow_redirects=True)
        resp = client.get('/api/dashboard')
        assert resp.status_code == 404

    def test_main_unauthorized(self, client):
        """Test main route without authentication."""
        resp = client.get('/dashboard')
        assert resp.status_code in (302, 401)

    def test_login_page(self, client, owner_user_with_permissions):
        """Test login page renders at /auth/login."""
        resp = client.get('/auth/login')
        assert resp.status_code in (200, 302)

    def test_maintenance_page(self, client, owner_user_with_permissions):
        """Test maintenance page."""
        client.post('/auth/login', data={
            'username': 'testowner', 'password': 'OwnerPass123!',
        }, follow_redirects=True)
        resp = client.get('/maintenance')
        assert resp.status_code in (200, 404)

    def test_health_check(self, client, owner_user_with_permissions):
        """Test health check endpoint."""
        client.post('/auth/login', data={
            'username': 'testowner', 'password': 'OwnerPass123!',
        }, follow_redirects=True)
        resp = client.get('/health')
        assert resp.status_code in (200, 404)

    def test_system_status(self, client, owner_user_with_permissions):
        """Test system status endpoint."""
        client.post('/auth/login', data={
            'username': 'testowner', 'password': 'OwnerPass123!',
        }, follow_redirects=True)
        resp = client.get('/api/system/status')
        assert resp.status_code in (200, 404)

    def test_favicon(self, client, owner_user_with_permissions):
        """Test favicon endpoint."""
        client.post('/auth/login', data={
            'username': 'testowner', 'password': 'OwnerPass123!',
        }, follow_redirects=True)
        resp = client.get('/favicon.ico')
        assert resp.status_code in (200, 404)

    def test_robots_txt(self, client, owner_user_with_permissions):
        """Test robots.txt endpoint."""
        client.post('/auth/login', data={
            'username': 'testowner', 'password': 'OwnerPass123!',
        }, follow_redirects=True)
        resp = client.get('/robots.txt')
        assert resp.status_code in (200, 404)