"""Canonical numeric precision for the whole system.

Problems this module prevents
-----------------------------
Different files used to round money to 2dp, quantities to 3dp and exchange
rates to 6dp using ad-hoc literals. Multiplying a 3dp average cost by a large
quantity (e.g. 2,835 units) accumulated a visible drift (1.44 ILS) between the
inventory valuation and the GL control account.

Rules (single source of truth)
------------------------------
MONEY    2dp  — currency amounts, GL lines, totals, report valuations
QTY      3dp  — quantities on hand / movements
UNIT_COST 6dp — average/last unit cost (prevents multiplication drift)
RATE     6dp  — exchange rates
"""
from decimal import Decimal, ROUND_HALF_UP

MONEY_DP = Decimal("0.01")
QTY_DP = Decimal("0.001")
UNIT_COST_DP = Decimal("0.000001")
RATE_DP = Decimal("0.000001")

ZERO = Decimal("0")


def _dec(value):
    if value is None:
        return ZERO
    return value if isinstance(value, Decimal) else Decimal(str(value))


def qMoney(value):
    """Round a monetary amount to 2dp (half-up)."""
    return _dec(value).quantize(MONEY_DP, rounding=ROUND_HALF_UP)


def qQty(value):
    """Round a quantity to 3dp (half-up)."""
    return _dec(value).quantize(QTY_DP, rounding=ROUND_HALF_UP)


def qUnitCost(value):
    """Round a unit cost to 6dp (half-up) — never store 3dp costs."""
    return _dec(value).quantize(UNIT_COST_DP, rounding=ROUND_HALF_UP)


def qRate(value):
    """Round an exchange rate to 6dp (half-up)."""
    return _dec(value).quantize(RATE_DP, rounding=ROUND_HALF_UP)


def valuation(quantity, unit_cost):
    """Canonical inventory valuation: q6 unit cost x q3 qty, rounded to 2dp."""
    return qMoney(qQty(quantity) * qUnitCost(unit_cost))
