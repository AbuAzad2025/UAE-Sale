"""Exchange rates must convert document amounts into the tenant base currency."""
import uuid
from decimal import Decimal

from sqlalchemy import text


def test_sale_in_foreign_currency_uses_exchange_rate(client, login_as, app, db):
    from models import Customer, Product, Warehouse

    mgr = login_as("manager")
    tag = uuid.uuid4().hex[:8]
    with app.app_context():
        from models.tenant_scope import set_current_tenant_id
        set_current_tenant_id(mgr.tenant_id)
        wh = Warehouse(name=f"FXW-{tag}", tenant_id=mgr.tenant_id, is_active=True)
        db.session.add(wh)
        db.session.flush()
        cust = Customer(name=f"FX-{tag}", customer_type="regular",
                        tenant_id=mgr.tenant_id, is_active=True)
        prod = Product(name=f"FXP-{tag}", sku=f"FXP-{tag}",
                       regular_price=Decimal("100"), cost_price=Decimal("50"),
                       current_stock=Decimal("10"), tenant_id=mgr.tenant_id,
                       is_active=True)
        db.session.add_all([cust, prod])
        db.session.commit()
        cid, pid, wid = cust.id, prod.id, wh.id

    # Sell 1 unit @ 100 USD with an explicit rate of 3.7 -> 370 ILS base.
    resp = client.post("/sales/create", data={
        "customer_id": str(cid), "warehouse_id": str(wid), "currency": "USD",
        "exchange_rate": "3.7", "tax_rate": "0", "line_count": "1",
        "lines[0][product_id]": str(pid), "lines[0][quantity]": "1",
        "lines[0][unit_price]": "100", "lines[0][discount_percent]": "0",
        "lines[0][tax_treatment]": "standard",
    }, follow_redirects=False)
    assert resp.status_code in (302, 303), resp.get_data(as_text=True)[:300]

    with app.app_context():
        row = db.session.execute(
            text("SELECT currency,exchange_rate,total_amount,amount_base "
                 "FROM sales WHERE customer_id=:i ORDER BY id DESC LIMIT 1"),
            {"i": cid}).first()
        assert row.currency == "USD"
        assert float(row.exchange_rate) == 3.7
        assert float(row.total_amount) == 100.0
        assert float(row.amount_base) == 370.0  # 100 USD x 3.7

        sid = db.session.execute(
            text("SELECT id FROM sales WHERE customer_id=:i ORDER BY id DESC LIMIT 1"),
            {"i": cid}).scalar()
        gl = db.session.execute(
            text("""SELECT gl.amount_base FROM gl_journal_lines gl
                    JOIN gl_accounts a ON a.id=gl.account_id
                    JOIN gl_journal_entries je ON je.id=gl.entry_id
                    WHERE je.reference_type='Sale' AND je.reference_id=:i AND a.code='1130'"""),
            {"i": sid}).scalar()
        assert float(gl) == 370.0  # AR booked at base value
