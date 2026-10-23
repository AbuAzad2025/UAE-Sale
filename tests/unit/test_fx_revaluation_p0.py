"""P0 — تسوية أرصدة العملات الأجنبية (FX revaluation) — اختبارات الوحدة.

تغطي هذه الملف ما كان ناقصاً في المحرك قبل ربطه:

* حساب فرق التسوية لكل عملة على حدة (ذمم مدينة وذمم دائنة).
* توازن القيد المرحَّل: مدين = دائن بعملة الأساس.
* الإشارة: عملة صعدت = ربح (دائن على حساب أرباح العملة)، ونزلت = خسارة
  (مدين على حساب خسائر العملة).
* سطر ربح/خسارة مستقل لكل عملة (لا يلغي ربح عملة خسارة أخرى).
* منع التكرار: تشغيل ثانٍ في نفس الفترة لا يرحّل قيداً ثانياً.
* dry run لا يرحّل شيئاً.
* الفترة المالية المغلقة ترفض الترحيل.
* ربط القيد بالمحرك وقابليته للعكس.
* سجل التدقيق.
* احترام عملة الأساس.
"""
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from extensions import db as _db
from models import AuditLog, GLJournalEntry
from services.fx_revaluation import FXRevaluationService
from utils.errors import ValidationError

BASE = 'ILS'
HIST_RATE = Decimal('3.6')
APPRECIATED = Decimal('3.7')
DEPRECIATED = Decimal('3.5')


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def core_accounts(db):
    """دليل الحسابات الأساسي (مع commit حتى لا يضيع مع أي rollback)."""
    from services.gl_service import GLService

    GLService.ensure_core_accounts()
    _db.session.commit()
    return True


@pytest.fixture
def closed_period(db):
    """فترة مالية سنوية مغلقة تغطي اليوم (تُرجَّح على المفتوحة: fail closed)."""
    from models.erp_modules import FiscalPeriod

    year = date.today().year
    period = FiscalPeriod(
        name=f'SFY {year} (closed)',
        year=year,
        period_type='annual',
        start_date=date(year, 1, 1),
        end_date=date(year, 12, 31),
        is_closed=True,
    )
    _db.session.add(period)
    _db.session.commit()
    return period


@pytest.fixture
def fixed_rates(monkeypatch):
    """أسعار صرف ثابتة بلا شبكة (المهمة المجدولة لا تمرّر أسعاراً)."""
    from services.currency_service import CurrencyService

    def _rate(from_currency, to_currency=None, user_rate=None):
        if user_rate is not None:
            return Decimal(str(user_rate))
        return Decimal('3.7')

    def _all_rates(base=None):
        return {'ILS': Decimal('1'), 'USD': Decimal('0.27'), 'EUR': Decimal('0.25')}

    monkeypatch.setattr(CurrencyService, 'get_exchange_rate', staticmethod(_rate))
    monkeypatch.setattr(CurrencyService, 'get_all_rates', staticmethod(_all_rates))
    return True


def _usd_sale(db, customer, seller_id, total=Decimal('1000'), rate=HIST_RATE,
              paid_base=Decimal('0'), status='confirmed', currency='USD'):
    """فاتورة أجنبية: المبلغ الأساسي = الإجمالي × السعر التاريخي."""
    from models import Sale

    sale = Sale(
        sale_number=f'S-FXP0-{total}-{rate}-{paid_base}-{currency}',
        customer_id=customer.id,
        seller_id=seller_id,
        total_amount=total,
        amount_base=(total * rate).quantize(Decimal('0.001')),
        paid_amount=Decimal('0'),
        paid_amount_base=paid_base,
        balance_due=((total * rate) - paid_base).quantize(Decimal('0.001')),
        currency=currency,
        exchange_rate=rate,
        payment_status='unpaid',
        status=status,
        is_active=True,
    )
    db.session.add(sale)
    db.session.commit()
    return sale


