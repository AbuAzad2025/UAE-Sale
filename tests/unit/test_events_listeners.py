"""
Event Listener Tests — models/events.py

Covers: Sale/Receipt customer-balance recalculation, Purchase/Payment supplier
totals, validation listeners (sale/purchase/receipt/payment/product), cheque,
product-return, expense, GL, stock-movement logging and utility helpers.
"""

import logging
from datetime import date, timedelta
from decimal import Decimal

EVENTS_LOGGER = 'models.events'


def _customer(db, name):
    from models import Customer

    c = Customer(
        name=name, name_ar=name, customer_type='regular',
        credit_limit=Decimal('50000'), balance=Decimal('0'), is_active=True,
    )
    db.session.add(c)
    db.session.commit()
    return c


def _supplier(db, name):
    from models import Supplier

    s = Supplier(name=name)
    db.session.add(s)
    db.session.commit()
    return s


def _warehouse(db, name):
    from models import Warehouse

    w = Warehouse(name=name, code=name)
    db.session.add(w)
    db.session.commit()
    return w


def _make_sale(db, number, customer_id, amount='100.000', paid='0', seller_id=None, **extra):
    from models import Sale

    sale = Sale(
        sale_number=number, customer_id=customer_id, seller_id=seller_id,
        total_amount=Decimal(amount), amount_base=Decimal(amount),
        paid_amount=Decimal(paid), paid_amount_base=Decimal(paid),
        balance_due=Decimal(amount) - Decimal(paid), currency='AED',
        exchange_rate=Decimal('1'), payment_status='unpaid',
        status='confirmed', is_active=True,
    )
    for k, v in extra.items():
        setattr(sale, k, v)
    db.session.add(sale)
    db.session.commit()
    return sale


def _make_purchase(db, number, supplier, user_id, amount='200.000', **extra):
    from models import Purchase

    p = Purchase(
        purchase_number=number, supplier_id=supplier.id,
        supplier_name=supplier.name, total_amount=Decimal(amount),
        amount_base=Decimal(amount), currency='AED',
        exchange_rate=Decimal('1'), status='confirmed', user_id=user_id,
    )
    for k, v in extra.items():
        setattr(p, k, v)
    db.session.add(p)
    db.session.commit()
    return p


def _make_payment(db, number, amount='50.000', supplier_id=None, customer_id=None, sale_id=None):
    from models import Payment

    pay = Payment(
        payment_number=number, payment_type='payment', direction='outgoing',
        supplier_id=supplier_id, customer_id=customer_id, sale_id=sale_id,
        amount=Decimal(amount), currency='AED', exchange_rate=Decimal('1'),
        amount_base=Decimal(amount), payment_method='cash',
        payment_confirmed=True,
    )
    db.session.add(pay)
    db.session.commit()
    return pay


def _make_receipt(db, number, customer_id, amount='25.000'):
    from models import Receipt

    r = Receipt(
        receipt_number=number, customer_id=customer_id, direction='incoming',
        amount=Decimal(amount), currency='AED', exchange_rate=Decimal('1'),
        amount_base=Decimal(amount), payment_method='cash',
        payment_confirmed=True,
    )
    db.session.add(r)
    db.session.commit()
    return r


