"""Unit tests for the owner tenant-management layer (routes/owner.py).

Covers: owner-only access (stealth 404 for others), create/edit with
server-side validation, suspend/activate with the last-active guard, and
a regression check that row-level tenant isolation still holds after
management operations.
"""
import pytest

from models import Tenant, User, Customer, Role
from models import set_current_tenant_id, clear_current_tenant_id
from extensions import db as _db


def _login(client, username, password):
    return client.post('/auth/login', data={
        'username': username, 'password': password,
    }, follow_redirects=True)


def _owner_login(client, owner_user):
    return _login(client, 'testowner', 'OwnerPass123!')


def _tenant_payload(slug='branch-a', name_ar='فرع أ', name_en='Branch A'):
    return {
        'name_ar': name_ar, 'name_en': name_en, 'slug': slug,
        'business_type': 'garage', 'industry': 'automotive',
        'city': 'Dubai', 'country': 'UAE',
        'phone_1': '', 'phone_2': '', 'mobile': '',
        'email': '', 'website': '',
        'tax_number': '', 'commercial_register': '', 'license_number': '',
        'default_currency': 'ILS', 'default_language': 'ar',
        'timezone': 'Asia/Dubai',
        'subscription_plan': 'basic',
        'max_users': '5', 'max_products': '1000', 'max_customers': '500',
    }


