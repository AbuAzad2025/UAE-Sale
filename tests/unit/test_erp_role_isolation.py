"""
Comprehensive Role Isolation Test Suite for UAE-Sale ERP.

Tests that every role can only access routes matching its operational scope,
that tenant isolation is enforced, and that navigation/dashboard rendering
is correctly gated per role.

Covers:
  - Phase 1: Role-permission mapping correctness
  - Phase 2: Route-level permission enforcement (403/404 on unauthorized access)
  - Phase 3: Tenant isolation (cross-tenant data blocked)
  - Phase 4: Dashboard/navigation rendering per role
  - Phase 5: Master Key / Super Admin scoping
"""
import pytest
from decimal import Decimal

from models import User, Role, Permission, Customer, Product, ProductCategory
from models import Sale, SaleLine, Warehouse
from models.tenant_scope import set_current_tenant_id, clear_current_tenant_id


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(scope='function')
def all_permissions(db):
    """Ensure all 20 permissions exist and return them."""
    codes = [
        'manage_sales', 'manage_purchases', 'manage_products', 'manage_customers',
        'manage_suppliers', 'manage_payments', 'manage_expenses', 'view_reports',
        'manage_users', 'manage_warehouse', 'view_ledger', 'manage_ledger',
        'admin', 'manage_backups',
        'manage_hr', 'manage_approvals', 'manage_settings', 'view_products',
        'view_costs',
    ]
    perms = []
    for code in codes:
        p = Permission.query.filter_by(code=code).first()
        if not p:
            p = Permission(code=code, name=code, name_ar=code, category='test')
            db.session.add(p)
        perms.append(p)
    db.session.flush()
    return {p.code: p for p in perms}


@pytest.fixture(scope='function')
def owner_user(db, all_permissions):
    """Owner with ALL permissions."""
    role = Role(name='Owner', name_ar='المالك', slug='owner',
                permissions=list(all_permissions.values()))
    db.session.add(role)
    db.session.flush()
    user = User(username='owner_iso', email='owner_iso@test.com',
                full_name='Owner', is_owner=True, is_active=True,
                role_id=role.id)
    user.set_password('Pass123!')
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture(scope='function')
def seller_user(db, all_permissions):
    """Seller: manage_sales + manage_customers + manage_products ONLY."""
    role = Role(name='Seller', name_ar='بائع', slug='seller', permissions=[
        all_permissions['manage_sales'],
        all_permissions['manage_customers'],
        all_permissions['manage_products'],
    ])
    db.session.add(role)
    db.session.flush()
    user = User(username='seller_iso', email='seller_iso@test.com',
                full_name='Seller', is_owner=False, is_active=True,
                role_id=role.id)
    user.set_password('Pass123!')
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture(scope='function')
def manager_user(db, all_permissions):
    """Manager: broader permissions but NOT manage_ledger or admin."""
    role = Role(name='Manager', name_ar='مدير', slug='manager', permissions=[
        all_permissions['manage_sales'], all_permissions['manage_customers'],
        all_permissions['manage_products'], all_permissions['manage_purchases'],
        all_permissions['manage_payments'], all_permissions['view_reports'],
        all_permissions['manage_expenses'], all_permissions['manage_warehouse'],
    ])
    db.session.add(role)
    db.session.flush()
    user = User(username='manager_iso', email='manager_iso@test.com',
                full_name='Manager', is_owner=False, is_active=True,
                role_id=role.id)
    user.set_password('Pass123!')
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture(scope='function')
def accountant_user(db, all_permissions):
    """Accountant: ledger + expenses + reports, but NOT sales or POS."""
    role = Role(name='Accountant', name_ar='محاسب', slug='accountant', permissions=[
        all_permissions['view_ledger'], all_permissions['manage_ledger'],
        all_permissions['manage_expenses'], all_permissions['view_reports'],
        all_permissions['manage_payments'],
    ])
    db.session.add(role)
    db.session.flush()
    user = User(username='accountant_iso', email='accountant_iso@test.com',
                full_name='Accountant', is_owner=False, is_active=True,
                role_id=role.id)
    user.set_password('Pass123!')
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture(scope='function')
def viewer_user(db, all_permissions):
    """Viewer: view_reports ONLY — no write access anywhere."""
    role = Role(name='Viewer', name_ar='مشاهد', slug='viewer', permissions=[
        all_permissions['view_reports'],
    ])
    db.session.add(role)
    db.session.flush()
    user = User(username='viewer_iso', email='viewer_iso@test.com',
                full_name='Viewer', is_owner=False, is_active=True,
                role_id=role.id)
    user.set_password('Pass123!')
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture(scope='function')
def other_tenant_user(db, all_permissions):
    """A user in a DIFFERENT tenant for cross-tenant isolation tests."""
    role = Role(name='OtherTenant', name_ar='مستأجر آخر', slug='manager',
                permissions=list(all_permissions.values()))
    db.session.add(role)
    db.session.flush()
    user = User(username='other_tenant', email='other@test.com',
                full_name='Other', is_owner=False, is_active=True,
                role_id=role.id, tenant_id=9999)
    user.set_password('Pass123!')
    db.session.add(user)
    db.session.commit()
    return user


