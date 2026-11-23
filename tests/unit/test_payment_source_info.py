"""Supplier payment receipts must reference the linked purchase invoice."""
import os
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

from app import create_app


def test_supplier_payment_shows_purchase_invoice():
    app = create_app()
    with app.app_context():
        from models import set_current_tenant_id, Payment
        set_current_tenant_id(2)
        p = Payment.query.filter(Payment.tenant_id == 2, Payment.purchase_id.isnot(None)).first()
        if not p:
            return
        src = p.get_source_info()
        assert src is not None
        assert src['number'].startswith('P-'), src
        assert src['date'] is not None, src


def test_all_purchase_linked_payments_have_date():
    app = create_app()
    with app.app_context():
        from models import set_current_tenant_id, Payment
        set_current_tenant_id(2)
        for p in Payment.query.filter_by(tenant_id=2).all():
            if p.purchase_id:
                src = p.get_source_info()
                assert src and src['date'], p.payment_number
