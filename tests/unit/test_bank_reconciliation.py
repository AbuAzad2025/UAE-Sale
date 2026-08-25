"""Unit tests for BankReconciliationService — مطابقة البنك."""
from datetime import date, datetime, timedelta
from decimal import Decimal
import itertools

import pytest
from flask_login import login_user
from werkzeug.exceptions import NotFound

from models import (
    BankReconciliation, Cheque, GLAccount, GLJournalEntry,
)
from services.bank_reconciliation_service import BankReconciliationService
from services.gl_service import GLService

PS = date(2026, 1, 1)
PE = date(2026, 1, 31)

_seq = itertools.count(1)


def _d(v):
    return Decimal(str(v))


@pytest.fixture(autouse=True)
def _offline_generate_number(monkeypatch):
    monkeypatch.setattr('utils.distributed_lock._get_redis', lambda: None)


@pytest.fixture
def bank_account(db):
    GLService.ensure_core_accounts()
    return GLAccount.query.filter_by(code='1120').first()


def _seed_gl(entries):
    for desc, debit, credit, day in entries:
        GLService.create_manual_entry(
            desc,
            [
                {'account_code': '1120', 'debit': debit or 0, 'credit': credit or 0},
                {'account_code': '1130', 'debit': credit or 0, 'credit': debit or 0},
            ],
            entry_date=datetime(day.year, day.month, day.day),
        )


def _cheque(db, cheque_type, amount_base, due_date, status='pending',
            is_active=True, drawer=None, payee=None):
    n = next(_seq)
    ch = Cheque(
        cheque_number=f'BRC-T{n:04d}', cheque_bank_number=f'BNK-T{n:04d}',
        cheque_type=cheque_type, bank_name='Emirates NBD',
        amount=_d(amount_base), currency='AED', exchange_rate=Decimal('1'),
        amount_base=_d(amount_base),
        issue_date=due_date - timedelta(days=5), due_date=due_date,
        status=status, is_active=is_active,
        drawer_name=drawer, payee_name=payee,
    )
    db.session.add(ch)
    db.session.commit()
    return ch


def _make_recon(bank, bank_balance, created_by=None):
    return BankReconciliationService.create_reconciliation(
        bank.id, PS, PE, bank_balance, created_by=created_by
    )


class TestCreateReconciliation:
    def test_seeds_books_balances_and_number(self, app, db, bank_account, owner_user):
        _seed_gl([
            ('إيداع', Decimal('10000'), 0, date(2026, 1, 10)),
            ('سحب', 0, Decimal('2500'), date(2026, 1, 20)),
        ])

        r = _make_recon(bank_account, Decimal('7500'), created_by=owner_user.id)

        assert r.reconciliation_number.startswith('BR-2026-')
        assert _d(r.opening_balance_per_books) == 0
        assert _d(r.closing_balance_per_books) == Decimal('7500')
        assert _d(r.closing_balance_per_bank) == Decimal('7500')
        assert r.status == 'draft'
        assert r.created_by == owner_user.id
        result = r.calculate_reconciliation()
        assert result['is_balanced'] is True
        assert result['difference'] == 0

    def test_created_by_fallback_authenticated_user(self, app, db, bank_account, owner_user):
        with app.test_request_context():
            login_user(owner_user)
            r = _make_recon(bank_account, Decimal('0'))
        assert r.created_by == owner_user.id

    def test_created_by_fallback_anonymous_is_none(self, app, db, bank_account):
        r = _make_recon(bank_account, Decimal('0'))
        assert r.created_by is None

    def test_unknown_bank_account_raises_not_found(self, db):
        with pytest.raises(NotFound):
            BankReconciliationService.create_reconciliation(
                99999, PS, PE, Decimal('0'))

    def test_accepts_float_closing_bank_balance(self, db, bank_account):
        _seed_gl([('إيداع', Decimal('7500'), 0, date(2026, 1, 15))])

        r = _make_recon(bank_account, 7500.0)

        assert _d(r.closing_balance_per_bank) == Decimal('7500')
        assert r.calculate_reconciliation()['is_balanced'] is True


