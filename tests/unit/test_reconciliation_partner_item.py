"""AR reconciliation must explain the partner current-account balance."""

import os

os.environ.setdefault("PYTHONIOENCODING", "utf-8")


def test_ar_reconciling_item_covers_partner_shares(posting_tenant):
    from services.subledger_reconciliation import SubLedgerReconciliation

    ar = SubLedgerReconciliation.reconcile_receivables(tenant_id=posting_tenant.id)
    codes = [i["code"] for i in ar["reconciling_items"]]
    assert "partner_current_shares" in codes
    assert abs(float(ar["adjusted_control_difference"])) < 0.01
    assert ar["balanced"] is True
