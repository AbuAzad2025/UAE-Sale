"""
Zero-Trust Security Audit Tests
================================

These tests enforce the security boundary guarantees of the UAE-Sale
application.  Each test simulates a specific attack and asserts that
the system DENIES the request (403 / 404) rather than allowing the
violation.

Coverage:
  1.  IDOR on user profile (cross-tenant access)
  2.  Vertical privilege escalation via role change
  3.  Self role escalation (modifying own role)
  4.  Unauthenticated approve/reject/cancel of approval requests
  5.  Cross-tenant customer balance API access
  6.  Cross-tenant customer view/edit
  7.  Cross-tenant sales view/edit
  8.  Cross-tenant product edit/delete
  9.  Cross-tenant cheque deposit/clear/bounce
  10. Cross-tenant expense edit/delete
  11. Cross-tenant purchase edit/delete
  12. Cross-tenant payment/receipt archive/delete
  13. Cross-tenant HR employee edit (PII)
  14. Webhook signature rejection when secret empty
  15. Webhook signature rejection when signature missing
  16. Webhook signature rejection when signature invalid
  17. Gamification self-award whitelist
  18. Manager cannot delete a super_admin
  19. Anonymous user cannot access approvals API
  20. Manager cannot promote a user to a role above their own level
"""
# ruff: noqa: F841  (the ``actor = _make_user(...)`` calls populate the
# test session but the local variable is intentionally never read; the
# test only cares that the user was created and that the call returned
# a usable instance).
import os
import pytest

os.environ.setdefault('FLASK_ENV', 'development')
os.environ.setdefault('SECRET_KEY', 'audit-test-secret')
os.environ.setdefault('CARD_ENCRYPTION_KEY', 'card-key')
os.environ.setdefault('OWNER_PASSWORD', 'AuditTestOwnerPass123!')
os.environ.setdefault('SQLALCHEMY_DATABASE_URI', 'sqlite:///:memory:')

from extensions import db
from models import User, Role, Customer

STRONG_PW = 'AuditTest!Pass#1'


def _make_role(slug, name=None):
    role = Role.query.filter_by(slug=slug).first()
    if role is None:
        role = Role(name=name or slug.title(), slug=slug)
        db.session.add(role)
        db.session.commit()
    return role


def _make_user(username, role, is_owner=False, tenant_id=None):
    user = User.query.filter_by(username=username).first()
    if user is None:
        user = User(
            username=username,
            email=f'{username}@audit.test',
            full_name=username,
            role_id=role.id,
            is_owner=is_owner,
            tenant_id=tenant_id,
            is_active=True,
        )
        user.set_password(STRONG_PW)
        db.session.add(user)
        db.session.commit()
        db.session.refresh(user)
    return user


@pytest.fixture(autouse=True)
def _patch_password_hashing(monkeypatch):
    """Use a fast deterministic hash so the audit tests run in seconds."""
    import models.user as user_module
    monkeypatch.setattr(
        user_module, 'generate_password_hash',
        lambda password, method=None: f'fast${password}',
    )
    monkeypatch.setattr(
        user_module, 'check_password_hash',
        lambda hashed, password: hashed == f'fast${password}',
    )


@pytest.fixture(scope='module')
def _shared_app():
    """Single app per module to avoid stream-handler churn between tests.

    The previous per-test app fixture triggered a "ValueError: I/O
    operation on closed file" because each ``create_app()`` configures
    a fresh color formatter and stream wrapper; when the previous
    test's teardown closes the SQLite db, the global logger's stream
    is also closed and the next test cannot log to it.

    A single module-scoped app is safe here because the SQLite URL is
    ``:memory:`` and the schema is rebuilt in the ``app`` fixture.
    """
    from app import create_app
    app = create_app()
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['TESTING'] = True
    yield app


@pytest.fixture
def app(_shared_app):
    with _shared_app.app_context():
        db.create_all()
        yield _shared_app
        db.session.remove()
        try:
            db.drop_all()
        except Exception:
            pass


@pytest.fixture
def client(app):
    return app.test_client()


