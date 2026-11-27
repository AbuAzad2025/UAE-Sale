"""Cheques must never mutate denormalised supplier purchase statistics."""

import os

os.environ.setdefault("PYTHONIOENCODING", "utf-8")


def test_cheque_does_not_touch_supplier_purchase_totals():
    src = open("models/cheque.py", encoding="utf-8").read()
    assert "supplier.total_purchases_aed" not in src


def test_integration_does_not_touch_supplier_purchase_totals():
    src = open("services/cheque_accounting_integration.py", encoding="utf-8").read()
    assert "supplier.total_purchases_aed" not in src


def test_reconciliation_ap_balanced(posting_tenant):
    from services.subledger_reconciliation import SubLedgerReconciliation

    r = SubLedgerReconciliation.reconcile_all(tenant_id=posting_tenant.id)
    ap = next(x for x in r if x.get("section") == "AP")
    assert abs(float(ap["control_difference"])) < 0.01