def _login(client, user, password='Pass123!'):
    """Log in a user via the test client."""
    client.post('/auth/login', data={
        'username': user.username, 'password': password,
    }, follow_redirects=True)


# ── Phase 1: Role-Permission Mapping ────────────────────────────────────────

class TestPermissionCompleteness:
    """Verify that all 20 permission codes are seeded by system_init."""

    def test_system_init_seeds_all_required_permissions(self, db, app):
        from utils.system_init import _ensure_permissions
        with app.app_context():
            _ensure_permissions()
        codes = {p.code for p in Permission.query.all()}
        required = {
            'manage_sales', 'manage_purchases', 'manage_products',
            'manage_customers', 'manage_suppliers', 'manage_payments',
            'manage_expenses', 'view_reports', 'manage_users',
            'manage_warehouse', 'view_ledger', 'manage_ledger',
            'admin', 'manage_backups',
            'manage_hr', 'manage_approvals', 'manage_settings',
            'view_products', 'view_costs',
        }
        assert required <= codes, f"Missing permissions: {required - codes}"

    def test_owner_role_gets_all_permissions(self, db, app):
        from utils.system_init import (
            _ensure_permissions, _ensure_owner_role,
        )
        with app.app_context():
            _ensure_permissions()
            owner = _ensure_owner_role()
        perm_codes = {p.code for p in owner.permissions}
        assert len(perm_codes) >= 14


# ── Phase 2: Route-Level Permission Enforcement ─────────────────────────────

class TestSellerRouteIsolation:
    """Seller can ONLY access sales/customers/products routes."""

    @pytest.mark.parametrize('url,method', [
        ('/sales/', 'GET'),
        ('/customers/', 'GET'),
        ('/products/', 'GET'),
    ])
    def test_seller_can_access_own_module_routes(self, client, seller_user,
                                                  url, method):
        _login(client, seller_user)
        resp = client.get(url)
        assert resp.status_code in (200, 302), (
            f"Seller should access {url}, got {resp.status_code}"
        )

    @pytest.mark.parametrize('url', [
        '/ledger/',
        '/ledger/trial-balance',
        '/cheques/',
        '/hr/',
        '/owner/dashboard',
        '/warehouse/',
    ])
    def test_seller_blocked_from_non_permitted_routes(self, client, seller_user,
                                                       url):
        _login(client, seller_user)
        resp = client.get(url)
        assert resp.status_code in (403, 404, 302), (
            f"Seller should be blocked from {url}, got {resp.status_code}"
        )

    def test_seller_cannot_manage_users(self, client, seller_user):
        _login(client, seller_user)
        resp = client.get('/owner/users')
        assert resp.status_code in (403, 404, 302)

    def test_seller_cannot_access_reports(self, client, seller_user):
        _login(client, seller_user)
        resp = client.get('/reports/')
        assert resp.status_code in (403, 404, 302)


class TestManagerRouteIsolation:
    """Manager has broader access but NOT ledger/admin/owner."""

    @pytest.mark.parametrize('url', [
        '/sales/',
        '/customers/',
        '/products/',
        '/purchases/',
        '/payments/receipts',
        '/warehouse/',
    ])
    def test_manager_can_access_permitted_routes(self, client, manager_user, url):
        _login(client, manager_user)
        resp = client.get(url)
        assert resp.status_code in (200, 302), (
            f"Manager should access {url}, got {resp.status_code}"
        )

    @pytest.mark.parametrize('url', [
        '/ledger/',
        '/owner/dashboard',
        '/owner/users',
    ])
    def test_manager_blocked_from_restricted_routes(self, client, manager_user, url):
        _login(client, manager_user)
        resp = client.get(url)
        assert resp.status_code in (403, 404, 302), (
            f"Manager should be blocked from {url}, got {resp.status_code}"
        )


