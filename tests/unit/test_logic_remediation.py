"""Logic Remediation Tests — Agent L wave (tests/unit/test_logic_remediation.py).

Covers every numbered remediation item:
  1. models/events.py supplier totals single-pass (N+1 double-count regression)
  2. services/payment_service.py C4 auto-FIFO vs explicit {} + per-sale FX
  3. models/purchase.py get_paid_amount tracked column
  4. models/cheque.py persisted gl_journal_entry_id / gl_bounce_entry_id
  5. services/cheque_accounting_integration.py C3 'deposited' + role routing
  6. services/sale_service.py merchant_receivable_codes()
  7. services/subledger_reconciliation.py AR includes merchant/partner buckets
  8. services/stock_service.py C1 post_gl=False + pre-mutation validation
  9. services/return_service.py historical COGS + sale currency on GL entry
 10. services/archive_service.py tablename→class resolution

All money math is Decimal; doc numbers are unique/explicit; fully offline.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from models import (
    ArchivedRecord,
    AuditLog,
    Cheque,
    Customer,
    ExpenseCategory,
    GLJournalEntry,
    Payment,
    Purchase,
    Sale,
    Supplier,
)
from services.cheque_accounting_integration import ChequeAccountingIntegration


# ─────────────────────────── shared helpers ───────────────────────────

def _supplier(db, name):
    s = Supplier(name=name)
    db.session.add(s)
    db.session.commit()
    return s


def _purchase(db, number, supplier, user_id, amount='200.000'):
    p = Purchase(
        purchase_number=number, supplier_id=supplier.id,
        supplier_name=supplier.name, total_amount=Decimal(amount),
        amount_base=Decimal(amount), currency='AED',
        exchange_rate=Decimal('1'), status='confirmed', user_id=user_id,
    )
    db.session.add(p)
    db.session.commit()
    return p


def _supplier_payment(db, number, supplier, amount='50.000'):
    pay = Payment(
        payment_number=number, payment_type='payment', direction='outgoing',
        supplier_id=supplier.id, amount=Decimal(amount), currency='AED',
        exchange_rate=Decimal('1'), amount_base=Decimal(amount),
        payment_method='cash', payment_confirmed=True,
    )
    db.session.add(pay)
    db.session.commit()
    return pay


def _make_sale(db, number, customer_id, total, paid='0',
               seller_id=None, currency='AED', exchange_rate='1', **extra):
    total_d = Decimal(str(total))
    paid_d = Decimal(str(paid))
    rate_d = Decimal(str(exchange_rate))
    if currency == 'ILS':
        amount_base = total_d
        paid_base = paid_d
    else:
        amount_base = (total_d * rate_d).quantize(Decimal('0.001'))
        paid_base = (paid_d * rate_d).quantize(Decimal('0.001'))
    sale = Sale(
        sale_number=number, customer_id=customer_id, seller_id=seller_id,
        total_amount=total_d, amount_base=amount_base,
        paid_amount=paid_d, paid_amount_base=paid_base,
        balance_due=max(amount_base - paid_base, Decimal('0')),
        currency=currency, exchange_rate=rate_d,
        payment_status='unpaid' if paid_d == 0 else 'partial',
        status='confirmed', is_active=True, sale_date=datetime.now(timezone.utc),
    )
    for k, v in extra.items():
        setattr(sale, k, v)
    db.session.add(sale)
    db.session.commit()
    return sale


def _incoming_cheque(db, customer, number, amount=Decimal('1000')):
    ch = Cheque(
        cheque_number=number, cheque_bank_number='BNK-' + number,
        cheque_type='incoming', bank_name='Emirates NBD',
        amount=amount, currency='ILS', exchange_rate=Decimal('1'),
        issue_date=date.today() - timedelta(days=5),
        due_date=date.today() + timedelta(days=30), status='pending',
        customer_id=customer.id,
    )
    ch.calculate_amount_base()
    db.session.add(ch)
    db.session.commit()
    return ch


def _outgoing_cheque(db, supplier, number, amount=Decimal('800')):
    ch = Cheque(
        cheque_number=number, cheque_bank_number='BNK-' + number,
        cheque_type='outgoing', bank_name='ADCB',
        amount=amount, currency='ILS', exchange_rate=Decimal('1'),
        issue_date=date.today() - timedelta(days=5),
        due_date=date.today() + timedelta(days=30), status='pending',
        supplier_id=supplier.id,
    )
    ch.calculate_amount_base()
    db.session.add(ch)
    db.session.commit()
    return ch


def _gl_lines_for(entry):
    return {ln.account.code: ln for ln in entry.lines}


# ─────────────────────── 1. events.py supplier totals ───────────────────────

class TestSupplierTotalsSinglePass:
    """Purchase listener recomputes supplier totals ONCE per event (no N+1)."""

    def test_second_purchase_does_not_multiply_payments(self, db, owner_user):
        """Legacy bug reproduced: with 2 purchases + one 50 AED payment the old
        loop computed total_paid = 2×50 (per-purchase query) + 50 (direct pass)
        = 150. Fixed value must be exactly 50."""
        sup = _supplier(db, 'LR-Sup-1')
        _purchase(db, 'P-LR-001', sup, owner_user.id, amount='200.000')
        _supplier_payment(db, 'PAY-LR-001', sup, amount='50.000')
        db.session.refresh(sup)
        assert sup.total_purchases_aed == Decimal('200.000')
        assert sup.total_paid_aed == Decimal('50.000')

        _purchase(db, 'P-LR-002', sup, owner_user.id, amount='60.000')

        db.session.refresh(sup)
        old_n_plus_one_delta = Decimal('150.000')  # 2 purchases × 50 + 50 direct
        assert sup.total_purchases_aed == Decimal('260.000')
        assert sup.total_paid_aed == Decimal('50.000')
        assert sup.total_paid_aed != old_n_plus_one_delta

    def test_purchase_update_keeps_single_pass_paid_total(self, db, owner_user):
        """Update path recomputes once too — paid stays the true payment sum."""
        sup = _supplier(db, 'LR-Sup-Upd')
        p1 = _purchase(db, 'P-LR-010', sup, owner_user.id, amount='200.000')
        _supplier_payment(db, 'PAY-LR-010', sup, amount='70.000')

        p1.amount_base = Decimal('350.000')
        db.session.commit()

        db.session.refresh(sup)
        assert sup.total_purchases_aed == Decimal('350.000')
        assert sup.total_paid_aed == Decimal('70.000')


# ─────────────────────── 2. payment_service C4 / FX ───────────────────────

class TestReceiptAllocationC4:

    def _two_open_sales(self, db, owner_user, customer):
        older = _make_sale(
            db, 'S-LR-FIFO-A', customer.id, 100,
            seller_id=owner_user.id,
            sale_date=datetime.now(timezone.utc) - timedelta(days=2))
        newer = _make_sale(
            db, 'S-LR-FIFO-B', customer.id, 200,
            seller_id=owner_user.id,
            sale_date=datetime.now(timezone.utc) - timedelta(days=1))
        return older, newer

    def test_auto_fifo_when_allocate_falsy(self, db, owner_user, test_customer):
        from services.payment_service import PaymentService

        older, newer = self._two_open_sales(db, owner_user, test_customer)

        receipt = PaymentService.create_receipt({
            'customer_id': test_customer.id,
            'amount': Decimal('250'),
            'currency': 'AED',
            'payment_method': 'cash',
            'user_exchange_rate': Decimal('1'),
            # allocate_to_sales omitted entirely → falsy → auto-FIFO (C4)
        })

        db.session.refresh(older)
        db.session.refresh(newer)
        assert receipt.source_type == 'manual'
        assert older.paid_amount == Decimal('100.000')
        assert older.payment_status == 'paid'
        assert newer.paid_amount == Decimal('150.000')
        assert newer.payment_status == 'partial'

    def test_explicit_empty_dict_forces_unallocated(self, db, owner_user, test_customer):
        from services.payment_service import PaymentService

        older, newer = self._two_open_sales(db, owner_user, test_customer)

        receipt = PaymentService.create_receipt({
            'customer_id': test_customer.id,
            'amount': Decimal('250'),
            'currency': 'AED',
            'payment_method': 'cash',
            'user_exchange_rate': Decimal('1'),
            'allocate_to_sales': {},  # explicit {} → force-unallocated (C4)
        })

        db.session.refresh(older)
        db.session.refresh(newer)
        assert receipt.source_type == 'manual'
        assert Decimal(str(older.paid_amount)) == 0
        assert Decimal(str(newer.paid_amount)) == 0
        assert older.payment_status == 'unpaid'

    def test_fx_converts_at_sale_exchange_rate_not_receipts(self, db, owner_user, test_customer):
        """paid_amount_base grows at the SALE's booked rate (3.5), never the
        receipt's rate (1.0)."""
        from services.payment_service import PaymentService

        sale = _make_sale(
            db, 'S-LR-FX-1', test_customer.id, 100,
            seller_id=owner_user.id, currency='USD', exchange_rate='3.5')

        receipt = PaymentService.create_receipt({
            'customer_id': test_customer.id,
            'amount': Decimal('60'),
            'currency': 'AED',
            'payment_method': 'cash',
            'user_exchange_rate': Decimal('1'),
            'allocate_to_sales': {sale.id: 60},
        })

        db.session.refresh(sale)
        assert Decimal(str(receipt.exchange_rate)) == Decimal('1')
        assert sale.paid_amount == Decimal('60')
        assert sale.paid_amount_base == Decimal('210.000')  # 60 × 3.5 (sale rate)
        assert sale.payment_status == 'partial'

    def test_audit_row_records_auto_fifo_flag(self, db, owner_user, test_customer):
        from services.payment_service import PaymentService

        self._two_open_sales(db, owner_user, test_customer)
        PaymentService.create_receipt({
            'customer_id': test_customer.id,
            'amount': Decimal('40'),
            'currency': 'AED',
            'payment_method': 'cash',
            'user_exchange_rate': Decimal('1'),
        })
        PaymentService.create_receipt({
            'customer_id': test_customer.id,
            'amount': Decimal('30'),
            'currency': 'AED',
            'payment_method': 'cash',
            'user_exchange_rate': Decimal('1'),
            'allocate_to_sales': {},
        })

        logs = AuditLog.query.filter_by(
            action='receipt_create', table_name='receipts'
        ).order_by(AuditLog.id.desc()).limit(2).all()
        flags = sorted(lg.changes['auto_fifo'] for lg in logs)
        assert flags == [False, True]


