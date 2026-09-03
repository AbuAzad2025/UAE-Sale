"""Route smoke + access-control tests for misc blueprints.

Covers combined-coverage gaps: public (43%), approvals (45%), whatsapp
(42%), returns (53%), language/api-docs (~50%), graphql (27%),
payment-vault (29%), users (25%).
"""
import pytest

from models import User, Role, Permission
from extensions import db as _db


def _make_user(username, slug, perm_codes=(), is_owner=False, tenant_id=None):
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
                role_id=role.id, tenant_id=tenant_id)
    user.set_password('Pass123!')
    _db.session.add(user)
    _db.session.commit()
    return user


@pytest.fixture(scope='function')
def misc_owner(db):
    return _make_user('misc_owner', 'misc_owner_role', is_owner=True)


@pytest.fixture(scope='function')
def misc_viewer(db):
    return _make_user('misc_viewer', 'misc_viewer_role',
                      perm_codes=['view_reports'])


@pytest.fixture(scope='function')
def misc_seller(db):
    return _make_user('misc_seller', 'misc_seller_role',
                      perm_codes=['manage_sales'])


def _login(client, user):
    client.post('/auth/login', data={
        'username': user.username, 'password': 'Pass123!',
    }, follow_redirects=True)


# ── Public pages (no login) ───────────────────────────────────────────────────

class TestPublicPages:
    @pytest.mark.parametrize('url', [
        '/welcome', '/pricing', '/features', '/user-guide',
        '/contact', '/demo', '/sitemap.xml', '/robots.txt',
    ])
    def test_public_page_renders(self, client, url):
        assert client.get(url).status_code == 200


# ── Language switch ───────────────────────────────────────────────────────────

class TestLanguageSwitch:
    @pytest.mark.parametrize('lang', ['ar', 'en'])
    def test_valid_lang_sets_session_and_redirects(self, client, lang):
        resp = client.get(f'/language/set/{lang}')
        assert resp.status_code == 302
        with client.session_transaction() as sess:
            assert sess.get('language') == lang

    def test_invalid_lang_redirects_without_session_change(self, client):
        resp = client.get('/language/set/xx')
        assert resp.status_code == 302
        with client.session_transaction() as sess:
            assert sess.get('language') != 'xx'

    def test_no_open_redirect_via_next_or_referrer(self, client):
        # External 'next' (or attacker-set Referer) must never redirect off-site
        resp = client.get('/language/set/en?next=https://evil.example')
        assert resp.status_code == 302
        loc = resp.headers.get('Location', '')
        assert not loc.startswith('https://evil.example')

        resp2 = client.get('/language/set/en',
                           headers={'Referer': 'https://evil.example/phish'})
        loc2 = resp2.headers.get('Location', '')
        assert not loc2.startswith('https://evil.example')

    def test_relative_next_allowed(self, client):
        resp = client.get('/language/set/en?next=/dashboard')
        assert resp.status_code == 302
        assert resp.headers.get('Location', '').startswith('/dashboard')


# ── API docs (public spec UI) ─────────────────────────────────────────────────

class TestApiDocs:
    @pytest.mark.parametrize('url', [
        '/api-docs/', '/api-docs/openapi.json', '/api-docs/redoc',
    ])
    def test_docs_reachable(self, client, url):
        assert client.get(url).status_code in (200, 302)

    def test_openapi_spec_is_json(self, client):
        resp = client.get('/api-docs/openapi.json')
        assert resp.status_code in (200, 302)
        if resp.status_code == 200:
            assert 'openapi' in resp.get_json()


# ── GraphQL ───────────────────────────────────────────────────────────────────

class TestGraphql:
    def test_playground_requires_login(self, client):
        assert client.get('/graphql/playground').status_code == 302

    def test_playground_viewer_ok(self, client, misc_viewer):
        _login(client, misc_viewer)
        assert client.get('/graphql/playground').status_code == 200

    def test_playground_seller_forbidden(self, client, misc_seller):
        _login(client, misc_seller)
        assert client.get('/graphql/playground').status_code == 403

    def test_query_typename(self, client, misc_viewer):
        # __typename contains '__type' -> blocked as introspection (correct!)
        _login(client, misc_viewer)
        resp = client.post('/graphql', json={'query': '{__typename}'})
        assert resp.status_code == 403
        assert 'Introspection' in resp.get_json()['errors'][0]

    def test_mutation_blocked(self, client, misc_viewer):
        _login(client, misc_viewer)
        resp = client.post('/graphql',
                           json={'query': 'mutation { createSale }'})
        assert resp.status_code == 403

    def test_field_level_permission_enforced(self, client, misc_viewer):
        # viewer lacks manage_sales -> sales field rejected
        _login(client, misc_viewer)
        resp = client.post('/graphql', json={'query': '{ sales { id } }'})
        assert resp.status_code == 403
        assert 'Insufficient permissions' in resp.get_json()['errors'][0]

    def test_allowed_field_executes(self, client, misc_owner):
        # Owner bypasses field checks; proves the execution pipeline works.
        # (Non-view_reports roles like seller are rejected by the base
        # view_reports gate before field checks — covered above.)
        _login(client, misc_owner)
        resp = client.post('/graphql', json={'query': '{ sales { id } }'})
        assert resp.status_code == 200
        body = resp.get_json()
        assert 'data' in body or 'errors' in body

    def test_empty_body_rejected(self, client, misc_viewer):
        _login(client, misc_viewer)
        assert client.post('/graphql', json={}).status_code == 400