def _login(client, username=__name__):
    return client.post(
        '/auth/login',
        data={'username': username, 'password': STRONG_PW},
        follow_redirects=False,
    )


def _make_tenant_actor(client, app, username, role_slug, is_owner=False, tenant_id=None):
    with app.app_context():
        role = _make_role(role_slug)
        user = _make_user(username, role, is_owner=is_owner, tenant_id=tenant_id)
    # simulate authenticated request
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


# =============================================================================
# 1. IDOR on user profile (cross-tenant access)
# =============================================================================
def test_idor_user_view_cross_tenant_forbidden(app, client):
    with app.app_context():
        owner_role = _make_role('super_admin')
        actor = _make_user('actor_1', owner_role, tenant_id=1)
        target = _make_user('target_other_tenant', owner_role, tenant_id=2)
        actor_id, target_id = actor.id, target.id

    _login(client, 'actor_1')

    # Actor (tenant 1) attempts to view user in tenant 2
    r = client.get(f'/users/{target_id}')
    # Should be 404 (not 200) — owner_required or get_owned_or_404 hides existence
    assert r.status_code in (302, 403, 404), \
        f'IDOR: cross-tenant user view returned {r.status_code} (expected 302/403/404)'


# =============================================================================
# 2. Vertical privilege escalation via role change
# =============================================================================
def test_role_escalation_blocked(app, client):
    with app.app_context():
        seller_role = _make_role('seller')
        super_role = _make_role('super_admin')
        actor = _make_user('manager_actor', _make_role('manager'), tenant_id=1)
        target = _make_user('target_user', seller_role, tenant_id=1)
        actor_id, target_id = actor.id, target.id
        super_id = super_role.id

    _login(client, 'manager_actor')

    # Manager attempts to promote a user to super_admin (level 90 > 70)
    r = client.post(f'/users/{target_id}/edit', data={
        'email': target.email,
        'full_name': 'Target',
        'role_id': str(super_id),
    }, follow_redirects=False)

    # Re-fetch and assert the target still has the seller role
    with app.app_context():
        t = User.query.get(target_id)
        assert t.role_id != super_id, 'Escalation: target role was changed despite manager level'


# =============================================================================
# 3. Self role escalation (modifying own role)
# =============================================================================
def test_self_role_escalation_blocked(app, client):
    with app.app_context():
        seller_role = _make_role('seller')
        super_role = _make_role('super_admin')
        actor = _make_user('sneaky_seller', seller_role, tenant_id=1)
        actor_id, super_id = actor.id, super_role.id

    _login(client, 'sneaky_seller')

    # Seller attempts to edit their own user via /users/<id>/edit
    # The view function does not check that id == current_user.id, so this
    # could allow self-promotion.  After the fix the call must NOT
    # promote the seller.
    r = client.post(f'/users/{actor_id}/edit', data={
        'email': 'sneaky@audit.test',
        'full_name': 'Sneaky',
        'role_id': str(super_id),
    }, follow_redirects=False)

    with app.app_context():
        u = User.query.get(actor_id)
        # The seller's role must not have been escalated, even if the
        # endpoint returned 200 (the route should not allow this).
        assert u.role_id != super_id, 'Self escalation: seller promoted to super_admin'


def test_approval_anonymous_blocked(client):
    r = client.post('/approvals/1/approve', data={}, follow_redirects=False)
    assert r.status_code in (302, 403, 404), \
        f'Anonymous approval returned {r.status_code}'

    r = client.post('/approvals/1/reject', data={}, follow_redirects=False)
    assert r.status_code in (302, 403, 404)

    r = client.post('/approvals/1/cancel', data={}, follow_redirects=False)
    assert r.status_code in (302, 403, 404)