def _usd_purchase(db, owner_user, total=Decimal('1000'), rate=Decimal('3.5'),
                  paid_base=Decimal('0'), status='confirmed'):
    """شراء foreign currency — paid_amount is in base currency (models/purchase.py)."""
    from models import Purchase

    purchase = Purchase(
        purchase_number=f'P-FXP0-{total}-{rate}-{paid_base}',
        supplier_name='مورد أجنبي',
        total_amount=total,
        amount_base=(total * rate).quantize(Decimal('0.001')),
        paid_amount=paid_base,
        currency='USD',
        exchange_rate=rate,
        payment_status='partial' if paid_base else 'unpaid',
        status=status,
        user_id=owner_user.id,
    )
    db.session.add(purchase)
    db.session.commit()
    return purchase


def _lines_by_role(draft):
    """{account_role: [lines]} من مسودة التسوية."""
    grouped = {}
    for line in draft['lines']:
        grouped.setdefault(line['account_role'], []).append(line)
    return grouped


def _entry_lines(entry):
    """{account_code: (debit, credit)} من قيد مرحَّل."""
    out = {}
    for line in entry.lines:
        out[line.account.code] = (Decimal(str(line.debit or 0)),
                                  Decimal(str(line.credit or 0)))
    return out


# ---------------------------------------------------------------------------
# جمع الأرصدة — فصل العملات
# ---------------------------------------------------------------------------

class TestCollectOpenBalances:
    def test_ar_foreign_open_is_derived_from_the_base_carrying(
            self, db, core_accounts, test_customer, owner_user):
        """``Sale.balance_due`` رصيد بعملة الأساس — لا يُعامل كأنه أجنبي."""
        _usd_sale(db, test_customer, owner_user.id)

        balances = FXRevaluationService.collect_open_ar_balances()
        assert set(balances) == {'USD'}
        assert balances['USD']['foreign'] == Decimal('1000.00')
        assert balances['USD']['historical_base'] == Decimal('3600.00')

    def test_ap_paid_amount_is_base_currency(
            self, db, core_accounts, owner_user):
        """``Purchase.paid_amount`` رصيد بالأساس — لا يُطرح من إجمالي أجنبي."""
        _usd_purchase(db, owner_user, paid_base=Decimal('200'))

        balances = FXRevaluationService.collect_open_ap_balances()
        assert balances['USD']['historical_base'] == Decimal('3300.00')
        assert balances['USD']['foreign'] == Decimal('942.86')

    def test_base_currency_and_unconfirmed_rows_are_excluded(
            self, db, core_accounts, test_customer, owner_user):
        _usd_sale(db, test_customer, owner_user.id, currency=BASE)
        _usd_sale(db, test_customer, owner_user.id, status='draft')

        balances = FXRevaluationService.collect_open_ar_balances()
        assert balances == {}

    def test_settled_rows_do_not_reach_the_balances(
            self, db, core_accounts, test_customer, owner_user):
        _usd_sale(db, test_customer, owner_user.id, paid_base=Decimal('3600'))

        balances = FXRevaluationService.collect_open_ar_balances()
        assert balances == {}

    def test_approved_returns_are_deducted_from_the_carrying_amount(
            self, db, core_accounts, test_customer, owner_user):
        """المرتجع المعتمد يُلغي قيمة الفاتورة (نفس models/sale.py:132)."""
        from models.product_return import ProductReturn

        sale = _usd_sale(db, test_customer, owner_user.id)
        ret = ProductReturn(
            return_number='PR-FXP0-1',
            sale_id=sale.id,
            customer_id=test_customer.id,
            total_amount=Decimal('200'),
            refund_amount=Decimal('200'),
            currency='USD',
            exchange_rate=HIST_RATE,
            amount_base=Decimal('720'),
            status='approved',
        )
        db.session.add(ret)
        db.session.commit()

        balances = FXRevaluationService.collect_open_ar_balances()
        assert balances['USD']['historical_base'] == Decimal('2880.00')
        assert balances['USD']['foreign'] == Decimal('800.00')


# ---------------------------------------------------------------------------
# حساب الفروق
# ---------------------------------------------------------------------------

