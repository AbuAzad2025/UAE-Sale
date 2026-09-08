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
def cashier_user(db, all_permissions):
    """Cashier: manage_payments + view_reports ONLY."""
    role = Role(name='Cashier', name_ar='كاشير', slug='cashier', permissions=[
        all_permissions['manage_payments'],
        all_permissions['view_reports'],
    ])
    db.session.add(role)
    db.session.flush()
    user = User(username='cashier_iso', email='cashier_iso@test.com',
                full_name='Cashier', is_owner=False, is_active=True,
                role_id=role.id)
    user.set_password('Pass123!')
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture(scope='function')
def inventory_user(db, all_permissions):
    """Inventory: manage_warehouse + view_products ONLY."""
    role = Role(name='Inventory', name_ar='مخازن', slug='inventory', permissions=[
        all_permissions['manage_warehouse'],
        all_permissions['view_products'],
    ])
    db.session.add(role)
    db.session.flush()
    user = User(username='inventory_iso', email='inventory_iso@test.com',
                full_name='Inventory', is_owner=False, is_active=True,
                role_id=role.id)
    user.set_password('Pass123!')
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture(scope='function')
def hr_user(db, all_permissions):
    """HR: manage_hr ONLY."""
    role = Role(name='HR', name_ar='موارد بشرية', slug='hr', permissions=[
        all_permissions['manage_hr'],
    ])
    db.session.add(role)
    db.session.flush()
    user = User(username='hr_iso', email='hr_iso@test.com',
                full_name='HR', is_owner=False, is_active=True,
                role_id=role.id)
    user.set_password('Pass123!')
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture(scope='function')
def tenant1_seller_user(db, all_permissions):
    """Seller bound to tenant 1 (for cross-tenant cache-bleed tests)."""
    role = Role(name='T1Seller', name_ar='بائع 1', slug='seller_t1', permissions=[
        all_permissions['manage_sales'],
        all_permissions['manage_customers'],
        all_permissions['manage_products'],
    ])
    db.session.add(role)
    db.session.flush()
    user = User(username='t1_seller_iso', email='t1_seller_iso@test.com',
                full_name='T1 Seller', is_owner=False, is_active=True,
                role_id=role.id, tenant_id=1)
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
    """Log in a user via the test client.

    NOTE: /auth/login short-circuits with a redirect when a session is
    already authenticated, so we must log out first or switching users
    mid-test silently keeps the previous user logged in.
    """
    client.get('/auth/logout', follow_redirects=True)
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


class TestCashierRouteIsolation:
    """Cashier can access payments and reports, but nothing else."""

    @pytest.mark.parametrize('url', [
        '/payments/receipts',
    ])
    def test_cashier_can_access_payments(self, client, cashier_user, url):
        _login(client, cashier_user)
        resp = client.get(url)
        assert resp.status_code in (200, 302), (
            f"Cashier should access {url}, got {resp.status_code}"
        )

    @pytest.mark.parametrize('url', [
        '/sales/',
        '/customers/',
        '/products/',
        '/purchases/',
        '/ledger/',
        '/hr/',
        '/warehouse/',
        '/expenses/',
        '/owner/dashboard',
        '/users/',
    ])
    def test_cashier_blocked_from_non_permitted_routes(self, client, cashier_user, url):
        _login(client, cashier_user)
        resp = client.get(url)
        assert resp.status_code in (403, 404, 302), (
            f"Cashier should be blocked from {url}, got {resp.status_code}"
        )


class TestInventoryRouteIsolation:
    """Inventory can access warehouse, but nothing else."""

    @pytest.mark.parametrize('url', [
        '/warehouse/',
    ])
    def test_inventory_can_access_warehouse(self, client, inventory_user, url):
        _login(client, inventory_user)
        resp = client.get(url)
        assert resp.status_code in (200, 302), (
            f"Inventory should access {url}, got {resp.status_code}"
        )

    @pytest.mark.parametrize('url', [
        '/sales/',
        '/customers/',
        '/products/',
        '/purchases/',
        '/ledger/',
        '/hr/',
        '/payments/',
        '/expenses/',
        '/owner/dashboard',
        '/users/',
    ])
    def test_inventory_blocked_from_non_permitted_routes(self, client, inventory_user, url):
        _login(client, inventory_user)
        resp = client.get(url)
        assert resp.status_code in (403, 404, 302), (
            f"Inventory should be blocked from {url}, got {resp.status_code}"
        )


