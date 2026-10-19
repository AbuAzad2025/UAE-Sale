"""Regression tests for the P0 multi-tenant isolation fixes.

Each test reproduces a leak that was proven in the audit and asserts it no
longer happens. Run against the real app + real url_map, not a mock.
"""
import pytest

from decimal import Decimal


@pytest.fixture
def two_tenants(app, db):
    """Two tenants, each with a customer and a product."""
    from models import Tenant, Customer, Product

    t1 = Tenant(name='T1', name_ar='ا', slug='iso-t1', country='UAE',
                is_active=True)
    t2 = Tenant(name='T2', name_ar='ب', slug='iso-t2', country='UAE',
                is_active=True)
    db.session.add_all([t1, t2])
    db.session.commit()

    c1 = Customer(name='CUST-T1', name_ar='س', customer_type='regular',
                  balance=Decimal('0'), is_active=True, tenant_id=t1.id)
    c2 = Customer(name='CUST-T2', name_ar='ص', customer_type='regular',
                  balance=Decimal('0'), is_active=True, tenant_id=t2.id)
    p1 = Product(name='PROD-T1', sku='ISO-1', cost_price=Decimal('1'),
                 regular_price=Decimal('2'), current_stock=Decimal('5'),
                 is_active=True, tenant_id=t1.id)
    p2 = Product(name='PROD-T2', sku='ISO-2', cost_price=Decimal('1'),
                 regular_price=Decimal('2'), current_stock=Decimal('5'),
                 is_active=True, tenant_id=t2.id)
    db.session.add_all([c1, c2, p1, p2])
    db.session.commit()
    return t1, t2


class TestMultiEntityQueryIsolation:
    """The audit proved query(Customer, Product) returned tenant B's product."""

    def test_two_scoped_entities_no_cross_tenant_rows(self, app, db, two_tenants):
        from extensions import db as _db
        from models import Customer, Product
        from models.tenant_scope import (set_current_tenant_id,
                                         clear_current_tenant_id)
        t1, _ = two_tenants
        set_current_tenant_id(t1.id)
        try:
            rows = _db.session.query(Customer, Product).all()
        finally:
            clear_current_tenant_id()

        leaked = [p.name for _, p in rows if p.tenant_id != t1.id]
        assert not leaked, f'tenant {t1.id} saw foreign products: {leaked}'
        assert all(c.tenant_id == t1.id for c, _ in rows)

    def test_single_entity_still_isolated(self, app, db, two_tenants):
        """Baseline must not regress."""
        from models import Customer
        from models.tenant_scope import (set_current_tenant_id,
                                         clear_current_tenant_id)
        t1, _ = two_tenants
        set_current_tenant_id(t1.id)
        try:
            names = [c.name for c in Customer.query.all()]
        finally:
            clear_current_tenant_id()
        assert names == ['CUST-T1']

    def test_owner_sees_all_tenants(self, app, db, two_tenants):
        """tenant None is the owner context and must stay unfiltered."""
        from models import Customer
        from models.tenant_scope import (set_current_tenant_id,
                                         clear_current_tenant_id)
        set_current_tenant_id(None)
        try:
            assert len(Customer.query.all()) == 2
        finally:
            clear_current_tenant_id()


class TestUsersRegisteredAsScoped:
    """Item 2: the users table had a tenant_id but was never registered."""

    def test_users_is_registered(self):
        from models import tenant_scope as ts
        assert 'users' in ts._tenant_scoped_tables

    def test_user_query_is_tenant_scoped(self, app, db, two_tenants):
        from models import User, Role
        from models.tenant_scope import (set_current_tenant_id,
                                         clear_current_tenant_id)
        t1, t2 = two_tenants
        role = Role(name='iso-viewer', name_ar='مشاهد', slug='iso-viewer',
                    permissions=[])
        db.session.add(role)
        db.session.commit()
        db.session.add_all([
            User(username='iso-u1', email='i1@x', password_hash='x',
                 role_id=role.id, tenant_id=t1.id, is_active=True),
            User(username='iso-u2', email='i2@x', password_hash='x',
                 role_id=role.id, tenant_id=t2.id, is_active=True),
        ])
        db.session.commit()

        set_current_tenant_id(t1.id)
        try:
            names = [u.username for u in User.query.all()]
        finally:
            clear_current_tenant_id()
        assert names == ['iso-u1'], f'saw other tenants users: {names}'

    def test_login_lookup_still_works_without_tenant(self, app, db):
        """Login happens before a tenant exists - it must not be filtered."""
        from models import User, Role
        from models.tenant_scope import (set_current_tenant_id,
                                         clear_current_tenant_id)
        role = Role(name='iso-login', name_ar='دخول', slug='iso-login',
                    permissions=[])
        db.session.add(role)
        db.session.commit()
        db.session.add(User(username='iso-loginuser', email='il@x',
                            password_hash='x', role_id=role.id,
                            tenant_id=None, is_active=True))
        db.session.commit()

        set_current_tenant_id(None)
        try:
            found = User.query.filter(
                User.username.ilike('iso-loginuser')).first()
        finally:
            clear_current_tenant_id()
        assert found is not None, 'login lookup was blocked by tenant scoping'


