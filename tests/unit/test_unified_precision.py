"""One canonical numeric precision module for the whole system."""
from decimal import Decimal as D
from utils.money import MONEY_DP, QTY_DP, UNIT_COST_DP, RATE_DP
from utils.money import qMoney, qQty, qUnitCost, qRate, valuation


def test_precision_constants():
    assert MONEY_DP == D("0.01")
    assert QTY_DP == D("0.001")
    assert UNIT_COST_DP == D("0.000001")
    assert RATE_DP == D("0.000001")


def test_rounding_is_half_up():
    assert qMoney(D("1.005")) == D("1.01")
    assert qQty(D("2.3455")) == D("2.346")
    assert qUnitCost(D("10.3448275")) == D("10.344828")


def test_valuation_uses_six_dp_unit_cost():
    # 10.344828 x 2835 = 29327.58638 -> 29327.59 (not 29327.59 from 3dp)
    assert valuation(D("2835"), D("10.344828")) == D("29327.59")


def test_average_cost_column_is_six_dp():
    from models import Product
    col = Product.__table__.c.average_cost.type
    assert col.scale == 6
