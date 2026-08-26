"""Unit tests for FX & multi-currency engine — محرك العملات وإعادة التقييم."""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

import services.currency_service as cs_module
from models import Cheque, GLJournalEntry, Purchase, Sale
from services.currency_service import CurrencyService
from services.fx_revaluation import FXRevaluationService


def _uid():
    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# 1) CurrencyService.format_amount — Bidi-safe formatting (pure function)
# ---------------------------------------------------------------------------

class TestFormatAmount:
    def test_basic_format_with_lrm(self):
        out = CurrencyService.format_amount(Decimal('1234.5'), 'ILS')
        assert out == '\u200e1,234.50 ILS'

    def test_negative_amount_keeps_sign(self):
        out = CurrencyService.format_amount(Decimal('-987.654'), 'usd')
        assert out == '\u200e-987.65 USD'

    def test_float_and_int_inputs_coerced(self):
        assert CurrencyService.format_amount(1234.5, 'ILS') == '\u200e1,234.50 ILS'
        assert CurrencyService.format_amount(42, 'JOD') == '\u200e42.00 JOD'

    def test_rounding_half_up_two_places(self):
        assert CurrencyService.format_amount(Decimal('1.005'), 'AED') == '\u200e1.01 AED'
        assert CurrencyService.format_amount(Decimal('1.004'), 'AED') == '\u200e1.00 AED'

    def test_zero_normalizes_negative_zero(self):
        assert CurrencyService.format_amount(Decimal('-0.001'), 'KWD') == '\u200e0.00 KWD'

    def test_custom_decimal_places_zero(self):
        assert CurrencyService.format_amount(Decimal('1234.5'), 'SAR', decimal_places=0) == '\u200e1,235 SAR'

    def test_large_value_grouping_of_three(self):
        out = CurrencyService.format_amount(Decimal('1234567.891'), 'EUR')
        assert out == '\u200e1,234,567.89 EUR'

    def test_bidi_safety_western_digits_only(self):
        out = CurrencyService.format_amount('78900.25', 'QAR')
        assert out.startswith('\u200e')
        digits = ''.join(ch for ch in out if ch.isdigit())
        assert digits == '7890025'
        assert all(ord(ch) < 128 for ch in digits)

    @pytest.mark.parametrize('amount,currency', [(None, 'ILS'), (Decimal('1'), None),
                                                 (Decimal('1'), '   '), ('abc', 'ILS')])
    def test_invalid_inputs_raise(self, amount, currency):
        with pytest.raises(ValueError):
            CurrencyService.format_amount(amount, currency)


# ---------------------------------------------------------------------------
# 2) Rate pipeline consistency — quantization + cache safety
# ---------------------------------------------------------------------------

class _FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _clear_cache():
    CurrencyService._rates_cache.clear()
    yield
    CurrencyService._rates_cache.clear()


class TestRatePipelineConsistency:
    def test_live_api_rates_quantized_to_six_places(self, monkeypatch):
        monkeypatch.setattr(cs_module.requests, 'get',
                            lambda url, timeout=5: _FakeResp({'rates': {'usd': '3.7'}}))
        rates = CurrencyService.get_all_rates(base='ILS')
        assert rates['USD'] == Decimal('3.7')
        assert rates['USD'].as_tuple().exponent == -6

    def test_forex_source_rates_quantized(self, monkeypatch):
        class FakeRates:
            def get_rates(self, base):
                return {'USD': 0.27}

        monkeypatch.setattr(cs_module.requests, 'get',
                            lambda url, timeout=5: _FakeResp({}, status=500))
        monkeypatch.setattr(cs_module, 'FOREX_AVAILABLE', True)
        monkeypatch.setattr(cs_module, 'CurrencyRates', FakeRates, raising=False)
        rates = CurrencyService.get_all_rates(base='ILS')
        assert rates['USD'].as_tuple().exponent == -6

    def test_returned_table_is_a_copy_not_cached_dict(self, monkeypatch):
        monkeypatch.setattr(cs_module, 'REQUESTS_AVAILABLE', False)
        monkeypatch.setattr(cs_module, 'FOREX_AVAILABLE', False)
        first = CurrencyService.get_all_rates(base='USD')
        first['ILS'] = Decimal('999')
        second = CurrencyService.get_all_rates(base='USD')
        assert second['ILS'] != Decimal('999')


# ---------------------------------------------------------------------------
# 3) Cheque FX lifecycle — sign conventions pinned
# ---------------------------------------------------------------------------

