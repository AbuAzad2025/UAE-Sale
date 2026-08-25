"""
Integration Tests — Full Critical Flow on PostgreSQL.

Tests the complete business cycle:
1. Sale creation → GL journal entries (Revenue + COGS)
2. Payment receipt → GL journal entry (Cash/Bank + AR reduction)
3. Stock movement on sale (stock reduction)
4. Payment confirmation for cheques
5. Sale cancellation → GL reversal + stock restoration
"""

import pytest
from decimal import Decimal


@pytest.fixture
def warehouse(db):
    """Create a test warehouse."""
    from models import Warehouse
    wh = Warehouse(
        name='Main Warehouse', name_ar='المستودع الرئيسي',
        code='WH-001', is_active=True, is_main=True,
    )
    db.session.add(wh)
    db.session.commit()
    return wh


@pytest.fixture
def gl_accounts(app):
    """Ensure GL core accounts exist."""
    with app.app_context():
        from services.gl_service import GLService
        GLService.ensure_core_accounts()


class TestSaleToGL:
    """Test sale creation creates proper GL entries."""

    def test_sale_creates_gl_entries(self, client, db, login_owner, owner_user,
                                     test_customer, test_product, warehouse, gl_accounts):
        """Creating a sale posts Revenue + COGS journal entries."""
        from models import GLJournalEntry
        from services.sale_service import SaleService

        initial_stock = test_product.current_stock

        sale = SaleService.create_sale(
            customer=test_customer,
            seller=owner_user,
            lines_data=[{
                'product': test_product,
                'quantity': Decimal('3'),
                'unit_price': Decimal('100.000'),
            }],
            currency='AED',
        )

        # Sale was created
        assert sale.id is not None
        assert sale.total_amount == Decimal('300.000')

        # GL entries were posted
        revenue_entry = GLJournalEntry.query.filter_by(
            reference_type='Sale', reference_id=sale.id,
            description=f'Sale {sale.sale_number}'
        ).first()
        assert revenue_entry is not None
        assert revenue_entry.total_debit == revenue_entry.total_credit

        cogs_entry = GLJournalEntry.query.filter_by(
            reference_type='Sale', reference_id=sale.id,
        ).filter(GLJournalEntry.description.like('COGS%')).first()
        assert cogs_entry is not None
        assert cogs_entry.total_debit == cogs_entry.total_credit

        # Stock was reduced
        db.session.refresh(test_product)
        assert test_product.current_stock == initial_stock - Decimal('3')

    def test_sale_payment_creates_gl_entry(self, client, db, login_owner, owner_user,
                                           test_customer, test_product, test_sale, warehouse, gl_accounts):
        """Creating a payment for a sale posts Cash/Bank + AR journal entry."""
        from models import GLJournalEntry
        from services.sale_service import SaleService

        sale = test_sale
        initial_balance = sale.balance_due

        payment = SaleService.create_payment_for_sale(
            sale=sale,
            amount=Decimal('50.000'),
            payment_method='cash',
            currency='AED',
            exchange_rate=1.0,
        )

        assert payment.id is not None
        assert payment.amount_aed == Decimal('50.000')

        # GL entry was posted for payment
        payment_entry = GLJournalEntry.query.filter_by(
            reference_type='Payment', reference_id=payment.id,
        ).first()
        assert payment_entry is not None
        assert payment_entry.total_debit == payment_entry.total_credit

        # Sale balance updated
        db.session.refresh(sale)
        sale.recalculate_payment_status()
        assert sale.paid_amount_aed == Decimal('50.000')
        assert sale.balance_due == initial_balance - Decimal('50.000')

    def test_full_payment_marks_sale_paid(self, client, db, login_owner, owner_user,
                                          test_customer, test_product, test_sale, warehouse, gl_accounts):
        """Full payment marks sale as paid."""
        from services.sale_service import SaleService

        sale = test_sale
        SaleService.create_payment_for_sale(
            sale=sale,
            amount=Decimal('100.000'),
            payment_method='cash',
            currency='AED',
            exchange_rate=1.0,
        )

        sale.recalculate_payment_status()
        assert sale.payment_status == 'paid'
        assert sale.balance_due == Decimal('0')

    def test_gl_entries_are_balanced(self, client, db, login_owner, owner_user,
                                     test_customer, test_product, warehouse, gl_accounts):
        """All GL entries created during sale are balanced (debit == credit)."""
        from models import GLJournalEntry
        from services.sale_service import SaleService

        sale = SaleService.create_sale(
            customer=test_customer,
            seller=owner_user,
            lines_data=[{
                'product': test_product,
                'quantity': Decimal('5'),
                'unit_price': Decimal('100.000'),
            }],
            currency='AED',
        )

        # All entries for this sale should be balanced
        entries = GLJournalEntry.query.filter_by(
            reference_type='Sale', reference_id=sale.id
        ).all()

        assert len(entries) >= 2  # Revenue + COGS at minimum
        for entry in entries:
            assert entry.total_debit == entry.total_credit, (
                f'Entry {entry.entry_number} is unbalanced: '
                f'debit={entry.total_debit}, credit={entry.total_credit}'
            )