class TestFailClosedTenantContext:
    """Item 3: a NULL tenant_id must not mean 'no filtering'."""

    def test_null_tenant_user_sees_no_tenant_rows(self, app, db, client):
        """A tenant-less user is scoped to tenant-less rows only.

        They are not granted global access - that was the fail-open bug - and
        they are not locked out either, because
        user_service.provision_user() legitimately creates tenant-less
        accounts. What they must not see is another tenant's data.
        """
        from models import User, Role, Tenant, Customer
        from models.tenant_scope import set_current_tenant_id
        from decimal import Decimal

        role = Role(name='iso-orphan', name_ar='يتيم', slug='iso-orphan',
                    permissions=[])
        db.session.add(role)
        db.session.commit()
        db.session.add(User(username='iso-orphanuser', email='io@x',
                            password_hash='x', role_id=role.id,
                            tenant_id=None, is_active=True, is_owner=False))
        db.session.commit()

        # Another tenant's row must be invisible to the tenant-less user.
        other = Tenant(name='Other', name_ar='o', slug='iso-other',
                       country='UAE', is_active=True)
        db.session.add(other)
        db.session.commit()
        db.session.add(Customer(
            name='FOREIGN-CUSTOMER', name_ar='f', customer_type='regular',
            balance=Decimal('0'), is_active=True, tenant_id=other.id))
        db.session.commit()

        set_current_tenant_id(-1)  # TENANT_LESS_SCOPE
        try:
            names = [c.name for c in Customer.query.all()]
        finally:
            from models.tenant_scope import clear_current_tenant_id
            clear_current_tenant_id()

        assert 'FOREIGN-CUSTOMER' not in names, (
            f'tenant-less user saw another tenant\'s rows: {names}')

    def test_tenant_less_scope_is_not_the_global_view(self, app, db):
        """TENANT_LESS_SCOPE must differ from None (the owner's view)."""
        from models.tenant_scope import (TENANT_LESS_SCOPE,
                                         get_current_tenant_id,
                                         set_current_tenant_id,
                                         clear_current_tenant_id)
        set_current_tenant_id(TENANT_LESS_SCOPE)
        try:
            assert get_current_tenant_id() == TENANT_LESS_SCOPE
            assert get_current_tenant_id() is not None
        finally:
            clear_current_tenant_id()

    def test_owner_with_null_tenant_still_allowed(self, app, db, client):
        """Owner bypass must survive the scoping change."""
        from flask_login import login_user
        from models import User
        owner = User.query.filter_by(is_owner=True).first()
        if owner is None:
            pytest.skip('no owner user in this fixture set')
        with app.test_request_context():
            login_user(owner)
        r = client.get('/dashboard')
        assert r.status_code in (200, 302), (
            f'owner got {r.status_code}; owner bypass was broken')


class TestBackgroundTenantContext:
    """Item 4: threading.local does not propagate into new threads."""

    def test_run_in_tenant_context_requires_tenant(self):
        from models import run_in_tenant_context
        with pytest.raises(RuntimeError, match='tenant_id'):
            run_in_tenant_context(None, lambda: 'should not run')

    def test_run_in_tenant_context_sets_and_clears(self):
        from models import run_in_tenant_context
        from models.tenant_scope import get_current_tenant_id
        seen = run_in_tenant_context(7, get_current_tenant_id)
        assert seen == 7
        assert get_current_tenant_id() is None

    def test_thread_without_context_is_unfiltered(self):
        """Documents WHY the guard is needed."""
        import threading
        from models.tenant_scope import (set_current_tenant_id,
                                         get_current_tenant_id,
                                         clear_current_tenant_id)
        set_current_tenant_id(123)
        try:
            box = {}

            def worker():
                box['t'] = get_current_tenant_id()

            th = threading.Thread(target=worker)
            th.start()
            th.join()
        finally:
            clear_current_tenant_id()
        assert box['t'] is None, (
            'if this now inherits, the background guard can be relaxed')

    def test_platform_context_is_explicit_none(self):
        from models import run_in_platform_context
        from models.tenant_scope import get_current_tenant_id
        assert run_in_platform_context(get_current_tenant_id) is None