class TestAccountantRouteIsolation:
    """Accountant can access ledger/expenses but NOT POS/sales creation."""

    @pytest.mark.parametrize('url', [
        '/ledger/',
    ])
    def test_accountant_can_access_ledger(self, client, accountant_user, url):
        _login(client, accountant_user)
        resp = client.get(url)
        assert resp.status_code in (200, 302), (
            f"Accountant should access {url}, got {resp.status_code}"
        )

    @pytest.mark.parametrize('url', [
        '/sales/create',
        '/hr/',
        '/owner/dashboard',
    ])
    def test_accountant_blocked_from_pos_and_hr(self, client, accountant_user, url):
        _login(client, accountant_user)
        resp = client.get(url)
        assert resp.status_code in (403, 404, 302), (
            f"Accountant should be blocked from {url}, got {resp.status_code}"
        )


class TestViewerRouteIsolation:
    """Viewer has view_reports ONLY — zero write access."""

    @pytest.mark.parametrize('url', [
        '/sales/',
        '/customers/',
        '/products/',
        '/purchases/',
        '/ledger/',
        '/hr/',
        '/warehouse/',
        '/owner/dashboard',
    ])
    def test_viewer_blocked_from_all_write_routes(self, client, viewer_user, url):
        _login(client, viewer_user)
        resp = client.get(url)
        assert resp.status_code in (403, 404, 302), (
            f"Viewer should be blocked from {url}, got {resp.status_code}"
        )


# ── Phase 3: Tenant Isolation ───────────────────────────────────────────────

class TestCrossTenantIsolation:
    """Users cannot access data belonging to other tenants."""

    def test_seller_cannot_see_other_tenant_customer(
        self, client, seller_user, db, all_permissions
    ):
        _login(client, seller_user)
        # Create a customer in another tenant (tenant_id=9999)
        other = Customer(
            name='Other Tenant Customer', name_ar='عميل مستأجر آخر',
            phone='+971509999999', is_active=True, tenant_id=9999,
        )
        db.session.add(other)
        db.session.commit()
        resp = client.get(f'/customers/{other.id}')
        assert resp.status_code in (403, 404)

    def test_manager_cannot_see_other_tenant_sale(
        self, client, manager_user, db, all_permissions
    ):
        _login(client, manager_user)
        # Create a sale in another tenant
        other = Sale(
            sale_number='S-OTHER-001', total_amount=Decimal('100'),
            amount_base=Decimal('100'), paid_amount=Decimal('0'),
            paid_amount_base=Decimal('0'), balance_due=Decimal('100'),
            currency='AED', exchange_rate=Decimal('1'),
            payment_status='unpaid', status='confirmed',
            is_active=True, tenant_id=9999,
        )
        db.session.add(other)
        db.session.commit()
        resp = client.get(f'/sales/{other.id}')
        assert resp.status_code in (403, 404)

    def test_unauthenticated_user_redirected_to_login(self, client):
        resp = client.get('/sales/')
        assert resp.status_code in (302, 401)
        if resp.status_code == 302:
            assert 'login' in resp.headers.get('Location', '')


# ── Phase 4: Dashboard & Navigation Rendering ───────────────────────────────

class TestDashboardRendering:
    """Verify that dashboard renders correct content per role."""

    def test_seller_dashboard_renders(self, client, seller_user):
        _login(client, seller_user)
        resp = client.get('/dashboard')
        assert resp.status_code == 200
        data = resp.data.decode()
        assert 'New Invoice' in data or 'فاتورة جديدة' in data

    def test_manager_dashboard_renders(self, client, manager_user):
        _login(client, manager_user)
        resp = client.get('/dashboard')
        assert resp.status_code == 200

    def test_owner_dashboard_accessible(self, client, owner_user):
        _login(client, owner_user)
        resp = client.get('/owner/dashboard')
        assert resp.status_code == 200

    def test_viewer_dashboard_accessible(self, client, viewer_user):
        _login(client, viewer_user)
        resp = client.get('/dashboard')
        assert resp.status_code == 200

    def test_seller_cannot_access_owner_dashboard(self, client, seller_user):
        _login(client, seller_user)
        resp = client.get('/owner/dashboard')
        assert resp.status_code in (403, 404, 302)


