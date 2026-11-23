"""Inventory report must use a real cost-price basis and unified valuation."""
from services.inventory_reconciliation import __file__ as _f  # noqa: F401


def test_cost_price_valuation_is_independent_in_source():
    src = open('services/inventory_reconciliation.py', encoding='utf-8').read()
    assert 'valuation = _valuation(qty, cost)' in src
    assert 'valuation_cost_price = _valuation(qty, cost_price)' in src
    assert '"valuation_at_cost_price": _q2(valuation_cost_price)' in src
    assert '"total_valuation_at_cost_price": _q2(total_valuation_cost_price)' in src
    # the old bug: both fields were assigned the same `valuation`
    assert '"valuation_at_cost_price": _q2(valuation),' not in src


def test_inventory_quantity_equality_is_checked():
    src = open('services/inventory_reconciliation.py', encoding='utf-8').read()
    assert 'total_difference = total_stock - total_qty' in src
    assert 'abs(total_difference) <= TOLERANCE' in src
