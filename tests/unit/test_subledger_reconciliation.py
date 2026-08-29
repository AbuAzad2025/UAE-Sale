"""
Sub-Ledger Reconciliation Tests — مطابقة الذمم الفرعية مع الأستاذ العام
========================================================================

Proves the STRICT MATCH RULE for AR ('1130') and AP ('2115' + '2110'):
    recomputed sub-ledger == GL control net == denormalized balance columns
All money math is Decimal; tolerance boundary is |delta| ≤ 0.01 inclusive.
"""

from decimal import Decimal

from models import Customer, Purchase, Sale, Supplier
from services.gl_service import GLService
from services.subledger_reconciliation import SubLedgerReconciliation


# ─────────────────────────── helpers ───────────────────────────

def _post(dr_code, cr_code, amount):
    """Post one balanced GL pair (flush only; caller commits)."""
    GLService.ensure_core_accounts()
    amount = Decimal(str(amount))
    GLService.post_entry(
        [
            {'account': dr_code, 'debit': amount},
            {'account': cr_code, 'credit': amount},
        ],
        description='subledger-reconciliation-test',
        currency='AED',
        exchange_rate=1,
    )


def _make_sale(customer_id, seller_id, number, total, paid,
               status='confirmed', is_active=True):
    total_d = Decimal(str(total))
    paid_d = Decimal(str(paid))
    return Sale(
        sale_number=number,
        customer_id=customer_id,
        seller_id=seller_id,
        total_amount=total_d,
        amount_base=total_d,
        paid_amount=paid_d,
        paid_amount_base=paid_d,
        balance_due=max(total_d - paid_d, Decimal('0')),
        currency='AED',
        exchange_rate=Decimal('1'),
        payment_status='paid' if paid_d >= total_d else (
            'partial' if paid_d > 0 else 'unpaid'),
        status=status,
        is_active=is_active,
    )


def _make_purchase(supplier_id, user_id, number, total, paid,
                   status='confirmed', paid_none=False):
    total_d = Decimal(str(total))
    return Purchase(
        purchase_number=number,
        supplier_id=supplier_id,
        supplier_name=f'Supplier-{supplier_id}',
        total_amount=total_d,
        amount_base=total_d,
        paid_amount=None if paid_none else Decimal(str(paid)),
        payment_status='partial' if Decimal(str(paid)) > 0 else 'pending',
        status=status,
        currency='AED',
        exchange_rate=Decimal('1'),
        user_id=user_id,
    )


def _sync_supplier_columns(supplier, purchases_total, paid_total):
    """
    Overwrite the denormalized supplier columns AFTER purchase inserts.
    The Purchase listeners derive total_paid_aed from the Payment table, so
    tests align the columns explicitly to the purchase-based sub-ledger world.
    """
    supplier.total_purchases_aed = Decimal(str(purchases_total))
    supplier.total_paid_aed = Decimal(str(paid_total))


# ─────────────────────────── AR section ───────────────────────────