class TestAutoPopulateOutstandingItems:
    def test_incoming_pending_cheque_becomes_outstanding_deposit(self, db, bank_account):
        ch = _cheque(db, 'incoming', '1200', date(2026, 1, 15), drawer='شركة دبي')

        r = _make_recon(bank_account, Decimal('0'))

        items = [i for i in r.items if i.item_type == 'outstanding_deposit']
        assert len(items) == 1
        item = items[0]
        assert item.amount == ch.amount_base
        assert item.cheque_id == ch.id
        assert item.transaction_date == ch.issue_date
        assert f'{ch.cheque_bank_number}' in item.description
        assert 'شركة دبي' in item.description
        assert _d(r.outstanding_deposits) == Decimal('1200')

    def test_deposited_status_still_outstanding(self, db, bank_account):
        _cheque(db, 'incoming', '300', date(2026, 1, 20), status='deposited')

        r = _make_recon(bank_account, Decimal('0'))

        assert [i.item_type for i in r.items] == ['outstanding_deposit']
        assert _d(r.outstanding_deposits) == Decimal('300')

    def test_outgoing_pending_cheque_becomes_outstanding_withdrawal(self, db, bank_account):
        _cheque(db, 'outgoing', '800', date(2026, 1, 18), payee='مورد عمان')

        r = _make_recon(bank_account, Decimal('0'))

        items = [i for i in r.items if i.item_type == 'outstanding_withdrawal']
        assert len(items) == 1
        assert 'مورد عمان' in items[0].description
        assert _d(r.outstanding_withdrawals) == Decimal('800')

    def test_cleared_inactive_future_and_cancelled_excluded(self, db, bank_account):
        _cheque(db, 'incoming', '100', date(2026, 1, 10), status='cleared')
        _cheque(db, 'incoming', '200', date(2026, 1, 11), is_active=False)
        _cheque(db, 'incoming', '300', PE + timedelta(days=1))
        _cheque(db, 'outgoing', '400', date(2026, 1, 12), status='bounced')
        _cheque(db, 'outgoing', '500', PE + timedelta(days=2))

        r = _make_recon(bank_account, Decimal('0'))

        assert len(r.items) == 0
        assert _d(r.outstanding_deposits) == 0
        assert _d(r.outstanding_withdrawals) == 0


class TestBalanceComputation:
    def test_unbalanced_difference_recorded(self, db, bank_account):
        _seed_gl([('إيداع', Decimal('5000'), 0, date(2026, 1, 8))])

        r = _make_recon(bank_account, Decimal('4600'))

        assert r.is_balanced is False
        assert _d(r.difference) == Decimal('400')
        result = r.calculate_reconciliation()
        assert result['adjusted_books'] == 5000.0
        assert result['adjusted_bank'] == 4600.0

    def test_difference_within_tolerance_is_balanced(self, db, bank_account):
        _seed_gl([('إيداع', Decimal('1000'), 0, date(2026, 1, 9))])

        r = _make_recon(bank_account, Decimal('1000.005'))

        assert abs(_d(r.difference)) == Decimal('0.005')
        assert r.is_balanced is True

    def test_difference_at_tolerance_threshold_not_balanced(self, db, bank_account):
        _seed_gl([('إيداع', Decimal('1000'), 0, date(2026, 1, 9))])

        r = _make_recon(bank_account, Decimal('1000.01'))

        assert abs(_d(r.difference)) == Decimal('0.01')
        assert r.is_balanced is False

    def test_outstanding_items_shift_bank_side_of_equation(self, db, bank_account):
        _seed_gl([('إيداع', Decimal('2000'), 0, date(2026, 1, 9))])
        _cheque(db, 'incoming', '500', date(2026, 1, 12))

        r = _make_recon(bank_account, Decimal('1500'))

        result = r.calculate_reconciliation()
        assert result['adjusted_bank'] == 2000.0
        assert result['is_balanced'] is True


