"""Outgoing cheques use 2120 until cleared, then move to Bank 1120."""
import uuid
from decimal import Decimal

from sqlalchemy import text
from utils.transaction import atomic_transaction


def test_cheque_payment_posting_lifecycle(client, login_as, app, db):
    from models import Product, Purchase, PurchaseLine, Supplier

    mgr = login_as("manager")
    tag = uuid.uuid4().hex[:8]
    with app.app_context():
        from models.tenant_scope import set_current_tenant_id
        set_current_tenant_id(mgr.tenant_id)
        sup = Supplier(name=f"CHQ-{tag}", supplier_type="materials",
                       tenant_id=mgr.tenant_id, is_active=True)
        p = Product(name=f"CHQP-{tag}", sku=f"CHQP-{tag}",
                    regular_price=Decimal("10"), cost_price=Decimal("8"),
                    current_stock=Decimal("0"), tenant_id=mgr.tenant_id,
                    is_active=True)
        db.session.add_all([sup, p])
        db.session.flush()
        with atomic_transaction():
            pur = Purchase(purchase_number=f"CHQ-{tag}", supplier_id=sup.id,
                           supplier_name=sup.name, user_id=mgr.id,
                           tenant_id=mgr.tenant_id, currency="ILS",
                           tax_rate=Decimal("0"), tax_inclusive=False,
                           vat_recoverable=True, exchange_rate=Decimal("1"),
                           subtotal=Decimal("100"), tax_amount=Decimal("0"),
                           total_amount=Decimal("100"), amount_base=Decimal("100"))
            db.session.add(pur)
            db.session.flush()
            db.session.add(PurchaseLine(purchase_id=pur.id, product_id=p.id,
                                        quantity=Decimal("10"), unit_cost=Decimal("10"),
                                        line_total=Decimal("100"),
                                        tax_treatment="standard",
                                        tenant_id=mgr.tenant_id))
        pid, sname = pur.id, sup.name

    resp = client.post(f"/payments/create_payment/{pid}", data={
        "amount": "100", "payment_method": "cheque", "currency": "ILS",
        "exchange_rate": "1", "cheque_number": f"CHQ{tag}",
        "bank_name": "بنك الوطني", "cheque_date": "2026-11-30", "notes": "test",
    }, follow_redirects=False)
    assert resp.status_code in (302, 303), resp.get_data(as_text=True)[:300]

    with app.app_context():
        codes = [r[0] for r in db.session.execute(
            text("SELECT a.code FROM gl_journal_lines gl "
                 "JOIN gl_accounts a ON a.id=gl.account_id "
                 "JOIN gl_journal_entries je ON je.id=gl.entry_id "
                 "WHERE je.reference_type='Payment' AND gl.credit>0")).fetchall()]
        assert "2120" in codes and "1120" not in codes
        cheque_id = db.session.execute(text("SELECT id FROM cheques ORDER BY id DESC LIMIT 1")).scalar()

    resp = client.post(f"/cheques/{cheque_id}/clear", data={
        "clearance_date": "2026-11-30"})
    assert resp.status_code in (302, 303)

    with app.app_context():
        rows = db.session.execute(
            text("SELECT a.code, gl.debit, gl.credit FROM gl_journal_lines gl "
                 "JOIN gl_accounts a ON a.id=gl.account_id "
                 "JOIN gl_journal_entries je ON je.id=gl.entry_id "
                 "WHERE je.reference_type='cheque_clear' AND je.reference_id=:i"),
            {"i": cheque_id}).fetchall()
        from models import Cheque

        chq = db.session.get(Cheque, cheque_id)
        actual = float(chq.actual_amount_base or 0)
        by_code = {r[0]: (float(r[1]), float(r[2])) for r in rows}
        assert by_code["2120"][0] == 100.0  # deferred cheques debited at book value
        assert by_code["1120"][1] == actual  # bank credited at cleared FX value
        assert actual > 0

        # Keep the shared SQLite test schema droppable (payments reference cheques).
        db.session.execute(
            text("DELETE FROM payments WHERE cheque_id=:i"), {"i": cheque_id})
        db.session.execute(text("DELETE FROM cheques WHERE id=:i"), {"i": cheque_id})
        db.session.commit()