class TestReceivablesReconciliation:

    def test_perfect_books_ar_balanced(self, db, owner_user, test_customer):
        """Invoice leg + receipt leg posted ⇒ all three ledgers agree."""
        db.session.add(_make_sale(test_customer.id, owner_user.id, 'S-SLR-001', 250, 100))
        db.session.add(_make_sale(test_customer.id, owner_user.id, 'S-SLR-002', 150, 150))
        db.session.commit()  # sale listener syncs customer.balance → 150

        _post('1130', '4100', 400)   # invoices
        _post('1110', '1130', 250)   # receipts
        db.session.commit()

        report = SubLedgerReconciliation.reconcile_receivables()

        assert report['section'] == 'AR'
        assert report['balanced'] is True
        assert report['breaks'] == []
        assert report['subledger_sum'] == Decimal('150.00')
        assert report['control_balance'] == Decimal('150.00')
        assert report['column_sum'] == Decimal('150.00')

    def test_empty_db_zeros(self, db):
        """Fresh DB ⇒ zero everywhere and still balanced."""
        report = SubLedgerReconciliation.reconcile_receivables()

        assert report['section'] == 'AR'
        assert report['subledger_sum'] == Decimal('0.00')
        assert report['control_balance'] == Decimal('0.00')
        assert report['column_sum'] == Decimal('0.00')
        assert report['breaks'] == []
        assert report['balanced'] is True

    def test_seeded_customer_drift_exact_delta(self, db, owner_user, test_customer):
        """One drifted customer column is detected with the exact delta."""
        db.session.add(_make_sale(test_customer.id, owner_user.id, 'S-SLR-010', 300, 0))
        db.session.commit()

        test_customer.balance = Decimal('280.00')  # seed drift after listener sync
        db.session.commit()

        report = SubLedgerReconciliation.reconcile_receivables()

        assert report['balanced'] is False
        assert len(report['breaks']) == 1
        brk = report['breaks'][0]
        assert brk['entity_id'] == test_customer.id
        assert brk['expected'] == Decimal('300.00')
        assert brk['stored'] == Decimal('280.00')
        assert brk['delta'] == Decimal('-20.00')

    def test_partial_payment_math(self, db, owner_user, test_customer):
        """amount_base − paid_amount_base drives the expectation exactly."""
        db.session.add(_make_sale(test_customer.id, owner_user.id, 'S-SLR-020', 999.99, 333.33))
        db.session.commit()

        _post('1130', '4100', 999.99)
        _post('1110', '1130', 333.33)
        db.session.commit()

        report = SubLedgerReconciliation.reconcile_receivables()

        assert report['subledger_sum'] == Decimal('666.66')
        assert report['balanced'] is True

    def test_cancelled_sale_excluded(self, db, owner_user, test_customer):
        """status='cancelled' invoices never enter any ledger side."""
        db.session.add(_make_sale(
            test_customer.id, owner_user.id, 'S-SLR-030', 999, 0, status='cancelled'))
        db.session.commit()

        report = SubLedgerReconciliation.reconcile_receivables()

        assert report['subledger_sum'] == Decimal('0.00')
        assert report['column_sum'] == Decimal('0.00')
        assert report['balanced'] is True

    def test_inactive_sale_excluded(self, db, owner_user, test_customer):
        """is_active=False sales are ignored per existing conventions."""
        db.session.add(_make_sale(
            test_customer.id, owner_user.id, 'S-SLR-031', 500, 0, is_active=False))
        db.session.commit()

        report = SubLedgerReconciliation.reconcile_receivables()

        assert report['subledger_sum'] == Decimal('0.00')
        assert report['balanced'] is True

    def test_inactive_customer_excluded(self, db, owner_user, test_customer):
        """Sales of deactivated customers are out of scope on both sides."""
        ghost = Customer(name='Ghost', customer_type='regular',
                         balance=Decimal('0'), is_active=False)
        db.session.add(ghost)
        db.session.flush()
        db.session.add(_make_sale(ghost.id, owner_user.id, 'S-SLR-032', 777, 0))
        db.session.commit()

        report = SubLedgerReconciliation.reconcile_receivables()

        assert report['subledger_sum'] == Decimal('0.00')
        assert report['column_sum'] == Decimal('0.00')
        assert report['balanced'] is True

    def test_tolerance_boundary_within_one_cent(self, db, owner_user, test_customer):
        """|delta| == 0.01 exactly ⇒ tolerated, still balanced (legacy rule)."""
        db.session.add(_make_sale(test_customer.id, owner_user.id, 'S-SLR-040', 100, 0))
        db.session.commit()

        test_customer.balance = Decimal('99.99')
        db.session.commit()

        _post('1130', '4100', 100)
        db.session.commit()

        report = SubLedgerReconciliation.reconcile_receivables()

        assert report['breaks'] == []
        assert report['balanced'] is True

    def test_tolerance_boundary_exceeded_two_cents(self, db, owner_user, test_customer):
        """|delta| == 0.02 ⇒ break reported with quantized delta."""
        db.session.add(_make_sale(test_customer.id, owner_user.id, 'S-SLR-041', 100, 0))
        db.session.commit()

        test_customer.balance = Decimal('100.02')
        db.session.commit()

        _post('1130', '4100', 100)
        db.session.commit()

        report = SubLedgerReconciliation.reconcile_receivables()

        assert report['balanced'] is False
        assert len(report['breaks']) == 1
        assert report['breaks'][0]['delta'] == Decimal('0.02')

    def test_multiple_customers_aggregate(self, db, owner_user):
        """Sub-ledger sums across customers; GL must carry the same total."""
        c1 = Customer(name='Agg One', customer_type='regular',
                      balance=Decimal('0'), is_active=True)
        c2 = Customer(name='Agg Two', customer_type='regular',
                      balance=Decimal('0'), is_active=True)
        db.session.add_all([c1, c2])
        db.session.flush()
        db.session.add(_make_sale(c1.id, owner_user.id, 'S-SLR-050', 200, 80))
        db.session.add(_make_sale(c2.id, owner_user.id, 'S-SLR-051', 75, 0))
        db.session.commit()

        _post('1130', '4100', 275)
        _post('1110', '1130', 80)
        db.session.commit()

        report = SubLedgerReconciliation.reconcile_receivables()

        assert report['subledger_sum'] == Decimal('195.00')
        assert report['control_balance'] == Decimal('195.00')
        assert report['column_sum'] == Decimal('195.00')
        assert report['balanced'] is True

    def test_output_shape_contract(self, db, owner_user, test_customer):
        """Report exposes exactly the contracted keys with Decimal money."""
        db.session.add(_make_sale(test_customer.id, owner_user.id, 'S-SLR-060', 50, 0))
        db.session.commit()

        report = SubLedgerReconciliation.reconcile_receivables()

        assert {'section', 'control_accounts', 'control_balance',
                'subledger_sum', 'column_sum', 'breaks', 'balanced'} <= set(report)
        assert isinstance(report['control_balance'], Decimal)
        assert isinstance(report['subledger_sum'], Decimal)
        assert isinstance(report['column_sum'], Decimal)

    def test_decimal_cents_never_float_drift(self, db, owner_user, test_customer):
        """Three 0.10 invoices sum to exactly 0.30 under Decimal arithmetic."""
        for i in range(3):
            db.session.add(_make_sale(
                test_customer.id, owner_user.id, f'S-SLR-07{i}', '0.10', 0))
        db.session.commit()

        _post('1130', '4100', '0.30')
        db.session.commit()

        report = SubLedgerReconciliation.reconcile_receivables()

        assert report['subledger_sum'] == Decimal('0.30')
        assert report['balanced'] is True