class TestBankAdjustments:
    def test_add_bank_charge_updates_item_totals_and_recovers_balance(
            self, db, bank_account):
        _seed_gl([('إيداع', Decimal('3000'), 0, date(2026, 1, 9))])
        r = _make_recon(bank_account, Decimal('2946'))

        item = BankReconciliationService.add_bank_charge(
            r.id, '54', 'عمولة تحويل بنكي')

        assert item.item_type == 'bank_charge'
        assert item.amount == Decimal('54')
        assert item.reconciliation_id == r.id
        assert _d(r.bank_charges) == Decimal('54')
        assert {i.item_type for i in r.items} == {'bank_charge'}
        assert r.calculate_reconciliation()['is_balanced'] is True

    def test_add_bank_charge_normalizes_negative_amount(self, db, bank_account):
        r = _make_recon(bank_account, Decimal('0'))

        item = BankReconciliationService.add_bank_charge(r.id, -12.5, 'رسوم')

        assert item.amount == Decimal('12.5')
        assert _d(r.bank_charges) == Decimal('12.5')

    def test_add_bank_charge_default_date_is_period_end(self, db, bank_account):
        r = _make_recon(bank_account, Decimal('0'))

        item = BankReconciliationService.add_bank_charge(r.id, 5, 'رسوم')

        assert item.transaction_date == PE

    def test_add_bank_interest_updates_totals(self, db, bank_account):
        _seed_gl([('إيداع', Decimal('3000'), 0, date(2026, 1, 9))])
        r = _make_recon(bank_account, Decimal('3050'))

        item = BankReconciliationService.add_bank_interest(
            r.id, '50', 'فائدة ودائع')

        assert item.item_type == 'bank_interest'
        assert item.amount == Decimal('50')
        assert _d(r.bank_interest) == Decimal('50')
        assert r.calculate_reconciliation()['is_balanced'] is True

    def test_adjustments_rejected_after_completion(self, db, bank_account):
        r = _make_recon(bank_account, Decimal('0'))
        BankReconciliationService.complete_reconciliation(r.id)
        db.session.expire_all()
        r = BankReconciliation.query.filter_by(id=r.id).first()

        with pytest.raises(ValueError, match='لا يمكن تعديل'):
            BankReconciliationService.add_bank_charge(r.id, 5, 'متأخر')
        with pytest.raises(ValueError, match='لا يمكن تعديل'):
            BankReconciliationService.add_bank_interest(r.id, 5, 'متأخر')


