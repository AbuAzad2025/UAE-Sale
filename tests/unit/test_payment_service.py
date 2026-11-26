"""Unit tests for PaymentService — سندات القبض والتوزيع."""

from decimal import Decimal
from datetime import date, timedelta

import pytest

from models import Receipt, Cheque, Sale
from services.payment_service import PaymentService


@pytest.mark.parametrize("method", ["cash", "cheque"])
def test_partner_receipt_assigns_control_line_to_partner(db, owner_user, method):
    from models import Customer, GLJournalEntry, Tenant
    from models.tenant_scope import run_in_tenant_context
    from services.account_resolution import AccountResolver, AccountRole

    tenant = Tenant(
        name="Collections", name_ar="التحصيل", slug="collections", default_currency="ILS"
    )
    db.session.add(tenant)
    db.session.commit()

    def check():
        partner = Customer(name="Partner", customer_type="partner", tenant_id=tenant.id)
        db.session.add(partner)
        db.session.flush()
        receipt = PaymentService.create_receipt({
            "customer_id": partner.id, "user_id": owner_user.id, "amount": Decimal("50"),
            "payment_method": method, "currency": "ILS", "allocate_to_sales": {},
            "user_exchange_rate": Decimal("1"),
            "cheque_number": "TEST-PARTNER", "bank_name": "Test bank",
            "cheque_date": (date.today() + timedelta(days=1)).isoformat(),
        })
        if method == "cheque":
            entry = db.session.get(GLJournalEntry, receipt.cheque.gl_journal_entry_id)
        else:
            entry = GLJournalEntry.query.filter_by(reference_type="Receipt", reference_id=receipt.id).one()
        control = AccountResolver.resolve(AccountRole.PARTNERS_CURRENT, tenant_id=tenant.id)
        line, = [line for line in entry.lines if line.account.code == control]
        assert line.credit == Decimal("50")
        assert line.party_id == partner.id
        assert all(other.party_id is None for other in entry.lines if other.id != line.id)

    run_in_tenant_context(tenant.id, check)


def test_sale_payment_is_recorded_as_incoming(db, owner_user):
    from models import Customer, GLJournalEntry, Tenant
    from models.tenant_scope import run_in_tenant_context
    from services.sale_service import SaleService

    tenant = Tenant(name="Sales", name_ar="المبيعات", slug="sales", default_currency="ILS")
    db.session.add(tenant)
    db.session.commit()

    def check():
        customer = Customer(name="Customer", tenant_id=tenant.id)
        db.session.add(customer)
        db.session.flush()
        sale = Sale(
            sale_number="SALE-CASH-TEST", customer_id=customer.id, seller_id=owner_user.id,
            tenant_id=tenant.id, status="confirmed", currency="ILS",
            total_amount=Decimal("100"), amount_base=Decimal("100"),
        )
        db.session.add(sale)
        db.session.flush()
        payment = SaleService.create_payment_for_sale(sale, Decimal("35.60"), "cash", "ILS")
        entry = GLJournalEntry.query.filter_by(reference_type="Payment", reference_id=payment.id).one()
        assert payment.direction == "incoming"
        assert entry.total_debit == entry.total_credit == Decimal("35.60")

    run_in_tenant_context(tenant.id, check)


@pytest.fixture
def second_unpaid_sale(db, owner_user, test_customer):
    """Older unpaid sale to verify FIFO allocation ordering."""
    from utils.helpers import generate_number

    sale = Sale(
        sale_number=generate_number("S", Sale, "sale_number"),
        customer_id=test_customer.id,
        seller_id=owner_user.id,
        total_amount=Decimal("200.000"),
        amount_base=Decimal("200.000"),
        paid_amount=Decimal("0"),
        paid_amount_base=Decimal("0"),
        balance_due=Decimal("200.000"),
        currency="AED",
        exchange_rate=Decimal("1"),
        payment_status="unpaid",
        status="confirmed",
        is_active=True,
    )
    db.session.add(sale)
    db.session.commit()
    return sale


