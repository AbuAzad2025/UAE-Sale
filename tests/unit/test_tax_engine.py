"""Unit tests for services/tax_engine.py (Agent 4).

Covers pure VAT math properties (roundtrips, half-up edges, multi-line
policy), defensive GL liability routing, and numeric parity of the refactored
ReturnService tax-reversal block against the legacy formula fixtures.
"""
import random
import sys
import types
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN
from enum import Enum

import pytest

from models import SaleLine, GLJournalEntry
from services.return_service import ReturnService
from services.tax_engine import TaxEngine, DEFAULT_QUANTUM, to_decimal

RATES = [Decimal('0'), Decimal('5'), Decimal('14'), Decimal('17'), Decimal('15.5')]
MILL = Decimal('0.001')


# --------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------- #
def _legacy_return_tax(net_amount, rate_percent):
    """The pre-refactor formula from services/return_service.py verbatim."""
    net = Decimal(net_amount)
    rate = Decimal(rate_percent) or Decimal('0')
    return (net * (rate / Decimal('100'))).quantize(MILL, rounding=ROUND_HALF_UP)


def _get_sale_line(sale):
    return SaleLine.query.filter_by(sale_id=sale.id).first()


# --------------------------------------------------------------------- #
# Pure math — basic behaviour
# --------------------------------------------------------------------- #
class TestComputeLineTax:
    def test_basic_exclusive_five_percent(self):
        result = TaxEngine.compute_line_tax('100', 5)
        assert result == {
            'net': Decimal('100.000'),
            'tax': Decimal('5.000'),
            'gross': Decimal('105.000'),
        }

    def test_zero_rate_no_tax(self):
        result = TaxEngine.compute_line_tax(250, 0)
        assert result['tax'] == Decimal('0.000')
        assert result['gross'] == result['net'] == Decimal('250.000')

    def test_rates_matrix_on_200(self):
        expected = {0: '0.000', 5: '10.000', 14: '28.000', 17: '34.000', 15.5: '31.000'}
        for rate, tax_str in expected.items():
            result = TaxEngine.compute_line_tax(200, rate)
            assert result['tax'] == Decimal(tax_str), f'rate={rate}'
            assert result['gross'] == result['net'] + result['tax']

    def test_half_up_edge_third_decimal(self):
        # 0.01 @ 5% -> raw 0.0005: HALF_UP must round UP away from zero.
        result = TaxEngine.compute_line_tax('0.01', 5)
        assert result['tax'] == Decimal('0.001')
        assert result['gross'] == Decimal('0.011')

    def test_rounding_parameter_respected(self):
        # 0.03 @ 5% -> raw 0.0015: HALF_UP -> 0.002, ROUND_DOWN -> 0.001.
        half_up = TaxEngine.compute_line_tax('0.03', 5, rounding=ROUND_HALF_UP)
        down = TaxEngine.compute_line_tax('0.03', 5, rounding=ROUND_DOWN)
        assert half_up['tax'] == Decimal('0.002')
        assert down['tax'] == Decimal('0.001')

    def test_quantum_parameter_respected(self):
        two_dp = TaxEngine.compute_line_tax('10.005', 5, quantum=Decimal('0.01'))
        assert two_dp['tax'] == Decimal('0.50')
        three_dp = TaxEngine.compute_line_tax('10.005', 5)
        assert three_dp['tax'] == Decimal('0.500')

    def test_inclusive_price_split(self):
        result = TaxEngine.compute_line_tax(105, 5, price_includes_tax=True)
        assert result == {
            'net': Decimal('100.000'),
            'tax': Decimal('5.000'),
            'gross': Decimal('105.000'),
        }

    def test_negative_amount_raises(self):
        with pytest.raises(ValueError):
            TaxEngine.compute_line_tax(-1, 5)

    def test_negative_rate_raises(self):
        with pytest.raises(ValueError):
            TaxEngine.compute_line_tax(100, -0.01)

    def test_invalid_quantum_raises(self):
        with pytest.raises(ValueError):
            TaxEngine.compute_line_tax(100, 5, quantum=Decimal('0'))

    def test_boundary_coercion_from_strings_ints_floats(self):
        a = TaxEngine.compute_line_tax('100', 5)
        b = TaxEngine.compute_line_tax(100, '5')
        c = TaxEngine.compute_line_tax(100.0, 5.0)
        assert a['gross'] == b['gross'] == c['gross'] == Decimal('105.000')
        assert to_decimal('12.345') == Decimal('12.345')

    def test_components_always_sum_exactly(self):
        for rate in RATES:
            for cents in (1, 3, 7, 33, 105, 999):
                amount = Decimal(cents) / 100
                result = TaxEngine.compute_line_tax(amount, rate)
                assert result['net'] + result['tax'] == result['gross']


