"""Unit tests for routes/owner.py — owner panel access control + guard rails.

Covers the biggest single coverage gap (owner.py ~25%): safe read-only
pages render for the owner, non-owners get the stealth 404, and the
dangerous table tools (truncate, browse) refuse malicious input without
touching data.
"""
import pytest

from models import User, Role, Permission, Customer
from extensions import db as _db


@pytest.fixture(scope='function')
def owner_client_user(db):
    role = Role(name='Owner', name_ar='المالك', slug='owner')
    _db.session.add(role)
    _db.session.flush()
    user = User(username='owner_panel', email='owner_panel@test.com',
                full_name='Owner', is_owner=True, is_active=True,
                role_id=role.id)
    user.set_password('Pass123!')
    _db.session.add(user)
    _db.session.commit()
    return user


@pytest.fixture(scope='function')
def plain_user(db):
    role = Role(name='Seller', name_ar='بائع', slug='seller')
    perm = Permission.query.filter_by(code='manage_sales').first()
    if perm is None:
        perm = Permission(code='manage_sales', name='Manage Sales',
                          name_ar='إدارة المبيعات', category='sales')
        _db.session.add(perm)
        _db.session.flush()
    role.permissions = [perm]
    _db.session.add(role)
    _db.session.flush()
    user = User(username='plain_panel', email='plain_panel@test.com',
                full_name='Plain', is_owner=False, is_active=True,
                role_id=role.id)
    user.set_password('Pass123!')
    _db.session.add(user)
    _db.session.commit()
    return user


def _login(client, user):
    client.post('/auth/login', data={
        'username': user.username, 'password': 'Pass123!',
    }, follow_redirects=True)


# Safe read-only owner pages: must render 200 for the owner.
OWNER_READ_PAGES = [
    '/owner/dashboard',
    '/owner/system-stats',
    '/owner/audit-logs',
    '/owner/users-list',
    '/owner/roles-permissions',
    '/owner/financial-overview',
    '/owner/database-tools',
    '/owner/reports',
    '/owner/system-health',
    '/owner/activity-monitor',
    '/owner/error-logs',
    '/owner/login-history',
    '/owner/performance-metrics',
    '/owner/security-alerts',
    '/owner/sales-insights',
    '/owner/customer-insights',
    '/owner/product-performance',
    '/owner/forecasting',
    '/owner/verify-backups',
    '/owner/import-export-tools',
    '/owner/convert-database',
    '/owner/scheduled-backups',
    '/owner/backups/list',
    '/owner/config',
    '/owner/integrations',
    '/owner/browse-table/customers',
    # settings pages (probed 200)
    '/owner/api-keys',
    '/owner/ip-whitelist',
    '/owner/tax-settings',
    '/owner/currency-settings',
    '/owner/payment-gateways',
    '/owner/email-settings',
    '/owner/sms-settings',
    '/owner/whatsapp-settings',
    '/owner/notification-templates',
    '/owner/company-info',
    '/owner/system-config',
    '/owner/invoice-settings',
    '/owner/data-cleanup',
    '/owner/cards-vault',
    '/owner/financial-dashboard-advanced',
]


class TestOwnerReadPages:
    @pytest.mark.parametrize('url', OWNER_READ_PAGES)
    def test_owner_can_open(self, client, owner_client_user, url):
        _login(client, owner_client_user)
        resp = client.get(url)
        assert resp.status_code == 200, f"{url} -> {resp.status_code}"

    @pytest.mark.parametrize('url', [
        '/owner/dashboard',
        '/owner/database-tools',
        '/owner/system-stats',
    ])
    def test_non_owner_gets_stealth_404(self, client, plain_user, url):
        _login(client, plain_user)
        assert client.get(url).status_code == 404

    def test_unauthenticated_redirects_to_login(self, client):
        resp = client.get('/owner/dashboard')
        assert resp.status_code in (302, 404)


class TestOwnerDatabaseToolsGuards:
    def test_truncate_rejects_unknown_table(self, client, owner_client_user, db):
        _login(client, owner_client_user)
        before = Customer.query.count()
        resp = client.post('/owner/truncate-table',
                           data={'table_name': 'no_such_table_xyz'},
                           follow_redirects=False)
        assert resp.status_code in (302, 400, 404)
        assert Customer.query.count() == before

    def test_browse_rejects_unknown_table(self, client, owner_client_user):
        _login(client, owner_client_user)
        resp = client.get('/owner/browse-table/no_such_table_xyz')
        assert resp.status_code in (302, 404)


class TestOwnerTemplatePreview:
    @pytest.mark.parametrize('url', [
        '/owner/preview-invoice/modern',
        '/owner/preview-invoice/classic',
        '/owner/preview-receipt/modern',
        '/owner/preview-receipt/gulf',
    ])
    def test_valid_template_renders(self, client, owner_client_user, url):
        _login(client, owner_client_user)
        assert client.get(url).status_code == 200

    @pytest.mark.parametrize('url', [
        '/owner/preview-invoice/default',
        '/owner/preview-invoice/nope',
        '/owner/preview-receipt/default',
        '/owner/preview-invoice/....',
        '/owner/preview-receipt/a%20b',
    ])
    def test_unknown_or_malicious_template_404(self, client, owner_client_user, url):
        _login(client, owner_client_user)
        assert client.get(url).status_code == 404


class TestOwnerPaymentGateways:
    def test_autocreates_valid_vault_row(self, client, owner_client_user, db):
        from models import PaymentVault
        _login(client, owner_client_user)
        assert PaymentVault.query.count() == 0
        assert client.get('/owner/payment-gateways').status_code == 200
        vault = PaymentVault.query.first()
        assert vault is not None
        assert vault.vault_password_hash  # NOT NULL satisfied
        assert vault.is_locked is not False  # stays locked

    def test_post_updates_keys(self, client, owner_client_user, db):
        _login(client, owner_client_user)
        resp = client.post('/owner/payment-gateways', data={
            'stripe_publishable_key': 'pk_test_123'})
        assert resp.status_code == 302
        from models import PaymentVault
        assert PaymentVault.query.first().stripe_publishable_key == 'pk_test_123'
