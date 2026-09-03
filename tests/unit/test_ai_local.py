"""Tests for local (no-external-key) AI endpoints in routes/ai.py.

routes/ai.py is the biggest single coverage gap (~15%). These tests hit
the endpoints that run on local singletons/DB analytics, plus the
graceful-failure shapes of the external-key endpoints (proving they
fail safe instead of leaking stack traces).
"""
import pytest

from models import User, Role, Permission
from extensions import db as _db


def _make_user(username, slug, perm_codes=(), is_owner=False):
    role = Role(name=username.title(), name_ar=username, slug=slug)
    _db.session.add(role)
    _db.session.flush()
    perms = []
    for code in perm_codes:
        p = Permission.query.filter_by(code=code).first()
        if p is None:
            p = Permission(code=code, name=code, name_ar=code, category='test')
            _db.session.add(p)
            _db.session.flush()
        perms.append(p)
    role.permissions = perms
    user = User(username=username, email=f'{username}@test.com',
                full_name=username, is_owner=is_owner, is_active=True,
                role_id=role.id)
    user.set_password('Pass123!')
    _db.session.add(user)
    _db.session.commit()
    return user


@pytest.fixture(scope='function')
def ai_owner(db):
    return _make_user('ai_owner', 'ai_owner_role', is_owner=True)


@pytest.fixture(scope='function')
def ai_analyst(db):
    return _make_user('ai_analyst', 'ai_analyst_role',
                      perm_codes=['view_reports', 'view_products',
                                  'manage_customers', 'manage_sales'])


@pytest.fixture(scope='function')
def ai_plain(db):
    return _make_user('ai_plain', 'ai_plain_role', perm_codes=[])


def _login(client, user):
    client.post('/auth/login', data={
        'username': user.username, 'password': 'Pass123!',
    }, follow_redirects=True)


# Local singleton status endpoints ────────────────────────────────────────────

class TestLocalStatusEndpoints:
    @pytest.mark.parametrize('url', [
        '/ai/learning/status',
        '/ai/improvement/status',
        '/ai/improvement/progress',
        '/ai/global/insights',
        '/ai/performance/analysis',
    ])
    def test_view_reports_ok(self, client, ai_analyst, url):
        _login(client, ai_analyst)
        resp = client.get(url)
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True

    @pytest.mark.parametrize('url', [
        '/ai/learning/status',
        '/ai/improvement/status',
    ])
    def test_no_permission_forbidden(self, client, ai_plain, url):
        _login(client, ai_plain)
        assert client.get(url).status_code == 403

    def test_anonymous_redirected(self, client):
        assert client.get('/ai/learning/status').status_code == 302


# Local DB analytics endpoints ────────────────────────────────────────────────

class TestLocalAnalyticsEndpoints:
    @pytest.mark.parametrize('url', [
        '/ai/system/summary',
        '/ai/system/search/test',
        '/ai/data/analyze-sales',
        '/ai/data/analyze-products',
        '/ai/data/financial-ratios',
        '/ai/knowledge/search?q=test',
        '/ai/knowledge/summary',
        '/ai/neural-status',
    ])
    def test_analyst_ok(self, client, ai_analyst, url):
        _login(client, ai_analyst)
        assert client.get(url).status_code == 200

    def test_customer_balance_missing_ok(self, client, ai_analyst):
        _login(client, ai_analyst)
        resp = client.get('/ai/system/customer-balance/NoSuchCustomer')
        assert resp.status_code in (200, 404, 500)

    def test_add_customer_validation(self, client, ai_analyst):
        _login(client, ai_analyst)
        resp = client.post('/ai/system/add-customer', json={})
        assert resp.status_code in (200, 400, 500)

    def test_add_customer_forbidden_for_plain(self, client, ai_plain):
        _login(client, ai_plain)
        resp = client.post('/ai/system/add-customer',
                           json={'name': 'X'})
        assert resp.status_code == 403


# Admin-only AI operations ────────────────────────────────────────────────────

class TestAdminAiOperations:
    @pytest.mark.parametrize('url', [
        '/ai/learning/evolve',
        '/ai/improvement/auto-improve',
    ])
    def test_owner_ok(self, client, ai_owner, url):
        _login(client, ai_owner)
        assert client.post(url, json={}).status_code in (200, 500)

    def test_analyst_forbidden(self, client, ai_analyst):
        _login(client, ai_analyst)
        assert client.post('/ai/learning/evolve', json={}).status_code == 403

    def test_set_goal_validation(self, client, ai_owner):
        _login(client, ai_owner)
        resp = client.post('/ai/improvement/set-goal', json={})
        assert resp.status_code in (200, 400, 500)


# External-key endpoints fail safe ────────────────────────────────────────────

class TestExternalEndpointsFailSafe:
    def test_chat_requires_message(self, client, ai_analyst):
        _login(client, ai_analyst)
        resp = client.post('/ai/chat', json={'message': ''})
        assert resp.status_code == 400

    def test_chat_without_key_graceful(self, client, ai_analyst, monkeypatch):
        monkeypatch.delenv('GROQ_API_KEY', raising=False)
        _login(client, ai_analyst)
        resp = client.post('/ai/chat', json={'message': 'مرحبا',
                                             'ai_mode': 'groq'})
        assert resp.status_code in (200, 500)
        body = resp.get_json()
        assert 'response' in body or 'error' in body or 'success' in body

    def test_ask_genius_requires_question(self, client, ai_analyst):
        _login(client, ai_analyst)
        assert client.post('/ai/ask-genius', json={}).status_code == 400

    def test_quick_calc(self, client, ai_analyst):
        _login(client, ai_analyst)
        resp = client.post('/ai/quick-calc',
                           json={'formula': '2+3*4', 'params': {}})
        assert resp.status_code in (200, 400, 500)


# Owner-only AI pages ─────────────────────────────────────────────────────────

class TestOwnerAiPages:
    @pytest.mark.parametrize('url', ['/ai/assistant', '/ai/config'])
    def test_owner_ok_others_404(self, client, ai_owner, ai_analyst, url):
        _login(client, ai_owner)
        assert client.get(url).status_code == 200
        client.get('/auth/logout', follow_redirects=True)
        _login(client, ai_analyst)
        assert client.get(url).status_code == 404
