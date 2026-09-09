"""Leak-guard regression tests (internal-audit fixes).

FIX1: cancelling a paid/partial invoice is refused (orphaned cash guard).
FIX2: discount edits after posting emit a balanced adjusting entry.
FIX3: returns on paid invoices settle cash-out + subledger consistently.
FIX4: payment GL failure rolls everything back (fail-closed).
"""
from decimal import Decimal

import pytest

from models import (Sale, SaleLine, Payment, Warehouse, GLJournalEntry,
                    GLJournalLine, GLAccount)
from extensions import db as _db
from services.sale_service import SaleService
from services.return_service import ReturnService
from services.gl_service import GLService


@pytest.fixture
def warehouse(db):
    wh = Warehouse(name='Leak WH', name_ar='مستودع التسريب',
                   code='WH-LEAK-01', is_active=True, is_main=True)
    db.session.add(wh)
    db.session.commit()
    return wh


def _make_sale(db, owner_user, test_customer, test_product, warehouse,
               qty='2', price='50.000'):
    return SaleService.create_sale(
        customer=test_customer, seller=owner_user,
        lines_data=[{'product': test_product, 'quantity': Decimal(qty),
                     'unit_price': Decimal(price)}],
        warehouse_id=warehouse.id, currency='ILS',
        user_exchange_rate=Decimal('1'),
    )


def _pay_in_full(sale):
    SaleService.create_payment_for_sale(sale, 100, 'cash')
    sale.paid_amount = Decimal('100')
    sale.paid_amount_base = Decimal('100')
    SaleService.update_payment_status(sale)


def _net(code):
    from sqlalchemy import func
    acc = GLAccount.query.filter_by(code=code).first()
    return _db.session.query(
        func.coalesce(func.sum(GLJournalLine.amount_base), 0)).filter(
        GLJournalLine.account_id == acc.id).scalar()


class TestCancelPaidGuard:
    def test_cancel_unpaid_still_works(self, db, owner_user, test_customer,
                                       test_product, warehouse):
        sale = _make_sale(db, owner_user, test_customer, test_product, warehouse)
        SaleService.cancel_sale(sale)
        assert sale.status == 'cancelled'

    def test_cancel_paid_blocked(self, db, owner_user, test_customer,
                                 test_product, warehouse):
        sale = _make_sale(db, owner_user, test_customer, test_product, warehouse)
        _pay_in_full(sale)
        assert sale.payment_status == 'paid'
        ar_before = _net('1130')
        with pytest.raises(ValueError, match='مدفوعة'):
            SaleService.cancel_sale(sale)
        _db.session.rollback()
        assert sale.status == 'confirmed'
        assert _net('1130') == ar_before
        assert GLJournalEntry.query.filter_by(
            reference_type='Sale', reference_id=sale.id,
            entry_type='reversing').count() == 0

    def test_cancel_partial_blocked(self, db, owner_user, test_customer,
                                    test_product, warehouse):
        sale = _make_sale(db, owner_user, test_customer, test_product, warehouse)
        SaleService.create_payment_for_sale(sale, 40, 'cash')
        sale.paid_amount = Decimal('40')
        sale.paid_amount_base = Decimal('40')
        SaleService.update_payment_status(sale)
        assert sale.payment_status == 'partial'
        with pytest.raises(ValueError, match='مدفوعة'):
            SaleService.cancel_sale(sale)


class TestDiscountAdjustment:
    def test_discount_edit_posts_balanced_adjustment(
            self, client, db, login_owner, owner_user, test_customer,
            test_product, warehouse):
        sale = _make_sale(db, owner_user, test_customer, test_product, warehouse)
        ar_before = _net('1130')
        disc_before = _net('5200')
        resp = client.post(f'/sales/{sale.id}/edit', data={
            'notes': 'خصم إضافي', 'discount_amount': '10'})
        assert resp.status_code == 302
        _db.session.refresh(sale)
        assert Decimal(str(sale.discount_amount)) == Decimal('10')
        assert Decimal(str(sale.total_amount)) == Decimal('90')
        # Adjusting entry exists, balanced, linked to the sale.
        adj = GLJournalEntry.query.filter_by(
            reference_type='Sale', reference_id=sale.id).filter(
            GLJournalEntry.description.like('Discount adjustment%')).all()
        assert len(adj) == 1
        from sqlalchemy import func
        tot = _db.session.query(
            func.coalesce(func.sum(GLJournalLine.debit), 0),
            func.coalesce(func.sum(GLJournalLine.credit), 0)).filter(
            GLJournalLine.entry_id == adj[0].id).one()
        assert tot[0] == tot[1] > 0
        # Economics: AR down 10, discounts up 10.
        assert _net('1130') == ar_before - Decimal('10')
        assert _net('5200') == disc_before + Decimal('10')

    def test_discount_unchanged_posts_nothing(
            self, client, db, login_owner, owner_user, test_customer,
            test_product, warehouse):
        sale = _make_sale(db, owner_user, test_customer, test_product, warehouse)
        before = GLJournalEntry.query.filter_by(
            reference_type='Sale', reference_id=sale.id).count()
        resp = client.post(f'/sales/{sale.id}/edit', data={
            'notes': 'فقط ملاحظة', 'discount_amount': '0'})
        assert resp.status_code == 302
        assert GLJournalEntry.query.filter_by(
            reference_type='Sale', reference_id=sale.id).count() == before