class TestSplitGross:
    def test_exact_cent_decomposition(self):
        result = TaxEngine.split_gross('105.00', 5)
        assert result == {'net': Decimal('100.00'), 'tax': Decimal('5.00'),
                          'gross': Decimal('105.00')}

    def test_zero_rate(self):
        result = TaxEngine.split_gross(88.88, 0)
        assert result['tax'] == Decimal('0.00')
        assert result['net'] == Decimal('88.88')

    def test_identity_is_exact_for_hundreds_of_grosses(self):
        rng = random.Random(20260826)
        for _ in range(300):
            cents = rng.randrange(1, 1_000_000)
            rate = rng.choice(RATES)
            gross = Decimal(cents) / 100
            result = TaxEngine.split_gross(gross, rate)
            assert result['net'] + result['tax'] == result['gross'] == gross
            assert result['net'].as_tuple().exponent >= -2
            assert result['tax'].as_tuple().exponent >= -2


class TestComputeInvoice:
    LINES = [
        {'amount': '100.00', 'rate': 5},
        {'amount': '49.50', 'rate': 14},
        {'net': '30', 'rate': 0},
        {'gross': '115.50', 'rate': 5},
    ]

    def test_totals_consistency(self):
        invoice = TaxEngine.compute_invoice(self.LINES)
        assert len(invoice['per_line']) == 4
        assert invoice['total_net'] + invoice['total_tax'] == invoice['total_gross']

    def test_totals_are_sum_of_per_line(self):
        invoice = TaxEngine.compute_invoice(self.LINES)
        assert invoice['total_net'] == sum(ln['net'] for ln in invoice['per_line'])
        assert invoice['total_tax'] == sum(ln['tax'] for ln in invoice['per_line'])
        assert invoice['total_gross'] == sum(ln['gross'] for ln in invoice['per_line'])

    def test_mixed_inclusive_exclusive_lines(self):
        invoice = TaxEngine.compute_invoice([
            {'net': '100', 'rate': 5},
            {'gross': '105', 'rate': 5},
        ])
        assert invoice['total_gross'] == Decimal('210.000')

    def test_empty_invoice(self):
        invoice = TaxEngine.compute_invoice([])
        assert invoice['per_line'] == []
        assert invoice['total_net'] == invoice['total_tax'] == \
            invoice['total_gross'] == Decimal('0.000')

    def test_multi_line_policy_is_per_line_then_sum(self):
        """DOCUMENTED POLICY: per-line rounding first, then sum.

        Two lines of 0.03 @ 5%: raw tax each = 0.0015 -> half-up 0.002,
        so Sigma(line.tax) = 0.004 whereas tax-on-total (0.06) = 0.003.
        Consumers MUST reconcile VAT returns to the per-line sum.
        """
        invoice = TaxEngine.compute_invoice([
            {'amount': '0.03', 'rate': 5},
            {'amount': '0.03', 'rate': 5},
        ])
        assert [ln['tax'] for ln in invoice['per_line']] == [
            Decimal('0.002'), Decimal('0.002')]
        assert invoice['total_tax'] == Decimal('0.004')
        aggregate = _legacy_return_tax('0.06', 5)
        assert aggregate == Decimal('0.003')
        assert invoice['total_tax'] != aggregate  # divergence is real, policy wins

    def test_divergence_from_aggregate_bounded(self):
        """Sigma(line.tax) never drifts beyond (n+1)/2 quanta from aggregate:
        each of n line roundings errs < q/2 and the single aggregate rounding
        errs < q/2 in the opposite direction at worst."""
        rng = random.Random(77)
        for n in range(1, 12):
            specs = [{'amount': Decimal(rng.randrange(1, 50000)) / 100, 'rate': 5}
                     for _ in range(n)]
            invoice = TaxEngine.compute_invoice(specs)
            total_net = invoice['total_net']
            aggregate = _legacy_return_tax(total_net, 5)
            assert abs(invoice['total_tax'] - aggregate) <= MILL * (n + 1) / 2


