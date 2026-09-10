"""Unit tests for the unified user pipeline (services/user_service.py).

Covers the merged strict rule-set plus the unified /users/* routes:
owner-adaptive roster, tenant prefill/lock, and guard parity.
"""
import pytest

from models import Role, Tenant, User
from extensions import db as _db
from services.user_service import UserService


@pytest.fixture
def mgr_role(db):
    role = Role(name='ManagerU', name_ar='مدير', slug='manager_u',
                is_active=True)
    _db.session.add(role)
    _db.session.commit()
    return role


@pytest.fixture
def tenant_a(db):
    t = Tenant(name='TA', name_ar='أ', slug='ta-u', business_type='garage',
               is_active=True, max_users=10)
    _db.session.add(t)
    _db.session.commit()
    return t


def _mk_user(username, role, tenant_id=None, is_owner=False):
    u = User(username=username, email=f'{username}@u.co',
             full_name=username, is_owner=is_owner, is_active=True,
             role_id=role.id, tenant_id=tenant_id)
    u.set_password('Str0ng!Pass#9z')
    _db.session.add(u)
    _db.session.commit()
    return u


class TestProvision:
    def test_success(self, db, owner_user, mgr_role, tenant_a):
        u = UserService.provision_user(
            username='uni_one', email='uni_one@u.co',
            password='Str0ng!Pass#9z', role_id=mgr_role.id,
            tenant_id=tenant_a.id, actor=owner_user)
        assert u.tenant_id == tenant_a.id
        assert u.is_owner is False
        assert u.check_password('Str0ng!Pass#9z')

    def test_duplicate_username(self, db, owner_user, mgr_role):
        UserService.provision_user(
            username='uni_dup', email='a@u.co', password='Str0ng!Pass#9z',
            role_id=mgr_role.id, actor=owner_user)
        with pytest.raises(ValueError, match='مستخدم بالفعل'):
            UserService.provision_user(
                username='uni_dup', email='b@u.co',
                password='Str0ng!Pass#9z', role_id=mgr_role.id,
                actor=owner_user)

    def test_duplicate_email(self, db, owner_user, mgr_role):
        UserService.provision_user(
            username='uni_e1', email='same@u.co', password='Str0ng!Pass#9z',
            role_id=mgr_role.id, actor=owner_user)
        with pytest.raises(ValueError, match='مستخدم بالفعل'):
            UserService.provision_user(
                username='uni_e2', email='same@u.co',
                password='Str0ng!Pass#9z', role_id=mgr_role.id,
                actor=owner_user)

    def test_weak_password(self, db, owner_user, mgr_role):
        with pytest.raises(ValueError, match='ضعيفة'):
            UserService.provision_user(
                username='uni_weak', email='w@u.co', password='short',
                role_id=mgr_role.id, actor=owner_user)

    def test_owner_mint_guard(self, db, seller_user, mgr_role):
        with pytest.raises(ValueError, match='المالك الحالي'):
            UserService.provision_user(
                username='uni_noown', email='n@u.co',
                password='Str0ng!Pass#9z', role_id=mgr_role.id,
                is_owner=True, actor=seller_user)

    def test_quota(self, db, owner_user, mgr_role, tenant_a):
        tenant_a.max_users = 1
        _db.session.commit()
        UserService.provision_user(
            username='uni_q1', email='q1@u.co', password='Str0ng!Pass#9z',
            role_id=mgr_role.id, tenant_id=tenant_a.id, actor=owner_user)
        with pytest.raises(ValueError, match='الحد الأقصى'):
            UserService.provision_user(
                username='uni_q2', email='q2@u.co',
                password='Str0ng!Pass#9z', role_id=mgr_role.id,
                tenant_id=tenant_a.id, actor=owner_user)


class TestUpdateDelete:
    def test_email_clash(self, db, owner_user, mgr_role):
        a = _mk_user('uni_upa', mgr_role)
        b = _mk_user('uni_upb', mgr_role)
        with pytest.raises(ValueError, match='مستخدم بالفعل'):
            UserService.update_user(a, email='uni_upb@u.co', actor=owner_user)

    def test_self_demote_blocked(self, db, owner_user, mgr_role):
        with pytest.raises(ValueError, match='حسابك الخاص'):
            UserService.update_user(owner_user, is_owner=False,
                                    actor=owner_user)

    def test_owner_toggle_immune(self, db, owner_user):
        with pytest.raises(ValueError, match='مالك'):
            UserService.set_active(owner_user, False, owner_user)

    def test_delete_owner_blocked(self, db, owner_user):
        with pytest.raises(ValueError, match='مالك'):
            UserService.delete_user(owner_user, owner_user)

    def test_delete_self_blocked(self, db, seller_user):
        with pytest.raises(ValueError, match='حسابك الخاص'):
            UserService.delete_user(seller_user, seller_user)

    def test_delete_without_sales_hard(self, db, owner_user, mgr_role):
        u = _mk_user('uni_del', mgr_role)
        assert UserService.delete_user(u, owner_user) == 'deleted'
        assert _db.session.get(User, u.id) is None


class TestUnifiedRoutes:
    def _login(self, client, username, password):
        return client.post('/auth/login', data={
            'username': username, 'password': password}, follow_redirects=True)

    def test_manager_roster_scoped(self, client, db, owner_user, seller_user,
                                   tenant_a):
        from models import Permission
        perm = Permission.query.filter_by(code='manage_users').first()
        if perm is None:
            perm = Permission(code='manage_users', name='Manage Users',
                              category='users')
            _db.session.add(perm)
            _db.session.flush()
        role = Role(name='MU', name_ar='م', slug='mu-x', is_active=True,
                    permissions=[perm])
        _db.session.add(role)
        _db.session.flush()
        boss = User(username='mu_boss', email='mu@u.co', full_name='B',
                    is_owner=False, is_active=True, role_id=role.id,
                    tenant_id=tenant_a.id)
        boss.set_password('Str0ng!Pass#9z')
        _db.session.add(boss)
        seller_user.tenant_id = tenant_a.id
        _mk_user('mgr_seen', role, tenant_id=tenant_a.id)
        _mk_user('mgr_hidden', role, tenant_id=None)
        _db.session.commit()
        self._login(client, 'mu_boss', 'Str0ng!Pass#9z')
        html = client.get('/users/').get_data(as_text=True)
        assert 'mgr_seen' in html
        assert 'mgr_hidden' not in html
        assert 'owner@test.com' not in html

    def test_owner_sees_all(self, client, owner_user, seller_user):
        self._login(client, 'testowner', 'OwnerPass123!')
        html = client.get('/users/').get_data(as_text=True)
        assert 'testseller' in html
        assert 'owner@test.com' in html

    def test_owner_mint_owner_flag(self, client, owner_user, mgr_role):
        self._login(client, 'testowner', 'OwnerPass123!')
        resp = client.post('/users/create', data={
            'username': 'sub_owner', 'email': 'sub@u.co',
            'password': 'Str0ng!Pass#9z', 'role_id': str(mgr_role.id),
            'is_owner': 'on', 'is_active': '1'}, follow_redirects=False)
        assert resp.status_code == 302
        assert User.query.filter_by(username='sub_owner').first().is_owner is True
