"""Pure pricing tests; they do not assert that invoices or GL are implemented."""
import random
from decimal import Decimal

import pytest

from services.maintenance_pricing import PriceLine, calculate_maintenance_pricing
from services.sale_tax_calculation import sale_tax_totals_mixed
from utils.errors import ValidationError


D = Decimal


@pytest.mark.parametrize('inclusive,price,expected_net,expected_tax,expected_total', [
    (False, '100', '100', '5', '105'),
    (True, '105', '100', '5', '105'),
])
def test_inclusive_and_exclusive_prices(inclusive, price, expected_net, expected_tax, expected_total):
    result = calculate_maintenance_pricing([PriceLine(1, price, 5)], tax_inclusive=inclusive)
    assert result.net_amount == D(expected_net)
    assert result.tax_amount == D(expected_tax)
    assert result.total_amount == D(expected_total)
    assert result.lines[0].total_amount == result.total_amount


def test_inclusive_order_discount_reduces_tax_as_well_as_total():
    result = calculate_maintenance_pricing([PriceLine(1, '105', 5)],
                                           tax_inclusive=True, discount_percent=10)
    assert result.price_basis_subtotal == D('105')
    assert result.order_discount == D('10.500')
    assert result.net_amount == D('90')
    assert result.tax_amount == D('4.50')
    assert result.total_amount == D('94.500')


def test_mixed_tax_treatments_and_order_discount():
    lines = [PriceLine(1, 100, 5), PriceLine(1, 50, 0, 'zero'),
             PriceLine(1, 50, 0, 'exempt')]
    result = calculate_maintenance_pricing(lines, discount_percent=10)
    assert result.order_discount == D('20')
    assert [line.order_discount for line in result.lines] == [D('10'), D('5'), D('5')]
    assert [line.tax_amount for line in result.lines] == [D('4.5'), D('0'), D('0')]
    assert (result.net_amount, result.tax_amount, result.total_amount) == (D('180'), D('4.5'), D('184.5'))


def test_fixed_order_discount_allocation_is_deterministic_and_exact():
    lines = [PriceLine(1, 1), PriceLine(1, 1), PriceLine(1, 1)]
    result = calculate_maintenance_pricing(lines, discount_value='0.001')
    assert [line.order_discount for line in result.lines] == [D('0.001'), D('0'), D('0')]
    assert result.total_amount == D('2.999')


def test_line_discount_is_not_applied_twice():
    result = calculate_maintenance_pricing([
        PriceLine(2, 50, discount_mode='value', discount_value=20),
        PriceLine(1, 100, discount_percent=10),
    ])
    assert result.line_discount == D('30')
    assert result.price_basis_subtotal == D('170')
    assert result.total_amount == D('170')


def test_vat_is_rounded_per_rate_bucket_and_allocated_to_lines():
    result = calculate_maintenance_pricing([PriceLine(1, '0.333', 5)] * 3)
    assert result.net_amount == D('0.999')
    assert result.tax_amount == D('0.050')
    assert [line.tax_amount for line in result.lines] == [D('0.017'), D('0.017'), D('0.016')]
    assert result.total_amount == D('1.049')


@pytest.mark.parametrize('inclusive,price', [(False, D('100')), (True, D('105'))])
def test_single_rate_matches_existing_sales_engine(inclusive, price):
    result = calculate_maintenance_pricing([PriceLine(1, price, 5)],
                                           tax_inclusive=inclusive, discount_percent=10)
    sales_tax, sales_total, *_ = sale_tax_totals_mixed(
        [{'line_total': price, 'tax_treatment': 'standard'}],
        discount=price * D('0.10'), shipping=0, rate=5, inclusive=inclusive,
    )
    assert (result.tax_amount, result.total_amount) == (sales_tax, sales_total)


@pytest.mark.parametrize('lines,kwargs', [
    ([PriceLine(0, 1)], {}),
    ([PriceLine(-1, 1)], {}),
    ([PriceLine(1, '-1')], {}),
    ([PriceLine(1, 'NaN')], {}),
    ([PriceLine(1, '1.0001')], {}),
    ([PriceLine(1, 1, '100.01')], {}),
    ([PriceLine(1, 1, 5, 'exempt')], {}),
    ([PriceLine(1, 1, discount_percent=101)], {}),
    ([PriceLine(1, 1, discount_mode='value', discount_value=2)], {}),
    ([PriceLine(1, 1, discount_percent=1, discount_value=1)], {}),
    ([PriceLine(1, 1)], {'discount_percent': 10, 'discount_value': 1}),
    ([PriceLine(1, 1)], {'discount_value': 2}),
    ([PriceLine(1, 1)], {'tax_inclusive': 'false'}),
    ([], {'discount_value': 1}),
])
def test_invalid_values_are_rejected(lines, kwargs):
    with pytest.raises(ValidationError):
        calculate_maintenance_pricing(lines, **kwargs)


def test_calculation_invariants_across_mixed_documents():
    generator = random.Random(1447)
    for _ in range(300):
        lines = []
        for _ in range(generator.randint(1, 8)):
            price = D(generator.randint(0, 100000)) / 1000
            rate = generator.choice([0, 5, 15])
            lines.append(PriceLine(1, price, rate))
        inclusive = generator.choice([True, False])
        result = calculate_maintenance_pricing(lines, tax_inclusive=inclusive,
                                               discount_percent=generator.randint(0, 30))
        assert result.net_amount == sum((line.net_amount for line in result.lines), D(0))
        assert result.tax_amount == sum((line.tax_amount for line in result.lines), D(0))
        assert result.total_amount == sum((line.total_amount for line in result.lines), D(0))
        assert result.total_amount == result.net_amount + result.tax_amount
        assert result.order_discount == sum((line.order_discount for line in result.lines), D(0))
        assert all(line.net_amount >= 0 and line.tax_amount >= 0 for line in result.lines)
        discounted_basis = result.price_basis_subtotal - result.order_discount
        assert (result.total_amount if inclusive else result.net_amount) == discounted_basis