class TestCompleteReconciliation:
    def test_complete_without_adjustments_posts_no_gl_entry(self, db, bank_account):
        r = _make_recon(bank_account, Decimal('0'))

        done = BankReconciliationService.complete_reconciliation(r.id)

        assert done.status == 'completed'
        assert GLJournalEntry.query.filter_by(
            reference_type='bank_reconciliation').count() == 0

    def test_complete_posts_charge_settlement_entry(self, db, bank_account):
        _seed_gl([('إيداع', Decimal('3000'), 0, date(2026, 1, 9))])
        r = _make_recon(bank_account, Decimal('2946'))
        BankReconciliationService.add_bank_charge(r.id, '54', 'عمولة')

        BankReconciliationService.complete_reconciliation(r.id)

        entry = GLJournalEntry.query.filter_by(
            reference_type='bank_reconciliation', reference_id=r.id).one()
        assert entry.total_debit == Decimal('54')
        debit_line = next(ln for ln in entry.lines if ln.debit > 0)
        credit_line = next(ln for ln in entry.lines if ln.credit > 0)
        assert debit_line.account.code == '6950'
        assert debit_line.debit == Decimal('54')
        assert credit_line.account.code == str(r.bank_account.code)
        assert credit_line.credit == Decimal('54')

    def test_complete_posts_interest_settlement_entry(self, db, bank_account):
        _seed_gl([('إيداع', Decimal('3000'), 0, date(2026, 1, 9))])
        r = _make_recon(bank_account, Decimal('3050'))
        BankReconciliationService.add_bank_interest(r.id, '50', 'فائدة')

        BankReconciliationService.complete_reconciliation(r.id)

        entry = GLJournalEntry.query.filter_by(
            reference_type='bank_reconciliation', reference_id=r.id).one()
        debit_line = next(ln for ln in entry.lines if ln.debit > 0)
        credit_line = next(ln for ln in entry.lines if ln.credit > 0)
        assert debit_line.account.code == str(r.bank_account.code)
        assert debit_line.debit == Decimal('50')
        assert credit_line.account.code == '4500'
        assert credit_line.credit == Decimal('50')

    def test_complete_posts_both_charge_and_interest_lines(self, db, bank_account):
        _seed_gl([('إيداع', Decimal('5000'), 0, date(2026, 1, 9))])
        r = _make_recon(bank_account, Decimal('4975'))
        BankReconciliationService.add_bank_charge(r.id, '40', 'عمولة')
        BankReconciliationService.add_bank_interest(r.id, '15', 'فائدة')

        BankReconciliationService.complete_reconciliation(r.id)

        entry = GLJournalEntry.query.filter_by(
            reference_type='bank_reconciliation', reference_id=r.id).one()
        posted = {
            (ln.account.code, 'D' if ln.debit > 0 else 'C'): _d(ln.debit or ln.credit)
            for ln in entry.lines
        }
        assert posted == {
            ('6950', 'D'): Decimal('40'),
            ('1120', 'C'): Decimal('40'),
            ('1120', 'D'): Decimal('15'),
            ('4500', 'C'): Decimal('15'),
        }

    def test_complete_unbalanced_raises_and_stays_draft(self, db, bank_account):
        _seed_gl([('إيداع', Decimal('1000'), 0, date(2026, 1, 9))])
        r = _make_recon(bank_account, Decimal('900'))

        with pytest.raises(ValueError, match='غير متوازنة'):
            BankReconciliationService.complete_reconciliation(r.id)

        assert r.status == 'draft'
        assert GLJournalEntry.query.filter_by(
            reference_type='bank_reconciliation').count() == 0

    def test_double_complete_rejected_without_duplicate_entries(self, db, bank_account):
        _seed_gl([('إيداع', Decimal('3000'), 0, date(2026, 1, 9))])
        r = _make_recon(bank_account, Decimal('2946'))
        BankReconciliationService.add_bank_charge(r.id, '54', 'عمولة')
        BankReconciliationService.complete_reconciliation(r.id)

        with pytest.raises(ValueError, match='معتمدة مسبقاً'):
            BankReconciliationService.complete_reconciliation(r.id)

        assert GLJournalEntry.query.filter_by(
            reference_type='bank_reconciliation').count() == 1


class TestRerunAndSummary:
    def test_rerun_after_clearing_creates_fresh_snapshot_and_keeps_old(
            self, db, bank_account):
        ch = _cheque(db, 'incoming', '700', date(2026, 1, 15))

        r1 = _make_recon(bank_account, Decimal('0'))
        assert len(r1.items) == 1

        ch.status = 'cleared'
        db.session.commit()

        r2 = _make_recon(bank_account, Decimal('0'))

        assert r2.reconciliation_number != r1.reconciliation_number
        assert len(r2.items) == 0
        assert _d(r2.outstanding_deposits) == 0
        db.session.refresh(r1)
        assert len(r1.items) == 1
        assert _d(r1.outstanding_deposits) == Decimal('700')

    def test_summary_counts_amounts_and_window_books_balance(self, db, bank_account):
        _seed_gl([
            ('إيداع ديسمبر', Decimal('10000'), 0, date(2025, 12, 20)),
            ('إيداع يناير', Decimal('2000'), 0, date(2026, 1, 15)),
        ])
        inc1 = _cheque(db, 'incoming', '300', date(2026, 1, 10))
        inc2 = _cheque(db, 'incoming', '200', date(2026, 1, 25), status='deposited')
        out1 = _cheque(db, 'outgoing', '150', date(2026, 1, 20))
        _cheque(db, 'incoming', '999', date(2026, 2, 15))
        _cheque(db, 'outgoing', '888', date(2026, 1, 5), status='cancelled')

        s = BankReconciliationService.get_reconciliation_summary(
            bank_account.id, PS, PE)

        assert s['closing_balance_per_books'] == 12000.0
        assert s['outstanding_deposits_count'] == 2
        assert s['outstanding_deposits_amount'] == 500.0
        assert s['outstanding_withdrawals_count'] == 1
        assert s['outstanding_withdrawals_amount'] == 150.0
        assert [c.id for c in s['outstanding_cheques_in']] == [inc1.id, inc2.id]
        assert [c.id for c in s['outstanding_cheques_out']] == [out1.id]
