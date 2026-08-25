"""Unit tests for AgingAnalysisService + CashFlowService — أعمار الذمم والتدفقات النقدية."""
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from models import Purchase, Receipt, Sale, Supplier
from services.aging_analysis_service import AgingAnalysisService
from services.cash_flow_service import CashFlowService
from services.gl_service import GLService


def _sale(customer_id, total, paid, status, days_ago, num):
    s = Sale(
        sale_number=num,
        customer_id=customer_id,
        total_amount=Decimal(str(total)), amount_base=Decimal(str(total)),
        paid_amount=Decimal(str(paid)), paid_amount_base=Decimal(str(paid)),
        balance_due=Decimal(str(total)) - Decimal(str(paid)),
        currency='AED', exchange_rate=Decimal('1'),
        payment_status=status, status='confirmed', is_active=True,
        sale_date=datetime.now() - timedelta(days=days_ago),
    )
    return s


@pytest.fixture
def aging_customer(db, test_customer):
    """One customer with three invoices across buckets."""
    recent = _sale(test_customer.id, 100, 40, 'partial', 10, 'S-AGE-001')   # bal 60 → 0-30
    mid = _sale(test_customer.id, 200, 0, 'pending', 45, 'S-AGE-002')       # bal 200 → 31-60
    old = _sale(test_customer.id, 300, 0, 'pending', 100, 'S-AGE-003')      # bal 300 → 91-120
    db.session.add_all([recent, mid, old])
    db.session.commit()
    return test_customer


class TestReceivablesAging:
    def test_buckets_and_totals(self, db, test_customer, aging_customer):
        result = AgingAnalysisService.get_receivables_aging()

        assert result['customer_count'] == 1
        t = result['totals']
        assert t['0-30'] == 60.0
        assert t['31-60'] == 200.0
        assert t['91-120'] == 300.0
        assert t['total'] == 560.0

        row = result['customers'][0]
        inv_categories = {i['age_category'] for i in row['invoices']}
        assert {'0-30', '31-60', '91-120'} <= inv_categories

    def test_paid_sales_excluded(self, db, test_customer, aging_customer):
        fully_paid = _sale(test_customer.id, 999, 999, 'paid', 500, 'S-AGE-PAID')
        db.session.add(fully_paid)
        db.session.commit()

        result = AgingAnalysisService.get_receivables_aging()
        numbers = {i['sale_number'] for i in result['customers'][0]['invoices']}
        assert fully_paid.sale_number not in numbers

    def test_inactive_customer_excluded(self, db, test_customer, aging_customer):
        test_customer.is_active = False
        db.session.commit()
        result = AgingAnalysisService.get_receivables_aging()
        assert result['customer_count'] == 0

    def test_as_of_string_date_parsed(self, db, test_customer, aging_customer):
        future = (date.today() + timedelta(days=400)).isoformat()
        result = AgingAnalysisService.get_receivables_aging(as_of_date=future)
        # everything lands in over_120 relative to far-future date? No: days negative → 0-30
        assert result['totals']['total'] == 560.0

    def test_over_120_bucket(self, db, test_customer):
        ancient = _sale(test_customer.id, 150, 0, 'pending', 200, 'S-AGE-OLD')
        db.session.add(ancient)
        db.session.commit()
        result = AgingAnalysisService.get_receivables_aging()
        assert result['totals']['over_120'] == 150.0

    def test_invoice_dated_today_included(self, db, test_customer):
        """انحدار: فاتورة اليوم نفسه يجب ألا تُستبعد بفلتر التاريخ المجرد."""
        today_sale = _sale(test_customer.id, 90, 0, 'pending', 0, 'S-AGE-TODAY')
        db.session.add(today_sale)
        db.session.commit()

        result = AgingAnalysisService.get_receivables_aging(as_of_date=date.today())
        assert result['totals']['total'] == 90.0
        assert result['totals']['0-30'] == 90.0