def _fx_cheque(db, cheque_type='incoming', amount=Decimal('100'), rate=Decimal('3.6')):
    ch = Cheque(
        cheque_number=f'CH-FX-{_uid()}', cheque_bank_number=_uid(),
        cheque_type=cheque_type, bank_name='ADCB',
        amount=amount, currency='USD', exchange_rate=rate,
        issue_date=datetime.now(timezone.utc).date() - timedelta(days=5),
        due_date=datetime.now(timezone.utc).date() + timedelta(days=20),
        status='deposited',
    )
    ch.calculate_amount_base()
    db.session.add(ch)
    db.session.commit()
    return ch


def _clearing_lines(ch):
    entry = GLJournalEntry.query.get(ch.gl_clearing_entry_id)
    return entry, list(entry.lines)


class TestChequeFxSignMatrix:
    def test_incoming_appreciation_is_gain_credit_fx_gain(self, db, owner_user):
        ch = _fx_cheque(db, 'incoming')  # booked 100*3.6 = 360
        ch.clear_cheque(clearance_exchange_rate=3.7)
        _, lines = _clearing_lines(ch)
        fx = next(ln for ln in lines if ln.account.code == '4400')
        assert ch.currency_gain_loss == Decimal('10.00')
        assert fx.credit == Decimal('10.00') and fx.debit == 0
        assert abs(sum(ln.debit for ln in lines) - sum(ln.credit for ln in lines)) <= Decimal('0.0001')

    def test_incoming_depreciation_is_loss_debit_fx_loss(self, db, owner_user):
        ch = _fx_cheque(db, 'incoming')
        ch.clear_cheque(clearance_exchange_rate=3.5)
        _, lines = _clearing_lines(ch)
        fx = next(ln for ln in lines if ln.account.code == '6900')
        assert ch.currency_gain_loss == Decimal('-10.00')
        assert fx.debit == Decimal('10.00') and fx.credit == 0

    def test_outgoing_appreciation_is_loss_debit_fx_loss(self, db, owner_user):
        ch = _fx_cheque(db, 'outgoing')  # liability booked 360; pays 370 cash
        ch.clear_cheque(clearance_exchange_rate=3.7)
        _, lines = _clearing_lines(ch)
        fx = next(ln for ln in lines if ln.account.code == '6900')
        assert ch.currency_gain_loss == Decimal('10.00')
        assert fx.debit == Decimal('10.00') and fx.credit == 0
        bank = next(ln for ln in lines if ln.account.code == '1120')
        assert bank.credit == Decimal('370.00')

    def test_outgoing_depreciation_is_gain_credit_fx_gain(self, db, owner_user):
        ch = _fx_cheque(db, 'outgoing')  # liability booked 360; pays 350 cash
        ch.clear_cheque(clearance_exchange_rate=3.5)
        _, lines = _clearing_lines(ch)
        fx = next(ln for ln in lines if ln.account.code == '4400')
        assert ch.currency_gain_loss == Decimal('-10.00')
        assert fx.credit == Decimal('10.00') and fx.debit == 0

    def test_immaterial_delta_posts_no_fx_line(self, db, owner_user):
        ch = _fx_cheque(db, 'incoming')
        ch.clear_cheque(clearance_exchange_rate=3.60003)  # rounds to same cent
        _, lines = _clearing_lines(ch)
        assert {ln.account.code for ln in lines} == {'1120', '1150'}
        assert ch.currency_gain_loss == Decimal('0.00')

    def test_nonpositive_explicit_rate_rejected_without_state_change(self, db, owner_user):
        ch = _fx_cheque(db, 'incoming')
        for bad in (0, -3.7):
            with pytest.raises(ValueError, match='clearance'):
                ch.clear_cheque(clearance_exchange_rate=bad)
        assert ch.status == 'deposited'
        assert ch.actual_amount_base is None

    def test_missing_amount_base_self_heals_before_gain_math(self, db, owner_user):
        ch = Cheque(
            cheque_number=f'CH-FX-{_uid()}', cheque_bank_number=_uid(),
            cheque_type='incoming', bank_name='ADCB', amount=Decimal('100'),
            currency='USD', exchange_rate=Decimal('3.6'),
            issue_date=datetime.now(timezone.utc).date(),
            due_date=datetime.now(timezone.utc).date() + timedelta(days=10),
            status='deposited',
        )
        db.session.add(ch)
        db.session.commit()
        assert ch.amount_base is None
        ch.clear_cheque(clearance_exchange_rate=3.7)
        assert ch.amount_base == Decimal('360.00')
        assert ch.currency_gain_loss == Decimal('10.00')

    def test_clear_links_gl_clearing_entry_id(self, db, owner_user):
        ch = _fx_cheque(db, 'incoming')
        assert ch.gl_clearing_entry_id is None
        ch.clear_cheque(clearance_exchange_rate=3.7)
        assert ch.gl_clearing_entry_id is not None
        entry = GLJournalEntry.query.get(ch.gl_clearing_entry_id)
        assert entry.reference_type == 'cheque_clear'


