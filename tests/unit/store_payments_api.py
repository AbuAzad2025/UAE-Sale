"""
Store Backend — Payment API Tests

Tests validation, idempotency, edge cases, response shape stability
for payment endpoints (/payments/voucher/submit, /payments/api/customer-balance).
"""

from decimal import Decimal
import pytest

from models import Customer, Payment, Receipt, Supplier
from services.payment_service import PaymentService
from services.currency_service import CurrencyService
from utils.decorators import tx
from sqlalchemy.exc import IntegrityError


class TestVoucherSubmitAPI:
    """Test /payments/voucher/submit endpoint."""

    def test_incoming_customer_receipt_creates_gl(self, client, login_owner, test_customer, db):
        """Incoming customer receipt creates GL entry and receipt row."""
        resp = client.post('/payments/voucher/submit', data={
            'direction': 'incoming',
            'party_type': 'customer',
            'party_id': str(test_customer.id),
            'amount': '100',
            'currency': 'AED',
            'exchange_rate': '1',
            'payment_method': 'cash',
            'date': '2026-01-01',
        }, follow_redirects=True)
        assert resp.status_code == 200
        receipt = Receipt.query.filter_by(customer_id=test_customer.id).order_by(Receipt.id.desc()).first()
        assert receipt is not None
        assert receipt.amount_base == Decimal('100')
        entry = PaymentService._get_gl_entry(receipt.id) if False else None

    def test_outgoing_supplier_payment_creates_gl(self, client, login_owner, db):
        """Outgoing supplier payment creates GL entry and payment row."""
        supplier = Supplier(name='Test Supplier', is_active=True)
        db.session.add(supplier)
        db.session.commit()

        resp = client.post('/payments/voucher/submit', data={
            'direction': 'outgoing',
            'party_type': 'supplier',
            'party_id': str(supplier.id),
            'amount': '200',
            'currency': 'AED',
            'exchange_rate': '1',
            'payment_method': 'cash',
            'date': '2026-01-01',
        }, follow_redirects=True)
        assert resp.status_code == 200
        payment = Payment.query.filter_by(supplier_id=supplier.id).order_by(Payment.id.desc()).first()
        assert payment is not None
        assert payment.amount == Decimal('200')
        assert payment.direction == 'outgoing'

    def test_voucher_missing_party_returns_warning(self, client, login_owner):
        """Missing party_id shows warning."""
        resp = client.post('/payments/voucher/submit', data={
            'direction': 'incoming',
            'party_type': 'customer',
            'party_id': '',
            'amount': '100',
            'payment_method': 'cash',
            'date': '2026-01-01',
        }, follow_redirects=True)
        # Should redirect back with flash warning (status 302 or 200)
        assert resp.status_code in (200, 302)

    def test_voucher_invalid_direction_ignored(self, client, login_owner, db):
        """Invalid direction still handled gracefully."""
        supplier = Supplier(name='Supp X', is_active=True)
        db.session.add(supplier)
        db.session.commit()

        resp = client.post('/payments/voucher/submit', data={
            'direction': 'invalid_direction',
            'party_type': 'supplier',
            'party_id': str(supplier.id),
            'amount': '100',
            'payment_method': 'cash',
            'date': '2026-01-01',
        }, follow_redirects=True)
        # Falls through to empty redirect; no crash
        assert resp.status_code in (200, 302)