class TestSaleBalanceListeners:
    """Sale insert/update must recalc Customer.balance = Σ(amount_base − paid)."""

    def test_sale_insert_recalculates_customer_balance(self, db, owner_user):
        c = _customer(db, 'BalCust-Ins')
        s1 = _make_sale(db, 'S-EV-BAL-1', c.id, amount='100.000')
        assert s1.id is not None
        db.session.refresh(c)
        assert c.balance == Decimal('100.000')

        _make_sale(db, 'S-EV-BAL-2', c.id, amount='250.000', seller_id=owner_user.id)
        db.session.refresh(c)
        assert c.balance == Decimal('350.000')

    def test_sale_update_recalculates_customer_balance(self, db, test_sale, test_customer):
        db.session.refresh(test_customer)
        assert test_customer.balance == Decimal('100.000')
        test_sale.paid_amount_base = Decimal('40.000')
        db.session.commit()
        db.session.refresh(test_customer)
        assert test_customer.balance == Decimal('60.000')

    def test_cancelled_sale_skips_recalc(self, db, test_sale, test_customer):
        test_sale.status = 'cancelled'
        test_sale.paid_amount_base = Decimal('40.000')
        db.session.commit()
        db.session.refresh(test_customer)
        assert test_customer.balance == Decimal('100.000')

    def test_inactive_sale_skips_recalc(self, db, owner_user):
        from models import Customer

        c = _customer(db, 'BalCust-Inact')
        _make_sale(db, 'S-EV-INACT-1', c.id, amount='80.000', seller_id=owner_user.id)
        sale = _make_sale(db, 'S-EV-INACT-2', c.id, amount='70.000')
        db.session.refresh(c)
        assert c.balance == Decimal('150.000')

        sale.is_active = False
        sale.notes = 'deactivated'
        db.session.commit()
        db.session.refresh(c)
        assert c.balance == Decimal('150.000')

        reloaded = db.session.get(Customer, c.id)
        assert reloaded.balance == Decimal('150.000')

    def test_sale_delete_logs_audit_warning(self, db, caplog):
        c = _customer(db, 'BalCust-Del')
        sale = _make_sale(db, 'S-EV-DEL-1', c.id, amount='30.000')

        with caplog.at_level(logging.INFO, logger=EVENTS_LOGGER):
            db.session.delete(sale)
            db.session.commit()

        msgs = [r.getMessage() for r in caplog.records]
        assert any('DELETED: Sale S-EV-DEL-1' in m for m in msgs)

    def test_sale_negative_amount_logged(self, db, caplog):
        from models import Sale

        c = _customer(db, 'BalCust-Neg')
        with caplog.at_level(logging.ERROR, logger=EVENTS_LOGGER):
            sale = _make_sale(
                db, 'S-EV-NEG-1', c.id,
                amount='-5.000',
                total_amount=Decimal('100.000'),
                balance_due=None,
            )

        assert isinstance(sale, Sale) and sale.id is not None
        assert any('S-EV-NEG-1' in r.getMessage() and 'Negative amount' in r.getMessage()
                   for r in caplog.records)

    def test_sale_balance_due_autocorrected_with_warning(self, db, caplog):
        from models import Sale

        c = _customer(db, 'BalCust-Fix')
        sale = Sale(
            sale_number='S-EV-FIX-1', customer_id=c.id,
            total_amount=Decimal('100.000'), amount_base=Decimal('100.000'),
            paid_amount=Decimal('40.000'), paid_amount_base=Decimal('40.000'),
            balance_due=Decimal('999.000'), currency='AED',
            exchange_rate=Decimal('1'), status='confirmed', is_active=True,
        )
        with caplog.at_level(logging.WARNING, logger=EVENTS_LOGGER):
            db.session.add(sale)
            db.session.commit()

        db.session.refresh(sale)
        assert sale.balance_due == Decimal('60.000')
        assert any('Balance auto-corrected' in r.getMessage() and 'S-EV-FIX-1' in r.getMessage()
                   for r in caplog.records)

    def test_sale_balance_within_tolerance_not_corrected(self, db, caplog):
        from models import Sale

        c = _customer(db, 'BalCust-Tol')
        sale = Sale(
            sale_number='S-EV-TOL-1', customer_id=c.id,
            total_amount=Decimal('100.000'), amount_base=Decimal('100.000'),
            paid_amount=Decimal('0'), paid_amount_base=Decimal('0'),
            balance_due=Decimal('100.005'), currency='AED',
            exchange_rate=Decimal('1'), status='confirmed', is_active=True,
        )
        with caplog.at_level(logging.WARNING, logger=EVENTS_LOGGER):
            db.session.add(sale)
            db.session.commit()

        db.session.refresh(sale)
        assert sale.balance_due == Decimal('100.005')
        assert not any('auto-corrected' in r.getMessage() and 'S-EV-TOL-1' in r.getMessage()
                       for r in caplog.records)