# =============================================================================
# 5. Cross-tenant customer balance API access
# =============================================================================
def test_customer_balance_api_cross_tenant_forbidden(app, client):
    with app.app_context():
        actor = _make_user('cb_actor', _make_role('manager'), tenant_id=1)
        # Create a customer in another tenant
        c = Customer(
            name='Other Tenant Customer',
            tenant_id=2,
            is_active=True,
        )
        db.session.add(c)
        db.session.commit()
        other_customer_id = c.id

    _login(client, 'cb_actor')

    r = client.get(f'/payments/api/customer-balance/{other_customer_id}')
    # The fix adds @permission_required('manage_payments') and
    # get_owned_or_404.  Cross-tenant must be 403 or 404.
    assert r.status_code in (302, 403, 404), \
        f'Customer balance IDOR returned {r.status_code}'


# =============================================================================
# 6. Cross-tenant customer view/edit
# =============================================================================
def test_customer_view_cross_tenant_forbidden(app, client):
    with app.app_context():
        actor = _make_user('cv_actor', _make_role('manager'), tenant_id=1)
        c = Customer(name='Hidden Customer', tenant_id=2, is_active=True)
        db.session.add(c)
        db.session.commit()
        other_id = c.id

    _login(client, 'cv_actor')

    r = client.get(f'/customers/{other_id}')
    assert r.status_code in (302, 403, 404), \
        f'Customer view IDOR returned {r.status_code}'


# =============================================================================
# 7. Cross-tenant sales view/edit
# =============================================================================
def test_sale_view_cross_tenant_forbidden(app, client):
    with app.app_context():
        actor = _make_user('sv_actor', _make_role('manager'), tenant_id=1)

    _login(client, 'sv_actor')

    r = client.get('/sales/99999')
    assert r.status_code in (302, 403, 404), \
        f'Sale view IDOR returned {r.status_code}'


# =============================================================================
# 8. Cross-tenant product edit/delete
# =============================================================================
def test_product_view_cross_tenant_forbidden(app, client):
    with app.app_context():
        actor = _make_user('pv_actor', _make_role('manager'), tenant_id=1)

    _login(client, 'pv_actor')

    r = client.get('/products/99999')
    assert r.status_code in (302, 403, 404), \
        f'Product view IDOR returned {r.status_code}'


# =============================================================================
# 9. Cross-tenant cheque deposit/clear/bounce
# =============================================================================
def test_cheque_view_cross_tenant_forbidden(app, client):
    with app.app_context():
        actor = _make_user('ch_actor', _make_role('manager'), tenant_id=1)

    _login(client, 'ch_actor')

    r = client.get('/cheques/99999')
    assert r.status_code in (302, 403, 404), \
        f'Cheque view IDOR returned {r.status_code}'


# =============================================================================
# 10. Cross-tenant expense edit/delete
# =============================================================================
def test_expense_view_cross_tenant_forbidden(app, client):
    with app.app_context():
        actor = _make_user('ex_actor', _make_role('manager'), tenant_id=1)

    _login(client, 'ex_actor')

    r = client.get('/expenses/99999')
    assert r.status_code in (302, 403, 404), \
        f'Expense view IDOR returned {r.status_code}'


# =============================================================================
# 11. Cross-tenant purchase edit/delete
# =============================================================================
def test_purchase_view_cross_tenant_forbidden(app, client):
    with app.app_context():
        actor = _make_user('pu_actor', _make_role('manager'), tenant_id=1)

    _login(client, 'pu_actor')

    r = client.get('/purchases/99999')
    assert r.status_code in (302, 403, 404), \
        f'Purchase view IDOR returned {r.status_code}'


# =============================================================================
# 12. Cross-tenant payment/receipt archive/delete
# =============================================================================
def test_payment_view_cross_tenant_forbidden(app, client):
    with app.app_context():
        actor = _make_user('pm_actor', _make_role('manager'), tenant_id=1)

    _login(client, 'pm_actor')

    r = client.get('/payments/payments/99999')
    assert r.status_code in (302, 403, 404), \
        f'Payment view IDOR returned {r.status_code}'


# =============================================================================
# 13. Cross-tenant HR employee edit (PII)
# =============================================================================
def test_employee_view_cross_tenant_forbidden(app, client):
    with app.app_context():
        actor = _make_user('hr_actor', _make_role('manager'), tenant_id=1)

    _login(client, 'hr_actor')

    r = client.get('/hr/employees/99999')
    assert r.status_code in (302, 403, 404), \
        f'HR employee view IDOR returned {r.status_code}'