# ---------------------------------------------------------------------------
# 4) FXRevaluationService — month-end unrealized revaluation
# ---------------------------------------------------------------------------


def _naive_utc(days_offset=0):
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=days_offset)


def _make_sale(db, customer, currency='USD', total=Decimal('1000'),
               rate=Decimal('3.6'), paid=Decimal('0'), status='confirmed'):
    sale = Sale(
        sale_number=f'S-FX-{_uid()}', customer_id=customer.id,
        total_amount=total, amount_base=(total * rate).quantize(Decimal('0.001')),
        paid_amount=paid, paid_amount_base=(paid * rate).quantize(Decimal('0.001')),
        balance_due=total - paid, currency=currency, exchange_rate=rate,
        payment_status='unpaid', status=status, is_active=True,
    )
    db.session.add(sale)
    db.session.commit()
    return sale


def _make_purchase(db, owner_user, currency='USD', total=Decimal('1000'),
                   rate=Decimal('3.5'), paid=Decimal('0'), status='confirmed'):
    purchase = Purchase(
        purchase_number=f'P-FX-{_uid()}', supplier_name='مورد أجنبي',
        total_amount=total, amount_base=(total * rate).quantize(Decimal('0.001')),
        paid_amount=paid, currency=currency, exchange_rate=rate,
        payment_status='pending', status=status, user_id=owner_user.id,
    )
    db.session.add(purchase)
    db.session.commit()
    return purchase


@pytest.fixture
def usd_sale(db, test_customer):
    return _make_sale(db, test_customer)


@pytest.fixture
def usd_purchase(db, owner_user):
    return _make_purchase(db, owner_user, paid=Decimal('200'))


class TestCollectOpenBalances:
    def test_ar_groups_foreign_only_excludes_base_cancelled_paid(
            self, db, test_customer, usd_sale):
        _make_sale(db, test_customer, currency='ILS', rate=Decimal('1'))
        _make_sale(db, test_customer, status='cancelled')
        _make_sale(db, test_customer, paid=Decimal('1000'))  # fully settled

        balances = FXRevaluationService.collect_open_ar_balances()
        assert set(balances) == {'USD'}
        assert balances['USD']['foreign'] == Decimal('1000.00')
        assert balances['USD']['historical_base'] == Decimal('3600.00')

    def test_ap_prorates_paid_portion_at_historical_rate(self, db, owner_user, usd_purchase):
        balances = FXRevaluationService.collect_open_ap_balances()
        assert balances['USD']['foreign'] == Decimal('800.00')
        assert balances['USD']['historical_base'] == Decimal('2800.00')

    def test_as_of_filters_future_documents(self, db, test_customer, usd_sale):
        assert FXRevaluationService.collect_open_ar_balances(as_of=_naive_utc(-1)) == {}
        balances = FXRevaluationService.collect_open_ar_balances(as_of=_naive_utc(1))
        assert set(balances) == {'USD'}