class TestReceiptListeners:
    """Receipt after_insert recalculates customer balance; delete warns."""

    def test_receipt_insert_recalculates_customer_balance(self, db, owner_user, caplog):
        from models import Customer

        c = _customer(db, 'Rcpt-Cust-1')
        _make_sale(db, 'S-EV-RCP-1', c.id, amount='300.000', paid='100.000',
                   seller_id=owner_user.id)
        db.session.refresh(c)
        assert c.balance == Decimal('200.000')

        Customer.query.filter_by(id=c.id).update({'balance': Decimal('777.000')})
        db.session.commit()

        with caplog.at_level(logging.INFO, logger=EVENTS_LOGGER):
            _make_receipt(db, 'RCP-EV-1', c.id, amount='50.000')

        db.session.refresh(c)
        assert c.balance == Decimal('200.000')
        assert any('after receipt' in r.getMessage() for r in caplog.records)

    def test_receipt_delete_warns_use_cancellation(self, db, caplog):
        c = _customer(db, 'Rcpt-Cust-Del')
        receipt = _make_receipt(db, 'RCP-EV-DEL-1', c.id, amount='25.000')

        with caplog.at_level(logging.WARNING, logger=EVENTS_LOGGER):
            db.session.delete(receipt)
            db.session.commit()

        msgs = [r.getMessage() for r in caplog.records]
        assert any('Attempted to delete receipt RCP-EV-DEL-1' in m and 'cancellation' in m
                   for m in msgs)


class TestPurchaseSupplierListeners:
    """Purchase/Payment listeners maintain Supplier totals."""

    def test_purchase_insert_updates_supplier_totals(self, db, owner_user):
        s = _supplier(db, 'Sup-Purch-1')
        _make_purchase(db, 'P-EV-1', s, owner_user.id, amount='200.000')
        db.session.refresh(s)
        assert s.total_purchases_aed == Decimal('200.000')
        assert s.total_paid_aed == Decimal('0')

        _make_purchase(db, 'P-EV-2', s, owner_user.id, amount='60.000')
        db.session.refresh(s)
        assert s.total_purchases_aed == Decimal('260.000')

    def test_purchase_update_updates_supplier_totals(self, db, owner_user):
        s = _supplier(db, 'Sup-Purch-Upd')
        p = _make_purchase(db, 'P-EV-UPD-1', s, owner_user.id, amount='200.000')
        db.session.refresh(s)
        assert s.total_purchases_aed == Decimal('200.000')

        p.amount_base = Decimal('350.000')
        db.session.commit()
        db.session.refresh(s)
        assert s.total_purchases_aed == Decimal('350.000')

    def test_cancelled_purchase_skips_supplier_update(self, db, owner_user):
        s = _supplier(db, 'Sup-Purch-Cxl')
        p = _make_purchase(db, 'P-EV-CXL-1', s, owner_user.id, amount='200.000')
        db.session.refresh(s)
        assert s.total_purchases_aed == Decimal('200.000')

        p.status = 'cancelled'
        p.amount_base = Decimal('500.000')
        db.session.commit()
        db.session.refresh(s)
        assert s.total_purchases_aed == Decimal('200.000')

    def test_payment_insert_updates_supplier_totals(self, db, owner_user):
        s = _supplier(db, 'Sup-Pay-1')
        _make_purchase(db, 'P-EV-PAY-1', s, owner_user.id, amount='200.000')
        _make_payment(db, 'PAY-EV-1', amount='50.000', supplier_id=s.id)
        db.session.refresh(s)
        assert s.total_purchases_aed == Decimal('200.000')
        assert s.total_paid_aed == Decimal('50.000')

    def test_payment_without_supplier_skips(self, db, caplog):
        c = _customer(db, 'Pay-NoSup-Cust')
        with caplog.at_level(logging.INFO, logger=EVENTS_LOGGER):
            pay = _make_payment(db, 'PAY-EV-NOSUP-1', amount='10.000', customer_id=c.id)

        assert pay.id is not None
        assert not any('Payment created' in r.getMessage() for r in caplog.records)


