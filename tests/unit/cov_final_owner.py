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


# ---------------------------------------------------------------------------
# Role editor (Owner Panel -> Roles & Permissions)
# ---------------------------------------------------------------------------

class TestRoleEditor:
    """Interactive permission editor for non-owner roles.

    Contract under test (models/user.py can_see_costs is permission-driven):
    - Owner role is never exposed nor editable (bypass-based access).
    - view_costs may only be granted to cost-bearing roles.
    - Every change is written to the audit log.
    """

    PASSWORD = 'OwnerPass123!'

    @pytest.fixture(scope='function')
    def staff_role(self, db):
        """A non-privileged editable role (acts as 'seller')."""
        # owner_user fixture may have already created manage_sales — reuse it.
        perm = Permission.query.filter_by(code='manage_sales').first()
        if perm is None:
            perm = Permission(code='manage_sales', name='Manage Sales', category='sales')
            db.session.add(perm)
            db.session.flush()
        role = Role(name='Seller', name_ar='بائع', slug='seller', permissions=[perm])
        db.session.add(role)
        db.session.flush()
        return role

    @pytest.fixture(scope='function')
    def manager_role(self, db):
        """A cost-bearing role (matches _COST_BEARING_ROLE_SLUGS)."""
        return Role(name='Manager', name_ar='مدير', slug='manager')

    @pytest.fixture(scope='function')
    def logged_in_owner(self, client, owner_user):
        client.get('/auth/logout', follow_redirects=True)
        client.post('/auth/login', data={
            'username': owner_user.username, 'password': self.PASSWORD,
        }, follow_redirects=True)
        return owner_user

    def test_editor_page_renders_roles_and_permissions(self, client, logged_in_owner, staff_role):
        resp = client.get('/owner/roles-permissions')
        assert resp.status_code == 200
        body = resp.data
        # Editable roles rendered with their slugs
        assert b'seller' in body
        assert b'manage_sales' in body
        # The view_costs control exists, and the security notice is shown
        assert b'view_costs' in body
        assert 'محرر صلاحيات الأدوار'.encode() in body

    def test_owner_role_hidden_from_editor(self, client, logged_in_owner):
        resp = client.get('/owner/roles-permissions')
        assert resp.status_code == 200
        # The owner role's checkbox form must not be rendered at all
        assert b'name="owner"' not in resp.data
        assert b"value=\"owner\"" not in resp.data

    def test_grant_permission_to_role(self, client, logged_in_owner, manager_role, db):
        db.session.add(manager_role)
        db.session.commit()
        resp = client.post(
            f'/owner/roles/{manager_role.id}/permissions',
            data={'permissions': ['view_costs']},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        db.session.expire(manager_role)
        assert manager_role.has_permission('view_costs')

    def test_revoke_all_permissions(self, client, logged_in_owner, staff_role, db):
        resp = client.post(
            f'/owner/roles/{staff_role.id}/permissions',
            data={},  # no checkboxes -> empty set
            follow_redirects=False,
        )
        assert resp.status_code == 302
        db.session.expire(staff_role)
        assert staff_role.permissions == []

    def test_owner_role_not_editable_via_post(self, client, logged_in_owner, owner_user, db):
        owner_role = owner_user.role
        before = {p.code for p in owner_role.permissions}
        resp = client.post(
            f'/owner/roles/{owner_role.id}/permissions',
            data={'permissions': ['manage_sales']},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        db.session.expire(owner_role)
        assert {p.code for p in owner_role.permissions} == before

    def test_view_costs_restricted_to_cost_bearing_roles(self, client, logged_in_owner, staff_role, db):
        resp = client.post(
            f'/owner/roles/{staff_role.id}/permissions',
            data={'permissions': ['manage_sales', 'view_costs']},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        db.session.expire(staff_role)
        assert not staff_role.has_permission('view_costs')
        # manage_sales was already present and resubmitted — kept intact
        assert staff_role.has_permission('manage_sales')

    def test_unknown_permission_code_rejected(self, client, logged_in_owner, staff_role, db):
        before = {p.code for p in staff_role.permissions}
        resp = client.post(
            f'/owner/roles/{staff_role.id}/permissions',
            data={'permissions': ['totally_bogus_perm']},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        db.session.expire(staff_role)
        assert {p.code for p in staff_role.permissions} == before

    def test_update_writes_audit_log(self, client, logged_in_owner, staff_role, db):
        from models import AuditLog
        # staff_role already has manage_sales — an empty submission revokes it,
        # which must be recorded in the audit trail.
        client.post(
            f'/owner/roles/{staff_role.id}/permissions',
            data={},
            follow_redirects=False,
        )
        log = (AuditLog.query.filter_by(table_name='roles', record_id=staff_role.id)
               .order_by(AuditLog.id.desc()).first())
        assert log is not None
        assert log.changes['role'] == 'seller'
        assert log.changes['removed_permissions'] == ['manage_sales']

    def test_noop_submit_redirects_with_info(self, client, logged_in_owner, staff_role, db):
        resp = client.post(
            f'/owner/roles/{staff_role.id}/permissions',
            data={'permissions': ['manage_sales']},  # identical to current state
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert '/owner/roles-permissions' in resp.headers['Location']

    def test_non_owner_cannot_edit(self, client, db, staff_role):
        """Non-owner session gets redirected and nothing changes."""
        perm = Permission.query.filter_by(code='manage_sales').first()
        user = User(username='plainstaff', email='plainstaff@test.com',
                    is_active=True, role_id=staff_role.id)
        user.set_password('StaffPass123!')
        db.session.add(user)
        db.session.commit()

        client.get('/auth/logout', follow_redirects=True)
        client.post('/auth/login', data={
            'username': 'plainstaff', 'password': 'StaffPass123!',
        }, follow_redirects=True)

        resp = client.post(
            f'/owner/roles/{staff_role.id}/permissions',
            data={'permissions': ['view_costs']},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        db.session.expire(staff_role)
        assert not staff_role.has_permission('view_costs')
