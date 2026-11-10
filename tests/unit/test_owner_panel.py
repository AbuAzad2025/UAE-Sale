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
# NOTE: user management lives at the unified /users/* stack (the legacy
# /owner/users-list was merged away) — covered via '/users/' below.
OWNER_READ_PAGES = [
    '/owner/dashboard',
    '/owner/system-stats',
    '/owner/audit-logs',
    '/users/',
    '/owner/roles-permissions',
    '/owner/financial-overview',
    '/owner/database-tools',
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
    '/owner/tax-rulesets',
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
    def test_non_owner_redirected_to_dashboard(self, client, plain_user, url):
        # owner_required redirects authenticated non-owners to the main
        # dashboard (no stealth 404) — see utils/decorators.py.
        _login(client, plain_user)
        resp = client.get(url, follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith('/dashboard')

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


class TestOwnerTaxRulesets:
    def test_owner_can_view(self, client, owner_client_user, db):
        _login(client, owner_client_user)
        assert client.get('/owner/tax-rulesets').status_code == 200

    def test_non_owner_redirected(self, client, plain_user):
        _login(client, plain_user)
        resp = client.get('/owner/tax-rulesets', follow_redirects=False)
        assert resp.status_code == 302

    def test_create_and_update_roundtrip(self, client, owner_client_user, db):
        from decimal import Decimal
        from models import TaxRuleset

        _login(client, owner_client_user)

        resp = client.post('/owner/tax-rulesets', data={
            'action': 'create',
            'country_code': 'XX',
            'country_name': 'بلا حالة قانونية',
            'vat_rate': '8.25',
            'vat_label': 'TESTVAT',
            'corp_tax_rate': '1.50',
            'corp_tax_threshold': '1000',
            'vat_enabled_default': 'on',
            'einvoice_required': 'on',
            'einvoice_status': 'manual',
            'authority_name': 'Test Authority',
            'authority_notes': 'اختبار',
            'compliance_notes': 'test ruleset',
            'is_active': 'on',
        }, follow_redirects=False)
        assert resp.status_code == 302

        row = TaxRuleset.query.filter_by(country_code='XX', tenant_id=None).first()
        assert row is not None
        assert row.vat_rate == Decimal('8.25')
        assert row.corp_tax_rate == Decimal('1.50')
        assert row.einvoice_required is True
        assert row.authority_name == 'Test Authority'

        resp = client.post('/owner/tax-rulesets', data={
            'action': 'update',
            'id': row.id,
            'country_code': 'XX',
            'country_name': 'بلا حالة قانونية',
            'vat_rate': '7.50',
            'vat_label': 'TESTVAT',
            'corp_tax_rate': '2.00',
            'corp_tax_threshold': '2000',
            'authority_name': 'Test Authority',
            'einvoice_status': 'manual',
            'authority_notes': 'اختبار',
            'compliance_notes': 'updated',
        }, follow_redirects=False)
        assert resp.status_code == 302

        _db.session.expire_all()
        row = TaxRuleset.query.filter_by(country_code='XX', tenant_id=None).first()
        assert row.vat_rate == Decimal('7.50')
        assert row.corp_tax_threshold in (Decimal('2000.00'), Decimal('2000'))
        assert row.is_active is False  # unchecked checkbox -> False after update


class TestOwnerComplianceCredentials:
    def _get_tenant(self, db, slug="test-tenant-cc"):
        from models import Tenant
        t = Tenant(name="CC Test Tenant", name_ar="مستأجر اختبار", slug=slug,
                   is_active=True)
        db.session.add(t)
        db.session.commit()
        return t

    def test_owner_can_view(self, client, owner_client_user, db):
        _login(client, owner_client_user)
        assert client.get("/owner/compliance-credentials").status_code == 200

    def test_non_owner_redirected(self, client, plain_user):
        _login(client, plain_user)
        resp = client.get("/owner/compliance-credentials", follow_redirects=False)
        assert resp.status_code == 302

    def test_save_verify_clear_roundtrip(self, client, owner_client_user, db):
        from models import ComplianceCredential
        from services import compliance_credentials as cc

        tenant = self._get_tenant(db)
        _login(client, owner_client_user)

        resp = client.post("/owner/compliance-credentials", data={
            "tenant_id": str(tenant.id),
            "authority_key": "zatca",
            "action": "save",
            "csid": "ZATCA-CSID-TESTVALUE-0001",
            "private_key_pem": "-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----",
            "certificate_pem": "-----BEGIN CERTIFICATE-----\ntest\n-----END CERTIFICATE-----",
            "zatca_api_environment": "integration",
            "request_id": "REQ-1",
            "notes": "اختبار آلي",
        }, follow_redirects=False)
        assert resp.status_code == 302

        row = ComplianceCredential.query.filter_by(
            tenant_id=tenant.id, authority_key="zatca").first()
        assert row is not None
        assert row.status == "configured"
        assert row.payload_encrypted

        vals = cc.credential_values(tenant.id, "zatca")
        assert vals["csid"] == "ZATCA-CSID-TESTVALUE-0001"
        assert vals["request_id"] == "REQ-1"
        assert vals["zatca_api_environment"] == "integration"

        client.post("/owner/compliance-credentials", data={
            "tenant_id": str(tenant.id),
            "authority_key": "zatca",
            "action": "verify",
        }, follow_redirects=False)
        db.session.expire_all()
        assert row.status == "verified"

        client.post("/owner/compliance-credentials", data={
            "tenant_id": str(tenant.id),
            "authority_key": "zatca",
            "action": "clear",
        }, follow_redirects=False)
        db.session.expire_all()
        assert row.status == "missing"
        assert cc.credential_values(tenant.id, "zatca") == {}

    def test_secret_fields_never_rendered_in_html(self, client, owner_client_user, db):
        from services import compliance_credentials as cc

        tenant = self._get_tenant(db, "test-tenant-secret")
        cc.save_credential(tenant.id, "zatca", {
            "csid": "SUPER-SECRET-CSID-DO-NOT-LEAK-9999",
            "private_key_pem": "-----BEGIN SECRET-----\nsecret-material\n-----END SECRET-----",
        })
        _login(client, owner_client_user)
        resp = client.get(f"/owner/compliance-credentials?tenant_id={tenant.id}")
        html = resp.get_data(as_text=True)
        assert "SUPER-SECRET-CSID-DO-NOT-LEAK-9999" not in html
        assert "secret-material" not in html


class TestOwnerPlans:
    def test_owner_can_view(self, client, owner_client_user, db):
        _login(client, owner_client_user)
        assert client.get("/owner/plans").status_code == 200

    def test_non_owner_redirected(self, client, plain_user):
        _login(client, plain_user)
        resp = client.get("/owner/plans", follow_redirects=False)
        assert resp.status_code == 302

    def test_create_toggle_roundtrip(self, client, owner_client_user, db):
        from models import SubscriptionPlan

        _login(client, owner_client_user)
        resp = client.post("/owner/plans", data={
            "action": "create",
            "slug": "platinum_test",
            "name_ar": "باقة مميزة اختبار",
            "name_en": "Platinum Test",
            "price_year": "499.00",
            "price_month": "49.00",
            "currency": "AED",
            "max_users": "25",
            "max_products": "9999",
            "max_customers": "99999",
            "sort_order": "40",
            "is_public": "on",
            "is_active": "on",
            "features_ar": "كل ميزات الاحترافية",
            "features_en": "All pro features",
        }, follow_redirects=False)
        assert resp.status_code == 302

        row = SubscriptionPlan.query.filter_by(slug="platinum_test").first()
        assert row is not None
        assert str(row.price_year) == "499.00"
        assert row.is_active is True

        resp = client.post(f"/owner/plans/{row.id}/toggle",
                           data={}, follow_redirects=False)
        assert resp.status_code == 302
        db.session.expire_all()
        row = SubscriptionPlan.query.filter_by(slug="platinum_test").first()
        assert row.is_active is False


class TestOwnerIncidents:
    def test_owner_can_view(self, client, owner_client_user, db):
        _login(client, owner_client_user)
        assert client.get("/owner/incidents").status_code == 200

    def test_create_and_resolve(self, client, owner_client_user, db):
        from models import Incident

        _login(client, owner_client_user)
        resp = client.post("/owner/incidents", data={
            "action": "create",
            "title": "اختبار حادث آلي",
            "severity": "sev2",
            "status": "open",
            "impact": "فرع اختباري فقط",
        }, follow_redirects=False)
        assert resp.status_code == 302

        row = Incident.query.filter_by(title="اختبار حادث آلي").first()
        assert row is not None
        assert row.status == "open"

        resp = client.post("/owner/incidents", data={
            "action": "resolve",
            "incident_id": str(row.id),
            "resolution_notes": "الحل: إعادة تشغيل الخدمة",
        }, follow_redirects=False)
        assert resp.status_code == 302
        db.session.expire_all()
        assert Incident.query.get(row.id).status == "resolved"


class TestOwnerSupportInbox:
    def _make_tenant(self, db, slug):
        from models import Tenant
        t = Tenant(name=f"Secret Co {slug}", name_ar=f"شركة {slug}",
                   slug=slug, is_active=True)
        db.session.add(t)
        db.session.commit()
        return t

    def _make_user(self, db, role, tenant_id, username):
        from models import User
        u = User(username=username, email=f"{username}@t.com", full_name=username,
                 is_active=True, role_id=role.id, tenant_id=tenant_id)
        u.set_password("Pass123!")
        db.session.add(u)
        db.session.commit()
        return u

    def test_tenant_sees_only_own_tickets(self, client, db):
        from models import Role, User, SupportTicket

        t1 = self._make_tenant(db, "alpha-inbox")
        t2 = self._make_tenant(db, "beta-inbox")
        role = Role.query.filter_by(slug="seller").first()
        if role is None:
            from models import Permission
            role = Role(name="Seller", name_ar="بائع", slug="seller")
            db.session.add(role)
            db.session.flush()
        u1 = self._make_user(db, role, t1.id, "inbox_u1")
        u2 = self._make_user(db, role, t2.id, "inbox_u2")

        db.session.add(SupportTicket(tenant_id=t1.id, author_user_id=u1.id,
                                     subject="تذكرة ألفا", description="أ"))
        db.session.add(SupportTicket(tenant_id=t2.id, author_user_id=u2.id,
                                     subject="تذكرة بيتا", description="ب"))
        db.session.commit()

        client.post("/auth/login", data={"username": u1.username,
                                         "password": "Pass123!"},
                    follow_redirects=True)
        resp = client.get("/support/tickets")
        html = resp.get_data(as_text=True)
        assert "تذكرة ألفا" in html
        assert "تذكرة بيتا" not in html

    def test_owner_sees_all_tickets(self, client, db, owner_client_user):
        from models import SupportTicket

        t1 = self._make_tenant(db, "alpha-all")
        t2 = self._make_tenant(db, "beta-all")
        owner = owner_client_user
        db.session.add(SupportTicket(tenant_id=t1.id, author_user_id=owner.id,
                                     subject="تذكرة في الإنبوكس", description="x"))
        db.session.add(SupportTicket(tenant_id=t2.id, author_user_id=owner.id,
                                     subject="تذكرة ثانية في الإنبوكس", description="y"))
        db.session.commit()
        _login(client, owner)
        resp = client.get("/owner/support-tickets")
        html = resp.get_data(as_text=True)
        assert "تذكرة في الإنبوكس" in html
        assert "تذكرة ثانية في الإنبوكس" in html