class TestCreateReceipt:
    def test_cash_receipt_created(self, db, owner_user, test_customer, app):
        receipt = PaymentService.create_receipt(
            {
                "customer_id": test_customer.id,
                "user_id": owner_user.id,
                "amount": Decimal("150"),
                "currency": "AED",
                "payment_method": "cash",
                "notes": "دفعة نقدية",
            }
        )
        assert receipt.id is not None
        assert receipt.receipt_number.startswith("RCV")
        assert receipt.direction == "incoming"
        assert receipt.source_type == "manual"
        assert Decimal(str(receipt.amount)) == Decimal("150")
        assert receipt.amount_base > 0
        assert receipt.user_id == owner_user.id

    def test_invalid_cheque_date_raises(self, db, owner_user, test_customer):
        with pytest.raises(ValueError):
            PaymentService.create_receipt(
                {
                    "customer_id": test_customer.id,
                    "amount": Decimal("50"),
                    "currency": "AED",
                    "payment_method": "cheque",
                    "cheque_number": "CH-001",
                    "cheque_date": "31-02-2026",
                }
            )

    def test_cheque_payment_creates_cheque_record(self, db, owner_user, test_customer):
        receipt = PaymentService.create_receipt(
            {
                "customer_id": test_customer.id,
                "amount": Decimal("500"),
                "currency": "AED",
                "payment_method": "cheque",
                "cheque_number": "CH-2026-77",
                "cheque_date": "2026-09-30",
                "bank_name": "Emirates NBD",
            }
        )
        cheque = Cheque.query.filter_by(cheque_number="CH-2026-77").first()
        assert cheque is not None
        assert cheque.cheque_type == "incoming"
        assert cheque.status == "pending"
        assert cheque.customer_id == test_customer.id
        assert receipt.cheque_id == cheque.id

    def test_allocation_partial_marks_sale_partial(
        self, db, owner_user, test_customer, test_sale
    ):
        sale = test_sale
        receipt = PaymentService.create_receipt(
            {
                "customer_id": test_customer.id,
                "amount": Decimal("60"),
                "currency": sale.currency,
                "payment_method": "cash",
                "user_exchange_rate": Decimal("1"),
                "allocate_to_sales": {sale.id: 60},
            }
        )
        db.session.refresh(sale)
        assert receipt.source_type == "sale"
        assert sale.paid_amount == Decimal("60.000")
        assert sale.balance_due == Decimal("40.000")
        assert sale.payment_status == "partial"

    def test_allocation_full_marks_sale_paid(
        self, db, owner_user, test_customer, test_sale
    ):
        sale = test_sale
        PaymentService.create_receipt(
            {
                "customer_id": test_customer.id,
                "amount": Decimal("100"),
                "currency": sale.currency,
                "payment_method": "cash",
                "user_exchange_rate": Decimal("1"),
                "allocate_to_sales": {sale.id: 100},
            }
        )
        db.session.refresh(sale)
        assert sale.paid_amount >= sale.total_amount
        assert sale.payment_status == "paid"
        assert sale.balance_due == 0


class TestBalances:
    def test_get_customer_balance_sums_confirmed_sales(
        self, db, owner_user, test_customer, test_sale, second_unpaid_sale
    ):
        balance = PaymentService.get_customer_balance(test_customer)
        assert balance == Decimal("300.000")

    def test_get_customer_balance_aed_uses_base_columns(
        self, db, owner_user, test_customer, test_sale
    ):
        balance = PaymentService.get_customer_balance_aed(test_customer)
        assert balance == Decimal("100.000")

    def test_get_unpaid_sales_orders_oldest_first(
        self, db, owner_user, test_customer, test_sale, second_unpaid_sale
    ):
        unpaid = PaymentService.get_unpaid_sales(test_customer)
        assert len(unpaid) == 2
        assert unpaid[0].id == test_sale.id
        assert unpaid[1].id == second_unpaid_sale.id


class TestAllocateToOldest:
    def test_allocates_fifo_across_sales(
        self, db, owner_user, test_customer, test_sale, second_unpaid_sale
    ):
        first, second = PaymentService.get_unpaid_sales(test_customer)[:2]
        receipt = Receipt(
            receipt_number="RCV-TEST-FIFO",
            source_type="manual",
            direction="incoming",
            customer_id=test_customer.id,
            amount=Decimal("250"),
            currency="AED",
            exchange_rate=Decimal("1"),
            amount_base=Decimal("250"),
            payment_method="cash",
            user_id=owner_user.id,
        )
        db.session.add(receipt)
        db.session.commit()

        PaymentService.allocate_receipt_to_oldest_sales(receipt, test_customer)

        db.session.refresh(first)
        db.session.refresh(second)
        assert first.paid_amount == Decimal("100.000")
        assert first.payment_status == "paid"
        assert second.paid_amount == Decimal("150.000")
        assert second.payment_status == "partial"

    def test_overpay_capped_at_balance_due(
        self, db, owner_user, test_customer, test_sale
    ):
        receipt = Receipt(
            receipt_number="RCV-TEST-CAP",
            source_type="manual",
            direction="incoming",
            customer_id=test_customer.id,
            amount=Decimal("999"),
            currency="AED",
            exchange_rate=Decimal("1"),
            amount_base=Decimal("999"),
            payment_method="cash",
            user_id=owner_user.id,
        )
        db.session.add(receipt)
        db.session.commit()

        PaymentService.allocate_receipt_to_oldest_sales(receipt, test_customer)

        db.session.refresh(test_sale)
        assert test_sale.paid_amount == Decimal("100.000")
        assert test_sale.payment_status == "paid"