class TestPayablesAging:
    def test_supplier_buckets(self, db, owner_user):
        supplier = Supplier(name='مورد A', is_active=True)
        db.session.add(supplier)
        db.session.flush()
        p = Purchase(
            purchase_number='P-TEST-001', supplier_name='مورد A',
            supplier_id=supplier.id,
            total_amount=Decimal('500'), amount_base=Decimal('500'),
            paid_amount=Decimal('200'), payment_status='partial',
            purchase_date=datetime.now() - timedelta(days=50),
            currency='ILS', user_id=owner_user.id,
        )
        db.session.add(p)
        db.session.commit()

        result = AgingAnalysisService.get_payables_aging()
        assert result['supplier_count'] == 1
        assert result['totals']['31-60'] == 300.0


# ────────────────────────── Cash Flow ──────────────────────────

PERIOD_START = date.today() - timedelta(days=7)
PERIOD_END = date.today()


def _gl_pair(debit_code, credit_code, amount, entry_date=None):
    GLService.create_manual_entry(
        description='cf-test',
        lines=[
            {'account_code': debit_code, 'debit': amount, 'credit': 0},
            {'account_code': credit_code, 'debit': 0, 'credit': amount},
        ],
        entry_date=datetime.combine(entry_date or date.today(), datetime.min.time()),
    )


@pytest.fixture
def gl_scenario(db):
    # Beginning cash: bank funded before period
    _gl_pair('1120', '3100', 1000, PERIOD_START - timedelta(days=30))
    # Within period: owner adds capital via cash, withdraws, loan flows
    _gl_pair('1110', '3100', 500)              # capital contribution
    _gl_pair('3300', '1110', 200)              # owner withdrawal
    _gl_pair('1110', '2210', 300)              # loan received
    _gl_pair('2210', '1120', 100)              # loan repayment
    # Investing: buy vehicle (1210), sell equipment credit (1250)
    _gl_pair('1210', '1120', 400)
    _gl_pair('1120', '1250', 150)
    # Operating: salary paid from cash
    _gl_pair('6100', '1110', 50)


class TestCashFlow:
    def test_full_statement_math(self, db, gl_scenario):
        cf = CashFlowService.generate_cash_flow(PERIOD_START, PERIOD_END)

        assert cf['operating_activities']['payments_for_salaries'] == 50.0
        assert cf['operating_activities']['net_cash_from_operating'] == -50.0

        inv = cf['investing_activities']
        assert inv['purchase_of_fixed_assets'] == 400.0
        assert inv['sale_of_fixed_assets'] == 150.0
        assert inv['net_cash_from_investing'] == -250.0

        fin = cf['financing_activities']
        assert fin['capital_contributions'] == 500.0
        assert fin['owner_withdrawals'] == 200.0
        assert fin['loans_received'] == 300.0
        assert fin['loan_repayments'] == 100.0
        assert fin['net_cash_from_financing'] == 500.0

        assert cf['net_change_in_cash'] == 200.0
        assert cf['cash_beginning'] == 1000.0
        assert cf['cash_ending'] == 1200.0

    def test_receipts_counted_in_operating(self, db, gl_scenario, test_customer):
        receipt = Receipt(
            receipt_number='RCV-CF-1', source_type='manual', direction='incoming',
            customer_id=test_customer.id, amount=Decimal('250'),
            currency='ILS', exchange_rate=Decimal('1'), amount_base=Decimal('250'),
            payment_method='cash',
        )
        db.session.add(receipt)
        db.session.commit()

        cf = CashFlowService.generate_cash_flow(PERIOD_START, PERIOD_END)
        assert cf['operating_activities']['receipts_from_customers'] == 250.0
        assert cf['net_change_in_cash'] == 450.0

    def test_empty_period_zeroed(self, db):
        cf = CashFlowService.generate_cash_flow(PERIOD_START, PERIOD_END)
        assert cf['cash_beginning'] == 0.0
        assert cf['net_change_in_cash'] == 0.0

    def test_string_dates_accepted(self, db):
        start = PERIOD_START.isoformat()
        end = PERIOD_END.isoformat()
        cf = CashFlowService.generate_cash_flow(start, end)
        assert cf['period_start'] == PERIOD_START
