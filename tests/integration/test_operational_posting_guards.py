from datetime import date, timedelta
from decimal import Decimal

import pytest

from models import Cheque, GLJournalEntry, Payment, Product, Supplier, Tenant, Warehouse
from models.advanced_accounting import AdvancedExpense
from models.expense import Expense, ExpenseCategory
from models.hr import Employee, Payslip
from models.tenant_scope import run_in_tenant_context
from services import ai_commands
from services.cheque_accounting_integration import ChequeAccountingIntegration


@pytest.fixture
def company(db):
    tenant = Tenant(
        name="Posting", name_ar="الفحص", slug="posting", default_currency="ILS"
    )
    db.session.add(tenant)
    db.session.commit()
    return tenant


@pytest.fixture
def company_client(client, login_owner, company):
    with client.session_transaction() as session:
        session["impersonate_tenant_id"] = company.id
    return client


def test_ai_expense_and_cheque_share_the_canonical_ledger(db, company, owner_user):
    def check():
        expense = ai_commands.create_expense("Test expense", "25", owner_user.id)
        cheque = ai_commands.create_cheque(
            "AI-001", "40", date.today(), "incoming", owner_user.id
        )
        expense_entry = GLJournalEntry.query.filter_by(
            reference_type="Expense", reference_id=expense.id
        ).one()
        cheque_entry = db.session.get(GLJournalEntry, cheque.gl_journal_entry_id)
        assert expense_entry.total_debit == expense_entry.total_credit == Decimal("25")
        assert {
            (line.account.code, line.amount_base) for line in cheque_entry.lines
        } == {("1150", Decimal("40")), ("1130", Decimal("-40"))}
        assert (
            db.session.get(Expense, expense.id).tenant_id
            == cheque.tenant_id
            == company.id
        )

    run_in_tenant_context(company.id, check)


def test_manual_warehouse_addition_posts_value_and_rejects_missing_cost(
    company_client, db, company
):
    warehouse = Warehouse(name="Main", tenant_id=company.id, is_active=True)
    priced = Product(
        name="Priced",
        part_number="PRICED",
        cost_price=3,
        regular_price=10,
        tenant_id=company.id,
    )
    unpriced = Product(
        name="Unpriced",
        part_number="UNPRICED",
        cost_price=0,
        regular_price=10,
        tenant_id=company.id,
    )
    db.session.add_all([warehouse, priced, unpriced])
    db.session.commit()
    form = {"warehouse_id": warehouse.id, "quantity": "2"}
    ok = company_client.post(f"/warehouse/add-stock/{priced.id}", data=form)
    assert ok.status_code == 200, ok.get_json()
    assert ok.get_json()["new_stock"] == 2
    entry = GLJournalEntry.query.filter_by(
        reference_type="stock_adjustment", tenant_id=company.id
    ).one()
    assert {(line.account.code, line.amount_base) for line in entry.lines} == {
        ("1140", Decimal("6")),
        ("5150", Decimal("-6")),
    }
    rejected = company_client.post(f"/warehouse/add-stock/{unpriced.id}", data=form)
    assert rejected.status_code == 400
    db.session.refresh(unpriced)
    assert not unpriced.current_stock
    assert (
        GLJournalEntry.query.filter_by(
            reference_type="stock_adjustment", tenant_id=company.id
        ).count()
        == 1
    )


def test_supplier_cheque_and_advanced_clear_use_one_canonical_posting(
    company_client, db, company, owner_user
):
    supplier = Supplier(name="Supplier", tenant_id=company.id)
    db.session.add(supplier)
    db.session.commit()
    response = company_client.post(
        "/payments/voucher/submit",
        data={
            "direction": "incoming",
            "party_type": "supplier",
            "party_id": supplier.id,
            "amount": "100",
            "currency": "ILS",
            "payment_method": "cheque",
            "cheque_number": "VENDOR-1",
            "cheque_date": date.today().isoformat(),
            "bank_name": "Test bank",
        },
    )
    assert response.status_code == 302 and response.location.endswith(
        "/payments/receipts"
    )
    cheque = Cheque.query.filter_by(
        cheque_bank_number="VENDOR-1", tenant_id=company.id
    ).one()
    cheque_id = cheque.id
    original_id = cheque.gl_journal_entry_id
    assert cheque.status == "pending"
    assert not db.session.get(Payment, cheque.payment_id).payment_confirmed
    url = f"/ledger/advanced/cheque-integration/{cheque_id}"
    assert company_client.post(f"{url}/receive").status_code == 302
    db.session.remove()
    deposited = db.session.get(Cheque, cheque_id)
    assert (
        deposited.status == "deposited" and deposited.gl_journal_entry_id == original_id
    )
    assert (
        company_client.post(f"{url}/clear", data={"bank_charges": "2"}).status_code
        == 302
    )
    db.session.remove()

    def check():
        cheque = db.session.get(Cheque, cheque_id)
        origin = db.session.get(GLJournalEntry, cheque.gl_journal_entry_id)
        assert {(line.account.code, line.amount_base) for line in origin.lines} == {
            ("1150", Decimal("100")),
            ("2110", Decimal("-100")),
        }
        payment = db.session.get(Payment, cheque.payment_id)
        assert cheque.status == "cleared" and payment.payment_confirmed
        clearing = db.session.get(GLJournalEntry, cheque.gl_clearing_entry_id)
        assert {(line.account.code, line.amount_base) for line in clearing.lines} == {
            ("1120", Decimal("98")),
            ("1150", Decimal("-100")),
            ("6950", Decimal("2")),
        }
        assert clearing.created_by == owner_user.id
        assert payment.payment_confirmed
        assert (
            GLJournalEntry.query.filter_by(
                reference_type="cheque_receive", reference_id=cheque.id
            ).count()
            == 1
        )
        with pytest.raises(ValueError, match="uncleared"):
            ChequeAccountingIntegration.clear_cheque(cheque.id, owner_user.id)

    run_in_tenant_context(company.id, check)