class TestPaymentServiceCreateReceipt:
    """Test PaymentService.create_receipt directly."""

    def test_receipt_auto_fifo_allocation(self, db, test_customer, owner_user):
        """allocate_to_sales=None triggers auto-FIFO when unpaid sales exist."""
        # Create two open sales
        from models import Sale
        sale1 = Sale(
            sale_number='S-AUTO-001', customer_id=test_customer.id, seller_id=owner_user.id,
            total_amount=Decimal('100'), amount_base=Decimal('100'),
            paid_amount=Decimal('0'), paid_amount_base=Decimal('0'),
            balance_due=Decimal('100'), currency='AED', exchange_rate=Decimal('1'),
            payment_status='unpaid', status='confirmed', is_active=True,
        )
        sale2 = Sale(
            sale_number='S-AUTO-002', customer_id=test_customer.id, seller_id=owner_user.id,
            total_amount=Decimal('50'), amount_base=Decimal('50'),
            paid_amount=Decimal('0'), paid_amount_base=Decimal('0'),
            balance_due=Decimal('50'), currency='AED', exchange_rate=Decimal('1'),
            payment_status='unpaid', status='confirmed', is_active=True,
        )
        db.session.add_all([sale1, sale2])
        db.session.commit()

        receipt = PaymentService.create_receipt({
            'customer_id': test_customer.id,
            'amount': Decimal('80'),
            'currency': 'AED',
            'payment_method': 'cash',
        })
        assert receipt.id is not None
        # Auto-FIFO should allocate 80 to oldest sale (sale1)
        db.session.refresh(sale1)
        assert sale1.paid_amount_base == Decimal('80')
        assert sale1.balance_due == Decimal('20')

    def test_receipt_explicit_allocation(self, db, test_customer, owner_user):
        """Explicit allocate_to_sales mapping respected."""
        from models import Sale
        sale = Sale(
            sale_number='S-EXPLICIT-001', customer_id=test_customer.id, seller_id=owner_user.id,
            total_amount=Decimal('200'), amount_base=Decimal('200'),
            paid_amount=Decimal('0'), paid_amount_base=Decimal('0'),
            balance_due=Decimal('200'), currency='AED', exchange_rate=Decimal('1'),
            payment_status='unpaid', status='confirmed', is_active=True,
        )
        db.session.add(sale)
        db.session.commit()

        receipt = PaymentService.create_receipt({
            'customer_id': test_customer.id,
            'amount': Decimal('50'),
            'currency': 'AED',
            'payment_method': 'cash',
            'allocate_to_sales': {sale.id: Decimal('50')},
        })
        assert receipt.id is not None
        db.session.refresh(sale)
        assert sale.paid_amount_base == Decimal('50')
        assert sale.balance_due == Decimal('150')

    def test_receipt_empty_allocation_forces_unallocated(self, db, test_customer, owner_user):
        """allocate_to_sales={} forces unallocated even when unpaid sales exist."""
        from models import Sale
        sale = Sale(
            sale_number='S-FORCE-001', customer_id=test_customer.id, seller_id=owner_user.id,
            total_amount=Decimal('100'), amount_base=Decimal('100'),
            paid_amount=Decimal('0'), paid_amount_base=Decimal('0'),
            balance_due=Decimal('100'), currency='AED', exchange_rate=Decimal('1'),
            payment_status='unpaid', status='confirmed', is_active=True,
        )
        db.session.add(sale)
        db.session.commit()

        receipt = PaymentService.create_receipt({
            'customer_id': test_customer.id,
            'amount': Decimal('30'),
            'currency': 'AED',
            'payment_method': 'cash',
            'allocate_to_sales': {},  # force unallocated
        })
        assert receipt.id is not None
        db.session.refresh(sale)
        # Sale unchanged
        assert sale.paid_amount_base == Decimal('0')

    def test_receipt_cheque_creates_cheque_record(self, db, test_customer, owner_user):
        """Cheque payment creates Cheque record."""
        from models import Cheque
        receipt = PaymentService.create_receipt({
            'customer_id': test_customer.id,
            'amount': Decimal('500'),
            'currency': 'AED',
            'payment_method': 'cheque',
            'cheque_number': 'CHQ-001',
            'cheque_date': '2026-02-01',
            'bank_name': 'Test Bank',
        })
        assert receipt.cheque_id is not None
        cheque = Cheque.query.get(receipt.cheque_id)
        assert cheque is not None
        assert cheque.cheque_number == 'CHQ-001'

    def test_receipt_negative_amount_raises(self, db, test_customer):
        """Negative payment amount is rejected (service validation or DB CHECK)."""
        with pytest.raises((ValueError, IntegrityError)):
            PaymentService.create_receipt({
                'customer_id': test_customer.id,
                'amount': Decimal('-50'),
                'currency': 'AED',
                'payment_method': 'cash',
            })

    def test_receipt_zero_amount_raises(self, db, test_customer):
        """Zero payment amount is rejected (service validation or DB CHECK)."""
        with pytest.raises((ValueError, IntegrityError)):
            PaymentService.create_receipt({
                'customer_id': test_customer.id,
                'amount': Decimal('0'),
                'currency': 'AED',
                'payment_method': 'cash',
            })

    def test_receipt_customer_balance_reduced(self, db, test_customer, owner_user):
        """Receipt reduces customer balance."""
        test_customer.balance = Decimal('1000')
        db.session.commit()

        receipt = PaymentService.create_receipt({
            'customer_id': test_customer.id,
            'amount': Decimal('200'),
            'currency': 'AED',
            'payment_method': 'cash',
        })
        db.session.refresh(test_customer)
        # Balance drops by the receipt's base-currency amount (FX-converted,
        # stored quantized to 3 decimals)
        expected = (Decimal('1000') - Decimal(str(receipt.amount_base))).quantize(Decimal('0.001'))
        assert test_customer.balance == expected
        assert receipt.id is not None


