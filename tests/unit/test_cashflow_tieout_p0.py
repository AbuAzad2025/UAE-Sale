"""اختبارات P0 — مطابقة قائمة التدفقات النقدية مع دفتر الأستاذ.

رصيد النقدية في نهاية الفترة حقيقة تُقرأ من دفتر الأستاذ، لا رقم يُستنتج
من جمع الأقسام. والرقم المحسوب (البداية + صافي التغير) يبقى للمقارنة
فقط، والفرق بين Truth والمحسوب يُعلن ولا يُخفى:

  • F: حالة متوازنة — رصيد الدفتر = الرصيد المحسوب، الفرق صفر.
  • G: حالة مختلفة — الفرق يُعلن (غير صفري) ولا يُخفى.
  • H: المفاتيح التي يستعملها المستهلكون القائمون ما زالت موجودة.
  • I: النسخة القديمة (generate_cash_flow) لا تناقض النسخة القائمة على
    دفتر الأستاذ.
  • J: المبالغ بعملة الأساس لا بعملة المعاملة.
  • K: الفترة المالية محترمة (services/fiscal_period_guard.py).
  • L: صفحة التقارير تُعرض بلا Keys مفقودة.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import insert, select

from models import GLAccount, GLJournalEntry, GLJournalLine
from services.cash_flow_service import CashFlowService
from services.gl_service import GLService

BASE_CURRENCY = 'ILS'

PERIOD_START = date.today() - timedelta(days=7)
PERIOD_END = date.today()

# مفاتيح القائمة التي يستعملها مسار التقارير ومسار دفتر الأستاذ والتصدير.
PUBLIC_KEYS = {
    'period_start',
    'period_end',
    'operating_items',
    'investing_items',
    'financing_items',
    'operating_total',
    'investing_total',
    'financing_total',
    'net_change',
    'cash_beginning',
    'cash_ending',
    'rows',
}

TIE_OUT_KEYS = {'gl_cash_ending', 'computed_ending', 'difference', 'balanced'}


@pytest.fixture
def chart_of_accounts(db):
    """شجرة الحسابات الأساسية + فترة مالية مفتوحة."""
    GLService.ensure_core_accounts()
    db.session.commit()
    return {acc.code: acc for acc in GLAccount.query.all()}


def _post(lines, entry_date=None, description='tie-out test',
          currency=BASE_CURRENCY, exchange_rate=Decimal('1')):
    return GLService.post_entry(
        lines,
        description=description,
        currency=currency,
        exchange_rate=exchange_rate,
        reference_type='manual',
        entry_date=entry_date or datetime.combine(PERIOD_START, datetime.min.time()),
    )


def _post_unbalanced_cash_entry(db, account_code, amount, entry_date):
    """قيد نقدي بلا مقابل — دفتر تالف لا تستطيع قيود الخدمة إنشاؤه.

    حارس التوازن (models/events.py) يرفض أي قيد غير متوازن عبر ORM، لكن
    استيراداً مباشراً (SQL/ترحيل) قد يترك حركة بلا مقابل. لذلك تُكتب
    السطور مباشرةً (Core insert) لتجاوز مستمعات ORM — والهدف هنا أن
    القائمة تعلن الفرق بدل ابتلاعه.
    """
    account = GLAccount.query.filter_by(code=account_code).first()
    number = f'CORRUPT-{uuid4().hex[:12]}'
    now = datetime.now()

    db.session.execute(
        insert(GLJournalEntry.__table__).values(
            entry_number=number,
            entry_date=entry_date,
            description='truncated cash movement',
            reference_type='manual',
            entry_type='manual',
            currency=BASE_CURRENCY,
            exchange_rate=Decimal('1'),
            total_debit=amount,
            total_credit=Decimal('0'),
            is_posted=True,
            created_at=now,
            updated_at=now,
        )
    )
    entry_id = db.session.execute(
        select(GLJournalEntry.__table__.c.id).where(
            GLJournalEntry.__table__.c.entry_number == number)
    ).scalar_one()
    db.session.execute(
        insert(GLJournalLine.__table__).values(
            entry_id=entry_id,
            account_id=account.id,
            description='truncated',
            debit=amount,
            credit=Decimal('0'),
            amount_base=amount,
        )
    )
    db.session.commit()
    return entry_id


def _in_period():
    return datetime.combine(PERIOD_START, datetime.min.time())


class TestCashFlowTieOut:

    def test_balanced_statement_matches_the_ledger(self, db, chart_of_accounts):
        """F: رصيد الدفتر = الرصيد المحسوب، والفرق صفر."""
        # رصيد افتتاحي قبل الفترة
        _post([
            {'account': '1110', 'debit': Decimal('500'), 'credit': Decimal('0')},
            {'account': '3100', 'debit': Decimal('0'), 'credit': Decimal('500')},
        ], entry_date=datetime.combine(
            PERIOD_START - timedelta(days=30), datetime.min.time()),
            description='opening capital')
        # داخل الفترة: بيع نقدي، صرف رواتب، شراء أصل ثابت
        _post([
            {'account': '1110', 'debit': Decimal('1000'), 'credit': Decimal('0')},
            {'account': '4100', 'debit': Decimal('0'), 'credit': Decimal('1000')},
        ], entry_date=_in_period(), description='cash sale')
        _post([
            {'account': '6100', 'debit': Decimal('200'), 'credit': Decimal('0')},
            {'account': '1110', 'debit': Decimal('0'), 'credit': Decimal('200')},
        ], entry_date=_in_period(), description='salaries paid')
        _post([
            {'account': '1230', 'debit': Decimal('400'), 'credit': Decimal('0')},
            {'account': '1120', 'debit': Decimal('0'), 'credit': Decimal('400')},
        ], entry_date=_in_period(), description='vehicle purchase')
        db.session.commit()

        report = CashFlowService.generate_gl_cash_flow(PERIOD_START, PERIOD_END)

        tie_out = report['tie_out']
        assert set(tie_out) == TIE_OUT_KEYS
        assert tie_out['balanced'] is True
        assert tie_out['difference'] == Decimal('0')
        assert tie_out['gl_cash_ending'] == tie_out['computed_ending']

        # الحقيقة من الدفتر: 500 + 1000 − 200 − 400
        assert report['cash_beginning'] == Decimal('500')
        assert report['cash_ending'] == Decimal('900')
        assert report['cash_ending_computed'] == Decimal('900')
        assert report['cash_ending_computed'] == (
            report['cash_beginning'] + report['net_change'])

        # الأقسام: بيع +1000، رواتب −200، شراء سيارة −400
        assert report['operating_total'] == Decimal('800')
        assert report['investing_total'] == Decimal('-400')
        assert report['financing_total'] == Decimal('0')
        assert report['net_change'] == Decimal('400')

    def test_cash_accounts_are_not_counted_as_sections(self, db, chart_of_accounts):
        """حسابات النقدية موضوع القائمة — لا بنود فيها (وإلا احتُسبت مرتين)."""
        _post([
            {'account': '1110', 'debit': Decimal('1000'), 'credit': Decimal('0')},
            {'account': '4100', 'debit': Decimal('0'), 'credit': Decimal('1000')},
        ], entry_date=_in_period(), description='cash sale')
        db.session.commit()

        report = CashFlowService.generate_gl_cash_flow(PERIOD_START, PERIOD_END)

        all_labels = list(report['operating_items']) + \
            list(report['investing_items']) + list(report['financing_items'])
        assert not any(label.startswith('1110') for label in all_labels)
        assert not any(label.startswith('1120') for label in all_labels)
        # صافي التغير = حركة النقدية نفسها
        assert report['net_change'] == Decimal('1000')
        assert report['cash_ending'] == Decimal('1000')

    def test_divergence_is_reported_not_swallowed(self, db, chart_of_accounts):
        """G: حركة نقدية بلا مقابل — الفرق يُعلن ولا يُخفى."""
        _post([
            {'account': '1110', 'debit': Decimal('1000'), 'credit': Decimal('0')},
            {'account': '4100', 'debit': Decimal('0'), 'credit': Decimal('1000')},
        ], entry_date=_in_period(), description='cash sale')
        # حركة نقدية لا يقابلها حساب: الأقسام لا تستطيع تفسيرها
        _post_unbalanced_cash_entry(
            db, '1110', Decimal('250'),
            datetime.combine(PERIOD_START, datetime.min.time()))
        db.session.commit()

        report = CashFlowService.generate_gl_cash_flow(PERIOD_START, PERIOD_END)

        tie_out = report['tie_out']
        assert tie_out['balanced'] is False
        assert tie_out['difference'] != Decimal('0')
        assert tie_out['difference'] == Decimal('250')
        # الحقيقة من الدفتر تُعرض كما هي (1000 + 250)
        assert report['cash_ending'] == Decimal('1250')
        assert tie_out['gl_cash_ending'] == Decimal('1250')
        # والمحسوب لا يستطيع شرح الحركة — والفرق بينهما معلن
        assert report['cash_ending_computed'] == Decimal('1000')
        assert tie_out['computed_ending'] == Decimal('1000')

    def test_statement_keeps_the_existing_public_keys(self, db, chart_of_accounts):
        """H: المفاتيح التي تستهلكها الصفحات والتصدير ما زالت موجودة."""
        report = CashFlowService.generate_gl_cash_flow(PERIOD_START, PERIOD_END)

        assert PUBLIC_KEYS <= set(report)
        assert {'cash_ending_computed', 'tie_out', 'fiscal_period'} <= set(report)
        assert isinstance(report['rows'], list)

    def test_legacy_implementation_agrees_with_the_ledger_one(self, db, chart_of_accounts):
        """I: النسخة القديمة لا تناقض النسخة القائمة على دفتر الأستاذ."""
        _post([
            {'account': '1120', 'debit': Decimal('1000'), 'credit': Decimal('0')},
            {'account': '3100', 'debit': Decimal('0'), 'credit': Decimal('1000')},
        ], entry_date=datetime.combine(
            PERIOD_START - timedelta(days=30), datetime.min.time()),
            description='opening capital')
        _post([
            {'account': '1110', 'debit': Decimal('500'), 'credit': Decimal('0')},
            {'account': '3100', 'debit': Decimal('0'), 'credit': Decimal('500')},
        ], entry_date=_in_period(), description='capital contribution')
        _post([
            {'account': '3300', 'debit': Decimal('200'), 'credit': Decimal('0')},
            {'account': '1110', 'debit': Decimal('0'), 'credit': Decimal('200')},
        ], entry_date=_in_period(), description='owner draw')
        _post([
            {'account': '1110', 'debit': Decimal('300'), 'credit': Decimal('0')},
            {'account': '2210', 'debit': Decimal('0'), 'credit': Decimal('300')},
        ], entry_date=_in_period(), description='loan received')
        _post([
            {'account': '2210', 'debit': Decimal('100'), 'credit': Decimal('0')},
            {'account': '1120', 'debit': Decimal('0'), 'credit': Decimal('100')},
        ], entry_date=_in_period(), description='loan repaid')
        _post([
            {'account': '1230', 'debit': Decimal('400'), 'credit': Decimal('0')},
            {'account': '1120', 'debit': Decimal('0'), 'credit': Decimal('400')},
        ], entry_date=_in_period(), description='vehicle purchase')
        _post([
            {'account': '6100', 'debit': Decimal('50'), 'credit': Decimal('0')},
            {'account': '1110', 'debit': Decimal('0'), 'credit': Decimal('50')},
        ], entry_date=_in_period(), description='salaries paid')
        db.session.commit()

        gl_report = CashFlowService.generate_gl_cash_flow(PERIOD_START, PERIOD_END)
        legacy = CashFlowService.generate_cash_flow(PERIOD_START, PERIOD_END)

        # رصيد نهاية الفترة في النسختين من دفتر الأستاذ — لا تعارض
        assert legacy['cash_ending'] == float(gl_report['cash_ending'])
        assert legacy['cash_beginning'] == float(gl_report['cash_beginning'])
        assert legacy['tie_out']['gl_cash_ending'] == \
            gl_report['tie_out']['gl_cash_ending']
        assert legacy['tie_out']['balanced'] is True
        assert gl_report['tie_out']['balanced'] is True

        # مفاتيح النسخة القديمة ما زالت كما هي
        assert {'operating_activities', 'investing_activities',
                'financing_activities', 'net_change_in_cash',
                'cash_beginning', 'cash_ending'} <= set(legacy)
        assert legacy['operating_activities']['payments_for_salaries'] == 50.0
        assert legacy['investing_activities']['purchase_of_fixed_assets'] == 400.0
        assert legacy['financing_activities']['capital_contributions'] == 500.0

    def test_amounts_are_in_base_currency(self, db, chart_of_accounts):
        """J: الرصيد بعملة الأساس لا بعملة المعاملة."""
        _post([
            {'account': '1110', 'debit': Decimal('100'), 'credit': Decimal('0')},
            {'account': '4100', 'debit': Decimal('0'), 'credit': Decimal('100')},
        ], entry_date=_in_period(), description='usd sale', currency='USD',
            exchange_rate=Decimal('3.5'))
        db.session.commit()

        report = CashFlowService.generate_gl_cash_flow(PERIOD_START, PERIOD_END)

        assert report['cash_ending'] == Decimal('350')
        assert report['net_change'] == Decimal('350')
        assert report['tie_out']['balanced'] is True

    def test_fiscal_period_is_respected(self, db, chart_of_accounts):
        """K: حالة الفترة المالية تُعلَن، والمدى غير الصالح يُكشف."""
        report = CashFlowService.generate_gl_cash_flow(PERIOD_START, PERIOD_END)
        facts = report['fiscal_period']
        assert facts['range_valid'] is True
        assert facts['defined'] is True
        assert facts['is_open'] is True
        assert facts['is_closed'] is False

        inverted = CashFlowService.generate_gl_cash_flow(PERIOD_END, PERIOD_START)
        assert inverted['fiscal_period']['range_valid'] is False

    def test_ledger_report_carries_the_tie_out(self, db, chart_of_accounts):
        """المطابقة تُنقل إلى صفحة دفتر الأستاذ كما هي."""
        _post([
            {'account': '1110', 'debit': Decimal('1000'), 'credit': Decimal('0')},
            {'account': '4100', 'debit': Decimal('0'), 'credit': Decimal('1000')},
        ], entry_date=_in_period(), description='cash sale')
        db.session.commit()

        gl_report = CashFlowService.generate_gl_cash_flow(PERIOD_START, PERIOD_END)
        ledger_report = CashFlowService.build_ledger_report(gl_report)

        assert ledger_report.cash_ending == float(gl_report['cash_ending'])
        assert ledger_report.cash_ending_computed == \
            float(gl_report['cash_ending_computed'])
        assert ledger_report.tie_out.difference == \
            float(gl_report['tie_out']['difference'])
        assert ledger_report.tie_out.balanced is gl_report['tie_out']['balanced']

    def test_report_page_renders_without_the_new_keys(
            self, client, db, owner_user, login_owner, chart_of_accounts):
        """L: صفحة التقارير تُعرض حتى قبل نقل مفاتيح المطابقة إليها."""
        _post([
            {'account': '1110', 'debit': Decimal('750'), 'credit': Decimal('0')},
            {'account': '4100', 'debit': Decimal('0'), 'credit': Decimal('750')},
        ], entry_date=_in_period(), description='cash sale')
        db.session.commit()

        resp = client.get('/reports/cash-flow')
        assert resp.status_code == 200

    def test_template_shows_the_ledger_balance_and_the_difference(
            self, app, db, owner_user, chart_of_accounts):
        """L: القالب يعرض رصيد الدفتر والمحسوب والفرق plainly."""
        from flask import render_template

        _post([
            {'account': '1110', 'debit': Decimal('750'), 'credit': Decimal('0')},
            {'account': '4100', 'debit': Decimal('0'), 'credit': Decimal('750')},
        ], entry_date=_in_period(), description='cash sale')
        db.session.commit()

        report = CashFlowService.generate_gl_cash_flow(PERIOD_START, PERIOD_END)
        context = {
            'operating_items': report['operating_items'],
            'investing_items': report['investing_items'],
            'financing_items': report['financing_items'],
            'operating_total': report['operating_total'],
            'investing_total': report['investing_total'],
            'financing_total': report['financing_total'],
            'net_change': report['net_change'],
            'date_from': PERIOD_START.isoformat(),
            'date_to': PERIOD_END.isoformat(),
            'report': report,
        }

        with app.test_request_context():
            html = render_template('reports/cash_flow.html', **context)

        assert 'مطابقة رصيد النقدية مع دفتر الأستاذ' in html
        assert 'رصيد النقدية في نهاية الفترة — دفتر الأستاذ' in html
        assert 'مطابق لدفتر الأستاذ' in html
        assert 'id="cash-flow-tie-out-break"' not in html

    def test_template_flags_the_difference(self, app, db, owner_user, chart_of_accounts):
        """L: الفرق يظهر unmistakably — لا يُعرض كصفّ عادي."""
        from flask import render_template

        _post([
            {'account': '1110', 'debit': Decimal('750'), 'credit': Decimal('0')},
            {'account': '4100', 'debit': Decimal('0'), 'credit': Decimal('750')},
        ], entry_date=_in_period(), description='cash sale')
        _post_unbalanced_cash_entry(
            db, '1110', Decimal('250'), _in_period())
        db.session.commit()

        report = CashFlowService.generate_gl_cash_flow(PERIOD_START, PERIOD_END)
        context = {
            'operating_items': report['operating_items'],
            'investing_items': report['investing_items'],
            'financing_items': report['financing_items'],
            'operating_total': report['operating_total'],
            'investing_total': report['investing_total'],
            'financing_total': report['financing_total'],
            'net_change': report['net_change'],
            'date_from': PERIOD_START.isoformat(),
            'date_to': PERIOD_END.isoformat(),
            'report': report,
        }

        with app.test_request_context():
            html = render_template('reports/cash_flow.html', **context)

        assert 'id="cash-flow-tie-out-break"' in html
        assert 'فرق في مطابقة النقدية مع دفتر الأستاذ' in html
        assert 'alert-danger' in html
