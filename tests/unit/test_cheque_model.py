"""Unit tests for Cheque model state machine — آلة حالات الشيك."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from models import Cheque, GLJournalEntry


def _cheque(status='pending', cheque_type='incoming', amount=Decimal('500'),
            due_in_days=30, currency='ILS', rate=Decimal('1')):
    return Cheque(
        cheque_number=f'CH-{status}-{due_in_days}', cheque_bank_number='998877',
        cheque_type=cheque_type, bank_name='ADCB',
        amount=amount, currency=currency, exchange_rate=rate,
        issue_date=date.today() - timedelta(days=5),
        due_date=date.today() + timedelta(days=due_in_days),
        status=status,
    )


class TestDateLogic:
    def test_update_status_computes_days_and_overdue(self, db):
        ch = _cheque(due_in_days=-3)
        db.session.add(ch)
        db.session.commit()
        ch.update_status_based_on_date()
        assert ch.is_overdue is True
        assert ch.days_until_due == -3

    def test_update_skips_terminal_states(self, db):
        ch = _cheque(status='cleared')
        db.session.add(ch)
        db.session.commit()
        ch.update_status_based_on_date()
        assert ch.days_until_due is None

    def test_is_due_soon_window(self, db):
        ch = _cheque(due_in_days=5)
        db.session.add(ch)
        db.session.commit()
        ch.update_status_based_on_date()
        assert ch.is_due_soon is True

        far = _cheque(due_in_days=60)
        db.session.add(far)
        db.session.commit()
        far.update_status_based_on_date()
        assert far.is_due_soon is False


class TestAmountBase:
    def test_with_rate(self, db):
        ch = _cheque(amount=Decimal('100'), rate=Decimal('3.67'))
        ch.calculate_amount_base()
        assert ch.amount_base == Decimal('367.00')

    def test_without_rate_falls_back_to_amount(self, db):
        ch = _cheque(amount=Decimal('250'))
        ch.exchange_rate = None
        ch.calculate_amount_base()
        assert ch.amount_base == Decimal('250')


class TestLifecycle:
    def test_deposit_from_pending(self, db):
        ch = _cheque()
        db.session.add(ch)
        db.session.commit()
        dep = date.today() - timedelta(days=1)
        ch.deposit_cheque(deposit_date=dep)
        assert ch.status == 'deposited'
        assert ch.deposit_date == dep

    def test_deposit_cleared_raises(self, db):
        ch = _cheque(status='cleared')
        with pytest.raises(ValueError, match='إيداع'):
            ch.deposit_cheque()

    def test_clear_sets_fx_and_gain_loss(self, db):
        ch = _cheque(currency='USD', rate=Decimal('3.6'), amount=Decimal('100'))
        ch.calculate_amount_base()
        db.session.add(ch)
        db.session.commit()

        cleared = date.today()
        ch.clear_cheque(clearance_date=cleared, clearance_exchange_rate=3.7)

        assert ch.status == 'cleared'
        assert ch.clearance_date == cleared
        assert Decimal(str(ch.clearance_exchange_rate)) == Decimal('3.7')
        assert ch.actual_amount_base == Decimal('370.00')
        assert ch.currency_gain_loss == Decimal('10.00')

    def test_clear_same_currency_forces_rate_one(self, db):
        from services.currency_service import CurrencyService
        base = CurrencyService.get_base_currency()
        ch = _cheque(currency=base)
        ch.calculate_amount_base()
        db.session.add(ch)
        db.session.commit()

        ch.clear_cheque()
        assert ch.clearance_exchange_rate == Decimal('1.0')
        assert ch.currency_gain_loss == 0

    def test_clear_wrong_state_raises(self, db):
        ch = _cheque(status='bounced')
        with pytest.raises(ValueError, match='صرف'):
            ch.clear_cheque()

    def test_bounce_records_reason_and_gl(self, app, db, owner_user):
        ch = _cheque(cheque_type='incoming', status='pending')
        db.session.add(ch)
        db.session.commit()
        before = GLJournalEntry.query.count()

        ch.bounce_cheque(reason='حساب مجمد')
        db.session.commit()

        assert ch.status == 'bounced'
        assert ch.bounce_reason == 'حساب مجمد'
        assert GLJournalEntry.query.count() > before

    def test_bounce_wrong_state_raises(self, db):
        ch = _cheque(status='cleared')
        with pytest.raises(ValueError, match='رفض'):
            ch.bounce_cheque('سبب')

    def test_cancel_is_idempotent(self, app, db, owner_user):
        ch = _cheque()
        db.session.add(ch)
        db.session.commit()
        entries_before_cancel = GLJournalEntry.query.count()
        ch.cancel_cheque('خطأ إدخال')
        after_first = GLJournalEntry.query.count()

        ch.cancel_cheque('مرة ثانية')
        assert GLJournalEntry.query.count() in (after_first, entries_before_cancel)
        assert 'خطأ إدخال' in (ch.notes or '')
        assert ch.status == 'cancelled'


class TestArchiveRestore:
    def test_archive_active_cheque_posts_reversal(self, app, db, owner_user):
        ch = _cheque(status='deposited')
        db.session.add(ch)
        db.session.commit()
        before = GLJournalEntry.query.count()

        ch.archive(reason='تنظيف دوري')

        assert ch.is_active is False
        assert ch.archived_at is not None
        assert ch.archive_reason == 'تنظيف دوري'
        assert GLJournalEntry.query.count() > before

    def test_restore_clears_archive_fields(self, db):
        ch = _cheque()
        ch.archive('سبب')
        ch.restore()
        assert ch.is_active is True
        assert ch.archived_at is None
        assert ch.archive_reason is None


class TestPropertiesAndQueries:
    def test_arabic_labels_and_flags(self, db):
        ch = _cheque(status='pending')
        assert ch.status_ar == 'معلق (استُلم)'
        assert ch.type_ar == 'وارد'
        assert ch.is_pending is True and ch.is_confirmed is False

        ch.status = 'cleared'
        assert ch.status_ar == 'مصروف'
        assert ch.is_confirmed is True and ch.is_pending is False

        ch.cheque_type = 'outgoing'
        assert ch.type_ar == 'صادر'

    def test_classmethod_filters(self, db, test_customer):
        inc = _cheque(cheque_type='incoming', due_in_days=40)
        out = _cheque(cheque_type='outgoing', due_in_days=41, status='deposited')
        db.session.add_all([inc, out])
        db.session.commit()

        incoming = Cheque.get_incoming_cheques(status='pending')
        outgoing = Cheque.get_outgoing_cheques(status='deposited')
        assert inc.id in [c.id for c in incoming]
        assert out.id in [c.id for c in outgoing]