# ─────────────────────── 3. purchase.get_paid_amount ───────────────────────

class TestPurchasePaidAmountTrackedColumn:

    def test_returns_tracked_paid_amount_column(self, db, owner_user):
        sup = _supplier(db, 'LR-Sup-Paid')
        p = Purchase(
            purchase_number='P-LR-PAID-1', supplier_id=sup.id,
            supplier_name=sup.name, total_amount=Decimal('300.000'),
            amount_base=Decimal('300.000'), currency='AED',
            exchange_rate=Decimal('1'), status='confirmed',
            paid_amount=Decimal('120.500'), user_id=owner_user.id,
        )
        db.session.add(p)
        db.session.commit()

        assert p.get_paid_amount() == Decimal('120.5')
        assert isinstance(p.get_paid_amount(), Decimal)

    def test_none_paid_amount_is_zero_without_payment_query(self, db, owner_user):
        sup = _supplier(db, 'LR-Sup-Paid-None')
        p = _purchase(db, 'P-LR-PAID-2', sup, owner_user.id, amount='80.000')
        p.paid_amount = None
        db.session.commit()

        assert p.get_paid_amount() == Decimal('0')


# ─────────────────────── 4. cheque GL id persistence ───────────────────────

class TestChequeGLEntryIdsPersisted:

    def test_receive_cheque_persists_gl_journal_entry_id(self, db, test_customer):
        ch = _incoming_cheque(db, test_customer, 'CH-LR-RCV-1')

        ch.receive_cheque()
        db.session.commit()

        assert ch.gl_journal_entry_id is not None
        entry = db.session.get(GLJournalEntry, ch.gl_journal_entry_id)
        assert entry is not None
        assert entry.reference_type == 'cheque_receive'
        assert entry.reference_id == ch.id

    def test_bounce_persists_gl_bounce_entry_id(self, db, test_customer):
        ch = _incoming_cheque(db, test_customer, 'CH-LR-BNC-1')

        ch.bounce_cheque('NSF — insufficient funds')
        db.session.commit()

        assert ch.gl_bounce_entry_id is not None
        entry = db.session.get(GLJournalEntry, ch.gl_bounce_entry_id)
        assert entry is not None
        assert entry.reference_type == 'cheque_bounce'
        assert entry.reference_id == ch.id