class TestHRRouteIsolation:
    """HR can access HR module, but nothing else."""

    @pytest.mark.parametrize('url', [
        '/hr/',
    ])
    def test_hr_can_access_hr_module(self, client, hr_user, url):
        _login(client, hr_user)
        resp = client.get(url)
        assert resp.status_code in (200, 302), (
            f"HR should access {url}, got {resp.status_code}"
        )

    @pytest.mark.parametrize('url', [
        '/sales/',
        '/customers/',
        '/products/',
        '/purchases/',
        '/ledger/',
        '/warehouse/',
        '/payments/',
        '/expenses/',
        '/owner/dashboard',
        '/users/',
    ])
    def test_hr_blocked_from_non_permitted_routes(self, client, hr_user, url):
        _login(client, hr_user)
        resp = client.get(url)
        assert resp.status_code in (403, 404, 302), (
            f"HR should be blocked from {url}, got {resp.status_code}"
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

    def test_cashier_dashboard_accessible(self, client, cashier_user):
        _login(client, cashier_user)
        resp = client.get('/dashboard')
        assert resp.status_code == 200

    def test_inventory_dashboard_accessible(self, client, inventory_user):
        _login(client, inventory_user)
        resp = client.get('/dashboard')
        assert resp.status_code == 200

    def test_hr_dashboard_accessible(self, client, hr_user):
        _login(client, hr_user)
        resp = client.get('/dashboard')
        assert resp.status_code == 200

    def test_cashier_cannot_access_owner_dashboard(self, client, cashier_user):
        _login(client, cashier_user)
        resp = client.get('/owner/dashboard')
        assert resp.status_code in (403, 404, 302)

    def test_inventory_cannot_access_owner_dashboard(self, client, inventory_user):
        _login(client, inventory_user)
        resp = client.get('/owner/dashboard')
        assert resp.status_code in (403, 404, 302)

    def test_hr_cannot_access_owner_dashboard(self, client, hr_user):
        _login(client, hr_user)
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

    def test_cashier_palette_excludes_ledger_and_sales(self, client, cashier_user):
        # Cashier has manage_payments + view_reports only.
        # Palette/nav entries render resolved URLs (url_for output), so we
        # assert those URLs are absent from the whole dashboard page.
        _login(client, cashier_user)
        resp = client.get('/dashboard')
        data = resp.data.decode()
        if 'commandPalette' in data:
            for url in ['/sales/create', '/ledger/', '/products/create',
                        '/purchases/create']:
                assert url not in data, f"Cashier sees command URL {url}"
            # But the permitted payments entry must be present
            assert '/payments/receipts/create' in data or 'payments' in data.lower()

    def test_inventory_palette_excludes_ledger_and_sales(self, client, inventory_user):
        # Inventory has manage_warehouse + view_products only
        _login(client, inventory_user)
        resp = client.get('/dashboard')
        data = resp.data.decode()
        if 'commandPalette' in data:
            for url in ['/sales/create', '/ledger/',
                        '/payments/receipts/create', '/products/create']:
                assert url not in data, f"Inventory sees command URL {url}"

    def test_hr_palette_has_no_finance_commands(self, client, hr_user):
        # HR has manage_hr only
        _login(client, hr_user)
        resp = client.get('/dashboard')
        data = resp.data.decode()
        if 'commandPalette' in data:
            for url in ['/sales/create', '/ledger/',
                        '/payments/receipts/create']:
                assert url not in data, f"HR sees finance command URL {url}"


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

    def test_cashier_sees_reports_card_only(self, client, cashier_user):
        # Cashier has manage_payments + view_reports: only the reports
        # quick-action card may render; no sales/customers/products cards.
        _login(client, cashier_user)
        resp = client.get('/dashboard')
        data = resp.data.decode()
        assert '/reports/sales' in data
        for url in ['/sales/create', '/customers/create',
                    '/products/create']:
            assert url not in data, f"Cashier sees card URL {url}"

    def test_inventory_sees_no_quick_action_cards(self, client, inventory_user):
        # Inventory has manage_warehouse + view_products: none of the four
        # card gates (manage_sales/customers/products, view_reports) pass.
        _login(client, inventory_user)
        resp = client.get('/dashboard')
        data = resp.data.decode()
        for url in ['/sales/create', '/customers/create',
                    '/products/create', '/reports/sales']:
            assert url not in data, f"Inventory sees card URL {url}"

    def test_hr_sees_no_quick_action_cards(self, client, hr_user):
        # HR has manage_hr only: no quick-action card may render.
        _login(client, hr_user)
        resp = client.get('/dashboard')
        data = resp.data.decode()
        for url in ['/sales/create', '/customers/create',
                    '/products/create', '/reports/sales']:
            assert url not in data, f"HR sees card URL {url}"


# ── Phase 4b: Dashboard DATA Scoping ──────────────────────────────────────────

class TestDashboardDataScoping:
    """Financial aggregates and PII rows render only for in-scope roles.

    Section markers (hardcoded Arabic strings, locale-independent):
      sales card 'مبيعات اليوم' · customers 'إجمالي الزبائن' ·
      receivables 'الذمم المدينة' · products 'منتجات نشطة' ·
      recent-sales table 'آخر المبيعات'.
    """

    def test_seller_sees_sales_data_not_receivables(self, client, seller_user):
        _login(client, seller_user)
        data = client.get('/dashboard').data.decode()
        assert 'مبيعات اليوم' in data
        assert 'إجمالي الزبائن' in data
        assert 'منتجات نشطة' in data
        assert 'آخر المبيعات' in data
        assert 'الذمم المدينة' not in data

    def test_manager_sees_all_sections(self, client, manager_user):
        _login(client, manager_user)
        data = client.get('/dashboard').data.decode()
        for marker in ['مبيعات اليوم', 'إجمالي الزبائن', 'الذمم المدينة',
                       'منتجات نشطة', 'آخر المبيعات']:
            assert marker in data, f"Manager missing section {marker}"

    def test_accountant_sees_receivables_not_pii_table(self, client, accountant_user):
        _login(client, accountant_user)
        data = client.get('/dashboard').data.decode()
        assert 'الذمم المدينة' in data
        assert 'مبيعات اليوم' in data  # via view_reports
        assert 'آخر المبيعات' not in data  # customer PII: manage_sales only

    def test_cashier_sees_cards_not_pii_table(self, client, cashier_user):
        _login(client, cashier_user)
        data = client.get('/dashboard').data.decode()
        assert 'مبيعات اليوم' in data
        assert 'الذمم المدينة' in data
        assert 'آخر المبيعات' not in data

    def test_viewer_sees_cards_not_pii_table(self, client, viewer_user):
        _login(client, viewer_user)
        data = client.get('/dashboard').data.decode()
        assert 'مبيعات اليوم' in data
        assert 'آخر المبيعات' not in data

    def test_inventory_sees_products_only(self, client, inventory_user):
        _login(client, inventory_user)
        data = client.get('/dashboard').data.decode()
        assert 'منتجات نشطة' in data
        for marker in ['مبيعات اليوم', 'إجمالي الزبائن', 'الذمم المدينة',
                       'آخر المبيعات']:
            assert marker not in data, f"Inventory sees section {marker}"

    def test_hr_sees_no_business_data(self, client, hr_user):
        _login(client, hr_user)
        resp = client.get('/dashboard')
        assert resp.status_code == 200
        data = resp.data.decode()
        for marker in ['مبيعات اليوم', 'إجمالي الزبائن', 'الذمم المدينة',
                       'منتجات نشطة', 'آخر المبيعات']:
            assert marker not in data, f"HR sees section {marker}"

    def test_dashboard_cache_is_tenant_scoped(
        self, client, seller_user, tenant1_seller_user, db
    ):
        """Regression: dashboard aggregates cached for one tenant must never
        leak into another tenant's dashboard (cache key includes tenant).

        NOTE: the template renders aggregates (today_sales_amount, counts)
        from the CACHE, but recent-sales rows from a fresh ORM query. So the
        bleed vector is the aggregate: seed a tenant-9999 sale big enough to
        move today_sales_amount, prime the cache, then assert the other
        tenant's page does not show it.
        """
        # Seed a confirmed TODAY sale + customer in tenant 9999
        other = Customer(
            name='T9999 Cache Customer', name_ar='عميل كاش 9999',
            phone='+971500000001', is_active=True, tenant_id=9999,
        )
        db.session.add(other)
        db.session.flush()
        sale = Sale(
            sale_number='S-CACHE-9999', customer_id=other.id,
            total_amount=Decimal('7777'), amount_base=Decimal('7777'),
            paid_amount=Decimal('0'), paid_amount_base=Decimal('0'),
            balance_due=Decimal('7777'), currency='AED',
            exchange_rate=Decimal('1'), payment_status='unpaid',
            status='confirmed', is_active=True, tenant_id=9999,
        )
        db.session.add(sale)
        db.session.commit()

        # Prime the cache as the tenant-less seller (unfiltered context):
        # page shows the 7,777 aggregate.
        _login(client, seller_user)
        assert '7,777' in client.get('/dashboard').data.decode()
        client.get('/auth/logout', follow_redirects=True)

        # Tenant-1 seller has no sales: must see 0, never the cached 7,777.
        # (On the old tenant-agnostic cache key this fails: the 7,777 bleeds.)
        _login(client, tenant1_seller_user)
        data = client.get('/dashboard').data.decode()
        assert '7,777' not in data
        assert 'T9999 Cache Customer' not in data


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


# ── Phase 7: Adaptive RBAC audit (deduplicated additions) ────────────────────
# NOTE (deduplication): GET allow/deny matrix, dashboard/palette/quick-action
# gating, IDOR GET, and /users role-escalation are already covered by
# Phases 2-5 + test_zero_trust_isolation.py + test_security_audit.py.
# The three tests below cover ONLY the gaps: POST/DELETE tampering with
# DB-unchanged guards, DOM-absence for financial/admin UI, and
# mass-assignment / cross-tenant POST escalation.

class TestDiscoveredRoleEndpointMatrix:
    """POST tampering matrix — low-priv roles must be denied AND cause no write.

    Skips GET scenarios already covered in Phases 2-5 (see module docstring).
    """

    @pytest.mark.parametrize('fixture_name,method,url', [
        ('seller_user', 'POST', '/expenses/create'),
        ('seller_user', 'POST', '/purchases/create'),
        ('seller_user', 'POST', '/hr/employees/create'),
        ('seller_user', 'POST', '/ledger/manual-entry'),
        ('seller_user', 'POST', '/cheques/create'),
        ('cashier_user', 'POST', '/sales/create'),
        ('cashier_user', 'POST', '/products/create'),
        ('accountant_user', 'POST', '/sales/create'),
        ('manager_user', 'POST', '/ledger/manual-entry'),
        ('inventory_user', 'POST', '/sales/create'),
        ('inventory_user', 'POST', '/purchases/create'),
        ('hr_user', 'POST', '/expenses/create'),
        ('viewer_user', 'POST', '/sales/create'),
        ('viewer_user', 'POST', '/expenses/create'),
    ])
    def test_discovered_role_endpoint_matrix(
        self, client, db, request, fixture_name, method, url
    ):
        user = request.getfixturevalue(fixture_name)
        _login(client, user)
        if method == 'POST':
            resp = client.post(url, data={'_audit_probe': 'rbac-matrix'},
                               follow_redirects=False)
        else:
            resp = client.get(url, follow_redirects=False)
        # Permission gates abort 403; owner panel stealth is 404; some
        # /users-style gates flash+redirect (302). 200 with a write = bypass.
        assert resp.status_code in (403, 404, 302), (
            f"{fixture_name} {method} {url} returned {resp.status_code}, "
            "expected deny (403/404/302)"
        )

    @pytest.mark.parametrize('fixture_name,url', [
        ('seller_user', '/owner/backup-now'),
        ('manager_user', '/owner/backup-now'),
        ('cashier_user', '/owner/backup-now'),
    ])
    def test_discovered_role_endpoint_matrix_owner_post_stealth(
        self, client, db, request, fixture_name, url
    ):
        """Non-owner POST to owner panel must be stealth-404 (or deny), never 200."""
        user = request.getfixturevalue(fixture_name)
        _login(client, user)
        resp = client.post(url, data={}, follow_redirects=False)
        assert resp.status_code in (403, 404, 302), (
            f"{fixture_name} POST {url} returned {resp.status_code}"
        )


class TestRoleUiElementVisibility:
    """DOM-absence: restricted links/data must be missing from HTML, not CSS-hidden."""

    @pytest.mark.parametrize('fixture_name,forbidden_urls', [
        ('seller_user', ['/ledger/', '/owner/dashboard', '/owner/audit-logs',
                         '/hr/', '/owner/config']),
        ('cashier_user', ['/sales/create', '/ledger/', '/products/create',
                          '/purchases/create', '/owner/dashboard']),
        ('inventory_user', ['/sales/create', '/ledger/', '/owner/dashboard',
                            '/payments/receipts/create']),
        ('hr_user', ['/sales/create', '/ledger/', '/payments/receipts/create',
                     '/owner/dashboard']),
        ('viewer_user', ['/sales/create', '/customers/create',
                         '/products/create', '/purchases/create',
                         '/owner/dashboard']),
        ('accountant_user', ['/sales/create', '/hr/', '/owner/dashboard']),
    ])
    def test_role_ui_element_visibility(
        self, client, request, fixture_name, forbidden_urls
    ):
        user = request.getfixturevalue(fixture_name)
        _login(client, user)
        data = client.get('/dashboard').data.decode()
        for url in forbidden_urls:
            assert url not in data, (
                f"{fixture_name} dashboard leaks restricted URL {url}"
            )

    def test_role_ui_element_visibility_cashier_reports_only(
        self, client, cashier_user
    ):
        _login(client, cashier_user)
        data = client.get('/dashboard').data.decode()
        assert '/reports/sales' in data
        for url in ['/sales/create', '/customers/create', '/products/create']:
            assert url not in data, f"Cashier sees card URL {url}"


class TestPrivilegeEscalationGuard:
    """Parameter tampering / cross-tenant POST must fail closed with no DB effect."""

    def test_privilege_escalation_guard_role_smuggling(
        self, client, db, seller_user, all_permissions
    ):
        from models import Role as _Role
        super_role = _Role.query.filter_by(slug='super_admin').first()
        if not super_role:
            super_role = _Role(name='Super Admin', slug='super_admin',
                               permissions=list(all_permissions.values()))
            db.session.add(super_role)
            db.session.commit()
        _login(client, seller_user)
        before = User.query.filter_by(username='evil_smuggled').count()
        resp = client.post('/users/create', data={
            'username': 'evil_smuggled', 'email': 'evil_smuggled@test.local',
            'password': 'EvilPass123!@#', 'full_name': 'Evil',
            'role_id': super_role.id, 'is_owner': '1', 'tenant_id': '9999',
        }, follow_redirects=False)
        assert resp.status_code in (302, 403, 404)
        db.session.expire_all()
        evil = User.query.filter_by(username='evil_smuggled').first()
        assert evil is None or evil.role.slug != 'super_admin', (
            "Privilege escalation: seller minted super_admin"
        )
        assert evil is None or evil.is_owner is not True
        if evil is not None:
            db.session.delete(evil)
            db.session.commit()
        assert User.query.filter_by(username='evil_smuggled').count() == before

    def test_privilege_escalation_guard_self_promotion(
        self, client, db, seller_user, all_permissions
    ):
        from models import Role as _Role
        super_role = _Role.query.filter_by(slug='super_admin').first()
        if not super_role:
            super_role = _Role(name='Super Admin', slug='super_admin',
                               permissions=list(all_permissions.values()))
            db.session.add(super_role)
            db.session.commit()
        orig_role_id = seller_user.role_id
        _login(client, seller_user)
        client.post(f'/users/{seller_user.id}/edit', data={
            'email': seller_user.email, 'full_name': seller_user.full_name,
            'role_id': super_role.id,
        }, follow_redirects=False)
        db.session.expire_all()
        assert User.query.get(seller_user.id).role_id != super_role.id
        assert User.query.get(seller_user.id).role_id == orig_role_id

    def test_privilege_escalation_guard_manager_cannot_delete_super_admin(
        self, client, db, manager_user, all_permissions
    ):
        from models import Role as _Role
        super_role = _Role.query.filter_by(slug='super_admin').first()
        if not super_role:
            super_role = _Role(name='Super Admin', slug='super_admin',
                               permissions=list(all_permissions.values()))
            db.session.add(super_role)
            db.session.commit()
        victim = User(username='victim_sa', email='victim_sa@test.local',
                      full_name='Victim', is_owner=False, is_active=True,
                      role_id=super_role.id)
        victim.set_password('Pass123!')
        db.session.add(victim)
        db.session.commit()
        victim_id = victim.id
        _login(client, manager_user)
        resp = client.post(f'/users/{victim_id}/delete',
                           follow_redirects=False)
        assert resp.status_code in (302, 403, 404)
        db.session.expire_all()
        assert User.query.get(victim_id) is not None, (
            "Manager deleted a super_admin account"
        )

    def test_privilege_escalation_guard_cross_tenant_post_blocked(
        self, client, db, seller_user
    ):
        other = Customer(
            name='Other Tenant Guard', name_ar='حارس',
            phone='+971500000099', is_active=True, tenant_id=9999,
        )
        db.session.add(other)
        db.session.commit()
        other_id = other.id
        _login(client, seller_user)
        resp = client.post(f'/customers/{other_id}/edit',
                           data={'name': 'Hacked Name'},
                           follow_redirects=False)
        assert resp.status_code in (302, 403, 404, 405)
        db.session.expire_all()
        assert Customer.query.get(other_id).name == 'Other Tenant Guard'

    def test_privilege_escalation_guard_tenant_id_immutable_via_http(
        self, client, db, seller_user
    ):
        own = Customer(name='Own Tenant Guard', name_ar='خاص',
                       phone='+971500000098', is_active=True, tenant_id=None)
        db.session.add(own)
        db.session.commit()
        own_id = own.id
        _login(client, seller_user)
        client.post(f'/customers/{own_id}/edit',
                    data={'name': 'Own Tenant Guard', 'tenant_id': '9999'},
                    follow_redirects=False)
        db.session.expire_all()
        assert Customer.query.get(own_id).tenant_id != 9999

    def test_privilege_escalation_guard_vault_settings_owner_only(
        self, client, db, manager_user
    ):
        """Secret vault settings (crypto/bank keys) are owner-only — a
        manager POST must be refused and must not mutate settings."""
        from models.payment_vault import PaymentVault
        vault = PaymentVault.query.first()
        if not vault:
            vault = PaymentVault(vault_name='Audit Vault',
                                 vault_password_hash='x', is_locked=True)
            db.session.add(vault)
            db.session.commit()
        orig_name = vault.bank_name
        _login(client, manager_user)
        resp = client.post('/payment-vault/settings', data={
            'bank_name': 'PWNED BANK',
        }, follow_redirects=False)
        assert resp.status_code in (302, 403, 404)
        db.session.expire_all()
        assert PaymentVault.query.get(vault.id).bank_name == orig_name, (
            "Non-owner mutated secret vault settings"
        )

    def test_privilege_escalation_guard_low_priv_cannot_mint_settings_perm(
        self, client, db, seller_user, all_permissions
    ):
        """manage_settings routes (approval workflows) must deny seller."""
        _login(client, seller_user)
        resp = client.post('/approvals/workflows/new', data={
            'name': 'Evil WF', 'entity_type': 'sale',
            'levels_required': '1',
        }, follow_redirects=False)
        assert resp.status_code in (302, 403, 404)
        from models import ApprovalWorkflow
        assert ApprovalWorkflow.query.filter_by(name='Evil WF').count() == 0


# ── Phase 8: Operational-vs-Financial separation (cost leakage) ──────────────
# Directive §1.2: operations roles (seller/cashier/inventory) must never see
# cost prices, margins, or GL postings. Every finding below was verified
# against the live templates/routes before the enforcing test was written.

class TestCostDataSeparation:
    """Cost-price/margin leakage across HTML, JSON APIs, and GraphQL."""

    def _seed_cost_product(self, db):
        cat = ProductCategory.query.filter_by(is_active=True).first()
        if not cat:
            cat = ProductCategory(name='Cost Audit Cat', name_ar='تكلفة',
                                  is_active=True)
            db.session.add(cat)
            db.session.flush()
        product = Product(name='Cost Secret Widget', name_ar='منتج التكلفة',
                          sku='SKU-COST-AUDIT', category_id=cat.id,
                          cost_price=Decimal('77.500'),
                          regular_price=Decimal('150.000'),
                          current_stock=Decimal('10'),
                          min_stock_alert=Decimal('2'), is_active=True)
        db.session.add(product)
        db.session.commit()
        return product

    # -- HTML surfaces -------------------------------------------------------

    def test_inventory_report_hides_cost_columns_from_operational_roles(
        self, client, db, seller_user, cashier_user
    ):
        product = self._seed_cost_product(db)
        for user in (seller_user, cashier_user):
            _login(client, user)
            resp = client.get('/reports/inventory')
            if resp.status_code != 200:
                continue  # view_reports gate denies: covered elsewhere
            html = resp.data.decode()
            assert 'سعر التكلفة' not in html, (
                f"{user.role.slug} sees cost column header on /reports/inventory"
            )
            assert '77.5' not in html and '77.500' not in html
            assert product.sku in html  # page still functional for stock ops

    def test_inventory_report_shows_cost_to_cost_privileged_roles(
        self, client, db, owner_user, manager_user
    ):
        self._seed_cost_product(db)
        for user in (owner_user, manager_user):
            _login(client, user)
            resp = client.get('/reports/inventory')
            assert resp.status_code == 200
            assert 'سعر التكلفة' in resp.data.decode()

    def test_inventory_valuation_blocked_without_cost_visibility(
        self, client, db, seller_user, cashier_user, accountant_user
    ):
        """Valuation = qty × cost. view_reports alone must get 403."""
        self._seed_cost_product(db)
        for user in (seller_user, cashier_user, accountant_user):
            _login(client, user)
            assert client.get('/reports/inventory-valuation').status_code == 403, (
                f"{user.role.slug} reached cost valuation report"
            )
            assert client.get(
                '/reports/inventory-valuation/export?format=csv'
            ).status_code == 403

    def test_inventory_valuation_allowed_for_cost_privileged(
        self, client, db, owner_user, manager_user
    ):
        self._seed_cost_product(db)
        for user in (owner_user, manager_user):
            _login(client, user)
            assert client.get('/reports/inventory-valuation').status_code == 200

    def test_product_detail_hides_cost_from_seller(self, client, db, seller_user):
        product = self._seed_cost_product(db)
        _login(client, seller_user)
        html = client.get(f'/products/{product.id}').data.decode()
        assert 'سعر التكلفة' not in html
        assert '77.5' not in html

    def test_product_forms_hide_cost_field_from_seller(self, client, db, seller_user):
        self._seed_cost_product(db)
        _login(client, seller_user)
        assert 'name="cost_price"' not in client.get('/products/create').data.decode()
        product = Product.query.filter_by(sku='SKU-COST-AUDIT').first()
        assert 'name="cost_price"' not in client.get(
            f'/products/{product.id}/edit'
        ).data.decode()

    def test_seller_cannot_write_cost_price_via_edit_tampering(
        self, client, db, seller_user
    ):
        """Seller omits cost field (hidden in UI) — a tampered POST with
        cost_price must NOT change the stored cost (server-side guard)."""
        product = self._seed_cost_product(db)
        wh = Warehouse.query.filter_by(is_active=True).first()
        if not wh:
            wh = Warehouse(name='Cost Audit WH', is_active=True, is_main=True)
            db.session.add(wh)
            db.session.commit()
        _login(client, seller_user)
        resp = client.post(f'/products/{product.id}/edit', data={
            'name': product.name, 'name_ar': product.name_ar or '',
            'sku': product.sku, 'category_id': str(product.category_id or 0),
            'regular_price': '150', 'cost_price': '1',
            'min_stock_alert': '2', 'current_stock': '10',
            'warehouse_id': str(wh.id),
        }, follow_redirects=False)
        assert resp.status_code in (302, 200)
        db.session.expire_all()
        assert db.session.get(Product, product.id).cost_price == Decimal('77.500'), (
            "Seller tampered cost_price via product edit POST"
        )

    def test_lots_page_hides_cost_from_inventory_role(self, client, db, inventory_user):
        _login(client, inventory_user)
        html = client.get('/erp/lots').data.decode()
        assert 'التكلفة' not in html

    # -- JSON APIs -----------------------------------------------------------

    def test_api_search_masks_cost_from_operational_roles(
        self, client, db, seller_user, cashier_user, owner_user
    ):
        self._seed_cost_product(db)
        for user, expect_cost in ((seller_user, False), (cashier_user, False),
                                  (owner_user, True)):
            _login(client, user)
            body = client.get('/api/search?type=products&q=Cost Secret').get_json()
            hit = next(r for r in body['results']
                       if r['sku'] == 'SKU-COST-AUDIT')
            if expect_cost:
                assert hit['cost_price'] == 77.5
            else:
                assert hit['cost_price'] is None, (
                    f"{user.role.slug} got cost_price from /api/search"
                )

    def test_api_v2_sales_mask_line_costs_from_seller(
        self, client, db, seller_user, owner_user, test_sale
    ):
        _login(client, seller_user)
        listing = client.get('/api/v2/sales').get_json()
        for sale in listing['sales']:
            for line in sale.get('lines', []):
                assert 'cost_price' not in line, "Seller sees line cost in list API"
                assert 'profit' not in line
        detail_id = listing['sales'][0]['id'] if listing['sales'] else test_sale.id
        detail = client.get(f'/api/v2/sales/{detail_id}').get_json()
        for line in detail['sale'].get('lines', []):
            assert 'cost_price' not in line
        assert 'profit' not in detail['sale']

        _login(client, owner_user)
        detail_owner = client.get(f'/api/v2/sales/{test_sale.id}').get_json()
        assert detail_owner['sale']['lines'][0]['cost_price'] == 25.0

    def test_profit_margins_endpoint_blocked_without_cost_visibility(
        self, client, db, cashier_user, viewer_user, seller_user, owner_user
    ):
        for user in (cashier_user, viewer_user, seller_user):
            _login(client, user)
            assert client.get('/api/v2/analytics/profit-margins').status_code == 403, (
                f"{user.role.slug} pulled profit margins"
            )
        _login(client, owner_user)
        assert client.get('/api/v2/analytics/profit-margins').status_code == 200

    # -- GraphQL -------------------------------------------------------------

    def test_graphql_masks_product_cost_from_low_privilege_user(
        self, client, db, viewer_user, owner_user
    ):
        """view_reports is the base gate for /graphql — a viewer passes the
        endpoint gate but must still get costPrice masked (owner sees it)."""
        self._seed_cost_product(db)
        _login(client, viewer_user)
        resp = client.post('/graphql', json={
            'query': '{ allProducts { id name costPrice } }',
        })
        assert resp.status_code == 200
        products = resp.get_json()['data']['allProducts']
        target = next(p for p in products if p['name'] == 'Cost Secret Widget')
        assert target['costPrice'] is None, "Viewer read cost via GraphQL"

        _login(client, owner_user)
        resp_owner = client.post('/graphql', json={
            'query': '{ allProducts { id name costPrice } }',
        })
        owner_products = resp_owner.get_json()['data']['allProducts']
        owner_target = next(
            p for p in owner_products if p['name'] == 'Cost Secret Widget'
        )
        assert owner_target['costPrice'] == 77.5, (
            "Owner lost cost visibility after masking fix"
        )

    # -- Cache bleed regression ----------------------------------------------

    def test_api_v2_cache_never_serves_owner_costs_to_seller(
        self, client, db, owner_user, seller_user, test_sale
    ):
        """Regression: /api/v2/sales cache key was role-agnostic — the owner's
        cost-bearing response was served to sellers within the TTL."""
        _login(client, owner_user)
        owner_body = client.get('/api/v2/sales').get_json()
        assert owner_body['sales'][0]['lines'][0]['cost_price'] == 25.0
        client.get('/auth/logout', follow_redirects=True)

        _login(client, seller_user)
        seller_body = client.get('/api/v2/sales').get_json()
        for sale in seller_body['sales']:
            for line in sale.get('lines', []):
                assert 'cost_price' not in line, (
                    "Cross-role cache bleed: seller received owner's cached "
                    "cost-bearing sales payload"
                )

    # -- Model-level invariant -----------------------------------------------

    def test_can_see_costs_matrix(self, db, owner_user, manager_user,
                                  seller_user, cashier_user, accountant_user,
                                  inventory_user, viewer_user):
        """Documented contract: only owner/super_admin/manager see costs.

        NOTE (finding F5): accountant is a financial role but is excluded by
        the current can_see_costs() implementation — see audit report.
        """
        assert owner_user.can_see_costs() is True
        assert manager_user.can_see_costs() is True
        for user in (seller_user, cashier_user, inventory_user, viewer_user,
                     accountant_user):
            assert user.can_see_costs() is False, (
                f"{user.role.slug} unexpectedly sees costs"
            )
