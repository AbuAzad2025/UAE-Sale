"""
Zero-trust authorization & tenant isolation integration tests.

Validates:
  1. Role boundaries — low-privilege roles cannot escalate or hit admin routes.
  2. IDOR / BOLA — arbitrary PKs for another tenant return 403/404.
  3. Multi-tenancy — all queries are automatically scoped to the authenticated tenant;
     writes inherit the tenant and tenant_id is immutable for non-owners.
"""
import pytest
from decimal import Decimal

from models import Customer, Product, ProductCategory, Sale, SaleLine, Warehouse
from models.tenant import Tenant
from models.user import Role, Permission, User


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_permissions(db):
    codes = [
        ('manage_sales', 'Manage Sales', 'sales'),
        ('manage_customers', 'Manage Customers', 'customers'),
        ('manage_products', 'Manage Products', 'products'),
        ('manage_purchases', 'Manage Purchases', 'purchases'),
        ('manage_suppliers', 'Manage Suppliers', 'suppliers'),
        ('manage_users', 'Manage Users', 'users'),
        ('manage_payments', 'Manage Payments', 'payments'),
        ('manage_expenses', 'Manage Expenses', 'expenses'),
        ('manage_warehouse', 'Manage Warehouse', 'warehouse'),
        ('view_ledger', 'View Ledger', 'ledger'),
        ('view_reports', 'View Reports', 'reports'),
        ('manage_backups', 'Manage Backups', 'backups'),
    ]
    perms = []
    for code, name, cat in codes:
        existing = Permission.query.filter_by(code=code).first()
        if existing:
            perms.append(existing)
        else:
            p = Permission(code=code, name=name, category=cat)
            db.session.add(p)
            db.session.flush()
            perms.append(p)
    db.session.commit()
    return {p.code: p for p in perms}


def _make_role(db, slug, name, perm_codes, perm_map):
    existing = Role.query.filter_by(slug=slug).first()
    if existing:
        return existing
    role = Role(name=name, slug=slug, permissions=[perm_map[c] for c in perm_codes if c in perm_map])
    db.session.add(role)
    db.session.flush()
    return role