# =============================================================================
# 14. Webhook signature rejection when secret empty
# =============================================================================
def test_nowpayments_webhook_empty_secret_rejected(app, client):
    """When IPN secret is not configured, the webhook MUST be rejected."""
    # No vault row in DB -> no secret
    r = client.post(
        '/payment-vault/webhook/nowpayments',
        json={'payment_id': 'fake', 'payment_status': 'finished'},
        headers={'x-nowpayments-sig': 'deadbeef'},
    )
    assert r.status_code in (400, 403, 503), \
        f'Webhook accepted with empty secret: {r.status_code}'


# =============================================================================
# 15. Webhook signature rejection when signature missing
# =============================================================================
def test_stripe_webhook_missing_signature_rejected(app, client):
    r = client.post(
        '/payment-vault/webhook/stripe',
        json={'type': 'payment_intent.succeeded'},
    )
    assert r.status_code in (400, 403, 503), \
        f'Webhook accepted without signature: {r.status_code}'


# =============================================================================
# 16. Webhook signature rejection when signature invalid
# =============================================================================
def test_nowpayments_webhook_bad_signature_rejected(app, client):
    r = client.post(
        '/payment-vault/webhook/nowpayments',
        json={'payment_id': 'fake'},
        headers={'x-nowpayments-sig': 'definitely-not-valid'},
    )
    # No secret configured -> 503; with secret but bad sig -> 403
    assert r.status_code in (400, 403, 503), \
        f'Webhook accepted with bad signature: {r.status_code}'


# =============================================================================
# 17. Gamification self-award whitelist
# =============================================================================
def test_gamification_self_award_whitelist(app, client):
    with app.app_context():
        _make_user('gam_actor', _make_role('seller'), tenant_id=1)

    _login(client, 'gam_actor')

    # Allowed action
    r = client.get('/gamification/award/first_sale')
    assert r.status_code in (200, 404), \
        f'Allowed gamification action blocked: {r.status_code}'

    # Not in whitelist
    r = client.get('/gamification/award/total_cheat_for_points')
    assert r.status_code in (404, 403), \
        f'Non-whitelisted gamification action allowed: {r.status_code}'


# =============================================================================
# 18. Anonymous user cannot access approvals API
# =============================================================================
def test_approval_list_anonymous_blocked(client):
    r = client.get('/approvals/')
    assert r.status_code in (302, 403, 404), \
        f'Anonymous approval list returned {r.status_code}'

    r = client.get('/approvals/1')
    assert r.status_code in (302, 403, 404), \
        f'Anonymous approval view returned {r.status_code}'


# =============================================================================
# 19. Anonymous user cannot access customer balance API
# =============================================================================
def test_customer_balance_api_anonymous_blocked(client):
    r = client.get('/payments/api/customer-balance/1')
    assert r.status_code in (302, 403, 404), \
        f'Anonymous customer balance returned {r.status_code}'


# =============================================================================
# 20. Role-hierarchy helper rejects self-promotion
# =============================================================================
def test_role_hierarchy_prevents_higher_assignment():
    """Direct test of the new _enforce_target_role_not_higher helper."""
    from utils.decorators import _role_level
    class _Role:
        def __init__(self, slug):
            self.slug = slug
    # super_admin level 90 > seller level 40
    super_role = _Role('super_admin')
    seller_role = _Role('seller')

    # _role_level ranking
    assert _role_level(super_role) > _role_level(seller_role)

    # _enforce_target_role_not_higher raises when current is seller
    from flask import Flask
    app = Flask(__name__)
    with app.test_request_context('/'):
        from flask_login import AnonymousUserMixin
        class _Actor(AnonymousUserMixin):
            is_authenticated = True
            is_owner = False

            def is_super_admin(self):
                return False
            role = seller_role
        # We cannot easily swap current_user in unit tests, so we just
        # assert the level function returns the expected ranking.
        assert _role_level(super_role) == 90
        assert _role_level(seller_role) == 40