class TestAdjustmentMath:
    def test_ar_appreciation_is_a_gain_on_the_receivable(
            self, db, core_accounts, test_customer, owner_user):
        _usd_sale(db, test_customer, owner_user.id)

        draft = FXRevaluationService.build_revaluation(rates={'USD': APPRECIATED})
        row = draft['per_currency'][0]
        assert row['current_base_ar'] == Decimal('3700.00')
        assert row['historical_base_ar'] == Decimal('3600.00')
        assert row['unrealized_gain_loss'] == Decimal('100.00')

        roles = _lines_by_role(draft)
        assert roles['AR_CONTROL'][0]['debit'] == Decimal('100.00')
        assert roles['FX_GAIN'][0]['credit'] == Decimal('100.00')
        assert roles['FX_GAIN'][0]['debit'] == Decimal('0.00')

    def test_ar_depreciation_is_a_loss_on_the_receivable(
            self, db, core_accounts, test_customer, owner_user):
        _usd_sale(db, test_customer, owner_user.id)

        draft = FXRevaluationService.build_revaluation(rates={'USD': DEPRECIATED})
        assert draft['per_currency'][0]['unrealized_gain_loss'] == Decimal('-100.00')

        roles = _lines_by_role(draft)
        assert roles['AR_CONTROL'][0]['credit'] == Decimal('100.00')
        assert roles['FX_LOSS'][0]['debit'] == Decimal('100.00')
        assert roles['FX_LOSS'][0]['credit'] == Decimal('0.00')

    def test_ap_appreciation_is_a_loss_on_the_payable(
            self, db, core_accounts, owner_user):
        _usd_purchase(db, owner_user)

        draft = FXRevaluationService.build_revaluation(rates={'USD': APPRECIATED})
        row = draft['per_currency'][0]
        assert row['current_base_ap'] == Decimal('3700.00')
        assert row['historical_base_ap'] == Decimal('3500.00')
        assert row['unrealized_gain_loss'] == Decimal('-200.00')

        roles = _lines_by_role(draft)
        assert roles['AP_CONTROL'][0]['credit'] == Decimal('200.00')
        assert roles['FX_LOSS'][0]['debit'] == Decimal('200.00')

    def test_ap_depreciation_is_a_gain_on_the_payable(
            self, db, core_accounts, owner_user):
        _usd_purchase(db, owner_user)

        draft = FXRevaluationService.build_revaluation(rates={'USD': Decimal('3.3')})
        assert draft['per_currency'][0]['unrealized_gain_loss'] == Decimal('200.00')

        roles = _lines_by_role(draft)
        assert roles['AP_CONTROL'][0]['debit'] == Decimal('200.00')
        assert roles['FX_GAIN'][0]['credit'] == Decimal('200.00')

    def test_every_currency_keeps_its_own_pl_line(
            self, db, core_accounts, test_customer, owner_user):
        """ربح عملة لا يُلغى خسارة عملة أخرى."""
        _usd_sale(db, test_customer, owner_user.id)
        from models import Sale

        second = Sale(
            sale_number='S-FXP0-EUR',
            customer_id=test_customer.id,
            seller_id=owner_user.id,
            total_amount=Decimal('1000'),
            amount_base=Decimal('3000'),
            paid_amount=Decimal('0'),
            paid_amount_base=Decimal('0'),
            balance_due=Decimal('3000'),
            currency='EUR',
            exchange_rate=Decimal('3'),
            payment_status='unpaid',
            status='confirmed',
            is_active=True,
        )
        db.session.add(second)
        db.session.commit()

        draft = FXRevaluationService.build_revaluation(
            rates={'USD': APPRECIATED, 'EUR': Decimal('2.9')})

        roles = _lines_by_role(draft)
        assert len(roles['FX_GAIN']) == 1
        assert len(roles['FX_LOSS']) == 1
        assert roles['FX_GAIN'][0]['credit'] == Decimal('100.00')
        assert roles['FX_LOSS'][0]['debit'] == Decimal('100.00')
        assert draft['total_unrealized_gain_loss'] == Decimal('0.00')
        assert draft['balanced'] is True

    def test_draft_is_balanced(self, db, core_accounts, test_customer, owner_user):
        _usd_sale(db, test_customer, owner_user.id)
        _usd_purchase(db, owner_user)

        draft = FXRevaluationService.build_revaluation(
            rates={'USD': APPRECIATED})
        assert draft['balanced'] is True
        assert draft['total_debit'] == draft['total_credit']

    def test_unchanged_rate_produces_no_movement(
            self, db, core_accounts, test_customer, owner_user):
        _usd_sale(db, test_customer, owner_user.id)

        draft = FXRevaluationService.build_revaluation(rates={'USD': HIST_RATE})
        assert draft['lines'] == []
        assert draft['total_unrealized_gain_loss'] == Decimal('0.00')