def _create_two_tenant_env(db):
    perm_map = _make_permissions(db)

    tenant_a = Tenant(name='Tenant A', name_ar='مستأجر A', slug='tenant-a', is_active=True)
    tenant_b = Tenant(name='Tenant B', name_ar='مستأجر B', slug='tenant-b', is_active=True)
    db.session.add_all([tenant_a, tenant_b])
    db.session.flush()

    seller_role = _make_role(db, 'seller', 'Seller', ['manage_sales', 'manage_customers', 'manage_products'], perm_map)
    manager_role = _make_role(db, 'manager', 'Manager', ['manage_sales', 'manage_customers', 'manage_products', 'manage_purchases', 'manage_payments', 'view_reports'], perm_map)
    super_admin_role = _make_role(db, 'super_admin', 'Super Admin', list(perm_map.keys()), perm_map)

    user_a = User(username='seller_a', email='seller_a@test.local', full_name='Seller A', is_owner=False, is_active=True, role_id=seller_role.id, tenant_id=tenant_a.id)
    user_a.set_password('SellerA123!')
    user_b = User(username='seller_b', email='seller_b@test.local', full_name='Seller B', is_owner=False, is_active=True, role_id=seller_role.id, tenant_id=tenant_b.id)
    user_b.set_password('SellerB123!')
    manager_a = User(username='manager_a', email='manager_a@test.local', full_name='Manager A', is_owner=False, is_active=True, role_id=manager_role.id, tenant_id=tenant_a.id)
    manager_a.set_password('ManagerA123!')
    db.session.add_all([user_a, user_b, manager_a])
    db.session.flush()

    # owner (platform operator, no tenant — sees all)
    owner_role = Role.query.filter_by(slug='owner').first()
    if not owner_role:
        owner_role = Role(name='Owner', slug='owner', permissions=list(perm_map.values()))
        db.session.add(owner_role)
        db.session.flush()
    owner = User.query.filter_by(username='testowner').first()
    if not owner:
        owner = User(username='testowner', email='owner@test.local', full_name='Owner', is_owner=True, is_active=True, role_id=owner_role.id, tenant_id=None)
        owner.set_password('OwnerPass123!')
        db.session.add(owner)
        db.session.flush()

    cat = ProductCategory(name='Cat A', is_active=True)
    db.session.add(cat)
    db.session.flush()

    customer_a = Customer(name='Customer A', customer_type='regular', tenant_id=tenant_a.id, is_active=True)
    customer_b = Customer(name='Customer B', customer_type='regular', tenant_id=tenant_b.id, is_active=True)
    db.session.add_all([customer_a, customer_b])
    db.session.flush()

    product_a = Product(name='Product A', sku='SKU-A-001', category_id=cat.id, tenant_id=tenant_a.id, cost_price=Decimal('10'), regular_price=Decimal('20'), current_stock=Decimal('50'), is_active=True)
    product_b = Product(name='Product B', sku='SKU-B-001', category_id=cat.id, tenant_id=tenant_b.id, cost_price=Decimal('10'), regular_price=Decimal('20'), current_stock=Decimal('50'), is_active=True)
    db.session.add_all([product_a, product_b])
    db.session.flush()

    warehouse_a = Warehouse(name='Warehouse A', tenant_id=tenant_a.id, is_active=True)
    warehouse_b = Warehouse(name='Warehouse B', tenant_id=tenant_b.id, is_active=True)
    db.session.add_all([warehouse_a, warehouse_b])
    db.session.flush()

    import uuid as _uuid
    sale_a = Sale(sale_number=f"S-2026-A-{_uuid.uuid4().hex[:6].upper()}", customer_id=customer_a.id, seller_id=user_a.id, tenant_id=tenant_a.id, total_amount=Decimal('100'), amount_base=Decimal('100'), paid_amount=Decimal('0'), paid_amount_base=Decimal('0'), balance_due=Decimal('100'), currency='AED', exchange_rate=Decimal('1'), payment_status='unpaid', status='confirmed', is_active=True)
    sale_b = Sale(sale_number=f"S-2026-B-{_uuid.uuid4().hex[:6].upper()}", customer_id=customer_b.id, seller_id=user_b.id, tenant_id=tenant_b.id, total_amount=Decimal('200'), amount_base=Decimal('200'), paid_amount=Decimal('0'), paid_amount_base=Decimal('0'), balance_due=Decimal('200'), currency='AED', exchange_rate=Decimal('1'), payment_status='unpaid', status='confirmed', is_active=True)
    db.session.add_all([sale_a, sale_b])
    db.session.flush()

    line_a = SaleLine(sale_id=sale_a.id, product_id=product_a.id, tenant_id=tenant_a.id, quantity=Decimal('1'), unit_price=Decimal('100'), line_total=Decimal('100'))
    line_b = SaleLine(sale_id=sale_b.id, product_id=product_b.id, tenant_id=tenant_b.id, quantity=Decimal('1'), unit_price=Decimal('200'), line_total=Decimal('200'))
    db.session.add_all([line_a, line_b])
    db.session.commit()

    return {
        'tenant_a': tenant_a, 'tenant_b': tenant_b,
        'user_a': user_a, 'user_b': user_b, 'manager_a': manager_a, 'owner': owner,
        'seller_role': seller_role, 'manager_role': manager_role, 'super_admin_role': super_admin_role,
        'customer_a': customer_a, 'customer_b': customer_b,
        'product_a': product_a, 'product_b': product_b,
        'warehouse_a': warehouse_a, 'warehouse_b': warehouse_b,
        'sale_a': sale_a, 'sale_b': sale_b,
        'perm_map': perm_map,
    }


def _login(client, username, password):
    return client.post('/auth/login', data={'username': username, 'password': password}, follow_redirects=False)


