"""
Domain H — Multi-Tenant isolation, RBAC and IDOR.

Real mechanism (models/tenant_scope.py:205-274):
  * A SQLAlchemy `before_compile` event appends `entity.tenant_id == <current>`
    to queries whose PRIMARY entity is a tenant-scoped table.
  * When no tenant is set the filter is skipped entirely — that is how the
    platform owner gets a global view.
  * The filter applies to the primary entity only, so a query rooted on a
    non-scoped model can still reach another tenant's rows. That is asserted
    below rather than assumed safe.
  * `_before_flush_tenant_guard` makes tenant_id immutable on update.
"""

from decimal import Decimal

import pytest

from extensions import db
from models import Tenant, Customer, Product, ProductCategory
from models.tenant_scope import (
    set_current_tenant_id, clear_current_tenant_id, get_current_tenant_id,
)
from models.gl import GLJournalEntry, GLJournalLine, GLAccount
from tests.e2e.harness import ACC, manual_entry_form, entry_id_from_redirect


@pytest.fixture
def tenants(db):
    """Two isolated businesses."""
    a = Tenant(name='Tenant A', name_ar='أ', slug='tenant-a',
               country='UAE', is_active=True)
    b = Tenant(name='Tenant B', name_ar='ب', slug='tenant-b',
               country='UAE', is_active=True)
    db.session.add_all([a, b])
    db.session.commit()
    return a, b


def _seed_customer(db, tenant, name):
    c = Customer(name=name, name_ar=name, customer_type='regular',
                 phone='+0000000000', email=f'{name}@test.local',
                 credit_limit=Decimal('1000'), balance=Decimal('0'),
                 is_active=True, tenant_id=tenant.id)
    db.session.add(c)
    db.session.commit()
    return c


@pytest.fixture
def tenant_user(db, users, tenants):
    """branch_manager scoped to tenant A, so a real non-owner user.

    The `users` fixture stamps every non-owner with e2e_tenant.id at
    construction time. Re-pointing a persisted row at tenants[0] is now
    rejected by the tenant-immutability guard (`users` is tenant-scoped), so
    this fixture builds a dedicated user for tenant A instead.

    It reuses the branch_manager ROLE from the shared fixture rather than
    building a new one: `_make_user` creates one Role per user, and a role
    rebuilt from scratch carries a different permission set - a fresh
    branch_manager without view_customers cannot open /customers/ at all,
    which is a permission failure (403), not a tenant leak.
    """
    from models import User
    source = users['branch_manager']
    user = User(username='domh_branch_mgr', email='domh@branch.local',
                full_name='DomH Branch Manager', is_owner=False,
                is_active=True, role_id=source.role_id,
                tenant_id=tenants[0].id)
    user.set_password('ManagerPass123!')
    db.session.add(user)
    db.session.commit()
    return user


class TestTenantScoping:
    def test_query_returns_only_current_tenant_rows(self, db, tenants):
        a, b = tenants
        _seed_customer(db, a, 'A-customer')
        _seed_customer(db, b, 'B-customer')

        clear_current_tenant_id()
        set_current_tenant_id(a.id)
        try:
            names = {c.name for c in Customer.query.all()}
        finally:
            clear_current_tenant_id()

        assert names == {'A-customer'}, (
            f'tenant A saw {names} — cross-tenant leak')

    def test_switching_tenant_switches_the_visible_set(self, db, tenants):
        a, b = tenants
        _seed_customer(db, a, 'A-customer')
        _seed_customer(db, b, 'B-customer')

        clear_current_tenant_id()
        try:
            set_current_tenant_id(a.id)
            assert {c.name for c in Customer.query.all()} == {'A-customer'}
            set_current_tenant_id(b.id)
            assert {c.name for c in Customer.query.all()} == {'B-customer'}
        finally:
            clear_current_tenant_id()

    def test_no_tenant_context_means_no_filtering(self, db, tenants):
        """This is the owner's global view — and the reason every isolation
        test must set a tenant explicitly."""
        a, b = tenants
        _seed_customer(db, a, 'A-customer')
        _seed_customer(db, b, 'B-customer')

        clear_current_tenant_id()
        assert get_current_tenant_id() is None
        assert {c.name for c in Customer.query.all()} == {'A-customer', 'B-customer'}

    def test_gl_is_tenant_scoped_too(self, db, users, login_as, client, tenants):
        a, b = tenants
        login_as('owner')
        r = client.post('/ledger/manual-entry', data=manual_entry_form(
            'tenant scoped entry',
            [{'account': ACC['cash'], 'debit': 100},
             {'account': ACC['sales_revenue'], 'credit': 100}],
        ))
        eid = entry_id_from_redirect(r)
        assert eid is not None

        clear_current_tenant_id()
        try:
            set_current_tenant_id(b.id)
            assert GLJournalEntry.query.all() == [], (
                f'entry {eid} created under no tenant leaked into tenant B')
            set_current_tenant_id(None)
            assert GLJournalEntry.query.filter_by(id=eid).first() is not None
        finally:
            clear_current_tenant_id()

    def test_join_from_unscoped_primary_cannot_reach_other_tenant(
            self, db, tenants):
        """The before_compile filter now scopes EVERY tenant-scoped entity.

        A query rooted on the unscoped GLAccount must no longer leak another
        tenant's GLJournalLine rows.
        """
        a, b = tenants
        entry = GLJournalEntry(entry_number='JE-T1', description='tenant A entry',
                               total_debit=100, total_credit=100, is_posted=True,
                               tenant_id=a.id)
        db.session.add(entry)
        db.session.flush()
        cash = db.session.query(GLAccount).filter_by(
            code=ACC['cash']).first()
        line = GLJournalLine(entry_id=entry.id, account_id=cash.id,
                             debit=100, credit=0, amount_base=100,
                             tenant_id=a.id)
        db.session.add(line)
        db.session.commit()

        clear_current_tenant_id()
        try:
            set_current_tenant_id(b.id)
            pairs = db.session.query(GLAccount, GLJournalLine).join(
                GLJournalLine, GLJournalLine.account_id == GLAccount.id
            ).filter(GLAccount.code == ACC['cash']).all()
            leaked_tenants = {ln.tenant_id for _, ln in pairs}
            assert a.id not in leaked_tenants, (
                f'tenant B (id={b.id}) reached tenant A journal lines: '
                f'{leaked_tenants}')
        finally:
            clear_current_tenant_id()

    def test_tenant_id_is_immutable_on_update(self, db, tenants):
        a, b = tenants
        cust = _seed_customer(db, a, 'A-customer')
        cust.name = 'A-renamed'
        try:
            cust.tenant_id = b.id
            db.session.commit()
        except Exception:
            db.session.rollback()
        db.session.refresh(cust)
        assert cust.tenant_id == a.id, (
            f'tenant_id was reassigned to {cust.tenant_id}')