class TestValidationListeners:
    """before_insert/before_update validators log and correct bad data."""

    def test_purchase_negative_amount_logged_and_blocked(self, db, owner_user, caplog):
        from models import Purchase
        from sqlalchemy.exc import IntegrityError

        s = _supplier(db, 'Sup-Neg')
        p = Purchase(
            purchase_number='P-EV-NEG-1', supplier_id=s.id, supplier_name=s.name,
            total_amount=Decimal('100.000'), amount_base=Decimal('-5.000'),
            currency='AED', status='confirmed', user_id=owner_user.id,
        )
        with caplog.at_level(logging.ERROR, logger=EVENTS_LOGGER):
            db.session.add(p)
            try:
                db.session.commit()
                raised = False
            except IntegrityError:
                raised = True
                db.session.rollback()

        assert raised
        assert any('P-EV-NEG-1' in r.getMessage() and 'Negative amount' in r.getMessage()
                   for r in caplog.records)

    def test_receipt_invalid_amount_logged(self, db, caplog):
        from models import Receipt
        from sqlalchemy.exc import IntegrityError

        c = _customer(db, 'Rcpt-Neg-Cust')
        r = Receipt(
            receipt_number='RCP-EV-NEG-1', customer_id=c.id,
            amount=Decimal('-5.000'), amount_base=Decimal('-5.000'),
            payment_method='cash',
        )
        with caplog.at_level(logging.ERROR, logger=EVENTS_LOGGER):
            db.session.add(r)
            try:
                db.session.commit()
                raised = False
            except IntegrityError:
                raised = True
                db.session.rollback()

        assert raised
        assert any('RCP-EV-NEG-1' in r.getMessage() and 'Invalid amount' in r.getMessage()
                   for r in caplog.records)

    def test_payment_invalid_amount_logged(self, db, caplog):
        from models import Payment
        from sqlalchemy.exc import IntegrityError

        pay = Payment(
            payment_number='PAY-EV-NEG-1', payment_type='payment',
            amount=Decimal('-5.000'), amount_base=Decimal('-5.000'),
            payment_method='cash',
        )
        with caplog.at_level(logging.ERROR, logger=EVENTS_LOGGER):
            db.session.add(pay)
            try:
                db.session.commit()
                raised = False
            except IntegrityError:
                raised = True
                db.session.rollback()

        assert raised
        assert any('Invalid amount' in r.getMessage() for r in caplog.records)

    def test_product_negative_stock_clamped_to_zero(self, db, test_product, caplog):
        with caplog.at_level(logging.ERROR, logger=EVENTS_LOGGER):
            test_product.current_stock = Decimal('-5')
            db.session.commit()

        db.session.refresh(test_product)
        assert test_product.current_stock == 0
        assert any('BLOCKED' in r.getMessage() and 'Negative stock' in r.getMessage()
                   for r in caplog.records)