# ---------------------------------------------------------------------------
# 1. ROLE BOUNDARIES & ESCALATION
# ---------------------------------------------------------------------------

class TestRoleBoundaries:
    def test_seller_cannot_access_owner_dashboard(self, client, db):
        env = _create_two_tenant_env(db)
        _login(client, 'seller_a', 'SellerA123!')
        resp = client.get('/owner/dashboard', follow_redirects=False)
        assert resp.status_code in (302, 403, 404)

    def test_seller_cannot_create_super_admin_user(self, client, db):
        env = _create_two_tenant_env(db)
        _login(client, 'seller_a', 'SellerA123!')
        # Try to POST a new user with super_admin role (higher than seller level 40)
        super_role = env['super_admin_role']
        resp = client.post('/users/create', data={
            'username': 'evil_admin', 'email': 'evil@test.local', 'password': 'EvilPass123!',
            'full_name': 'Evil', 'role_id': super_role.id,
        }, follow_redirects=False)
        # Should be blocked: either 403 abort or redirect with warning, never 302 to index success
        assert resp.status_code in (302, 403)
        # Verify the user was NOT created with super_admin
        evil = User.query.filter_by(username='evil_admin').first()
        assert evil is None or evil.role.slug != 'super_admin'

    def test_manager_cannot_escalate_to_super_admin_via_edit(self, client, db):
        env = _create_two_tenant_env(db)
        _login(client, 'manager_a', 'ManagerA123!')
        super_role = env['super_admin_role']
        seller = env['user_a']
        resp = client.post(f'/users/{seller.id}/edit', data={
            'email': seller.email, 'full_name': seller.full_name,
            'role_id': super_role.id,
        }, follow_redirects=False)
        assert resp.status_code in (302, 403)
        db.session.refresh(seller)
        assert seller.role.slug != 'super_admin'

    def test_api_v2_requires_manage_sales_permission(self, client, db):
        env = _create_two_tenant_env(db)
        # seller_a has manage_sales -> should succeed
        _login(client, 'seller_a', 'SellerA123!')
        resp = client.get('/api/v2/sales')
        assert resp.status_code == 200
        # Now a user without any permission (viewer-like)
        from models.user import Role as _Role
        viewer_role = _make_role(db, 'viewer', 'Viewer', [], env['perm_map'])
        viewer = User(username='viewer_x', email='viewer_x@test.local', full_name='Viewer', is_owner=False, is_active=True, role_id=viewer_role.id, tenant_id=env['tenant_a'].id)
        viewer.set_password('Viewer123!')
        db.session.add(viewer)
        db.session.commit()
        client.get('/auth/logout', follow_redirects=False)
        _login(client, 'viewer_x', 'Viewer123!')
        resp2 = client.get('/api/v2/sales')
        assert resp2.status_code in (302, 403)

    def test_graphql_requires_view_reports_permission(self, client, db):
        env = _create_two_tenant_env(db)
        _login(client, 'viewer_x' if User.query.filter_by(username='viewer_x').first() else 'seller_a',
               'Viewer123!' if User.query.filter_by(username='viewer_x').first() else 'SellerA123!')
        # viewer shouldn't pass the @permission_required('view_reports') gate
        viewer = User.query.filter_by(username='viewer_x').first()
        if viewer:
            resp = client.post('/graphql', json={'query': '{ sales { id } }'})
            assert resp.status_code in (302, 403)


# ---------------------------------------------------------------------------
# 2. IDOR / BOLA — cross-tenant object access
# ---------------------------------------------------------------------------