# ---------------------------------------------------------------------------
# الترحيل
# ---------------------------------------------------------------------------

class TestPosting:
    def test_dry_run_posts_nothing(self, db, core_accounts, test_customer, owner_user):
        _usd_sale(db, test_customer, owner_user.id)
        before = GLJournalEntry.query.count()

        result = FXRevaluationService.run_revaluation(
            rates={'USD': APPRECIATED}, dry_run=True)

        assert result['dry_run'] is True
        assert result['journal_entry_id'] is None
        assert GLJournalEntry.query.count() == before

    def test_post_creates_a_balanced_entry_in_the_base_currency(
            self, db, core_accounts, test_customer, owner_user):
        from services.currency_service import CurrencyService

        _usd_sale(db, test_customer, owner_user.id)

        result = FXRevaluationService.run_revaluation(
            rates={'USD': APPRECIATED}, dry_run=False, created_by=owner_user.id)

        assert result['posted'] is True
        assert result['journal_entry_id'] is not None

        entry = _db.session.get(GLJournalEntry, result['journal_entry_id'])
        assert entry.is_posted is True
        assert Decimal(str(entry.total_debit)) == Decimal(str(entry.total_credit))
        assert abs(Decimal(str(entry.total_debit)) - Decimal('100')) < Decimal('0.001')

        # عملة القاعدة في القيد، لا عملة المستند
        assert entry.currency == CurrencyService.get_base_currency()
        assert entry.currency != 'USD'
        assert Decimal(str(entry.exchange_rate)) == Decimal('1')

        codes = _entry_lines(entry)
        assert codes['1130'][0] == Decimal('100.00')
        assert codes['4400'][1] == Decimal('100.00')

    def test_second_run_in_the_same_period_does_not_duplicate(
            self, db, core_accounts, test_customer, owner_user):
        _usd_sale(db, test_customer, owner_user.id)

        first = FXRevaluationService.run_revaluation(
            rates={'USD': APPRECIATED}, dry_run=False, created_by=owner_user.id)
        _db.session.commit()
        assert first['posted'] is True
        count_after_first = GLJournalEntry.query.count()

        second = FXRevaluationService.run_revaluation(
            rates={'USD': APPRECIATED}, dry_run=False, created_by=owner_user.id)

        assert second['posted'] is False
        assert second['already_posted'] is True
        assert second['journal_entry_id'] == first['journal_entry_id']
        assert GLJournalEntry.query.count() == count_after_first

    def test_the_period_is_stored_on_the_entry_reference(
            self, db, core_accounts, test_customer, owner_user):
        _usd_sale(db, test_customer, owner_user.id)

        result = FXRevaluationService.run_revaluation(
            rates={'USD': APPRECIATED}, dry_run=False, created_by=owner_user.id)
        entry = _db.session.get(GLJournalEntry, result['journal_entry_id'])

        assert entry.reference_type == FXRevaluationService.REFERENCE_TYPE
        assert entry.reference_id == FXRevaluationService.reference_id_for(
            result['period_key'])
        assert result['period_key'] in str(entry.notes or '')

    def test_closed_fiscal_period_refuses_the_posting(
            self, db, core_accounts, closed_period, test_customer, owner_user):
        _usd_sale(db, test_customer, owner_user.id)
        before = GLJournalEntry.query.count()

        with pytest.raises(ValidationError):
            FXRevaluationService.run_revaluation(
                rates={'USD': APPRECIATED}, dry_run=False, created_by=owner_user.id)

        _db.session.rollback()
        assert GLJournalEntry.query.count() == before

    def test_the_entry_is_auditable(self, db, core_accounts, test_customer, owner_user):
        _usd_sale(db, test_customer, owner_user.id)

        result = FXRevaluationService.run_revaluation(
            rates={'USD': APPRECIATED}, dry_run=False, created_by=owner_user.id)
        _db.session.commit()

        audit = AuditLog.query.filter_by(
            table_name='gl_journal_entries',
            record_id=result['journal_entry_id'],
            action='create',
        ).first()
        assert audit is not None, 'الترحيل بلا سجل تدقيق'
        assert audit.changes['action'] == 'fx_revaluation'
        assert audit.changes['period_key'] == result['period_key']

    def test_the_entry_is_linked_and_reversible(
            self, db, core_accounts, test_customer, owner_user):
        _usd_sale(db, test_customer, owner_user.id)

        result = FXRevaluationService.run_revaluation(
            rates={'USD': APPRECIATED}, dry_run=False, created_by=owner_user.id)
        entry = _db.session.get(GLJournalEntry, result['journal_entry_id'])

        reversal = FXRevaluationService.reverse_revaluation(
            entry.id, created_by=owner_user.id)
        _db.session.commit()

        assert reversal is not None
        assert reversal.entry_type == 'reversing'
        assert reversal.reversed_entry_id == entry.id
        assert entry.is_reversed is True
        assert reversal.reference_type == FXRevaluationService.REFERENCE_TYPE

        reversed_codes = _entry_lines(reversal)
        assert reversed_codes['1130'][1] == Decimal('100.00')
        assert reversed_codes['4400'][0] == Decimal('100.00')

    def test_nothing_to_revalue_posts_no_entry(
            self, db, core_accounts, owner_user):
        before = GLJournalEntry.query.count()

        result = FXRevaluationService.run_revaluation(
            rates={'USD': APPRECIATED}, dry_run=False, created_by=owner_user.id)

        assert result['journal_entry_id'] is None
        assert result['skip_reason'] == 'nothing_to_revalue'
        assert GLJournalEntry.query.count() == before