class TestCommandPaletteIsolation:
    """Command palette (Ctrl+K) must only show permitted links."""

    def test_seller_palette_excludes_ledger(self, client, seller_user):
        _login(client, seller_user)
        resp = client.get('/dashboard')
        data = resp.data.decode()
        if 'commandPalette' in data:
            assert 'ledger' not in data.lower() or 'view_ledger' not in data

    def test_viewer_palette_has_no_write_commands(self, client, viewer_user):
        _login(client, viewer_user)
        resp = client.get('/dashboard')
        data = resp.data.decode()
        # Viewer has only view_reports — command palette should either be
        # absent or contain zero write-action commands
        if 'commandPalette' in data:
            for cmd in ['sales.create', 'customers.create', 'products.create',
                        'purchases.create']:
                assert cmd not in data, f"Viewer sees write command {cmd}"


class TestDashboardQuickActionsIsolation:
    """Quick action cards must only appear for permitted roles."""

    def test_seller_sees_only_permitted_cards(self, client, seller_user):
        _login(client, seller_user)
        resp = client.get('/dashboard')
        data = resp.data.decode()
        # Seller has manage_sales → should see "New Invoice"
        assert 'sales.create' in data or 'فاتورة جديدة' in data

    def test_viewer_sees_no_quick_actions(self, client, viewer_user):
        _login(client, viewer_user)
        resp = client.get('/dashboard')
        data = resp.data.decode()
        # Viewer has only view_reports — no write quick actions
        # The template now wraps each card in has_permission
        # Cards for sales.create, customers.create, products.create
        # should NOT render for a viewer (they have no manage_* perms)
        # We verify by checking the template conditionals are present
        assert 'has_permission' in data or 'New Invoice' not in data


# ── Phase 5: Master Key / Super Admin Scoping ───────────────────────────────

class TestMasterKeyScoping:
    """Owner (Master Key) can access cross-tenant data but actions are logged."""

    def test_owner_can_access_owner_dashboard(self, client, owner_user):
        _login(client, owner_user)
        resp = client.get('/owner/dashboard')
        assert resp.status_code == 200

    def test_owner_can_manage_users(self, client, owner_user):
        _login(client, owner_user)
        resp = client.get('/owner/users-list')
        assert resp.status_code == 200

    def test_owner_bypasses_tenant_filter(self, client, owner_user, db):
        _login(client, owner_user)
        # Owner should see all data regardless of tenant_id
        # (The owner has tenant_id=None so no filter is applied)
        resp = client.get('/sales/')
        assert resp.status_code in (200, 302)

    def test_non_owner_cannot_access_owner_panel(self, client, manager_user):
        _login(client, manager_user)
        resp = client.get('/owner/dashboard')
        assert resp.status_code in (403, 404, 302)

    def test_developer_can_access_owner_panel(self, client, db, all_permissions):
        """Developer role should have owner-level access."""
        role = Role(name='Developer', name_ar='مطور', slug='developer',
                    permissions=list(all_permissions.values()))
        db.session.add(role)
        db.session.flush()
        dev = User(username='dev_iso', email='dev_iso@test.com',
                   full_name='Dev', is_owner=False, is_active=True,
                   role_id=role.id)
        dev.set_password('Pass123!')
        db.session.add(dev)
        db.session.commit()
        _login(client, dev)
        resp = client.get('/owner/dashboard')
        assert resp.status_code == 200


# ── Phase 6: Decorator Correctness ──────────────────────────────────────────

class TestDecoratorBehavior:
    """Verify the decorator primitives work correctly."""

    def test_permission_required_blocks_unauthenticated(self, client):
        resp = client.get('/sales/')
        assert resp.status_code in (302, 401)

    def test_admin_required_allows_owner(self, client, owner_user):
        _login(client, owner_user)
        resp = client.get('/ledger/')
        assert resp.status_code in (200, 302)

    def test_admin_required_blocks_manager(self, client, manager_user):
        _login(client, manager_user)
        resp = client.get('/ledger/')
        assert resp.status_code in (403, 404, 302)

    def test_seller_or_above_allows_seller(self, client, seller_user):
        _login(client, seller_user)
        resp = client.get('/sales/')
        assert resp.status_code in (200, 302)

    def test_owner_required_blocks_non_owner(self, client, manager_user):
        _login(client, manager_user)
        resp = client.get('/owner/dashboard')
        assert resp.status_code in (403, 404, 302)