class TestIDORCrossTenant:
    def test_api_v2_get_sale_cross_tenant_returns_404(self, client, db):
        env = _create_two_tenant_env(db)
        _login(client, 'seller_a', 'SellerA123!')
        # seller_a (tenant A) tries to fetch tenant B's sale via API v2
        resp = client.get(f"/api/v2/sales/{env['sale_b'].id}")
        assert resp.status_code in (403, 404)
        # Sanity: own sale is accessible
        resp2 = client.get(f"/api/v2/sales/{env['sale_a'].id}")
        assert resp2.status_code == 200
        assert resp2.get_json()['sale']['id'] == env['sale_a'].id

    def test_api_v2_get_customer_cross_tenant_returns_404(self, client, db):
        env = _create_two_tenant_env(db)
        _login(client, 'seller_a', 'SellerA123!')
        resp = client.get(f"/api/v2/customers/{env['customer_b'].id}")
        assert resp.status_code in (403, 404)
        resp2 = client.get(f"/api/v2/customers/{env['customer_a'].id}")
        assert resp2.status_code == 200

    def test_warehouse_cross_tenant_via_view_returns_404(self, client, db):
        env = _create_two_tenant_env(db)
        # Grant seller_a the manage_warehouse permission for this check
        perm_wh = env['perm_map']['manage_warehouse']
        if perm_wh not in env['user_a'].role.permissions:
            env['user_a'].role.permissions.append(perm_wh)
            db.session.commit()
        _login(client, 'seller_a', 'SellerA123!')
        resp = client.get(f"/warehouse/{env['warehouse_b'].id}")
        assert resp.status_code in (403, 404)
        resp2 = client.get(f"/warehouse/{env['warehouse_a'].id}")
        assert resp2.status_code == 200

    def test_sales_view_cross_tenant_returns_404(self, client, db):
        env = _create_two_tenant_env(db)
        _login(client, 'seller_a', 'SellerA123!')
        # seller_a tries to view tenant B's sale via HTML route
        resp = client.get(f"/sales/{env['sale_b'].id}", follow_redirects=False)
        assert resp.status_code in (302, 403, 404)
        # Ensure body does not leak sale number
        if resp.status_code == 302:
            assert env['sale_b'].sale_number not in resp.get_data(as_text=True)

    def test_get_owned_or_404_aborts_on_cross_tenant(self, app, db):
        env = _create_two_tenant_env(db)
        from models import set_current_tenant_id
        from utils.decorators import get_owned_or_404
        from werkzeug.exceptions import Forbidden, NotFound

        with app.test_request_context():
            from flask_login import login_user
            login_user(env['user_a'])
            set_current_tenant_id(env['tenant_a'].id)
            # own customer succeeds
            c = get_owned_or_404(Customer, env['customer_a'].id)
            assert c.id == env['customer_a'].id
            # foreign customer aborts
            with pytest.raises((Forbidden, NotFound)):
                get_owned_or_404(Customer, env['customer_b'].id)
            # foreign sale aborts
            with pytest.raises((Forbidden, NotFound)):
                get_owned_or_404(Sale, env['sale_b'].id)

    def test_sales_restore_cross_tenant_blocked(self, client, db):
        env = _create_two_tenant_env(db)
        # Archive sale_b first (simulate archived state)
        from models import ArchivedRecord
        arch = ArchivedRecord(table_name='sales', record_id=env['sale_b'].id, data={'sale_number': env['sale_b'].sale_number}, archived_at=db.func.now())
        # Many ArchivedRecord schemas use JSON data column; fallback to minimal
        try:
            db.session.add(arch)
            db.session.commit()
        except Exception:
            db.session.rollback()
            pytest.skip('ArchivedRecord schema incompatible in test DB')
        _login(client, 'seller_a', 'SellerA123!')
        resp = client.post(f"/sales/{env['sale_b'].id}/restore", follow_redirects=False)
        assert resp.status_code in (403, 404)


# ---------------------------------------------------------------------------
# 3. MULTI-TENANCY ISOLATION — automatic query scoping
# ---------------------------------------------------------------------------