class TestTenantAccess:
    def test_list_owner_200(self, client, owner_user):
        _owner_login(client, owner_user)
        resp = client.get('/owner/tenants')
        assert resp.status_code == 200
        assert 'المستأجرين' in resp.get_data(as_text=True)

    def test_list_anonymous_redirects_to_login(self, client, db):
        resp = client.get('/owner/tenants', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_list_seller_404(self, client, seller_user):
        _login(client, 'testseller', 'SellerPass123!')
        assert client.get('/owner/tenants').status_code == 404

    def test_detail_unknown_404(self, client, owner_user):
        _owner_login(client, owner_user)
        assert client.get('/owner/tenants/99999').status_code == 404


class TestTenantCreate:
    def test_create_success(self, client, owner_user):
        _owner_login(client, owner_user)
        resp = client.post('/owner/tenants/new',
                           data=_tenant_payload(), follow_redirects=False)
        assert resp.status_code == 302
        assert '/owner/tenants/' in resp.headers['Location']
        t = Tenant.query.filter_by(slug='branch-a').first()
        assert t is not None
        assert t.name_ar == 'فرع أ'
        assert t.is_active is True
        assert t.is_suspended is False

    def test_create_slug_normalized(self, client, owner_user):
        _owner_login(client, owner_user)
        payload = _tenant_payload(slug='  Branch-B  ')
        client.post('/owner/tenants/new', data=payload)
        assert Tenant.query.filter_by(slug='branch-b').first() is not None

    def test_create_duplicate_slug_rejected(self, client, owner_user):
        _owner_login(client, owner_user)
        client.post('/owner/tenants/new', data=_tenant_payload(slug='dup-x'))
        before = Tenant.query.count()
        resp = client.post('/owner/tenants/new',
                           data=_tenant_payload(slug='dup-x', name_en='Other'))
        assert resp.status_code == 200
        assert Tenant.query.count() == before
        assert 'مستخدم بالفعل' in resp.get_data(as_text=True)

    def test_create_invalid_slug_rejected(self, client, owner_user):
        _owner_login(client, owner_user)
        before = Tenant.query.count()
        resp = client.post('/owner/tenants/new',
                           data=_tenant_payload(slug='bad slug!!'))
        assert resp.status_code == 200
        assert Tenant.query.count() == before

    def test_create_missing_name_rejected(self, client, owner_user):
        _owner_login(client, owner_user)
        payload = _tenant_payload()
        payload['name_ar'] = ''
        payload['name_en'] = ''
        resp = client.post('/owner/tenants/new', data=payload)
        assert resp.status_code == 200
        assert Tenant.query.filter_by(slug='branch-a').first() is None

    def test_seller_cannot_create(self, client, seller_user):
        _login(client, 'testseller', 'SellerPass123!')
        before = Tenant.query.count()
        resp = client.post('/owner/tenants/new', data=_tenant_payload())
        assert resp.status_code == 404
        assert Tenant.query.count() == before


class TestTenantEdit:
    def test_edit_updates_fields(self, client, owner_user):
        _owner_login(client, owner_user)
        client.post('/owner/tenants/new', data=_tenant_payload())
        t = Tenant.query.filter_by(slug='branch-a').first()
        payload = _tenant_payload(slug='branch-a2', name_ar='فرع أ معدل')
        payload.update({'is_active': 'on'})
        resp = client.post(f'/owner/tenants/{t.id}/edit', data=payload,
                           follow_redirects=False)
        assert resp.status_code == 302
        _db.session.refresh(t)
        assert t.slug == 'branch-a2'
        assert t.name_ar == 'فرع أ معدل'

    def test_edit_duplicate_slug_rejected(self, client, owner_user):
        _owner_login(client, owner_user)
        client.post('/owner/tenants/new', data=_tenant_payload(slug='t-one', name_en='One'))
        client.post('/owner/tenants/new', data=_tenant_payload(slug='t-two', name_en='Two'))
        two = Tenant.query.filter_by(slug='t-two').first()
        payload = _tenant_payload(slug='t-one', name_ar='فرع أ')
        payload.update({'is_active': 'on'})
        resp = client.post(f'/owner/tenants/{two.id}/edit', data=payload)
        assert resp.status_code == 200
        _db.session.refresh(two)
        assert two.slug == 't-two'


class TestTenantSuspendActivate:
    def test_suspend_last_active_blocked(self, client, owner_user):
        _owner_login(client, owner_user)
        # Deterministic setup: only the two tenants below are active.
        Tenant.query.update({'is_active': False})
        _db.session.commit()
        client.post('/owner/tenants/new',
                    data=_tenant_payload(slug='la-one', name_en='LA1'))
        client.post('/owner/tenants/new',
                    data=_tenant_payload(slug='la-two', name_en='LA2'))
        one = Tenant.query.filter_by(slug='la-one').first()
        two = Tenant.query.filter_by(slug='la-two').first()
        # Suspending one of two actives is allowed...
        client.post(f'/owner/tenants/{one.id}/suspend', follow_redirects=False)
        _db.session.refresh(one)
        assert one.is_active is False
        # ...but suspending the remaining last active is refused.
        client.post(f'/owner/tenants/{two.id}/suspend', follow_redirects=False)
        _db.session.refresh(two)
        assert two.is_active is True
        assert two.is_suspended is False

    def test_suspend_and_activate(self, client, owner_user):
        _owner_login(client, owner_user)
        client.post('/owner/tenants/new', data=_tenant_payload(slug='s-one', name_en='S1'))
        client.post('/owner/tenants/new', data=_tenant_payload(slug='s-two', name_en='S2'))
        one = Tenant.query.filter_by(slug='s-one').first()
        resp = client.post(f'/owner/tenants/{one.id}/suspend',
                           data={'suspension_reason': 'test'},
                           follow_redirects=False)
        assert resp.status_code == 302
        _db.session.refresh(one)
        assert one.is_active is False
        assert one.is_suspended is True
        assert one.suspension_reason == 'test'
        resp = client.post(f'/owner/tenants/{one.id}/activate',
                           follow_redirects=False)
        assert resp.status_code == 302
        _db.session.refresh(one)
        assert one.is_active is True
        assert one.is_suspended is False

    def test_seller_cannot_suspend(self, client, owner_user, seller_user):
        _owner_login(client, owner_user)
        client.post('/owner/tenants/new', data=_tenant_payload())
        t = Tenant.query.filter_by(slug='branch-a').first()
        client.get('/auth/logout', follow_redirects=True)
        _login(client, 'testseller', 'SellerPass123!')
        resp = client.post(f'/owner/tenants/{t.id}/suspend')
        assert resp.status_code == 404
        _db.session.refresh(t)
        assert t.is_active is True


class TestTenantIsolationRegression:
    def test_isolation_holds_after_management(self, client, owner_user):
        """Management writes must not weaken row-level isolation.

        NOTE: ``User`` is deliberately NOT auto-filtered (see
        models/__init__.py registry); user isolation is enforced
        explicitly per-route via get_owned_or_404 / filter_by, which is
        exactly the pattern tenant_detail uses.  Auto-filtering is
        asserted on the scoped ``Customer`` model.
        """
        _owner_login(client, owner_user)
        client.post('/owner/tenants/new', data=_tenant_payload(slug='iso-a', name_en='IsoA'))
        client.post('/owner/tenants/new', data=_tenant_payload(slug='iso-b', name_en='IsoB'))
        a = Tenant.query.filter_by(slug='iso-a').first()
        b = Tenant.query.filter_by(slug='iso-b').first()
        role = Role(name='IsoSeller', name_ar='بائع', slug='iso-seller')
        _db.session.add(role)
        _db.session.flush()
        for tenant, tag in ((a, 'A'), (b, 'B')):
            user = User(
                username=f'iso_{tag}'.lower(), email=f'iso_{tag}@t.co',
                full_name=f'Iso {tag}', is_owner=False, is_active=True,
                role_id=role.id, tenant_id=tenant.id)
            user.set_password('IsoPass123!')
            _db.session.add(user)
            _db.session.add(Customer(
                name=f'Iso {tag}', name_ar=f'زبون {tag}',
                customer_type='regular', tenant_id=tenant.id,
                is_active=True))
        _db.session.commit()

        try:
            set_current_tenant_id(a.id)
            assert {c.name for c in Customer.query.all()} == {'Iso A'}
            set_current_tenant_id(b.id)
            assert {c.name for c in Customer.query.all()} == {'Iso B'}
        finally:
            clear_current_tenant_id()

        # Users: explicit per-tenant scoping (the route-level pattern).
        assert {u.username for u in
                User.query.filter_by(tenant_id=a.id).all()} == {'iso_a'}
        assert {u.username for u in
                User.query.filter_by(tenant_id=b.id).all()} == {'iso_b'}

        # Unscoped (owner) context still sees everything.
        assert Customer.query.filter(
            Customer.name.in_(['Iso A', 'Iso B'])).count() == 2