def test_advanced_expense_reverses_its_linked_posting(
    company_client, db, company, owner_user
):
    category = ExpenseCategory(name="Advanced Expense", gl_account_code="6990")
    db.session.add(category)
    db.session.commit()
    response = company_client.post(
        "/ledger/advanced/advanced-expenses/add",
        data={
            "expense_date": date.today().isoformat(),
            "category_id": category.id,
            "description": "Expense",
            "amount": "30",
            "payment_method": "bank_transfer",
            "payment_status": "paid",
        },
    )
    assert response.status_code == 302
    db.session.remove()

    def check():
        expense = AdvancedExpense.query.filter_by(tenant_id=company.id).one()
        original = db.session.get(GLJournalEntry, expense.gl_journal_entry_id)
        assert original.is_posted
        assert expense.post_expense().id == original.id
        reversal = expense.reverse_expense("Test correction", owner_user)
        with pytest.raises(ValueError, match="Invalid prior journal"):
            expense.post_expense()
        assert expense.gl_journal_entry_id == original.id
        assert reversal.reversed_entry_id == original.id
        assert {(line.account.code, line.amount_base) for line in reversal.lines} == {
            ("1120", Decimal("30")),
            ("6990", Decimal("-30")),
        }

    run_in_tenant_context(company.id, check)


def test_asset_disposal_uses_the_tenant_bank_mapping(db, company):
    from models import FixedAsset, GLAccount, SystemSettings

    def check():
        asset_account = GLAccount(code="1500", name="Asset", type="asset")
        depreciation = GLAccount(
            code="1501", name="Accumulated depreciation", type="asset"
        )
        settings = SystemSettings(system_name="Bank mapping", is_active=True)
        settings.set_custom_setting(f"gl_role_map:{company.id}", {"BANK": "1121"})
        db.session.add_all([asset_account, depreciation, settings])
        db.session.flush()
        asset = FixedAsset(
            tenant_id=company.id,
            asset_number="TEST-ASSET",
            name_ar="أصل",
            purchase_date=date.today(),
            purchase_price=Decimal("100"),
            accumulated_depreciation=Decimal("40"),
            book_value=Decimal("60"),
            useful_life_years=5,
            asset_account_id=asset_account.id,
            depreciation_account_id=depreciation.id,
            status="active",
        )
        db.session.add(asset)
        db.session.flush()
        asset.dispose(date.today(), Decimal("70"))
        entry = GLJournalEntry.query.filter_by(
            reference_type="asset_disposal", reference_id=asset.id
        ).one()
        assert {(line.account.code, line.amount_base) for line in entry.lines} == {
            ("1121", Decimal("70")),
            ("1501", Decimal("40")),
            ("4500", Decimal("-10")),
            ("1500", Decimal("-100")),
        }

    run_in_tenant_context(company.id, check)


def test_payroll_posts_on_actual_disbursement_date_to_selected_account(
    company_client, db, company, owner_user
):
    today = date.today()
    employee = Employee(
        employee_number="TEST-HR",
        user_id=owner_user.id,
        hire_date=today,
        tenant_id=company.id,
    )
    db.session.add(employee)
    db.session.flush()
    payslip = Payslip(
        payslip_number="TEST-PAY",
        employee_id=employee.id,
        tenant_id=company.id,
        pay_period_start=today,
        pay_period_end=today,
        pay_date=today + timedelta(days=2),
        total_earnings=100,
        net_salary=100,
        status="approved",
    )
    db.session.add(payslip)
    db.session.commit()
    url = f"/hr/payroll/{payslip.id}/pay"
    company_client.post(
        url, data={"disbursed_on": payslip.pay_date, "payment_method": "bank_transfer"}
    )
    db.session.refresh(payslip)
    assert payslip.status == "approved"
    assert payslip.gl_journal_entry_id is None
    response = company_client.post(
        url, data={"disbursed_on": today, "payment_method": "bank_transfer"}
    )
    assert response.status_code == 302
    db.session.refresh(payslip)
    assert payslip.status == "paid"
    assert payslip.disbursed_on == today and payslip.payment_method == "bank_transfer"
    entry = db.session.get(GLJournalEntry, payslip.gl_journal_entry_id)
    assert entry.entry_date.date() == today
    assert {(line.account.code, line.amount_base) for line in entry.lines} == {
        ("6100", Decimal("100")),
        ("1120", Decimal("-100")),
    }