class TestPropertiesSeeded:
    def test_gross_net_roundtrip_hundreds_of_cases_deterministic(self):
        """Exclusive -> gross -> inclusive recovery within 0.001, seeded."""
        def run():
            rng = random.Random(4242)
            outcomes = []
            for i in range(400):
                amount = Decimal(rng.randrange(1, 500_000)) / 100
                rate = RATES[i % len(RATES)]
                excl = TaxEngine.compute_line_tax(amount, rate)
                incl = TaxEngine.compute_line_tax(
                    excl['gross'], rate, price_includes_tax=True)
                assert abs(incl['net'] - amount) <= MILL
                assert abs(incl['tax'] - excl['tax']) <= Decimal('0.01')
                split = TaxEngine.split_gross(excl['gross'], rate)
                assert split['net'] + split['tax'] == split['gross']
                outcomes.append((str(amount), str(rate), str(excl['gross'])))
            return outcomes

        first_run = run()
        second_run = run()
        assert first_run == second_run  # deterministic under fixed seed
        assert len(first_run) == 400


# --------------------------------------------------------------------- #
# Liability routing (defensive Agent-1 resolver consumption)
# --------------------------------------------------------------------- #
class TestLiabilityRouting:
    def test_fallback_literals_without_resolver_module(self):
        try:
            import services.account_resolution  # noqa: F401
            resolver_present = True
        except ImportError:
            resolver_present = False

        routing = TaxEngine.liability_routing()
        assert set(routing) >= {
            'output_vat', 'sales_returns', 'sales_revenue',
            'ar_control', 'inventory', 'cogs'}
        assert all(isinstance(code, str) and code for code in routing.values())
        if not resolver_present:
            assert routing['output_vat'] == '2130'

    def test_consumes_account_resolver_when_available(self, monkeypatch):
        fake = types.ModuleType('services.account_resolution')

        class AccountRole(str, Enum):
            TAX_PAYABLE = 'TAX_PAYABLE'
            SALES_RETURNS = 'SALES_RETURNS'

        class AccountResolver:
            @staticmethod
            def resolve(role, tenant_id=None):
                mapping = {'TAX_PAYABLE': '9999'}
                return mapping.get(role.value, f'R{tenant_id}-{role.value}')

        fake.AccountRole = AccountRole
        fake.AccountResolver = AccountResolver
        monkeypatch.setitem(sys.modules, 'services.account_resolution', fake)

        routing = TaxEngine.liability_routing(tenant_id=7)
        assert routing['output_vat'] == '9999'
        assert routing['sales_returns'] == 'R7-SALES_RETURNS'


# --------------------------------------------------------------------- #
# ReturnService reversal parity (refactor regression guard)
# --------------------------------------------------------------------- #
@pytest.fixture
def taxable_sale(db, owner_user, test_customer, test_product, test_sale):
    test_sale.tax_rate = Decimal('15.5')
    db.session.commit()
    return test_sale