# ---------------------------------------------------------------------------
# المهمة المجدولة
# ---------------------------------------------------------------------------

class TestScheduledRevaluation:
    def test_the_beat_schedule_carries_both_controls(self):
        from services.celery_tasks import celery

        schedule = celery.conf.beat_schedule
        assert schedule['fx-revaluation-daily']['task'] == \
            'celery_tasks.run_fx_revaluation'
        assert schedule['subledger-reconciliation-weekly']['task'] == \
            'celery_tasks.run_subledger_reconciliation'

    def test_the_task_posts_once_and_then_skips(
            self, app, db, core_accounts, test_customer, owner_user,
            fixed_rates, monkeypatch):
        from services.celery_tasks import run_fx_revaluation

        monkeypatch.setattr('app.create_app', lambda: app)
        _usd_sale(db, test_customer, owner_user.id)

        first = run_fx_revaluation.run()
        assert first['success'] is True
        assert first['posted'] == 1
        assert GLJournalEntry.query.filter_by(
            reference_type=FXRevaluationService.REFERENCE_TYPE).count() == 1

        second = run_fx_revaluation.run()
        assert second['success'] is True
        assert second['posted'] == 0
        assert second['reports'][0]['reason'] == 'already_posted'
        assert GLJournalEntry.query.filter_by(
            reference_type=FXRevaluationService.REFERENCE_TYPE).count() == 1

    def test_the_task_skips_a_closed_period(
            self, app, db, core_accounts, closed_period, test_customer, owner_user,
            fixed_rates, monkeypatch):
        from services.celery_tasks import run_fx_revaluation

        monkeypatch.setattr('app.create_app', lambda: app)
        _usd_sale(db, test_customer, owner_user.id)

        result = run_fx_revaluation.run()
        assert result['success'] is True
        assert result['posted'] == 0
        assert result['reports'][0]['reason'] == 'period_closed_or_missing'
        assert GLJournalEntry.query.filter_by(
            reference_type=FXRevaluationService.REFERENCE_TYPE).count() == 0

    def test_the_task_never_raises_into_the_scheduler(
            self, app, db, monkeypatch):
        from services.celery_tasks import run_fx_revaluation

        monkeypatch.setattr('app.create_app', lambda: app)

        def _boom():
            raise RuntimeError('boom')

        monkeypatch.setattr('services.celery_tasks._run_per_tenant', _boom)

        result = run_fx_revaluation.run()
        assert result['success'] is False
        assert 'boom' in result['error']

    def test_the_subledger_task_reports_both_sections(
            self, app, db, monkeypatch):
        from services.celery_tasks import run_subledger_reconciliation

        monkeypatch.setattr('app.create_app', lambda: app)

        result = run_subledger_reconciliation.run()
        assert result['success'] is True
        assert {section['section'] for section in result['sections']} == {'AR', 'AP'}