class TestReturnSettlement:
    def _line(self, sale):
        return SaleLine.query.filter_by(sale_id=sale.id).first()

    def test_return_paid_sale_settles_cash(self, db, owner_user, test_customer,
                                           test_product, warehouse):
        GLService.ensure_core_accounts()
        stock_before = test_product.current_stock
        sale = _make_sale(db, owner_user, test_customer, test_product, warehouse)
        _pay_in_full(sale)
        ret = ReturnService.create_return(
            sale.id, [{'sale_line_id': self._line(sale).id, 'quantity': 2}],
            user_id=owner_user.id)
        assert ret.refund_amount == Decimal('100.000')
        # Cash-out recorded as an outgoing refund payment...
        refund = Payment.query.filter_by(sale_id=sale.id,
                                         payment_type='refund').one()
        assert refund.direction == 'outgoing'
        assert refund.amount_base == Decimal('100.000')
        # ...and the books net to zero with no negative AR.
        assert _net('1130') == 0
        assert _net('1110') == 0
        assert _net('4100') == 0
        _db.session.refresh(sale)
        assert sale.paid_amount_base == 0
        assert sale.balance_due == 0
        _db.session.refresh(test_customer)
        assert test_customer.balance == 0
        # Derived formulas agree (listener / checker / display).
        from utils.balance_checker import check_customer_balance
        from services.payment_service import PaymentService
        assert check_customer_balance(test_customer.id) == []
        assert PaymentService.get_customer_balance_aed(test_customer) == 0
        _db.session.refresh(test_product)
        assert test_product.current_stock == stock_before

    def test_return_unpaid_updates_subledger(self, db, owner_user, test_customer,
                                             test_product, warehouse):
        GLService.ensure_core_accounts()
        sale = _make_sale(db, owner_user, test_customer, test_product, warehouse)
        assert test_customer.balance == Decimal('100')
        ret = ReturnService.create_return(
            sale.id, [{'sale_line_id': self._line(sale).id, 'quantity': 2}],
            user_id=owner_user.id)
        assert ret.refund_amount == Decimal('100.000')
        # No cash moved: no refund payment row.
        assert Payment.query.filter_by(sale_id=sale.id,
                                       payment_type='refund').count() == 0
        assert _net('1130') == 0
        _db.session.refresh(sale)
        assert sale.balance_due == 0
        _db.session.refresh(test_customer)
        assert test_customer.balance == 0
        from utils.balance_checker import check_customer_balance
        from services.payment_service import PaymentService
        assert check_customer_balance(test_customer.id) == []
        assert PaymentService.get_customer_balance_aed(test_customer) == 0


class TestPaymentFailClosed:
    def test_gl_failure_rolls_back_payment(self, db, owner_user, test_customer,
                                           test_product, warehouse, monkeypatch):
        sale = _make_sale(db, owner_user, test_customer, test_product, warehouse)
        bal_before = test_customer.balance
        count_before = Payment.query.count()

        def _boom(*a, **k):
            raise RuntimeError('GL down')

        monkeypatch.setattr(GLService, 'post_entry', staticmethod(_boom))
        with pytest.raises(RuntimeError, match='GL down'):
            SaleService.create_payment_for_sale(sale, 50, 'cash')
        _db.session.rollback()
        assert Payment.query.count() == count_before
        _db.session.refresh(test_customer)
        assert test_customer.balance == bal_before