class TestChequeListeners:
    """Cheque overdue warning + status-change logging."""

    def _cheque(self, db, number, due_date):
        from models import Cheque

        chq = Cheque(
            cheque_number=number, cheque_bank_number='BNK-' + number,
            cheque_type='incoming', bank_name='Test Bank',
            amount=Decimal('1000.000'), issue_date=date.today(),
            due_date=due_date, status='pending',
        )
        db.session.add(chq)
        db.session.commit()
        return chq

    def test_overdue_cheque_logs_warning(self, db, caplog):
        overdue = date.today() - timedelta(days=10)
        with caplog.at_level(logging.WARNING, logger=EVENTS_LOGGER):
            self._cheque(db, 'CHQ-EV-OVR-1', overdue)

        assert any('CHQ-EV-OVR-1' in r.getMessage() and 'overdue by' in r.getMessage()
                   for r in caplog.records)

    def test_future_cheque_no_overdue_warning(self, db, caplog):
        future = date.today() + timedelta(days=15)
        with caplog.at_level(logging.WARNING, logger=EVENTS_LOGGER):
            self._cheque(db, 'CHQ-EV-FUT-1', future)

        assert not any('CHQ-EV-FUT-1' in r.getMessage() and 'overdue by' in r.getMessage()
                       for r in caplog.records)

    def test_cheque_cleared_status_change_logged(self, db, caplog):
        chq = self._cheque(db, 'CHQ-EV-CLR-1', date.today() + timedelta(days=5))

        with caplog.at_level(logging.INFO, logger=EVENTS_LOGGER):
            chq.status = 'cleared'
            db.session.commit()

        assert any('CHQ-EV-CLR-1' in r.getMessage() and 'تم الصرف' in r.getMessage()
                   for r in caplog.records)


class TestProductReturnExpenseGLStockListeners:
    """Misc after_insert/before_insert logging branches."""

    def test_approved_product_return_logged(self, db, test_sale, test_customer, caplog):
        from models import ProductReturn

        pr = ProductReturn(
            return_number='RET-EV-APPR-1', sale_id=test_sale.id,
            customer_id=test_customer.id, total_amount=Decimal('50.000'),
            amount_base=Decimal('50.000'), status='approved',
        )
        with caplog.at_level(logging.INFO, logger=EVENTS_LOGGER):
            db.session.add(pr)
            db.session.commit()

        assert any('RET-EV-APPR-1' in r.getMessage() and 'approved' in r.getMessage()
                   for r in caplog.records)

    def test_pending_product_return_not_logged_as_approved(self, db, test_sale, test_customer, caplog):
        from models import ProductReturn

        pr = ProductReturn(
            return_number='RET-EV-PEND-1', sale_id=test_sale.id,
            customer_id=test_customer.id, total_amount=Decimal('20.000'),
            amount_base=Decimal('20.000'), status='pending',
        )
        with caplog.at_level(logging.INFO, logger=EVENTS_LOGGER):
            db.session.add(pr)
            db.session.commit()

        assert not any('RET-EV-PEND-1' in r.getMessage() and 'approved - stock' in r.getMessage()
                       for r in caplog.records)

    def _expense_category(self, db, name):
        from models import ExpenseCategory

        cat = ExpenseCategory(name=name)
        db.session.add(cat)
        db.session.commit()
        return cat

    def test_active_expense_logged(self, db, owner_user, caplog):
        from models import Expense

        cat = self._expense_category(db, 'EvCat-Active-1')
        exp = Expense(
            expense_number='EXP-EV-ACT-1', category_id=cat.id,
            description='office supplies', amount=Decimal('75.000'),
            amount_base=Decimal('75.000'), payment_method='cash',
            user_id=owner_user.id, is_active=True,
        )
        with caplog.at_level(logging.INFO, logger=EVENTS_LOGGER):
            db.session.add(exp)
            db.session.commit()

        assert any('Expense recorded' in r.getMessage() and '75.0' in r.getMessage()
                   for r in caplog.records)

    def test_inactive_expense_not_logged(self, db, owner_user, caplog):
        from models import Expense

        cat = self._expense_category(db, 'EvCat-Inactive-1')
        exp = Expense(
            expense_number='EXP-EV-INACT-1', category_id=cat.id,
            description='void entry', amount=Decimal('10.000'),
            amount_base=Decimal('10.000'), payment_method='cash',
            user_id=owner_user.id, is_active=False,
        )
        with caplog.at_level(logging.INFO, logger=EVENTS_LOGGER):
            db.session.add(exp)
            db.session.commit()

        assert exp.id is not None
        assert not any('EXP-EV-INACT-1' in r.getMessage() for r in caplog.records)

    def test_unbalanced_gl_entry_logs_error(self, db, caplog):
        from models import GLJournalEntry

        entry = GLJournalEntry(
            entry_number='JE-EV-UNBAL-1', total_debit=Decimal('100.000'),
            total_credit=Decimal('90.000'),
        )
        with caplog.at_level(logging.ERROR, logger=EVENTS_LOGGER):
            db.session.add(entry)
            db.session.commit()

        assert any('JE-EV-UNBAL-1' in r.getMessage() and 'UNBALANCED' in r.getMessage()
                   for r in caplog.records)

    def test_balanced_gl_entry_logs_info(self, db, caplog):
        from models import GLJournalEntry

        entry = GLJournalEntry(
            entry_number='JE-EV-BAL-1', total_debit=Decimal('50.000'),
            total_credit=Decimal('50.000'),
        )
        with caplog.at_level(logging.INFO, logger=EVENTS_LOGGER):
            db.session.add(entry)
            db.session.commit()

        assert any('JE-EV-BAL-1' in r.getMessage() and 'is balanced' in r.getMessage()
                   for r in caplog.records)

    def test_inbound_stock_movement_logged_with_plus(self, db, test_product, caplog):
        from models import StockMovement

        w = _warehouse(db, 'WH-EV-IN-1')
        mv = StockMovement(
            product_id=test_product.id, warehouse_id=w.id,
            movement_type='purchase', quantity=Decimal('10.000'),
            reference_type='adjustment', reference_id=None,
        )
        with caplog.at_level(logging.INFO, logger=EVENTS_LOGGER):
            db.session.add(mv)
            db.session.commit()

        assert any('➕' in r.getMessage() and 'شراء (دخول)' in r.getMessage()
                   for r in caplog.records)

    def test_outbound_stock_movement_logged_with_minus(self, db, test_product, caplog):
        from models import StockMovement

        w = _warehouse(db, 'WH-EV-OUT-1')
        mv = StockMovement(
            product_id=test_product.id, warehouse_id=w.id,
            movement_type='sale', quantity=Decimal('-3.000'),
            reference_type='adjustment', reference_id=None,
        )
        with caplog.at_level(logging.INFO, logger=EVENTS_LOGGER):
            db.session.add(mv)
            db.session.commit()

        assert any('➖' in r.getMessage() and 'بيع (خروج)' in r.getMessage()
                   for r in caplog.records)


