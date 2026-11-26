"""Inventory reconciliation must end at zero difference and use HALF_UP."""

import os

os.environ.setdefault("PYTHONIOENCODING", "utf-8")


def test_control_balance_uses_canonical_rounding():
    src = open("utils/balance_checker.py", encoding="utf-8").read()
    assert "from utils.money import qMoney" in src
    assert "return qMoney(total)" in src


def test_unallocated_control_balance_is_reported(db, posting_tenant):
    from services.gl_service import GLService
    from services.inventory_reconciliation import reconcile_inventory

    GLService.post_entry(
        [{"account": "1140", "debit": 75}, {"account": "3100", "credit": 75}],
        description="Unallocated inventory",
        tenant_id=posting_tenant.id,
    )
    result = reconcile_inventory(tenant_id=posting_tenant.id)
    assert result["unattributed_gl_balance"] == 75
    assert result["gl_difference"] == 75
    assert result["balanced"] is False


def test_inventory_zero_difference_today(db, posting_tenant):
    from services.inventory_reconciliation import reconcile_inventory

    result = reconcile_inventory(tenant_id=posting_tenant.id)
    assert result["gl_difference"] == 0
    assert result["balanced"] is True
