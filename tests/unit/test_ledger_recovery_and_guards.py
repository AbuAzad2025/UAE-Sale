from datetime import date
from decimal import Decimal

import pytest

from scripts.restore_journals import restore_journals
from models import GLAccount, GLJournalEntry, SystemSettings, Tenant
from models.tenant_scope import run_in_tenant_context
from services.advanced_journal_manager import AdvancedJournalEntryManager
from services.gl_service import GLService
from services.account_resolution import AccountResolver, AccountRole


@pytest.fixture
def company(db):
    tenant = Tenant(name="Recovery Test", name_ar="الفحص", slug="recovery-test")
    db.session.add(tenant)
    db.session.commit()
    return tenant


def test_recovery_is_scoped_atomic_and_repeatable(db, company, owner_user):
    record = {
        "entry_number": "SOURCE-1",
        "entry_date": date.today().isoformat(),
        "currency": "ILS",
        "exchange_rate": "1",
        "description": "Cash opening",
        "lines": [
            {"account": "1110", "debit": "20"},
            {"account": "3100", "credit": "20"},
        ],
    }
    export = {"tenant_id": company.id, "journals": [record]}
    with pytest.raises(ValueError, match="explicitly selected tenant"):
        restore_journals(company.id + 1, owner_user.id, export)
    broken = {**record, "entry_number": "SOURCE-2", "lines": record["lines"][:1]}

    with pytest.raises(ValueError, match="not balanced"):
        restore_journals(
            company.id, owner_user.id, {**export, "journals": [record, broken]}
        )
    assert GLJournalEntry.query.filter_by(tenant_id=company.id).count() == 0
    assert restore_journals(company.id, owner_user.id, export) == 1
    assert restore_journals(company.id, owner_user.id, export) == 0
    assert GLJournalEntry.query.filter_by(tenant_id=company.id).count() == 1


def test_posting_balances_base_currency_after_line_rounding(db, company, owner_user):
    def post():
        entry = GLService.post_entry(
            [
                {"account": "1110", "debit": "0.02"},
                {"account": "4100", "credit": "0.01"},
                {"account": "4100", "credit": "0.01"},
            ],
            exchange_rate="0.05",
            tenant_id=company.id,
            created_by=owner_user.id,
        )
        assert entry.total_debit == entry.total_credit == Decimal("0.02")
        assert sum(line.amount_base for line in entry.lines) == 0

    run_in_tenant_context(company.id, post)


def test_draft_approval_rechecks_disabled_account(db, company, owner_user):
    def check():
        entry = GLService.create_manual_entry(
            "Draft",
            [{"account": "1110", "debit": 20}, {"account": "3100", "credit": 20}],
            is_posted=False,
            tenant_id=company.id,
            created_by=owner_user.id,
        )
        cash = GLAccount.query.filter_by(code="1110").one()
        cash.is_active = False
        with pytest.raises(ValueError, match="inactive"):
            AdvancedJournalEntryManager.approve_entry(entry.id, owner_user.id)
        assert not entry.is_posted

    run_in_tenant_context(company.id, check)


def test_draft_approval_requires_zero_residual_and_open_period(db, company, owner_user):
    from services.fiscal_period_guard import ensure_current_period
    from utils.errors import ValidationError

    def check():
        period = ensure_current_period(tenant_id=company.id)
        draft = GLService.create_manual_entry(
            "Draft",
            [{"account": "1110", "debit": 20}, {"account": "3100", "credit": 20}],
            is_posted=False,
            tenant_id=company.id,
            created_by=owner_user.id,
        )
        debit = next(line for line in draft.lines if line.debit)
        debit.debit = Decimal("20.001")
        with pytest.raises(ValueError, match="غير متوازن"):
            AdvancedJournalEntryManager.approve_entry(draft.id, owner_user.id)
        assert not draft.is_posted
        debit.debit = Decimal("20")
        period.is_closed = True
        with pytest.raises(ValidationError, match="مغلقة"):
            AdvancedJournalEntryManager.approve_entry(draft.id, owner_user.id)
        assert not draft.is_posted

    run_in_tenant_context(company.id, check)


def test_role_map_is_scoped_and_invalid_configuration_raises(db, company):
    other = Tenant(name="Other", name_ar="أخرى", slug="other")
    db.session.add(other)
    db.session.flush()
    settings = SystemSettings(system_name="role test", is_active=True)
    settings.set_custom_setting("gl_role_map", {"BANK": "1120"})
    settings.set_custom_setting(f"gl_role_map:{company.id}", {"BANK": "1121"})
    db.session.add(settings)
    db.session.commit()
    assert (
        run_in_tenant_context(company.id, AccountResolver.resolve, AccountRole.BANK)
        == "1121"
    )
    assert (
        run_in_tenant_context(other.id, AccountResolver.resolve, AccountRole.BANK)
        == "1120"
    )
    for method in ("bank_transfer", "card", "e_wallet"):
        assert (
            GLService.get_payment_debit_account(method, tenant_id=company.id) == "1121"
        )
    settings.set_custom_setting(f"gl_role_map:{company.id}", {"BANK": ""})
    db.session.flush()
    with pytest.raises(ValueError, match="Invalid account code"):
        AccountResolver.resolve(AccountRole.BANK, tenant_id=company.id)


def test_concurrent_posting_of_the_same_key_creates_one_journal(
    app, db, company, owner_user
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from utils.transaction import atomic_transaction

    if db.engine.dialect.name != "postgresql":
        pytest.skip("Verifies transaction-scoped PostgreSQL journal locking.")
    GLService.ensure_core_accounts()
    db.session.commit()
    tenant_id, actor_id = company.id, owner_user.id
    start = Barrier(2)

    def worker():
        def post():
            start.wait(timeout=10)
            with atomic_transaction():
                entry = GLService.post_entry(
                    [
                        {"account": "1110", "debit": 20},
                        {"account": "3100", "credit": 20},
                    ],
                    tenant_id=tenant_id,
                    created_by=actor_id,
                    idempotency_key="same-operation",
                )
                return entry.id

        with app.app_context():
            return run_in_tenant_context(tenant_id, post)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(worker), pool.submit(worker)
        assert first.result(timeout=15) == second.result(timeout=15)
    assert (
        GLJournalEntry.query.filter_by(
            tenant_id=tenant_id, idempotency_key="same-operation"
        ).count()
        == 1
    )
