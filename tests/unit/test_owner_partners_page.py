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
def candidate_customer(db, tenant):
    c = Customer(
        name="شريك محتمل", name_ar="شريك محتمل", customer_type="regular", is_active=True,
        tenant_id=tenant.id,
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

    def test_owner_selected_company_cannot_change_unassigned_customer(self, client, owner, tenant, db):
        outsider = Customer(name="خارج الشركة", customer_type="regular")
        db.session.add(outsider)
        db.session.commit()
        _login(client, owner)
        _impersonate(client, tenant)
        client.post("/owner/partners", data={
            "action": "set_scope", "customer_id": outsider.id, "scope": "company", "share": "10",
        })
        assert db.session.get(Customer, outsider.id).partner_scope == "none"

    @pytest.mark.parametrize("role,permissions,expected", [
        ("partner-accountant", ("view_ledger", "manage_payments", "manage_ledger"), (200, 403, 302, 302)),
        ("partner-manager", ("view_ledger", "manage_customers", "manage_payments", "manage_ledger"), (200, 302, 302, 302)),
        ("partner-seller", ("manage_customers",), (403, 403, 403, 403)),
    ])
    def test_financial_actions_follow_the_role(self, client, db, tenant, role, permissions, expected):
        from models import Permission

        grants = []
        for code in permissions:
            grant = Permission.query.filter_by(code=code).first()
            grants.append(grant or Permission(code=code, name=code))
        group = Role(name=role, slug=role, tenant_id=tenant.id, permissions=grants)
        user = User(username=role, email=f"{role}@test.invalid", role=group, tenant_id=tenant.id)
        user.set_password("Pass123!")
        db.session.add(user)
        db.session.commit()
        _login(client, user)
        path = "/settings/partners"
        response = client.get(path)
        body = response.get_data(as_text=True)
        assert response.status_code == expected[0]
        assert ('name="action" value="set_scope"' in body) == ("manage_customers" in permissions and expected[0] == 200)
        for action, status in zip(("set_scope", "record_draw", "distribute"), expected[1:]):
            assert client.post(path, data={"action": action}).status_code == status


class TestRecordDrawAndDistributeViaPage:
    """مسار كامل: دخول سياق الشركة → تسجيل المسحوبات وتوزيع الأرباح من الصفحة."""

    def test_record_draw_via_page_creates_partner_draw_entry(
        self, client, owner, tenant, db
    ):
        partner = Customer(
            name="شريك المسحوبات",
            tenant_id=tenant.id,
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
            reference_type="PartnerDraw", reference_id=partner.id, tenant_id=tenant.id,
        ).all()
        assert entries, "يجب أن تُسجَّل المسحوبات كقيد PartnerDraw"
        lines = GLJournalLine.query.filter_by(party_id=partner.id).all()
        assert any(l.debit == Decimal("120.000") for l in lines)
        assert all(line.tenant_id == tenant.id for line in lines)

    def test_distribute_via_page_posts_tenant_scoped_entry(
        self, client, owner, tenant, db
    ):
        from models import Sale
        from models.tenant_scope import run_in_tenant_context
        from services.account_resolution import AccountResolver, AccountRole
        from services.gl_service import GLService
        from services.partner_profit import preview_partner_distributions

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
            db.session.add(Sale(
                sale_number="PARTNER-FX", tenant_id=tenant.id, customer_id=partner.id, seller_id=owner.id,
                total_amount=100, amount_base=200, balance_due=200, currency="USD", exchange_rate=2,
                status="confirmed",
            ))
            db.session.commit()
            return partner

        partner = run_in_tenant_context(tenant.id, _setup)
        rows = preview_partner_distributions(tenant_id=tenant.id)
        preview = next(row for row in rows if row["partner_id"] == partner.id)
        assert preview["sales_to_partner_deducted"] == Decimal("200.000")

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
        assert partner_lines[0].credit == Decimal("250.000")


def test_reversal_preserves_partner_and_nets_posted_profit(db, tenant, owner_user):
    from models.tenant_scope import run_in_tenant_context
    from services.account_resolution import AccountResolver, AccountRole
    from services.advanced_journal_manager import AdvancedJournalEntryManager
    from services.gl_service import GLService
    from services.partner_profit import compute_net_income

    def verify():
        partner = Customer(name="شريك قيد العكس", tenant_id=tenant.id)
        db.session.add(partner)
        db.session.flush()
        original = GLService.post_entry([
            {"account": "1110", "debit": Decimal("90")},
            {"account": AccountResolver.resolve(AccountRole.SALES_REVENUE), "credit": Decimal("90"), "party_id": partner.id},
        ], currency="USD", exchange_rate=2, created_by=owner_user.id)
        assert compute_net_income(tenant_id=tenant.id) == Decimal("180.000")
        reversal = AdvancedJournalEntryManager.reverse_entry_advanced(original.id, owner_user.id, "اختبار العكس")
        assert reversal.currency == "USD" and reversal.exchange_rate == 2
        assert any(line.party_id == partner.id and line.amount_base == Decimal("180") for line in reversal.lines)
        assert compute_net_income(tenant_id=tenant.id) == Decimal("0.000")
        with pytest.raises(ValueError, match="معكوس"):
            AdvancedJournalEntryManager.reverse_entry_advanced(reversal.id, owner_user.id, "اختبار العكس المكرر")

    run_in_tenant_context(tenant.id, verify)