# ─────────────────────────── AP mirror ───────────────────────────

class TestPayablesReconciliation:

    def test_perfect_books_ap_balanced(self, db, owner_user):
        """Purchase leg + payment leg posted ⇒ all three sides agree on 2115+2110."""
        supplier = Supplier(name='SLR Sup A', is_active=True)
        db.session.add(supplier)
        db.session.flush()
        db.session.add(_make_purchase(supplier.id, owner_user.id, 'P-SLR-001', 400, 150))
        db.session.commit()

        _sync_supplier_columns(supplier, 400, 150)  # align columns to sub-ledger
        _post('1140', '2110', 400)                  # procurement invoice
        _post('2110', '1110', 150)                  # supplier payment
        db.session.commit()

        report = SubLedgerReconciliation.reconcile_payables()

        assert report['section'] == 'AP'
        assert set(report['control_accounts']) == {'2115', '2110'}
        assert report['balanced'] is True
        assert report['breaks'] == []
        assert report['subledger_sum'] == Decimal('250.00')
        assert report['control_balance'] == Decimal('250.00')
        assert report['column_sum'] == Decimal('250.00')

    def test_ap_empty_db_zeros(self, db):
        report = SubLedgerReconciliation.reconcile_payables()

        assert report['section'] == 'AP'
        assert report['subledger_sum'] == Decimal('0.00')
        assert report['control_balance'] == Decimal('0.00')
        assert report['column_sum'] == Decimal('0.00')
        assert report['breaks'] == []
        assert report['balanced'] is True

    def test_ap_none_paid_amount_treated_zero(self, db, owner_user):
        """paid_amount was added recently — None must behave as 0, never crash."""
        supplier = Supplier(name='SLR Sup B', is_active=True)
        db.session.add(supplier)
        db.session.flush()
        db.session.add(_make_purchase(
            supplier.id, owner_user.id, 'P-SLR-002', 300, 0, paid_none=True))
        db.session.commit()

        _sync_supplier_columns(supplier, 300, 0)
        _post('1140', '2110', 300)
        db.session.commit()

        report = SubLedgerReconciliation.reconcile_payables()

        assert report['subledger_sum'] == Decimal('300.00')
        assert report['balanced'] is True

    def test_ap_stored_column_drift_detected(self, db, owner_user):
        """Simulated events.py double-count in total_paid_aed is caught exactly."""
        supplier = Supplier(name='SLR Sup C', is_active=True)
        db.session.add(supplier)
        db.session.flush()
        db.session.add(_make_purchase(supplier.id, owner_user.id, 'P-SLR-003', 400, 150))
        db.session.commit()

        _sync_supplier_columns(supplier, 400, 300)  # seeded drift: paid inflated
        db.session.commit()

        report = SubLedgerReconciliation.reconcile_payables()

        assert report['balanced'] is False
        assert len(report['breaks']) == 1
        brk = report['breaks'][0]
        assert brk['entity_id'] == supplier.id
        assert brk['expected'] == Decimal('250.00')
        assert brk['stored'] == Decimal('100.00')
        assert brk['delta'] == Decimal('-150.00')

    def test_ap_cancelled_purchase_excluded(self, db, owner_user):
        """Cancelled procurement never enters the payable sub-ledger."""
        supplier = Supplier(name='SLR Sup D', is_active=True)
        db.session.add(supplier)
        db.session.flush()
        db.session.add(_make_purchase(
            supplier.id, owner_user.id, 'P-SLR-004', 999, 0, status='cancelled'))
        db.session.commit()

        report = SubLedgerReconciliation.reconcile_payables()

        assert report['subledger_sum'] == Decimal('0.00')
        assert report['column_sum'] == Decimal('0.00')
        assert report['balanced'] is True

    def test_ap_partial_payment_math(self, db, owner_user):
        supplier = Supplier(name='SLR Sup E', is_active=True)
        db.session.add(supplier)
        db.session.flush()
        db.session.add(_make_purchase(supplier.id, owner_user.id, 'P-SLR-005', 500, 200))
        db.session.commit()

        _sync_supplier_columns(supplier, 500, 200)
        _post('1140', '2110', 500)
        _post('2110', '1110', 200)
        db.session.commit()

        report = SubLedgerReconciliation.reconcile_payables()

        assert report['subledger_sum'] == Decimal('300.00')
        assert report['balanced'] is True