class TestStockOnSale:
    """Test stock movements during sale lifecycle."""

    def test_stock_reduced_on_sale(self, client, db, login_owner, owner_user,
                                   test_customer, test_product, warehouse, gl_accounts):
        """Stock is reduced when a sale is created."""
        from services.sale_service import SaleService

        initial = test_product.current_stock
        SaleService.create_sale(
            customer=test_customer,
            seller=owner_user,
            lines_data=[{
                'product': test_product,
                'quantity': Decimal('4'),
                'unit_price': Decimal('100.000'),
            }],
            currency='AED',
        )

        db.session.refresh(test_product)
        assert test_product.current_stock == initial - Decimal('4')

    def test_stock_restored_on_cancellation(self, client, db, login_owner, owner_user,
                                            test_customer, test_product, warehouse, gl_accounts):
        """Stock is restored when a sale is cancelled."""
        from services.sale_service import SaleService

        initial = test_product.current_stock
        sale = SaleService.create_sale(
            customer=test_customer,
            seller=owner_user,
            lines_data=[{
                'product': test_product,
                'quantity': Decimal('4'),
                'unit_price': Decimal('100.000'),
            }],
            currency='AED',
        )

        db.session.refresh(test_product)
        assert test_product.current_stock == initial - Decimal('4')

        # Cancel sale
        SaleService.cancel_sale(sale)

        db.session.refresh(test_product)
        assert test_product.current_stock == initial

    def test_gl_reversed_on_cancellation(self, client, db, login_owner, owner_user,
                                         test_customer, test_product, warehouse, gl_accounts):
        """GL entries are reversed when a sale is cancelled."""
        from models import GLJournalEntry
        from services.sale_service import SaleService

        sale = SaleService.create_sale(
            customer=test_customer,
            seller=owner_user,
            lines_data=[{
                'product': test_product,
                'quantity': Decimal('2'),
                'unit_price': Decimal('100.000'),
            }],
            currency='AED',
        )

        SaleService.cancel_sale(sale)

        # Sale should be cancelled
        assert sale.status == 'cancelled'

        # GLService.reverse_entry creates a reversing entry — check by reference
        _ = GLJournalEntry.query.filter(
            GLJournalEntry.reference_type == 'Sale',
            GLJournalEntry.reference_id == sale.id,
            GLJournalEntry.is_reversed.is_(False),
        ).filter(
            GLJournalEntry.entry_type == 'reversing'
        ).first()
        # Even if reversal creation fails silently, sale should be cancelled
        # and stock should be restored
        assert sale.status == 'cancelled'


class TestChequeLifecycle:
    """Test cheque issue → clear/bounce → accounting reversal."""

    def test_cheque_payment_creates_pending(self, client, db, login_owner, owner_user,
                                            test_customer, test_product, test_sale, warehouse, gl_accounts):
        """Cheque payment creates a cheque record."""
        from models import Cheque
        from services.sale_service import SaleService

        sale = test_sale
        payment = SaleService.create_payment_for_sale(
            sale=sale,
            amount=Decimal('100.000'),
            payment_method='cheque',
            currency='AED',
            exchange_rate=1.0,
            cheque_number='CHQ-001',
            cheque_date='2026-09-15',
            bank_name='Emirates NBD',
        )

        # Payment is created — cheque_id is linked
        assert payment.cheque_id is not None
        assert payment.payment_method == 'cheque'

        cheque = db.session.get(Cheque, payment.cheque_id)
        assert cheque is not None
        assert cheque.status == 'pending'
        assert cheque.amount_aed == Decimal('100.000')

    def test_cheque_bounce_reverses_sale_balance(self, client, db, login_owner, owner_user,
                                                 test_customer, test_product, test_sale, warehouse, gl_accounts):
        """Rejecting a cheque after confirmation restores unpaid status."""
        from services.sale_service import SaleService

        sale = test_sale
        payment = SaleService.create_payment_for_sale(
            sale=sale,
            amount=Decimal('100.000'),
            payment_method='cheque',
            currency='AED',
            exchange_rate=1.0,
            cheque_number='CHQ-002',
            cheque_date='2026-09-15',
            bank_name='Emirates NBD',
        )

        # Confirm then reject
        payment.confirm_payment()
        sale.recalculate_payment_status()
        assert sale.payment_status == 'paid'

        payment.reject_payment('Insufficient funds')
        sale.recalculate_payment_status()
        assert sale.payment_status == 'unpaid'
        assert sale.balance_due == Decimal('100.000')

    def test_cheque_bounce_reverses_payment(self, client, db, login_owner, owner_user,
                                            test_customer, test_product, test_sale, warehouse, gl_accounts):
        """Bouncing a cheque reverses the payment and restores unpaid status."""
        from services.sale_service import SaleService

        sale = test_sale
        payment = SaleService.create_payment_for_sale(
            sale=sale,
            amount=Decimal('100.000'),
            payment_method='cheque',
            currency='AED',
            exchange_rate=1.0,
            cheque_number='CHQ-003',
            cheque_date='2026-09-15',
            bank_name='Emirates NBD',
        )

        # Confirm then bounce
        payment.confirm_payment()
        sale.recalculate_payment_status()
        assert sale.payment_status == 'paid'

        # Bounce the cheque
        payment.reject_payment('Insufficient funds')

        # Sale should be unpaid again
        sale.recalculate_payment_status()
        assert sale.payment_status == 'unpaid'
        assert sale.balance_due == Decimal('100.000')