# ─────────────────── 5. integration statuses + role routing ───────────────────

class TestChequeIntegrationDepositedContract:

    def test_receive_sets_model_valid_deposited_status(self, db, test_customer):
        ch = _incoming_cheque(db, test_customer, 'CH-LR-INT-1')

        entry = ChequeAccountingIntegration.receive_cheque(ch.id)

        db.session.refresh(ch)
        assert ch.status == 'deposited'
        assert ch.status != 'received'  # invented status eliminated (C3)
        assert ch.gl_journal_entry_id == entry.id

    def test_issue_sets_model_valid_deposited_status(self, db):
        sup = _supplier(db, 'LR-Sup-Chq-Issue')
        ch = _outgoing_cheque(db, sup, 'CH-LR-INT-2')

        entry = ChequeAccountingIntegration.issue_cheque(ch.id)

        db.session.refresh(ch)
        assert ch.status == 'deposited'
        assert ch.status != 'issued'  # invented status eliminated (C3)
        assert ch.gl_journal_entry_id == entry.id

    def test_clear_routes_bank_charge_and_fx_roles(self, db, test_customer):
        ch = _incoming_cheque(db, test_customer, 'CH-LR-INT-3')
        ChequeAccountingIntegration.receive_cheque(ch.id)

        entry = ChequeAccountingIntegration.clear_cheque(
            ch.id, bank_charges=Decimal('25'), exchange_gain_loss=Decimal('40'))

        codes = _gl_lines_for(entry)
        assert codes['6950'].debit == Decimal('25.00')   # BANK_CHARGES fallback
        assert codes['4400'].credit == Decimal('40.00')  # FX_GAIN fallback
        assert total_debit(entry) == total_credit(entry)

    def test_clear_loss_routes_fx_loss_role(self, db, test_customer):
        ch = _incoming_cheque(db, test_customer, 'CH-LR-INT-4')
        ChequeAccountingIntegration.receive_cheque(ch.id)

        entry = ChequeAccountingIntegration.clear_cheque(ch.id, exchange_gain_loss=Decimal('-15'))

        codes = _gl_lines_for(entry)
        assert codes['6900'].debit == Decimal('15.00')  # FX_LOSS fallback
        assert total_debit(entry) == total_credit(entry)