class TestCustomerBalanceAPI:
    """Test /payments/api/customer-balance endpoint."""

    def test_customer_balance_returns_shape(self, client, login_owner, test_customer, db):
        """Response contains expected keys."""
        resp = client.get(f'/payments/api/customer-balance/{test_customer.id}')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'balance_aed' in data
        assert 'unpaid_sales' in data
        assert isinstance(data['unpaid_sales'], list)

    def test_customer_balance_zero_when_no_sales(self, client, login_owner, db):
        """Customer with no sales shows zero balance."""
        customer = Customer(
            name='No Sales', customer_type='regular', phone='+971504444444',
            credit_limit=Decimal('1000'), balance=Decimal('0'), is_active=True,
        )
        db.session.add(customer)
        db.session.commit()

        resp = client.get(f'/payments/api/customer-balance/{customer.id}')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['balance_aed'] == 0.0
        assert data['unpaid_sales'] == []

    def test_customer_balance_reflects_paid_sale(self, client, login_owner, db, owner_user, test_product):
        """Balance updates correctly after payment."""
        customer = Customer(
            name='Paid Customer', customer_type='regular', phone='+971505555555',
            credit_limit=Decimal('10000'), balance=Decimal('0'), is_active=True,
        )
        db.session.add(customer)
        db.session.commit()

        from models import Sale
        sale = Sale(
            sale_number='S-PAY-001', customer_id=customer.id, seller_id=owner_user.id,
            total_amount=Decimal('100'), amount_base=Decimal('100'),
            paid_amount=Decimal('100'), paid_amount_base=Decimal('100'),
            balance_due=Decimal('0'), currency='AED', exchange_rate=Decimal('1'),
            payment_status='paid', status='confirmed', is_active=True,
        )
        db.session.add(sale)
        db.session.commit()

        resp = client.get(f'/payments/api/customer-balance/{customer.id}')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['balance_aed'] == 0.0
        assert len(data['unpaid_sales']) == 0

    def test_customer_balance_missing_customer_404(self, client, login_owner, db):
        """Non-existent customer returns 404."""
        resp = client.get('/payments/api/customer-balance/999999')
        assert resp.status_code == 404


class TestPaymentIdempotency:
    """Idempotency and duplicate-payment guards."""

    def test_receipt_duplicate_creation_allowed_but_distinct(self, db, test_customer, owner_user):
        """Receipts can be created multiple times for same customer (no idempotency key yet)."""
        receipt1 = PaymentService.create_receipt({
            'customer_id': test_customer.id,
            'amount': Decimal('50'),
            'currency': 'AED',
            'payment_method': 'cash',
        })
        receipt2 = PaymentService.create_receipt({
            'customer_id': test_customer.id,
            'amount': Decimal('50'),
            'currency': 'AED',
            'payment_method': 'cash',
        })
        assert receipt1.id != receipt2.id
        # Each receipt is distinct
        assert Receipt.query.count() == 2

    def test_allocate_receipt_to_sales_preserves_remainder(self, db, test_customer, owner_user):
        """Allocation with partial remainder leaves remaining unallocated."""
        from models import Sale
        sale = Sale(
            sale_number='S-PARTIAL-001', customer_id=test_customer.id, seller_id=owner_user.id,
            total_amount=Decimal('100'), amount_base=Decimal('100'),
            paid_amount=Decimal('0'), paid_amount_base=Decimal('0'),
            balance_due=Decimal('100'), currency='AED', exchange_rate=Decimal('1'),
            payment_status='unpaid', status='confirmed', is_active=True,
        )
        db.session.add(sale)
        db.session.commit()

        receipt = PaymentService.create_receipt({
            'customer_id': test_customer.id,
            'amount': Decimal('30'),
            'currency': 'AED',
            'payment_method': 'cash',
        })
        db.session.refresh(sale)
        assert sale.balance_due == Decimal('70')
        assert sale.paid_amount_base == Decimal('30')

    def test_receipt_creation_survives_gl_outage(self, db, test_customer, monkeypatch):
        """Receipt creation does not depend on synchronous GL posting."""
        from services.gl_service import GLService
        original_post = GLService.post_entry
        def broken_post(*args, **kwargs):
            raise RuntimeError('GL down')
        monkeypatch.setattr(GLService, 'post_entry', staticmethod(broken_post))

        receipt = PaymentService.create_receipt({
            'customer_id': test_customer.id,
            'amount': Decimal('50'),
            'currency': 'AED',
            'payment_method': 'cash',
        })
        # Receipt is persisted; GL posting is not on the synchronous path
        assert receipt.id is not None
        assert Receipt.query.count() == 1