class TestBuildRevaluationDraft:
    def test_default_dry_run_posts_nothing(self, db, owner_user, usd_sale):
        before = GLJournalEntry.query.count()
        draft = FXRevaluationService.build_revaluation(rates={'USD': Decimal('3.7')})
        assert draft['dry_run'] is True
        assert draft['journal_entry_id'] is None
        assert GLJournalEntry.query.count() == before

    def test_required_per_currency_keys_present(self, db, owner_user, usd_sale):
        draft = FXRevaluationService.build_revaluation(rates={'USD': Decimal('3.7')})
        row = draft['per_currency'][0]
        for key in ('historical_base', 'current_rate', 'current_base', 'unrealized_gain_loss'):
            assert key in row
        assert row['currency'] == 'USD'
        assert row['current_rate'] == Decimal('3.7')

    def test_ar_appreciation_dr_ar_cr_fx_gain(self, db, owner_user, usd_sale):
        draft = FXRevaluationService.build_revaluation(rates={'USD': Decimal('3.7')})
        assert draft['balanced'] is True
        assert draft['per_currency'][0]['unrealized_gain_loss'] == Decimal('100.00')
        dr_ar = next(ln for ln in draft['lines']
                     if ln['account_role'] == 'AR_CONTROL' and ln['debit'] > 0)
        cr_gain = next(ln for ln in draft['lines'] if ln['account_role'] == 'FX_GAIN')
        assert dr_ar['debit'] == Decimal('100.00')
        assert cr_gain['credit'] == Decimal('100.00')

    def test_ar_depreciation_dr_fx_loss_cr_ar(self, db, owner_user, usd_sale):
        draft = FXRevaluationService.build_revaluation(rates={'USD': Decimal('3.5')})
        assert draft['per_currency'][0]['unrealized_gain_loss'] == Decimal('-100.00')
        cr_ar = next(ln for ln in draft['lines']
                     if ln['account_role'] == 'AR_CONTROL' and ln['credit'] > 0)
        dr_loss = next(ln for ln in draft['lines'] if ln['account_role'] == 'FX_LOSS')
        assert cr_ar['credit'] == Decimal('100.00')
        assert dr_loss['debit'] == Decimal('100.00')

    def test_ap_appreciation_cr_ap_dr_fx_loss(self, db, owner_user):
        _make_purchase(db, owner_user)  # fully open: hist base 3500
        draft = FXRevaluationService.build_revaluation(rates={'USD': Decimal('3.7')})
        assert draft['balanced'] is True
        assert draft['per_currency'][0]['unrealized_gain_loss'] == Decimal('-200.00')
        cr_ap = next(ln for ln in draft['lines']
                     if ln['account_role'] == 'AP_CONTROL' and ln['credit'] > 0)
        dr_loss = next(ln for ln in draft['lines'] if ln['account_role'] == 'FX_LOSS')
        assert cr_ap['credit'] == Decimal('200.00')
        assert dr_loss['debit'] == Decimal('200.00')

    def test_ap_depreciation_dr_ap_cr_fx_gain(self, db, owner_user):
        _make_purchase(db, owner_user)
        draft = FXRevaluationService.build_revaluation(rates={'USD': Decimal('3.3')})
        assert draft['balanced'] is True
        assert draft['per_currency'][0]['unrealized_gain_loss'] == Decimal('200.00')
        dr_ap = next(ln for ln in draft['lines']
                     if ln['account_role'] == 'AP_CONTROL' and ln['debit'] > 0)
        cr_gain = next(ln for ln in draft['lines'] if ln['account_role'] == 'FX_GAIN')
        assert dr_ap['debit'] == Decimal('200.00')
        assert cr_gain['credit'] == Decimal('200.00')

    def test_mixed_ar_and_ap_nets_single_pl_plug(self, db, test_customer, owner_user,
                                                 usd_sale):
        """AR مكسب +100 وAP خسارة -200 → صافي خسارة 100 بسطر P&L واحد."""
        _make_purchase(db, owner_user, paid=Decimal('0'))  # fully open: hist 3500
        draft = FXRevaluationService.build_revaluation(rates={'USD': Decimal('3.7')})
        assert draft['total_unrealized_gain_loss'] == Decimal('-100.00')
        pl_lines = [ln for ln in draft['lines'] if ln['account_role'].startswith('FX_')]
        assert len(pl_lines) == 1
        assert pl_lines[0]['account_role'] == 'FX_LOSS'
        assert pl_lines[0]['debit'] == Decimal('100.00')
        assert draft['balanced'] is True
        assert abs(draft['total_debit'] - draft['total_credit']) <= Decimal('0.0001')

    def test_no_movement_when_rate_unchanged(self, db, owner_user, usd_sale):
        draft = FXRevaluationService.build_revaluation(rates={'USD': Decimal('3.6')})
        assert draft['lines'] == []
        assert draft['total_unrealized_gain_loss'] == Decimal('0.00')

    def test_empty_ledger_yields_empty_draft(self, db, owner_user):
        draft = FXRevaluationService.build_revaluation()
        assert draft['per_currency'] == []
        assert draft['lines'] == []
        assert draft['balanced'] is True

    def test_nonpositive_override_rate_raises(self, db, owner_user, usd_sale):
        with pytest.raises(ValueError, match='override'):
            FXRevaluationService.build_revaluation(rates={'USD': Decimal('0')})


class TestPostRevaluation:
    def test_commit_posts_balanced_entry_with_audit_fields(self, db, owner_user, usd_sale):
        before = GLJournalEntry.query.count()
        result = FXRevaluationService.run_revaluation(
            rates={'USD': Decimal('3.7')}, dry_run=False, created_by=owner_user.id)
        assert result['dry_run'] is False
        assert result['journal_entry_id'] is not None
        assert GLJournalEntry.query.count() == before + 1

        entry = GLJournalEntry.query.get(result['journal_entry_id'])
        assert entry.reference_type == 'fx_revaluation'
        assert entry.created_by == owner_user.id
        assert abs(entry.total_debit - entry.total_credit) <= Decimal('0.0001')
        codes = {ln.account.code for ln in entry.lines}
        assert {'1130', '4400'} <= codes

    def test_commit_with_no_lines_posts_nothing(self, db, owner_user):
        before = GLJournalEntry.query.count()
        result = FXRevaluationService.run_revaluation(dry_run=False, created_by=owner_user.id)
        assert result['journal_entry_id'] is None
        assert GLJournalEntry.query.count() == before