class TestEventUtilities:
    """validate_decimal_precision + ensure_balance_consistency."""

    def test_validate_decimal_precision_accepts_none_and_valid(self):
        from models.events import validate_decimal_precision

        assert validate_decimal_precision(None) is True
        assert validate_decimal_precision(Decimal('1.234')) is True
        assert validate_decimal_precision(123) is True

    def test_validate_decimal_precision_rejects_bad_values(self):
        from models.events import validate_decimal_precision

        assert validate_decimal_precision('1.2345') is False
        assert validate_decimal_precision('1234567890123456789') is False
        assert validate_decimal_precision('abc') is False

    def test_ensure_balance_consistency_consistent(self, db, test_sale, test_customer):
        from models import Customer
        from models.events import ensure_balance_consistency

        result = ensure_balance_consistency(db.session.connection(), Customer, test_customer.id)
        assert result['stored'] == Decimal('100.000')
        assert result['calculated'] == Decimal('100.000')
        assert result['consistent'] is True

    def test_ensure_balance_consistency_detects_drift(self, db, test_sale, test_customer):
        from models import Customer
        from models.events import ensure_balance_consistency

        Customer.query.filter_by(id=test_customer.id).update({'balance': Decimal('555.000')})
        db.session.commit()

        result = ensure_balance_consistency(db.session.connection(), Customer, test_customer.id)
        assert result['stored'] == Decimal('555.000')
        assert result['calculated'] == Decimal('100.000')
        assert result['consistent'] is False