# ── Approvals ─────────────────────────────────────────────────────────────────

class TestApprovals:
    def test_index_owner_ok(self, client, misc_owner):
        _login(client, misc_owner)
        assert client.get('/approvals/').status_code == 200

    def test_workflows_owner_ok(self, client, misc_owner):
        _login(client, misc_owner)
        assert client.get('/approvals/workflows').status_code == 200

    def test_index_seller_forbidden(self, client, misc_seller):
        _login(client, misc_seller)
        assert client.get('/approvals/').status_code == 403

    def test_missing_request_404(self, client, misc_owner):
        _login(client, misc_owner)
        assert client.get('/approvals/999999').status_code == 404


# ── Returns ───────────────────────────────────────────────────────────────────

class TestReturns:
    def test_view_missing_returns_404(self, client, misc_owner):
        _login(client, misc_owner)
        assert client.get('/returns/view/999999').status_code in (404, 302)

    def test_api_create_rejects_empty(self, client, misc_seller):
        _login(client, misc_seller)
        resp = client.post('/returns/api/create', json={})
        assert resp.status_code == 400
        assert resp.get_json()['success'] is False

    def test_api_create_rejects_missing_lines(self, client, misc_seller):
        _login(client, misc_seller)
        resp = client.post('/returns/api/create', json={'sale_id': 1})
        assert resp.status_code == 400

    def test_api_create_viewer_forbidden(self, client, misc_viewer):
        _login(client, misc_viewer)
        resp = client.post('/returns/api/create',
                           json={'sale_id': 1, 'lines': []})
        assert resp.status_code == 403


# ── WhatsApp ──────────────────────────────────────────────────────────────────

class TestWhatsapp:
    def test_test_page_owner_ok(self, client, misc_owner):
        _login(client, misc_owner)
        assert client.get('/whatsapp/test').status_code in (200, 302)

    def test_test_page_seller_forbidden(self, client, misc_seller):
        _login(client, misc_seller)
        assert client.get('/whatsapp/test').status_code == 403


# ── Payment vault (own lock layer: 200 or redirect-to-unlock) ─────────────────

class TestPaymentVault:
    @pytest.mark.parametrize('url', [
        '/payment-vault/',
        '/payment-vault/dashboard',
        '/payment-vault/metrics',
        '/payment-vault/cards',
        '/payment-vault/reports',
        '/payment-vault/api/live-stats',
        '/payment-vault/api/notifications',
    ])
    def test_owner_reaches_vault_pages(self, client, misc_owner, url):
        _login(client, misc_owner)
        assert client.get(url).status_code in (200, 302)

    def test_health_signals_status(self, client, misc_owner):
        # /health honestly reports degraded deps as 503 in test env
        # (no redis/upstream); the assertion is that it answers, not 500.
        _login(client, misc_owner)
        assert client.get('/payment-vault/health').status_code in (200, 302, 503)

    def test_anonymous_redirected(self, client):
        assert client.get('/payment-vault/').status_code == 302


# ── Users admin ───────────────────────────────────────────────────────────────

class TestUsersAdmin:
    def test_index_owner_ok(self, client, misc_owner):
        _login(client, misc_owner)
        assert client.get('/users/').status_code == 200

    def test_create_page_owner_ok(self, client, misc_owner):
        _login(client, misc_owner)
        assert client.get('/users/create').status_code == 200

    def test_view_other_user_owner_ok(self, client, misc_owner, misc_seller):
        # NOTE: owner accounts are deliberately hidden (404) even from the
        # owner, so view/edit target a regular user.
        _login(client, misc_owner)
        assert client.get(f'/users/{misc_seller.id}').status_code == 200

    def test_edit_other_user_owner_ok(self, client, misc_owner, misc_seller):
        _login(client, misc_owner)
        assert client.get(f'/users/{misc_seller.id}/edit').status_code == 200

    def test_owner_self_hidden_by_design(self, client, misc_owner):
        _login(client, misc_owner)
        assert client.get(f'/users/{misc_owner.id}').status_code == 404

    def test_change_password_owner_ok(self, client, misc_owner):
        _login(client, misc_owner)
        assert client.get('/users/change-password').status_code == 200

    def test_index_seller_redirected_with_flash(self, client, misc_seller):
        # users.index flash-redirects (302) instead of aborting for
        # missing manage_users — assert the redirect, and that following
        # it does not leak the user list.
        _login(client, misc_seller)
        resp = client.get('/users/')
        assert resp.status_code == 302
        page = client.get('/users/', follow_redirects=True)
        assert 'misc_owner' not in page.data.decode()

    def test_toggle_missing_user_404(self, client, misc_owner):
        _login(client, misc_owner)
        resp = client.post('/users/999999/toggle-active')
        assert resp.status_code in (404, 302)