def total_debit(entry):
    return sum((ln.debit or Decimal('0')) for ln in entry.lines)


def total_credit(entry):
    return sum((ln.credit or Decimal('0')) for ln in entry.lines)


# ─────────────────────── 6. merchant bucket helper ───────────────────────

class TestMerchantReceivableCodes:

    def test_returns_merchant_then_partner_buckets(self):
        from services.sale_service import merchant_receivable_codes

        assert merchant_receivable_codes() == ['2115', '3350']


# ─────────────── 7. subledger recon includes merchant buckets ───────────────

class TestSubledgerARMerchantAware:

    @staticmethod
    def _merchant_and_partner(db):
        mer = Customer(name='LR-Merchant', name_ar='تاجر', customer_type='merchant',
                       balance=Decimal('0'), is_active=True)
        par = Customer(name='LR-Partner', name_ar='شريك', customer_type='partner',
                       balance=Decimal('0'), is_active=True)
        db.session.add_all([mer, par])
        db.session.flush()
        return mer, par

    def test_control_accounts_include_merchant_and_partner_buckets(self, db, owner_user, test_customer):
        from services.subledger_reconciliation import SubLedgerReconciliation

        mer, par = self._merchant_and_partner(db)
        _make_sale(db, 'S-LR-R1', test_customer.id, 100, seller_id=owner_user.id)
        _make_sale(db, 'S-LR-M1', mer.id, 300, seller_id=owner_user.id)
        _make_sale(db, 'S-LR-P1', par.id, 200, seller_id=owner_user.id)

        report = SubLedgerReconciliation.reconcile_receivables()

        assert {'1130', '2115', '3350'} <= set(report['control_accounts'])

    def test_merchant_partner_sales_reconcile_balanced(self, db, owner_user, test_customer):
        from services.subledger_reconciliation import SubLedgerReconciliation
        from services.gl_service import GLService

        mer, par = self._merchant_and_partner(db)
        _make_sale(db, 'S-LR-R2', test_customer.id, 100, seller_id=owner_user.id)
        _make_sale(db, 'S-LR-M2', mer.id, 300, seller_id=owner_user.id)
        _make_sale(db, 'S-LR-P2', par.id, 200, seller_id=owner_user.id)

        GLService.ensure_core_accounts()
        GLService.post_entry(
            [{'account': '1130', 'debit': Decimal('100')},
             {'account': '4100', 'credit': Decimal('100')}],
            description='regular invoice leg', currency='AED', exchange_rate=1)
        GLService.post_entry(
            [{'account': '2115', 'debit': Decimal('300')},
             {'account': '4100', 'credit': Decimal('300')}],
            description='merchant invoice leg', currency='AED', exchange_rate=1)
        GLService.post_entry(
            [{'account': '3350', 'debit': Decimal('200')},
             {'account': '4100', 'credit': Decimal('200')}],
            description='partner invoice leg', currency='AED', exchange_rate=1)
        db.session.commit()

        report = SubLedgerReconciliation.reconcile_receivables()

        assert report['balanced'] is True
        assert report['breaks'] == []
        assert report['subledger_sum'] == Decimal('600.00')
        assert report['control_balance'] == Decimal('600.00')

    def test_report_has_per_bucket_detail_lines(self, db, owner_user, test_customer):
        from services.subledger_reconciliation import SubLedgerReconciliation
        from services.gl_service import GLService

        mer, par = self._merchant_and_partner(db)
        _make_sale(db, 'S-LR-D1', test_customer.id, 100, seller_id=owner_user.id)
        _make_sale(db, 'S-LR-D2', mer.id, 300, seller_id=owner_user.id)
        GLService.ensure_core_accounts()
        GLService.post_entry(
            [{'account': '2115', 'debit': Decimal('300')},
             {'account': '4100', 'credit': Decimal('300')}],
            description='detail bucket probe', currency='AED', exchange_rate=1)
        db.session.commit()

        report = SubLedgerReconciliation.reconcile_receivables()

        breakdown = {b['account_code']: b['balance'] for b in report['control_breakdown']}
        assert set(breakdown) >= {'1130', '2115', '3350'}
        assert breakdown['2115'] == Decimal('300.00')
        assert sum(breakdown.values()) == report['control_balance']


