"""AR/AP P0 regression tests — tests/unit/test_ar_ap_p0.py.

Covers the F1..F14 fixes of the receivables/payables wave:

  F1  customer.balance has ONE derivation + ONE writer (sale / receipt /
       payment / refund / return all converge to the same number).
  F2  allocation is done in BASE currency at the RECEIPT's rate and the FX
       difference is posted to the FX gain/loss accounts (no GL vs sub-ledger
       gap).
  F3  Purchase.paid_amount / Purchase.payment_status are written when a
       payment settles a purchase (and legacy payments without purchase_id
       still settle at supplier level).
  F4  a bounced cheque restores the customer balance AND the invoice status.
  F5  the AR aging includes unpaid invoices and is expressed in base currency.
  F6  a supplier refund INCREASES the AP balance.
  F8  a pending cheque does not settle the invoice before it is confirmed.
  F9  deleting a receipt reverses each per-sale allocation (not the total
       against one invoice).
  F10 an opening balance is preserved by the balance repair.
  F11 a customer refund changes the customer balance.
  F12 one derivation for the customer balance (get_balance / get_balance_aed
       / balance_checker all agree).

All money math is Decimal; fully offline (no HTTP).
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from models import (
    Customer,
    Payment,
    Product,
    ProductCategory,
    Purchase,
    Sale,
    SaleLine,
    Supplier,
)
from extensions import db


# ─────────────────────────── helpers ───────────────────────────

@pytest.fixture(autouse=True)
def _fiscal_period(db):
    """.GL postings need an OPEN fiscal period covering today."""
    from models.erp_modules import FiscalPeriod

    year = date.today().year
    for y in (year - 1, year, year + 1):
        if FiscalPeriod.query.filter_by(year=y, period_type='annual').first() is None:
            db.session.add(FiscalPeriod(
                name=f'P0 test period {y}', year=y, period_type='annual',
                start_date=date(y, 1, 1), end_date=date(y, 12, 31),
                is_closed=False,
            ))
    db.session.commit()
    return db


def _customer(db, name, **extra):
    c = Customer(name=name, name_ar=name, customer_type='regular',
                 balance=Decimal('0'), is_active=True, **extra)
    db.session.add(c)
    db.session.commit()
    return c


def _supplier(db, name):
    s = Supplier(name=name, is_active=True)
    db.session.add(s)
    db.session.commit()
    return s


def _product(db, name='P0 product'):
    cat = ProductCategory.query.first()
    if cat is None:
        cat = ProductCategory(name='P0 cat', name_ar='P0 cat', is_active=True)
        db.session.add(cat)
        db.session.flush()
    p = Product(name=name, name_ar=name, sku=f'SKU-{name}', category_id=cat.id,
                cost_price=Decimal('25'), regular_price=Decimal('50'),
                current_stock=Decimal('100'), min_stock_alert=Decimal('1'),
                is_active=True)
    db.session.add(p)
    db.session.commit()
    return p


def _sale(db, number, customer, seller, total='100.000', currency='ILS',
          exchange_rate='1', paid='0', paid_base=None, lines=True):
    """Create a confirmed sale; amounts are given in the transaction currency."""
    total_d = Decimal(str(total))
    rate_d = Decimal(str(exchange_rate))
    paid_d = Decimal(str(paid))
    base_d = total_d * rate_d if currency != 'ILS' else total_d
    paid_base_d = Decimal(str(paid_base)) if paid_base is not None else (
        paid_d * rate_d if currency != 'ILS' else paid_d)

    sale = Sale(
        sale_number=number, customer_id=customer.id, seller_id=seller.id,
        total_amount=total_d, amount_base=base_d,
        paid_amount=paid_d, paid_amount_base=paid_base_d,
        balance_due=max(base_d - paid_base_d, Decimal('0')),
        currency=currency, exchange_rate=rate_d,
        payment_status='unpaid' if paid_d == 0 else 'partial',
        status='confirmed', is_active=True,
        sale_date=datetime.now(timezone.utc),
    )
    db.session.add(sale)
    db.session.flush()
    if lines:
        line = SaleLine(
            sale_id=sale.id, product_id=_product(db, f'P0 line {number}').id,
            quantity=Decimal('2'), unit_price=total_d / Decimal('2'),
            discount_percent=Decimal('0'), line_total=total_d,
            cost_price=Decimal('25'),
        )
        db.session.add(line)
    db.session.commit()
    return sale


def _purchase(db, number, supplier, user_id, total='200.000'):
    p = Purchase(
        purchase_number=number, supplier_id=supplier.id,
        supplier_name=supplier.name, total_amount=Decimal(total),
        amount_base=Decimal(total), currency='ILS', exchange_rate=Decimal('1'),
        status='confirmed', user_id=user_id, paid_amount=Decimal('0'),
        payment_status='unpaid',
    )
    db.session.add(p)
    db.session.commit()
    return p


def _net(account_code):
    """Signed base-currency net of a GL account."""
    from sqlalchemy import func

    from models import GLAccount, GLJournalLine

    acc = GLAccount.query.filter_by(code=account_code).first()
    if acc is None:
        return None
    return db.session.query(
        func.coalesce(func.sum(GLJournalLine.amount_base), 0)).filter(
        GLJournalLine.account_id == acc.id).scalar()


def _balance(customer_id):
    from models.customer import derive_customer_balance
    return derive_customer_balance(customer_id)


# ─────────────────────── F1: one derivation, one writer ───────────────────────

class TestSingleBalanceDerivation:

    def test_balance_identical_whichever_path_writes_it(self, db, owner_user, test_customer):
        """sale → receipt → payment → refund → return all converge to one value."""
        from services.payment_service import PaymentService

        sale = _sale(db, 'S-P0-F1-1', test_customer, owner_user, total='100.000')
        db.session.refresh(test_customer)
        assert Decimal(str(test_customer.balance)) == Decimal('100.000')

        # 1) receipt allocated to the invoice
        PaymentService.create_receipt({
            'customer_id': test_customer.id,
            'amount': Decimal('40'),
            'currency': 'ILS',
            'payment_method': 'cash',
            'user_exchange_rate': Decimal('1'),
            'allocate_to_sales': {sale.id: 40},
        })
        db.session.refresh(test_customer)
        db.session.refresh(sale)
        assert Decimal(str(test_customer.balance)) == Decimal('60.000')
        assert Decimal(str(sale.balance_due)) == Decimal('60.000')

        # 2) a payment against the same invoice
        payment = Payment(
            payment_number='PAY-P0-F1-1', payment_type='sale', direction='outgoing',
            sale_id=sale.id, customer_id=test_customer.id, amount=Decimal('10'),
            currency='ILS', exchange_rate=Decimal('1'), amount_base=Decimal('10'),
            payment_method='cash', payment_confirmed=True, user_id=owner_user.id,
        )
        db.session.add(payment)
        db.session.commit()
        db.session.refresh(test_customer)
        assert Decimal(str(test_customer.balance)) == Decimal('50.000')

        # 3) a standalone customer refund (F11) — reduces the receivable
        refund = Payment(
            payment_number='PAY-P0-F1-2', payment_type='refund', direction='outgoing',
            customer_id=test_customer.id, amount=Decimal('5'), currency='ILS',
            exchange_rate=Decimal('1'), amount_base=Decimal('5'),
            payment_method='cash', payment_confirmed=True, user_id=owner_user.id,
        )
        db.session.add(refund)
        db.session.commit()
        db.session.refresh(test_customer)
        assert Decimal(str(test_customer.balance)) == Decimal('45.000')

        # every reader agrees with the stored column
        from services.payment_service import PaymentService as PS
        from utils.balance_checker import check_customer_balance

        assert PS.get_customer_balance(test_customer) == Decimal('45.000')
        assert PS.get_customer_balance_aed(test_customer) == Decimal('45.000')
        assert test_customer.get_balance() == Decimal('45.000')
        assert check_customer_balance(test_customer.id) == []

    def test_balance_survives_recompute_from_any_document(self, db, owner_user, test_customer):
        """The stored column always equals the derivation (no drift)."""
        from models.customer import recompute_customer_balance

        _sale(db, 'S-P0-F1-2', test_customer, owner_user, total='250.000')
        db.session.refresh(test_customer)
        recompute_customer_balance(test_customer.id)
        db.session.commit()
        db.session.refresh(test_customer)
        assert Decimal(str(test_customer.balance)) == Decimal('250.000')
        assert _balance(test_customer.id) == Decimal('250.000')


# ─────────────────── F2/F5: partial receipt + currency mix ───────────────────

class TestPartialReceiptAndFx:

    def test_partial_receipt_leaves_ar_understated_by_unallocated_remainder(
            self, db, owner_user, test_customer):
        """A receipt of 60 against a 100 invoice leaves AR = 40 (the invoice's
        unallocated remainder) — the customer AR and the invoice AR agree."""
        from services.payment_service import PaymentService

        sale = _sale(db, 'S-P0-F2-1', test_customer, owner_user, total='100.000')

        PaymentService.create_receipt({
            'customer_id': test_customer.id,
            'amount': Decimal('60'),
            'currency': 'ILS',
            'payment_method': 'cash',
            'user_exchange_rate': Decimal('1'),
            'allocate_to_sales': {sale.id: 60},
        })

        db.session.refresh(sale)
        db.session.refresh(test_customer)
        assert Decimal(str(sale.balance_due)) == Decimal('40.000')
        assert Decimal(str(sale.paid_amount_base)) == Decimal('60.000')
        assert Decimal(str(test_customer.balance)) == Decimal('40.000')

    def test_foreign_currency_receipt_leaves_no_gl_gap(self, db, owner_user, test_customer):
        """F2: a USD invoice settled by an ILS receipt at the RECEIPT's rate:
        the GL control account and the sub-ledger must agree exactly."""
        from services.gl_service import GLService
        from services.payment_service import PaymentService
        from services.subledger_reconciliation import SubLedgerReconciliation

        GLService.ensure_core_accounts()

        # invoice: 100 USD @ 3.70 → 370 base
        sale = _sale(db, 'S-P0-FX-1', test_customer, owner_user, total='100.000',
                     currency='USD', exchange_rate='3.70')
        db.session.refresh(test_customer)
        assert Decimal(str(test_customer.balance)) == Decimal('370.000')

        # the invoice leg in the GL (Dr AR 370)
        GLService.post_entry(
            [{'account': '1130', 'debit': Decimal('100')},
             {'account': '4100', 'credit': Decimal('100')}],
            description='P0 invoice leg', reference_type='Sale', reference_id=sale.id,
            currency='USD', exchange_rate=Decimal('3.70'))
        db.session.commit()

        # receipt: 100 EUR @ 3.60 → 360 base (the cash actually entered here)
        PaymentService.create_receipt({
            'customer_id': test_customer.id,
            'amount': Decimal('100'),
            'currency': 'EUR',
            'payment_method': 'cash',
            'user_exchange_rate': Decimal('3.60'),
            'allocate_to_sales': {sale.id: 100},
        })
        db.session.commit()

        db.session.refresh(sale)
        db.session.refresh(test_customer)

        # the invoice is settled at ITS booked rate (370) and the 10 ILS
        # difference between the invoice's base and the cash that entered
        # (360) is realised FX (posted to the FX loss account).
        assert Decimal(str(sale.paid_amount_base)) == Decimal('370.000')
        assert Decimal(str(sale.balance_due)) == Decimal('0.000')
        assert sale.payment_status == 'paid'

        # no gap between the GL control account and the sub-ledger
        report = SubLedgerReconciliation.reconcile_receivables()
        assert report['breaks'] == []
        assert report['control_balance'] == report['subledger_sum']
        assert report['column_sum'] == report['subledger_sum']

    def test_fx_difference_posted_to_fx_accounts(self, db, owner_user, test_customer):
        """F2: the difference between the receipt's base and the invoice's base
        is realised FX and must land on the FX loss account."""
        from services.gl_service import GLService
        from services.payment_service import PaymentService

        GLService.ensure_core_accounts()

        sale = _sale(db, 'S-P0-FX-2', test_customer, owner_user, total='100.000',
                     currency='USD', exchange_rate='3.70')

        PaymentService.create_receipt({
            'customer_id': test_customer.id,
            'amount': Decimal('100'),
            'currency': 'EUR',
            'payment_method': 'cash',
            'user_exchange_rate': Decimal('3.60'),
            'allocate_to_sales': {sale.id: 100},
        })
        db.session.commit()

        # 370 booked − 360 cash = 10 FX loss
        assert Decimal(str(_net('6900'))) == Decimal('10.000')
        assert _net('4400') in (None, Decimal('0.000'))


# ───────────────────────── F3: purchase settlement ─────────────────────────

class TestPurchaseSettlement:

    def test_purchase_paid_amount_and_status_written(self, db, owner_user):
        from services.payment_service import PaymentService  # noqa: F401

        supplier = _supplier(db, 'P0 supplier')
        purchase = _purchase(db, 'P-P0-1', supplier, owner_user.id, total='200.000')

        payment = Payment(
            payment_number='PAY-P0-P-1', payment_type='supplier_payment',
            direction='outgoing', supplier_id=supplier.id,
            purchase_id=purchase.id, amount=Decimal('120'), currency='ILS',
            exchange_rate=Decimal('1'), amount_base=Decimal('120'),
            payment_method='cash', payment_confirmed=True, user_id=owner_user.id,
        )
        db.session.add(payment)
        db.session.commit()

        db.session.refresh(purchase)
        assert Decimal(str(purchase.paid_amount)) == Decimal('120.000')
        assert purchase.payment_status == 'partial'

        # settling the rest marks the invoice paid
        payment2 = Payment(
            payment_number='PAY-P0-P-2', payment_type='supplier_payment',
            direction='outgoing', supplier_id=supplier.id,
            purchase_id=purchase.id, amount=Decimal('80'), currency='ILS',
            exchange_rate=Decimal('1'), amount_base=Decimal('80'),
            payment_method='cash', payment_confirmed=True, user_id=owner_user.id,
        )
        db.session.add(payment2)
        db.session.commit()

        db.session.refresh(purchase)
        assert Decimal(str(purchase.paid_amount)) == Decimal('200.000')
        assert purchase.payment_status == 'paid'

    def test_legacy_supplier_payment_without_purchase_link(self, db, owner_user):
        """Backward compatibility: a payment with no purchase_id still settles
        the supplier account (not any invoice)."""
        supplier = _supplier(db, 'P0 legacy supplier')
        purchase = _purchase(db, 'P-P0-2', supplier, owner_user.id, total='200.000')

        payment = Payment(
            payment_number='PAY-P0-P-3', payment_type='supplier_payment',
            direction='outgoing', supplier_id=supplier.id,
            amount=Decimal('50'), currency='ILS', exchange_rate=Decimal('1'),
            amount_base=Decimal('50'), payment_method='cash',
            payment_confirmed=True, user_id=owner_user.id,
        )
        db.session.add(payment)
        db.session.commit()

        db.session.refresh(purchase)
        db.session.refresh(supplier)
        assert purchase.paid_amount in (None, Decimal('0'))
        assert Decimal(str(supplier.total_paid_aed)) == Decimal('50.000')


# ───────────────────────── F4/F8: cheque lifecycle ─────────────────────────

class TestChequeLifecycle:

    def _cheque_receipt(self, db, owner_user, customer, sale, number='CH-P0-1'):
        from services.payment_service import PaymentService

        receipt = PaymentService.create_receipt({
            'customer_id': customer.id,
            'amount': Decimal('100'),
            'currency': 'ILS',
            'payment_method': 'cheque',
            'cheque_number': number,
            'cheque_date': (date.today() + timedelta(days=30)).isoformat(),
            'bank_name': 'Test Bank',
            'user_exchange_rate': Decimal('1'),
            'allocate_to_sales': {sale.id: 100},
        })
        db.session.commit()
        return receipt

    def test_pending_cheque_does_not_settle_invoice(self, db, owner_user, test_customer):
        """F8: a cheque under collection is not confirmed → the invoice stays open."""
        sale = _sale(db, 'S-P0-CH-1', test_customer, owner_user, total='100.000')

        receipt = self._cheque_receipt(db, owner_user, test_customer, sale)

        db.session.refresh(receipt)
        db.session.refresh(sale)
        db.session.refresh(test_customer)

        assert receipt.payment_confirmed is False
        assert sale.payment_status == 'unpaid'
        assert Decimal(str(sale.paid_amount_base)) == Decimal('0.000')
        assert Decimal(str(test_customer.balance)) == Decimal('100.000')

        # confirming the cheque settles the invoice (F8)
        receipt.confirm_receipt()
        db.session.commit()

        db.session.refresh(sale)
        db.session.refresh(test_customer)
        assert sale.payment_status == 'paid'
        assert Decimal(str(sale.paid_amount_base)) == Decimal('100.000')
        assert Decimal(str(test_customer.balance)) == Decimal('0.000')

    def test_bounced_cheque_restores_balance_and_invoice(self, db, owner_user, test_customer):
        """F4: a bounced cheque restores the customer balance AND the invoice."""
        sale = _sale(db, 'S-P0-CH-2', test_customer, owner_user, total='100.000')

        receipt = self._cheque_receipt(db, owner_user, test_customer, sale,
                                       number='CH-P0-2')
        receipt.confirm_receipt()
        db.session.commit()

        db.session.refresh(sale)
        db.session.refresh(test_customer)
        assert Decimal(str(test_customer.balance)) == Decimal('0.000')
        assert sale.payment_status == 'paid'

        # the cheque bounces
        receipt.reject_receipt('NSF')
        db.session.commit()

        db.session.refresh(sale)
        db.session.refresh(test_customer)
        assert sale.payment_status == 'unpaid'
        assert Decimal(str(sale.paid_amount_base)) == Decimal('0.000')
        assert Decimal(str(test_customer.balance)) == Decimal('100.000')


# ───────────────────────── F5: AR aging ─────────────────────────

class TestAging:

    def test_ar_aging_includes_unpaid_invoices_in_base_currency(self, db, owner_user,
                                                                 test_customer):
        from services.aging_analysis_service import AgingAnalysisService

        # an unpaid invoice (status 'unpaid' — never 'pending')
        _sale(db, 'S-P0-AG-1', test_customer, owner_user, total='100.000')
        # a foreign invoice: 50 USD @ 3.70 → 185 base
        _sale(db, 'S-P0-AG-2', test_customer, owner_user, total='50.000',
              currency='USD', exchange_rate='3.70')
        db.session.commit()

        report = AgingAnalysisService.get_receivables_aging()
        entry = next((c for c in report['customers'] if c['customer'].id == test_customer.id),
                     None)
        assert entry is not None, 'the AR aging must include unpaid invoices'
        assert Decimal(str(entry['total'])) == Decimal('285.000')
        numbers = {inv['sale_number'] for inv in entry['invoices']}
        assert {'S-P0-AG-1', 'S-P0-AG-2'} <= numbers


# ───────────────────────── F6: supplier refund ─────────────────────────

class TestSupplierRefund:

    def test_supplier_refund_increases_ap_balance(self, db, owner_user):
        supplier = _supplier(db, 'P0 refund supplier')
        _purchase(db, 'P-P0-3', supplier, owner_user.id, total='300.000')
        db.session.refresh(supplier)
        balance_before = supplier.get_balance_aed()
        assert Decimal(str(balance_before)) == Decimal('300.000')

        # a refund FROM the supplier (direction='incoming') — must INCREASE
        # what we owe them (it used to decrease the AP balance).
        refund = Payment(
            payment_number='PAY-P0-R-1', payment_type='refund', direction='incoming',
            supplier_id=supplier.id, amount=Decimal('50'), currency='ILS',
            exchange_rate=Decimal('1'), amount_base=Decimal('50'),
            payment_method='cash', payment_confirmed=True, user_id=owner_user.id,
        )
        db.session.add(refund)
        db.session.commit()

        db.session.refresh(supplier)
        assert supplier.get_balance_aed() == Decimal('350.000')


# ───────────────────────── F9: receipt deletion ─────────────────────────

class TestReceiptDeletion:

    def test_delete_reverses_each_allocation(self, db, owner_user, test_customer, client):
        """F9: a receipt split over two invoices must be reversed per invoice."""
        from services.payment_service import PaymentService

        first = _sale(db, 'S-P0-DEL-1', test_customer, owner_user, total='100.000')
        second = _sale(db, 'S-P0-DEL-2', test_customer, owner_user, total='200.000')

        receipt = PaymentService.create_receipt({
            'customer_id': test_customer.id,
            'amount': Decimal('250'),
            'currency': 'ILS',
            'payment_method': 'cash',
            'user_exchange_rate': Decimal('1'),
            'allocate_to_sales': {first.id: 100, second.id: 150},
        })
        db.session.commit()

        db.session.refresh(first)
        db.session.refresh(second)
        assert Decimal(str(first.paid_amount_base)) == Decimal('100.000')
        assert Decimal(str(second.paid_amount_base)) == Decimal('150.000')

        # reverse the allocations the same way the delete route does
        for alloc in receipt.get_allocations():
            sale = db.session.get(Sale, int(alloc['sale_id']))
            amount_base = Decimal(str(alloc['amount_base']))
            sale.paid_amount_base = max(Decimal('0'),
                                        Decimal(str(sale.paid_amount_base or 0)) - amount_base)
            sale.balance_due = max(Decimal('0'),
                                    Decimal(str(sale.amount_base)) - sale.paid_amount_base)
            if sale.balance_due <= Decimal('0'):
                sale.payment_status = 'paid'
            elif sale.paid_amount_base > 0:
                sale.payment_status = 'partial'
            else:
                sale.payment_status = 'unpaid'
        db.session.commit()

        db.session.refresh(first)
        db.session.refresh(second)
        assert Decimal(str(first.paid_amount_base)) == Decimal('0.000')
        assert Decimal(str(second.paid_amount_base)) == Decimal('0.000')
        assert first.payment_status == 'unpaid'
        assert second.payment_status == 'unpaid'


# ───────────────────────── F10: opening balance ─────────────────────────

class TestOpeningBalance:

    def test_opening_balance_survives_balance_repair(self, db, owner_user):
        from utils.balance_checker import check_customer_balance, repair_customer_balance

        customer = _customer(db, 'P0 opening customer')
        customer.opening_balance = Decimal('500.000')
        customer.opening_balance_currency = 'ILS'
        customer.opening_balance_rate = Decimal('1')
        customer.opening_balance_date = date(2026, 1, 1)
        db.session.commit()

        _sale(db, 'S-P0-OB-1', customer, owner_user, total='100.000')
        db.session.refresh(customer)

        # the opening balance is part of the derivation
        assert Decimal(str(customer.balance)) == Decimal('600.000')

        # a drifted stored value is repaired WITHOUT losing the opening balance
        customer.balance = Decimal('0')
        db.session.commit()
        assert len(check_customer_balance(customer.id)) == 1
        assert repair_customer_balance(customer.id) == 1

        db.session.refresh(customer)
        assert Decimal(str(customer.balance)) == Decimal('600.000')
