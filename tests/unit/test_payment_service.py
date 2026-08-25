"""Unit tests for PaymentService — سندات القبض والتوزيع."""
from decimal import Decimal

import pytest

from models import Receipt, Cheque, Sale
from services.payment_service import PaymentService


@pytest.fixture
def second_unpaid_sale(db, owner_user, test_customer):
    """Older unpaid sale to verify FIFO allocation ordering."""
    from utils.helpers import generate_number
    sale = Sale(
        sale_number=generate_number('S', Sale, 'sale_number'),
        customer_id=test_customer.id, seller_id=owner_user.id,
        total_amount=Decimal('200.000'), amount_base=Decimal('200.000'),
        paid_amount=Decimal('0'), paid_amount_base=Decimal('0'),
        balance_due=Decimal('200.000'), currency='AED',
        exchange_rate=Decimal('1'), payment_status='unpaid',
        status='confirmed', is_active=True,
    )
    db.session.add(sale)
    db.session.commit()
    return sale


class TestCreateReceipt:
    def test_cash_receipt_created(self, db, owner_user, test_customer, app):
        receipt = PaymentService.create_receipt({
            'customer_id': test_customer.id,
            'amount': Decimal('150'),
            'currency': 'AED',
            'payment_method': 'cash',
            'notes': 'دفعة نقدية',
        })
        assert receipt.id is not None
        assert receipt.receipt_number.startswith('RCV')
        assert receipt.direction == 'incoming'
        assert receipt.source_type == 'manual'
        assert Decimal(str(receipt.amount)) == Decimal('150')
        assert receipt.amount_base > 0
        assert receipt.user_id == owner_user.id

    def test_invalid_cheque_date_raises(self, db, owner_user, test_customer):
        with pytest.raises(ValueError):
            PaymentService.create_receipt({
                'customer_id': test_customer.id,
                'amount': Decimal('50'),
                'currency': 'AED',
                'payment_method': 'cheque',
                'cheque_number': 'CH-001',
                'cheque_date': '31-02-2026',
            })

    def test_cheque_payment_creates_cheque_record(self, db, owner_user, test_customer):
        receipt = PaymentService.create_receipt({
            'customer_id': test_customer.id,
            'amount': Decimal('500'),
            'currency': 'AED',
            'payment_method': 'cheque',
            'cheque_number': 'CH-2026-77',
            'cheque_date': '2026-09-30',
            'bank_name': 'Emirates NBD',
        })
        cheque = Cheque.query.filter_by(cheque_number='CH-2026-77').first()
        assert cheque is not None
        assert cheque.cheque_type == 'incoming'
        assert cheque.status == 'pending'
        assert cheque.customer_id == test_customer.id
        assert receipt.cheque_id == cheque.id

    def test_allocation_partial_marks_sale_partial(self, db, owner_user, test_customer, test_sale):
        sale = test_sale
        receipt = PaymentService.create_receipt({
            'customer_id': test_customer.id,
            'amount': Decimal('60'),
            'currency': sale.currency,
            'payment_method': 'cash',
            'user_exchange_rate': Decimal('1'),
            'allocate_to_sales': {sale.id: 60},
        })
        db.session.refresh(sale)
        assert receipt.source_type == 'sale'
        assert sale.paid_amount == Decimal('60.000')
        assert sale.balance_due == Decimal('40.000')
        assert sale.payment_status == 'partial'

    def test_allocation_full_marks_sale_paid(self, db, owner_user, test_customer, test_sale):
        sale = test_sale
        PaymentService.create_receipt({
            'customer_id': test_customer.id,
            'amount': Decimal('100'),
            'currency': sale.currency,
            'payment_method': 'cash',
            'user_exchange_rate': Decimal('1'),
            'allocate_to_sales': {sale.id: 100},
        })
        db.session.refresh(sale)
        assert sale.paid_amount >= sale.total_amount
        assert sale.payment_status == 'paid'
        assert sale.balance_due == 0


class TestBalances:
    def test_get_customer_balance_sums_confirmed_sales(self, db, owner_user, test_customer, test_sale, second_unpaid_sale):
        balance = PaymentService.get_customer_balance(test_customer)
        assert balance == Decimal('300.000')

    def test_get_customer_balance_aed_uses_base_columns(self, db, owner_user, test_customer, test_sale):
        balance = PaymentService.get_customer_balance_aed(test_customer)
        assert balance == Decimal('100.000')

    def test_get_unpaid_sales_orders_oldest_first(self, db, owner_user, test_customer, test_sale, second_unpaid_sale):
        unpaid = PaymentService.get_unpaid_sales(test_customer)
        assert len(unpaid) == 2
        assert unpaid[0].id == test_sale.id
        assert unpaid[1].id == second_unpaid_sale.id


class TestAllocateToOldest:
    def test_allocates_fifo_across_sales(self, db, owner_user, test_customer, test_sale, second_unpaid_sale):
        first, second = PaymentService.get_unpaid_sales(test_customer)[:2]
        receipt = Receipt(
            receipt_number='RCV-TEST-FIFO', source_type='manual', direction='incoming',
            customer_id=test_customer.id, amount=Decimal('250'),
            currency='AED', exchange_rate=Decimal('1'), amount_base=Decimal('250'),
            payment_method='cash', user_id=owner_user.id,
        )
        db.session.add(receipt)
        db.session.commit()

        PaymentService.allocate_receipt_to_oldest_sales(receipt, test_customer)

        db.session.refresh(first)
        db.session.refresh(second)
        assert first.paid_amount == Decimal('100.000')
        assert first.payment_status == 'paid'
        assert second.paid_amount == Decimal('150.000')
        assert second.payment_status == 'partial'

    def test_overpay_capped_at_balance_due(self, db, owner_user, test_customer, test_sale):
        receipt = Receipt(
            receipt_number='RCV-TEST-CAP', source_type='manual', direction='incoming',
            customer_id=test_customer.id, amount=Decimal('999'),
            currency='AED', exchange_rate=Decimal('1'), amount_base=Decimal('999'),
            payment_method='cash', user_id=owner_user.id,
        )
        db.session.add(receipt)
        db.session.commit()

        PaymentService.allocate_receipt_to_oldest_sales(receipt, test_customer)

        db.session.refresh(test_sale)
        assert test_sale.paid_amount == Decimal('100.000')
        assert test_sale.payment_status == 'paid'
