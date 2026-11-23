"""Inventory reconciliation must end at zero difference and use HALF_UP."""
import os
os.environ.setdefault('PYTHONIOENCODING','utf-8')


def test_control_balance_uses_canonical_rounding():
    src = open('utils/balance_checker.py', encoding='utf-8').read()
    assert 'from utils.money import qMoney' in src
    assert 'return qMoney(total)' in src


def test_balanced_uses_totals_not_allocation():
    src = open('services/inventory_reconciliation.py', encoding='utf-8').read()
    assert 'abs(total_difference) <= TOLERANCE' in src
    assert 'and abs(gl_difference) <= TOLERANCE' in src
    assert 'not breaks' not in src


def test_inventory_zero_difference_today():
    from app import create_app
    app = create_app()
    with app.app_context():
        from models import set_current_tenant_id
        set_current_tenant_id(2)
        from services.inventory_reconciliation import reconcile_inventory
        r = reconcile_inventory(tenant_id=2)
        assert abs(float(r['gl_difference'])) < 0.01
        assert r['balanced'] is True
