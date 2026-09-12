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
        # system_integrator returns success=False (no raise) -> jsonify 200.
        _login(client, ai_analyst)
        resp = client.get('/ai/system/customer-balance/NoSuchCustomer')
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['success'] is False
        assert 'غير موجود' in body['error']

    def test_add_customer_validation(self, client, ai_analyst):
        # Empty payload fails required-field check -> success=False, 200.
        _login(client, ai_analyst)
        resp = client.post('/ai/system/add-customer', json={})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['success'] is False
        assert 'مطلوب' in body['error']

    def test_add_customer_forbidden_for_plain(self, client, ai_plain):
        _login(client, ai_plain)
        resp = client.post('/ai/system/add-customer',
                           json={'name': 'X'})
        assert resp.status_code == 403


# Admin-only AI operations ────────────────────────────────────────────────────

class TestAdminAiOperations:
    @pytest.mark.parametrize('url,key', [
        ('/ai/learning/evolve', 'evolution'),
        ('/ai/improvement/auto-improve', 'improvements'),
    ])
    def test_owner_ok(self, client, ai_owner, url, key):
        # Owner passes admin gate; success carries the payload key,
        # failure carries success=False + error (both JSON, never HTML).
        _login(client, ai_owner)
        resp = client.post(url, json={})
        assert resp.status_code in (200, 500)
        body = resp.get_json()
        assert body['success'] in (True, False)
        if resp.status_code == 200:
            assert body['success'] is True
            assert key in body
        else:
            assert 'error' in body

    def test_analyst_forbidden(self, client, ai_analyst):
        _login(client, ai_analyst)
        assert client.post('/ai/learning/evolve', json={}).status_code == 403

    def test_set_goal_validation(self, client, ai_owner):
        # Empty payload misses area/target_score -> exact 400 contract.
        _login(client, ai_owner)
        resp = client.post('/ai/improvement/set-goal', json={})
        assert resp.status_code == 400
        body = resp.get_json()
        assert body['success'] is False
        assert body['error'] == 'المجال والهدف مطلوبان'


# External-key endpoints fail safe ────────────────────────────────────────────

class TestExternalEndpointsFailSafe:
    def test_chat_requires_message(self, client, ai_analyst):
        _login(client, ai_analyst)
        resp = client.post('/ai/chat', json={'message': ''})
        assert resp.status_code == 400

    def test_chat_without_key_graceful(self, client, ai_analyst, monkeypatch):
        # No key -> local fallback path returns 200 with the response envelope.
        monkeypatch.delenv('GROQ_API_KEY', raising=False)
        monkeypatch.delenv('GEMINI_API_KEY', raising=False)
        monkeypatch.delenv('OPENAI_API_KEY', raising=False)
        _login(client, ai_analyst)
        resp = client.post('/ai/chat', json={'message': 'مرحبا',
                                             'ai_mode': 'groq'})
        assert resp.status_code == 200
        body = resp.get_json()
        assert 'response' in body and body['response']
        assert body['ai_mode'] == 'groq'
        assert body['ai_enabled'] is True

    def test_ask_genius_requires_question(self, client, ai_analyst):
        _login(client, ai_analyst)
        assert client.post('/ai/ask-genius', json={}).status_code == 400

    def test_quick_calc(self, client, ai_analyst):
        # '2+3*4' is not a named formula -> brain returns success=False,
        # route wraps it as 200 {'success': False, 'result': {...}}.
        _login(client, ai_analyst)
        resp = client.post('/ai/quick-calc',
                           json={'formula': '2+3*4', 'params': {}})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['success'] is False
        assert body['result']['success'] is False
        assert 'Unknown formula' in body['result']['error']


# Owner-only AI pages ─────────────────────────────────────────────────────────

class TestOwnerAiPages:
    @pytest.mark.parametrize('url', ['/ai/assistant', '/ai/config'])
    def test_owner_ok_others_redirected(self, client, ai_owner, ai_analyst, url):
        _login(client, ai_owner)
        assert client.get(url).status_code == 200
        client.get('/auth/logout', follow_redirects=True)
        _login(client, ai_analyst)
        # owner-guarded pages redirect non-owners to the main dashboard.
        resp = client.get(url, follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith('/dashboard')