# ─────────────────────────── cross-section ───────────────────────────

class TestReconciliationSuite:

    def test_reconcile_all_returns_both_sections(self, db):
        reports = SubLedgerReconciliation.reconcile_all()

        assert [r['section'] for r in reports] == ['AR', 'AP']
        for report in reports:
            assert {'control_balance', 'subledger_sum', 'column_sum',
                    'breaks', 'balanced'} <= set(report)
            assert report['balanced'] is True

    def test_gl_reversal_keeps_books_balanced(self, db, owner_user, test_customer):
        """Immutability: corrections via reversing entries preserve the match."""
        db.session.add(_make_sale(test_customer.id, owner_user.id, 'S-SLR-080', 90, 0))
        db.session.commit()

        GLService.ensure_core_accounts()
        GLService.post_entry(
            [
                {'account': '1130', 'debit': Decimal('90')},
                {'account': '4100', 'credit': Decimal('90')},
            ],
            description='invoice leg',
            currency='AED',
            exchange_rate=1,
        )
        entry = GLService.post_entry(
            [
                {'account': '1130', 'debit': Decimal('40')},
                {'account': '4100', 'credit': Decimal('40')},
            ],
            description='wrong posting to be reversed',
            currency='AED',
            exchange_rate=1,
        )
        entry.reverse_entry()
        db.session.commit()

        report = SubLedgerReconciliation.reconcile_receivables()

        assert report['control_balance'] == Decimal('90.00')
        assert report['balanced'] is True

    def test_missing_gl_postings_flagged_as_unbalanced(self, db, owner_user, test_customer):
        """Sub-ledger without its GL leg proves the control check has teeth."""
        db.session.add(_make_sale(test_customer.id, owner_user.id, 'S-SLR-081', 60, 0))
        db.session.commit()

        report = SubLedgerReconciliation.reconcile_receivables()

        assert report['subledger_sum'] == Decimal('60.00')
        assert report['control_balance'] == Decimal('0.00')
        assert report['balanced'] is False


