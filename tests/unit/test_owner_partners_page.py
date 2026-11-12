"""Smoke اختبارات صفحة المالك /owner/partners — العرض + حدود الأمان."""

from decimal import Decimal

import pytest

from extensions import db as _db
from models import Customer, Role, Tenant, User


def _login(client, user):
    client.post(
        "/auth/login",
        data={
            "username": user.username,
            "password": "Pass123!",
        },
    )


@pytest.fixture(scope="function")
def owner(db):
    role = Role(name="OwnerPartners", name_ar="المالك", slug="owner")
    _db.session.add(role)
    _db.session.flush()
    user = User(
        username="owner_partners",
        email="owner_partners@test.com",
        full_name="Owner",
        is_owner=True,
        is_active=True,
        role_id=role.id,
    )
    user.set_password("Pass123!")
    _db.session.add(user)
    _db.session.commit()
    return user


@pytest.fixture(scope="function")
def tenant(db):
    t = Tenant(
        name="شركة التوزيع",
        name_ar="شركة التوزيع",
        slug="distribution-co",
        is_active=True,
    )
    _db.session.add(t)
    _db.session.commit()
    return t


@pytest.fixture(scope="function")
def candidate_customer(db):
    c = Customer(
        name="شريك محتمل", name_ar="شريك محتمل", customer_type="regular", is_active=True
    )
    _db.session.add(c)
    _db.session.commit()
    return c


def _impersonate(client, tenant):
    with client.session_transaction() as sess:
        sess["impersonate_tenant_id"] = tenant.id


class TestOwnerPartnersPage:
    def test_anonymous_is_redirected(self, client):
        resp = client.get("/owner/partners")
        assert resp.status_code in (302, 404)

    def test_owner_without_impersonation_gets_overview(self, client, owner, tenant):
        _login(client, owner)
        resp = client.get("/owner/partners")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "تجميعي" in body

    def test_owner_with_impersonation_gets_tenant_view(self, client, owner, tenant):
        _login(client, owner)
        _impersonate(client, tenant)
        resp = client.get("/owner/partners")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "سياق الشركة" in body

    def test_post_without_impersonation_is_refused(
        self, client, owner, tenant, candidate_customer
    ):
        _login(client, owner)
        resp = client.post(
            "/owner/partners",
            data={
                "action": "set_scope",
                "customer_id": str(candidate_customer.id),
                "scope": "company",
                "share": "25",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        # لا يُحفظ أي تعديل بدون سياق الشركة
        _db.session.refresh(candidate_customer)
        assert candidate_customer.partner_scope == "none"

    def test_set_scope_with_impersonation_saves(
        self, client, owner, tenant, candidate_customer
    ):
        _login(client, owner)
        _impersonate(client, tenant)
        resp = client.post(
            "/owner/partners",
            data={
                "action": "set_scope",
                "customer_id": str(candidate_customer.id),
                "scope": "company",
                "share": "30",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        _db.session.refresh(candidate_customer)
        assert candidate_customer.partner_scope == "company"
        assert str(candidate_customer.partner_share) in ("30", "30.000")
        assert candidate_customer.customer_type == "partner"

    def test_cover_html_renders_without_jinja_errors(self, client, owner, tenant):
        _login(client, owner)
        _impersonate(client, tenant)
        resp = client.get("/owner/partners")
        body = resp.get_data(as_text=True)
        assert "توزيع أرباح الشركاء" in body
        assert "Traceback" not in body


class TestRecordDrawAndDistributeViaPage:
    """مسار كامل: دخول سياق الشركة → تسجيل المسحوبات وتوزيع الأرباح من الصفحة."""

    def test_record_draw_via_page_creates_partner_draw_entry(
        self, client, owner, tenant, db
    ):
        partner = Customer(
            name="شريك المسحوبات",
            name_ar="شريك المسحوبات",
            customer_type="partner",
            partner_scope="company",
            partner_share=Decimal("25.000"),
            is_active=True,
        )
        db.session.add(partner)
        db.session.commit()

        _login(client, owner)
        _impersonate(client, tenant)
        resp = client.post(
            "/owner/partners",
            data={
                "action": "record_draw",
                "partner_id": str(partner.id),
                "amount": "120",
                "source": "cash",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302

        from models import GLJournalEntry, GLJournalLine

        entries = GLJournalEntry.query.filter_by(
            reference_type="PartnerDraw", reference_id=partner.id
        ).all()
        assert entries, "يجب أن تُسجَّل المسحوبات كقيد PartnerDraw"
        lines = GLJournalLine.query.filter_by(party_id=partner.id).all()
        assert any(l.debit == Decimal("120.000") for l in lines)

    def test_distribute_via_page_posts_tenant_scoped_entry(
        self, client, owner, tenant, db
    ):
        from models.tenant_scope import run_in_tenant_context
        from services.account_resolution import AccountResolver, AccountRole
        from services.gl_service import GLService

        def _setup():
            partner = Customer(
                name="شريك التوزيع",
                name_ar="شريك التوزيع",
                customer_type="partner",
                partner_scope="company",
                partner_share=Decimal("50.000"),
                is_active=True,
            )
            db.session.add(partner)
            db.session.flush()
            GLService.post_entry(
                [
                    {
                        "account": AccountResolver.resolve(AccountRole.CASH),
                        "debit": Decimal("900"),
                        "description": "d",
                    },
                    {
                        "account": AccountResolver.resolve(AccountRole.SALES_REVENUE),
                        "credit": Decimal("900"),
                        "description": "d",
                    },
                ],
                description="إيراد اختبار صفحة التوزيع",
                reference_type="Test",
                exchange_rate=Decimal("1"),
            )
            db.session.commit()
            return partner

        partner = run_in_tenant_context(tenant.id, _setup)

        _login(client, owner)
        _impersonate(client, tenant)
        resp = client.post(
            "/owner/partners",
            data={
                "action": "distribute",
                "from": "2020-01-01",
                "to": "2099-12-31",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302

        from models import GLJournalEntry

        entries = GLJournalEntry.query.filter_by(
            reference_type="PartnerDistribution", tenant_id=tenant.id, is_reversed=False
        ).all()
        assert entries, "يجب أن يُرحَّل توزيع الشركة تحت تينانت الشركة"
        entry = entries[0]
        assert entry.total_debit == entry.total_credit
        partner_lines = [l for l in entry.lines if l.party_id == partner.id]
        assert partner_lines, "قيد التوزيع يجب أن يسجل party_id للشريك"