class TestRequestScopedIsolation:
    def test_request_context_scopes_a_non_owner_user(
            self, client, db, users, tenant_user, tenants):
        """A non-owner request must be scoped to their own tenant."""
        a, b = tenants
        _seed_customer(db, a, 'A-customer')
        _seed_customer(db, b, 'B-customer')

        resp = client.post('/auth/login', data={
            'username': tenant_user.username, 'password': 'ManagerPass123!',
        })
        assert resp.status_code in (302, 303)

        r = client.get('/customers/')
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert 'A-customer' in body
        assert 'B-customer' not in body, (
            'tenant B customer leaked into tenant A response')

    def test_owner_sees_both_tenants(self, client, db, users, tenants):
        """Owner bypasses tenant scoping (app.py before_request)."""
        a, b = tenants
        _seed_customer(db, a, 'A-customer')
        _seed_customer(db, b, 'B-customer')

        client.post('/auth/login', data={
            'username': users['owner'].username, 'password': 'OwnerPass123!'})
        r = client.get('/customers/')
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert 'A-customer' in body and 'B-customer' in body, (
            'owner should have a cross-tenant view')


class TestIdor:
    def test_cross_tenant_record_access_is_forbidden(
            self, client, db, users, tenant_user, tenants):
        """A tenant-A user asking for a tenant-B record must be refused.

        utils/decorators.get_owned_or_404 403s on a cross-tenant row and 404s
        only on a genuinely missing one, so 403 is the documented contract for
        this case — the row exists but belongs to another tenant. The test also
        asserts no field of the record is echoed back.
        """
        a, b = tenants
        b_customer = _seed_customer(db, b, 'B-customer')

        client.post('/auth/login', data={
            'username': tenant_user.username, 'password': 'ManagerPass123!'})
        r = client.get(f'/customers/{b_customer.id}')
        assert r.status_code == 403, (
            f'cross-tenant read returned {r.status_code}, expected 403 '
            f'(get_owned_or_404 contract)')
        assert 'B-customer' not in r.get_data(as_text=True), (
            'denied response leaked the record name')

    def test_missing_record_is_404_not_403(
            self, client, db, users, tenant_user, tenants):
        """Contrast case: a non-existent id must 404, proving the 403 above is
        a tenant decision rather than a blanket error."""
        client.post('/auth/login', data={
            'username': tenant_user.username, 'password': 'ManagerPass123!'})
        r = client.get('/customers/99999999')
        assert r.status_code == 404, f'expected 404, got {r.status_code}'

    def test_anonymous_cannot_reach_protected_data(self, anonymous, db, tenants):
        a, b = tenants
        _seed_customer(db, a, 'A-customer')
        for path in ('/customers/', '/sales/', '/ledger/', '/warehouse/'):
            r = anonymous.get(path)
            assert r.status_code in (302, 303), (
                f'{path} returned {r.status_code} to an anonymous client')
            assert '/auth/login' in r.headers.get('Location', ''), (
                f'{path} did not redirect to login')
