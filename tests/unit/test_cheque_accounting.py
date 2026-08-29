"""Unit tests for ChequeAccountingIntegration — التكامل المحاسبي للشيكات."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from models import Cheque, Supplier
from services.cheque_accounting_integration import ChequeAccountingIntegration


def _cheque(cheque_type='incoming', amount=Decimal('1000'), status='pending',
            customer_id=None, supplier_id=None):
    today = date.today()
    return Cheque(
        cheque_number=f'CH-{cheque_type}-{amount}', cheque_bank_number='123456',
        cheque_type=cheque_type, bank_name='Emirates NBD',
        amount=amount, currency='ILS', exchange_rate=Decimal('1'),
        issue_date=today - timedelta(days=10), due_date=today + timedelta(days=20),
        status=status, customer_id=customer_id, supplier_id=supplier_id,
    )


@pytest.fixture
def incoming_pending(db, test_customer):
    ch = _cheque('incoming', customer_id=test_customer.id)
    ch.calculate_amount_base()
    db.session.add(ch)
    db.session.commit()
    return ch


@pytest.fixture
def outgoing_pending(db):
    supplier = Supplier(name='مورد التجريبي', is_active=True)
    db.session.add(supplier)
    db.session.flush()
    ch = _cheque('outgoing', supplier_id=supplier.id)
    ch.calculate_amount_base()
    db.session.add(ch)
    db.session.commit()
    return ch


class TestReceiveCheque:
    def test_receive_posts_gl_and_updates_state(self, db, owner_user, incoming_pending):
        entry = ChequeAccountingIntegration.receive_cheque(incoming_pending.id, received_by=owner_user.id)

        assert entry.id is not None
        assert entry.reference_type == 'cheque_receive'
        assert entry.reference_id == incoming_pending.id
        db.session.refresh(incoming_pending)
        assert incoming_pending.status == 'deposited'
        assert incoming_pending.gl_journal_entry_id == entry.id

        codes = {ln.account.code for ln in entry.lines}
        assert codes == {'1150', '1130'}
        debit_line = next(ln for ln in entry.lines if ln.debit > 0)
        assert debit_line.account.code == '1150'
        assert debit_line.debit == Decimal('1000.00')

    def test_receive_outgoing_rejected(self, db, outgoing_pending):
        with pytest.raises(Exception, match='ليس شيك وارد'):
            ChequeAccountingIntegration.receive_cheque(outgoing_pending.id)

    def test_missing_amount_base_self_heals(self, db, test_customer):
        """شيك بدون amount_base يجب أن يُحسب تلقائيًا — لا قيود صفرية صامتة"""
        ch = _cheque('incoming', amount=Decimal('777'), customer_id=test_customer.id)
        db.session.add(ch)
        db.session.commit()
        assert ch.amount_base is None

        entry = ChequeAccountingIntegration.receive_cheque(ch.id)

        total = sum(ln.debit for ln in entry.lines)
        assert total > 0
        assert total == Decimal('777.00')


class TestIssueCheque:
    def test_issue_posts_gl_and_updates_state(self, db, owner_user, outgoing_pending):
        entry = ChequeAccountingIntegration.issue_cheque(outgoing_pending.id, issued_by=owner_user.id)

        assert entry.reference_type == 'cheque_issue'
        codes = {ln.account.code for ln in entry.lines}
        assert codes == {'2110', '2120'}
        credit_line = next(ln for ln in entry.lines if ln.credit > 0)
        assert credit_line.account.code == '2120'

        db.session.refresh(outgoing_pending)
        assert outgoing_pending.status == 'deposited'
        assert outgoing_pending.gl_journal_entry_id == entry.id

    def test_issue_incoming_rejected(self, db, incoming_pending):
        with pytest.raises(Exception, match='ليس شيك صادر'):
            ChequeAccountingIntegration.issue_cheque(incoming_pending.id)


class TestClearCheque:
    def test_clear_incoming_simple(self, db, owner_user, incoming_pending):
        ChequeAccountingIntegration.receive_cheque(incoming_pending.id)
        entry = ChequeAccountingIntegration.clear_cheque(incoming_pending.id, cleared_by=owner_user.id)

        assert entry.reference_type == 'cheque_clear'
        codes = {ln.account.code for ln in entry.lines}
        assert '1120' in codes and '1150' in codes
        db.session.refresh(incoming_pending)
        assert incoming_pending.status == 'cleared'
        assert incoming_pending.cleared_date is not None
        assert incoming_pending.gl_clearing_entry_id == entry.id

    def test_clear_incoming_with_charges_balances(self, db, owner_user, incoming_pending):
        ChequeAccountingIntegration.receive_cheque(incoming_pending.id)
        entry = ChequeAccountingIntegration.clear_cheque(
            incoming_pending.id, bank_charges=Decimal('25'), exchange_gain_loss=Decimal('-15'))

        total_debit = sum(ln.debit for ln in entry.lines)
        total_credit = sum(ln.credit for ln in entry.lines)
        assert total_debit == total_credit
        fee_line = next(ln for ln in entry.lines if ln.account.code == '6950')
        assert fee_line.debit == Decimal('25')
        loss_line = next(ln for ln in entry.lines if ln.account.code == '6900')
        assert loss_line.debit == Decimal('15')

    def test_clear_outgoing_with_gain(self, db, owner_user, outgoing_pending):
        ChequeAccountingIntegration.issue_cheque(outgoing_pending.id)
        entry = ChequeAccountingIntegration.clear_cheque(
            outgoing_pending.id, bank_charges=Decimal('10'), exchange_gain_loss=Decimal('40'))

        total_debit = sum(ln.debit for ln in entry.lines)
        total_credit = sum(ln.credit for ln in entry.lines)
        assert total_debit == total_credit
        gain_line = next(ln for ln in entry.lines if ln.account.code == '4400')
        assert gain_line.credit == Decimal('40')

        db.session.refresh(outgoing_pending)
        assert outgoing_pending.status == 'cleared'

    def test_clear_pending_status_rejected(self, db, incoming_pending):
        with pytest.raises(ValueError, match='يمكن صرفه'):
            ChequeAccountingIntegration.clear_cheque(incoming_pending.id)


class TestBounceCheque:
    def test_bounce_incoming_restores_ar(self, db, owner_user, incoming_pending, test_customer):
        ChequeAccountingIntegration.receive_cheque(incoming_pending.id)
        entry = ChequeAccountingIntegration.bounce_cheque(
            incoming_pending.id, bounced_by=owner_user.id, bounce_reason='عدم كفاية الرصيد')

        codes = {ln.account.code for ln in entry.lines}
        assert codes == {'1130', '1150'}
        debit_line = next(ln for ln in entry.lines if ln.debit > 0)
        assert debit_line.account.code == '1130'

        db.session.refresh(incoming_pending)
        assert incoming_pending.status == 'bounced'
        assert incoming_pending.bounce_reason == 'عدم كفاية الرصيد'
        assert incoming_pending.bounced_date is not None

        # التحقق من تحديث رصيد العميل عند الارتداد
        db.session.refresh(test_customer)
        assert test_customer.balance == Decimal('1000.00')

    def test_bounce_outgoing_restores_ap(self, db, owner_user, outgoing_pending):
        ChequeAccountingIntegration.issue_cheque(outgoing_pending.id)
        supplier = outgoing_pending.supplier
        db.session.refresh(supplier)
        initial_total_purchases = supplier.total_purchases_aed

        entry = ChequeAccountingIntegration.bounce_cheque(outgoing_pending.id)

        codes = {ln.account.code for ln in entry.lines}
        assert codes == {'2110', '2120'}
        credit_line = next(ln for ln in entry.lines if ln.credit > 0)
        assert credit_line.account.code == '2110'

        # التحقق من تحديث رصيد المورد عند الارتداد
        db.session.refresh(supplier)
        assert supplier.total_purchases_aed == initial_total_purchases - Decimal('1000.00')

    def test_bounce_cleared_rejected(self, db, incoming_pending):
        incoming_pending.status = 'cleared'
        db.session.commit()
        with pytest.raises(ValueError, match='ارتداده'):
            ChequeAccountingIntegration.bounce_cheque(incoming_pending.id)


class TestCancelCheque:
    def test_cancel_incoming_restores_customer_balance(self, db, owner_user, incoming_pending, test_customer):
        """إلغاء الشيك الوارد يعيد رصيد العميل"""
        # استلام الشيك يزيد رصيد العميل
        ChequeAccountingIntegration.receive_cheque(incoming_pending.id, received_by=owner_user.id)
        db.session.refresh(test_customer)
        balance_after_receive = test_customer.balance

        # إلغاء الشيك يعيد رصيد العميل
        incoming_pending.cancel_cheque(reason='إلغاء تجريبي')
        db.session.refresh(test_customer)
        assert test_customer.balance == balance_after_receive - Decimal('1000.00')

    def test_cancel_outgoing_restores_supplier_balance(self, db, owner_user, outgoing_pending):
        """إلغاء الشيك الصادر يعيد رصيد المورد"""
        # إصدار الشيك يزيد التزامات المورد
        ChequeAccountingIntegration.issue_cheque(outgoing_pending.id, issued_by=owner_user.id)
        supplier = outgoing_pending.supplier
        db.session.refresh(supplier)
        purchases_after_issue = supplier.total_purchases_aed

        # إلغاء الشيك يعيد رصيد المورد
        outgoing_pending.cancel_cheque(reason='إلغاء تجريبي')
        db.session.refresh(supplier)
        assert supplier.total_purchases_aed == purchases_after_issue - Decimal('1000.00')

    def test_cancel_already_cancelled_noop(self, db, incoming_pending):
        """إلغاء شيك ملغي مسبقاً لا يحدث تغيير"""
        incoming_pending.cancel_cheque()
        incoming_pending.cancel_cheque()  # استدعاء ثاني يجب أن يكون no-op
        assert incoming_pending.status == 'cancelled'


class TestArchiveCheque:
    def test_archive_active_cheque_restores_balance(self, db, owner_user, incoming_pending, test_customer):
        """أرشفة شيك نشط تعيد رصيد العميل"""
        ChequeAccountingIntegration.receive_cheque(incoming_pending.id, received_by=owner_user.id)
        db.session.refresh(test_customer)
        balance_after_receive = test_customer.balance

        # أرشفة الشيك النشط
        incoming_pending.archive(reason='أرشفة تجريبية')
        db.session.refresh(test_customer)
        assert test_customer.balance == balance_after_receive - Decimal('1000.00')
        assert incoming_pending.is_active is False
        assert incoming_pending.archived_at is not None

    def test_archive_cancelled_cheque_no_balance_change(self, db, owner_user, incoming_pending, test_customer):
        """أرشفة شيك ملغي لا تؤثر على الرصيد (تم عكسه مسبقاً)"""
        ChequeAccountingIntegration.receive_cheque(incoming_pending.id, received_by=owner_user.id)
        incoming_pending.cancel_cheque()
        db.session.refresh(test_customer)
        balance_after_cancel = test_customer.balance

        # أرشفة الشيك الملغي
        incoming_pending.archive(reason='أرشفة بعد الإلغاء')
        db.session.refresh(test_customer)
        assert test_customer.balance == balance_after_cancel


class TestSummary:
    def test_full_lifecycle_summary(self, db, owner_user, incoming_pending):
        ChequeAccountingIntegration.receive_cheque(incoming_pending.id, received_by=owner_user.id)
        ChequeAccountingIntegration.clear_cheque(incoming_pending.id)

        summary = ChequeAccountingIntegration.get_cheque_accounting_summary(incoming_pending.id)

        info = summary['cheque_info']
        assert info['number'] == '123456'
        assert info['type'] == 'وارد'
        assert info['status'] == 'مصروف'
        assert info['date'] is not None

        entry_types = [e['type'] for e in summary['journal_entries']]
        assert 'receive' in entry_types and 'clear' in entry_types

        affected_codes = {a['code'] for a in summary['account_impact']}
        assert {'1150', '1120'} <= affected_codes
        for acc in summary['account_impact']:
            assert isinstance(acc['balance'], float)
            assert acc['name']