class TestReturnReversalParity:
    def test_parity_with_legacy_formula_fixture(self, owner_user, taxable_sale):
        line = _get_sale_line(taxable_sale)
        ret = ReturnService.create_return(
            sale_id=taxable_sale.id,
            return_lines_data=[{'sale_line_id': line.id, 'quantity': 2}],
            user_id=owner_user.id,
        )
        net = Decimal('100.000')  # 2 x 50.000
        expected_tax = _legacy_return_tax(net, Decimal('15.5'))
        assert ret.total_amount == net
        assert ret.refund_amount == net + expected_tax == Decimal('115.500')
        assert ret.refund_amount == _legacy_refund(net, Decimal('15.5'))

    def test_tax_gl_line_uses_routed_output_vat_account(self, taxable_sale):
        line = _get_sale_line(taxable_sale)
        ret = ReturnService.create_return(
            sale_id=taxable_sale.id,
            return_lines_data=[{'sale_line_id': line.id, 'quantity': 2}],
            user_id=None,
        )
        entry = GLJournalEntry.query.filter_by(
            reference_type='ProductReturn', reference_id=ret.id).first()
        assert entry is not None
        tax_lines = [ln for ln in entry.lines.all()
                     if 'Tax Reversal' in (ln.description or '')]
        assert len(tax_lines) == 1
        assert tax_lines[0].account.code == TaxEngine.liability_routing()['output_vat']
        assert tax_lines[0].debit == _legacy_return_tax(Decimal('100.000'), Decimal('15.5'))

    def test_return_gl_entry_balanced(self, taxable_sale):
        line = _get_sale_line(taxable_sale)
        ret = ReturnService.create_return(
            sale_id=taxable_sale.id,
            return_lines_data=[{'sale_line_id': line.id, 'quantity': 1}],
            user_id=None,
        )
        entry = GLJournalEntry.query.filter_by(
            reference_type='ProductReturn', reference_id=ret.id).first()
        total_dr = sum((ln.debit for ln in entry.lines.all()), Decimal('0'))
        total_cr = sum((ln.credit for ln in entry.lines.all()), Decimal('0'))
        assert abs(total_dr - total_cr) <= Decimal('0.0001')

    def test_multi_line_return_matches_per_line_policy(self, db, owner_user,
                                                       test_customer, test_product):
        """Two returned lines: refund equals SUM of per-line taxes (engine
        policy), which for these amounts equals the aggregate fixture too."""
        from models import Sale
        from utils.helpers import generate_number

        sale = Sale(
            sale_number=generate_number('S', Sale, 'sale_number'),
            customer_id=test_customer.id, seller_id=owner_user.id,
            subtotal=Decimal('60.000'), discount_amount=Decimal('0'),
            shipping_cost=Decimal('0'), tax_rate=Decimal('5'),
            tax_amount=Decimal('3.000'), total_amount=Decimal('63.000'),
            paid_amount=Decimal('0'), balance_due=Decimal('63.000'),
            currency='AED', exchange_rate=Decimal('1'),
            amount_base=Decimal('63.000'), paid_amount_base=Decimal('0'),
            payment_status='unpaid', status='confirmed', is_active=True,
        )
        db.session.add(sale)
        db.session.flush()
        for price in (Decimal('30.000'), Decimal('30.000')):
            db.session.add(SaleLine(
                sale_id=sale.id, product_id=test_product.id,
                quantity=Decimal('1'), unit_price=price,
                discount_percent=Decimal('0'), line_total=price,
                cost_price=Decimal('10.000'),
            ))
        db.session.commit()

        ret = ReturnService.create_return(
            sale_id=sale.id,
            return_lines_data=[
                {'sale_line_id': ln.id, 'quantity': 1}
                for ln in sale.lines
            ],
            user_id=owner_user.id,
        )
        assert ret.total_amount == Decimal('60.000')
        assert ret.refund_amount == Decimal('63.000')

    def test_zero_rate_return_posts_no_tax_line(self, db, owner_user, test_sale):
        assert not test_sale.tax_rate  # default None -> zero rate
        line = _get_sale_line(test_sale)
        ret = ReturnService.create_return(
            sale_id=test_sale.id,
            return_lines_data=[{'sale_line_id': line.id, 'quantity': 1}],
            user_id=owner_user.id,
        )
        assert ret.refund_amount == Decimal('50.000')
        entry = GLJournalEntry.query.filter_by(
            reference_type='ProductReturn', reference_id=ret.id).first()
        tax_lines = [ln for ln in entry.lines.all()
                     if 'Tax Reversal' in (ln.description or '')]
        assert tax_lines == []

    def test_default_quantum_constant(self):
        assert DEFAULT_QUANTUM == MILL


def _legacy_refund(net, rate_percent):
    return Decimal(net) + _legacy_return_tax(net, rate_percent)