# ─────────────────────── 8. stock_service C1 + validation ───────────────────────

class TestAdjustStockPostGL:

    def test_post_gl_false_skips_gl_rows_entirely(self, db, test_product):
        from services.stock_service import StockService

        movement = StockService.adjust_stock(
            test_product.id, 5, notes='pure transfer leg', post_gl=False)

        db.session.refresh(test_product)
        assert test_product.current_stock == Decimal('105')
        rows = GLJournalEntry.query.filter_by(
            reference_type='stock_adjustment', reference_id=movement.id).count()
        assert rows == 0

    def test_post_gl_default_still_posts_adjustment_entry(self, db, test_product):
        from services.stock_service import StockService

        movement = StockService.adjust_stock(test_product.id, 3, notes='with GL')

        rows = GLJournalEntry.query.filter_by(
            reference_type='stock_adjustment', reference_id=movement.id).all()
        assert len(rows) == 1
        codes = {ln.account.code for ln in rows[0].lines}
        assert codes == {'1140', '5150'}

    def test_insufficient_stock_rejected_before_mutation_with_honest_message(self, db, test_product):
        from services.stock_service import StockService

        db.session.refresh(test_product)
        available = Decimal(str(test_product.current_stock))

        with pytest.raises(ValueError) as excinfo:
            StockService.adjust_stock(test_product.id, -(available * 1000))

        msg = str(excinfo.value)
        assert 'المتوفر' in msg
        assert str(available) in msg          # shows AVAILABLE, not post-mutation
        assert str(-available * 1000) not in msg
        db.session.refresh(test_product)
        assert Decimal(str(test_product.current_stock)) == available

    def test_failed_adjustment_does_not_poison_outer_session(self, db, test_product):
        """Old code blanket-rolled-back the caller's session on rejection;
        now a rejected adjustment leaves prior uncommitted work intact."""
        from services.stock_service import StockService

        marker = ExpenseCategory(name='LR-Survivor-Cat')
        db.session.add(marker)
        db.session.flush()

        with pytest.raises(ValueError):
            StockService.adjust_stock(test_product.id, -999999999)

        db.session.commit()

        survivors = ExpenseCategory.query.filter_by(name='LR-Survivor-Cat').count()
        assert survivors == 1
        db.session.refresh(test_product)
        assert Decimal(str(test_product.current_stock)) == Decimal('100')


