"""AR reconciliation must explain the partner current-account balance."""
import os
os.environ.setdefault('PYTHONIOENCODING','utf-8')

from app import create_app


def test_ar_reconciling_item_covers_partner_shares():
    app = create_app()
    with app.app_context():
        from models import set_current_tenant_id
        set_current_tenant_id(2)
        from services.subledger_reconciliation import SubLedgerReconciliation
        ar = SubLedgerReconciliation.reconcile_receivables(tenant_id=2)
        codes = [i['code'] for i in ar['reconciling_items']]
        assert 'partner_current_shares' in codes
        assert abs(float(ar['adjusted_control_difference'])) < 0.01
        assert ar['balanced'] is True