class TestChequeBounceSubledgerReconciliation:
    """اختبارات مطابقة الذمم الفرعية بعد ارتداد الشيك"""

    def _create_incoming_cheque(self, test_customer, owner_user):
        from datetime import date
        from models import Cheque
        cheque = Cheque(
            cheque_number='CH-TEST-001',
            cheque_bank_number='123456',
            cheque_type='incoming',
            bank_name='Emirates NBD',
            amount=Decimal('1000'),
            currency='AED',
            exchange_rate=Decimal('1'),
            issue_date=date.today(),
            due_date=date.today(),
            status='pending',
            customer_id=test_customer.id,
            user_id=owner_user.id,
        )
        cheque.calculate_amount_base()
        from extensions import db
        db.session.add(cheque)
        db.session.commit()
        return cheque

    def _create_outgoing_cheque(self, db, owner_user):
        from datetime import date
        from models import Cheque, Supplier
        supplier = Supplier(name='مورد اختبار', is_active=True)
        db.session.add(supplier)
        db.session.flush()
        cheque = Cheque(
            cheque_number='CH-TEST-002',
            cheque_bank_number='123457',
            cheque_type='outgoing',
            bank_name='Emirates NBD',
            amount=Decimal('1000'),
            currency='AED',
            exchange_rate=Decimal('1'),
            issue_date=date.today(),
            due_date=date.today(),
            status='pending',
            supplier_id=supplier.id,
            user_id=owner_user.id,
        )
        cheque.calculate_amount_base()
        db.session.add(cheque)
        db.session.commit()
        return cheque

    def test_bounce_cheque_customer_balance_restored(self, db, owner_user, test_customer):
        """بعد ارتداد الشيك، يجب أن يسترد رصيد العميل"""
        from services.cheque_accounting_integration import ChequeAccountingIntegration

        cheque = self._create_incoming_cheque(test_customer, owner_user)
        balance_before = test_customer.balance or Decimal('0')

        # استلام الشيك
        ChequeAccountingIntegration.receive_cheque(cheque.id, received_by=owner_user.id)
        db.session.refresh(test_customer)

        # ارتداد الشيك
        ChequeAccountingIntegration.bounce_cheque(cheque.id, bounced_by=owner_user.id, bounce_reason='عدم كفاية الرصيد')
        db.session.refresh(test_customer)

        # التحقق من أن الرصيد زاد بمبلغ الشيك
        assert test_customer.balance == balance_before + Decimal('1000.00')

    def test_cancel_cheque_customer_balance_restored(self, db, owner_user, test_customer):
        """بعد إلغاء الشيك، يجب أن يسترد رصيد العميل"""
        from services.cheque_accounting_integration import ChequeAccountingIntegration

        cheque = self._create_incoming_cheque(test_customer, owner_user)
        balance_before = test_customer.balance or Decimal('0')

        # استلام الشيك
        ChequeAccountingIntegration.receive_cheque(cheque.id, received_by=owner_user.id)
        db.session.refresh(test_customer)

        # إلغاء الشيك
        cheque.cancel_cheque(reason='إلغاء تجريبي')
        db.session.refresh(test_customer)

        # التحقق من أن الرصيد انخفض بمبلغ الشيك
        assert test_customer.balance == balance_before - Decimal('1000.00')

    def test_bounce_cheque_outgoing_supplier_balance_restored(self, db, owner_user):
        """بعد ارتداد الشيك الصادر، يجب أن يسترد رصيد المورد"""
        from services.cheque_accounting_integration import ChequeAccountingIntegration

        cheque = self._create_outgoing_cheque(db, owner_user)
        supplier = cheque.supplier
        db.session.refresh(supplier)
        balance_before = supplier.total_purchases_aed or Decimal('0')

        # إصدار الشيك
        ChequeAccountingIntegration.issue_cheque(cheque.id, issued_by=owner_user.id)
        db.session.refresh(supplier)

        # ارتداد الشيك
        ChequeAccountingIntegration.bounce_cheque(cheque.id, bounced_by=owner_user.id, bounce_reason='عدم كفاية الرصيد')
        db.session.refresh(supplier)

        # التحقق من أن رصيد المورد انخفض بمبلغ الشيك
        assert supplier.total_purchases_aed == balance_before - Decimal('1000.00')