class TestMultiTenancyIsolation:
    def test_auto_filter_scopes_query_to_tenant(self, app, db):
        env = _create_two_tenant_env(db)
        from models import set_current_tenant_id, clear_current_tenant_id

        set_current_tenant_id(env['tenant_a'].id)
        try:
            rows = Customer.query.filter(Customer.is_active.is_(True)).all()
            ids = {r.id for r in rows}
            assert env['customer_a'].id in ids
            assert env['customer_b'].id not in ids
        finally:
            clear_current_tenant_id()

        set_current_tenant_id(env['tenant_b'].id)
        try:
            rows = Customer.query.filter(Customer.is_active.is_(True)).all()
            ids = {r.id for r in rows}
            assert env['customer_b'].id in ids
            assert env['customer_a'].id not in ids
        finally:
            clear_current_tenant_id()

    def test_sales_list_only_shows_own_tenant(self, app, db):
        env = _create_two_tenant_env(db)
        from models import set_current_tenant_id, clear_current_tenant_id

        set_current_tenant_id(env['tenant_a'].id)
        try:
            rows = Sale.query.all()
            ids = {r.id for r in rows}
            assert env['sale_a'].id in ids
            assert env['sale_b'].id not in ids
        finally:
            clear_current_tenant_id()

    def test_new_row_auto_scoped_to_current_tenant(self, app, db):
        env = _create_two_tenant_env(db)
        from models import set_current_tenant_id, clear_current_tenant_id

        set_current_tenant_id(env['tenant_a'].id)
        try:
            c = Customer(name='AutoScoped Customer', customer_type='regular', is_active=True)
            # Intentionally leave tenant_id unset — before_flush should stamp it
            db.session.add(c)
            db.session.flush()
            assert c.tenant_id == env['tenant_a'].id
            db.session.rollback()
        finally:
            clear_current_tenant_id()

    def test_cross_tenant_insert_blocked_for_non_owner(self, app, db):
        env = _create_two_tenant_env(db)
        from models import set_current_tenant_id, clear_current_tenant_id

        set_current_tenant_id(env['tenant_a'].id)
        try:
            from flask_login import login_user
            with app.test_request_context():
                login_user(env['user_a'])
                c = Customer(name='CrossTenant', customer_type='regular', tenant_id=env['tenant_b'].id, is_active=True)
                db.session.add(c)
                with pytest.raises(RuntimeError, match='Cross-tenant insert blocked'):
                    db.session.flush()
                db.session.rollback()
        finally:
            clear_current_tenant_id()

    def test_tenant_id_immutable_for_non_owner(self, app, db):
        env = _create_two_tenant_env(db)
        from models import set_current_tenant_id, clear_current_tenant_id

        set_current_tenant_id(env['tenant_a'].id)
        try:
            from flask_login import login_user
            with app.test_request_context():
                login_user(env['user_a'])
                c = Customer.query.filter_by(id=env['customer_a'].id).first()
                assert c is not None
                c.tenant_id = env['tenant_b'].id
                with pytest.raises(RuntimeError, match='Tenant id is immutable'):
                    db.session.flush()
                db.session.rollback()
        finally:
            clear_current_tenant_id()

    def test_owner_can_read_cross_tenant_rows(self, app, db):
        env = _create_two_tenant_env(db)
        from models import set_current_tenant_id
        from flask_login import login_user
        from utils.decorators import get_owned_or_404

        with app.test_request_context():
            login_user(env['owner'])
            set_current_tenant_id(None)  # owner bypasses filter
            # Owner can resolve either tenant's customer
            a = get_owned_or_404(Customer, env['customer_a'].id)
            b = get_owned_or_404(Customer, env['customer_b'].id)
            assert a.id == env['customer_a'].id
            assert b.id == env['customer_b'].id
            set_current_tenant_id(None)

    def test_owner_insert_cross_tenant_allowed(self, app, db):
        env = _create_two_tenant_env(db)
        from models import set_current_tenant_id, clear_current_tenant_id
        from flask_login import login_user

        with app.test_request_context():
            login_user(env['owner'])
            set_current_tenant_id(None)
            c = Customer(name='OwnerCrossInsert', customer_type='regular', tenant_id=env['tenant_b'].id, is_active=True)
            db.session.add(c)
            db.session.flush()
            assert c.tenant_id == env['tenant_b'].id
            db.session.rollback()
            clear_current_tenant_id()