# ─────────────────────── 9. return_service COGS basis + FX ───────────────────────

def _return_line_for(sale):
    from models import SaleLine
    return SaleLine.query.filter_by(sale_id=sale.id).first()


class TestReturnCostBasisAndFx:

    def test_cogs_reversal_uses_sale_line_historical_cost(self, db, owner_user, test_product, test_sale):
        """Sale line captured cost 25 while product's CURRENT cost is 50 —
        the reversal must credit the historical 25, not today's 50."""
        from services.return_service import ReturnService

        assert Decimal(str(test_product.cost_price)) == Decimal('50')
        line = _return_line_for(test_sale)
        assert Decimal(str(line.cost_price)) == Decimal('25')

        ret = ReturnService.create_return(
            sale_id=test_sale.id,
            return_lines_data=[{'sale_line_id': line.id, 'quantity': 1}],
            user_id=owner_user.id,
        )

        entry = GLJournalEntry.query.filter_by(
            reference_type='ProductReturn', reference_id=ret.id).first()
        assert entry is not None
        cogs_line = next(ln for ln in entry.lines if 'COGS Reversal' in (ln.description or ''))
        inv_line = next(ln for ln in entry.lines if 'Inventory Restock' in (ln.description or ''))
        assert cogs_line.credit == Decimal('25.000')
        assert inv_line.debit == Decimal('25.000')

    def test_return_gl_entry_carries_sale_currency_and_rate(self, db, owner_user, test_product, test_sale):
        from services.return_service import ReturnService

        test_sale.currency = 'USD'
        test_sale.exchange_rate = Decimal('3.55')
        db.session.commit()

        line = _return_line_for(test_sale)
        ret = ReturnService.create_return(
            sale_id=test_sale.id,
            return_lines_data=[{'sale_line_id': line.id, 'quantity': 1}],
            user_id=owner_user.id,
        )

        entry = GLJournalEntry.query.filter_by(
            reference_type='ProductReturn', reference_id=ret.id).first()
        assert entry is not None
        assert entry.currency == 'USD'
        assert Decimal(str(entry.exchange_rate)) == Decimal('3.55')


# ─────────────────────── 10. archive restore resolution ───────────────────────

class TestArchiveRestoreModelResolution:

    def test_restore_resolves_model_by_tablename(self, db, test_customer):
        from services.archive_service import ArchiveService, resolve_model_class

        test_customer.is_active = False
        db.session.commit()

        record = ArchivedRecord(
            table_name='customers',  # tablename, NOT class name
            record_id=test_customer.id,
            data={'name': test_customer.name},
            reason='lr-restore-probe',
        )
        db.session.add(record)
        db.session.commit()

        restored = ArchiveService.restore_record(record)

        assert isinstance(restored, Customer)
        db.session.refresh(restored)
        assert restored.is_active is True
        # legacy class-name archives still resolve through the direct path
        assert resolve_model_class('Customer') is Customer

    def test_restore_unknown_table_raises_value_error(self, db, test_customer):
        from services.archive_service import ArchiveService

        record = ArchivedRecord(
            table_name='not_a_real_table_xyz',
            record_id=test_customer.id,
            data={'name': test_customer.name},
            reason='lr-unknown-probe',
        )
        db.session.add(record)
        db.session.commit()

        with pytest.raises(ValueError, match='Model not found'):
            ArchiveService.restore_record(record)
