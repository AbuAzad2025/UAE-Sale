"""Sales return UI and reversal accounting."""
import uuid
from decimal import Decimal

from sqlalchemy import text


def test_sale_view_has_return_form(client, login_as, app, db):
    from models import Customer, Product, Sale, SaleLine

    mgr = login_as("manager")
    tag = uuid.uuid4().hex[:8]
    with app.app_context():
        from models.tenant_scope import set_current_tenant_id
        set_current_tenant_id(mgr.tenant_id)
        cust = Customer(name=f"RT-{tag}", customer_type="regular",
                        tenant_id=mgr.tenant_id, is_active=True)
        prod = Product(name=f"RTP-{tag}", sku=f"RTP-{tag}",
                       regular_price=Decimal("10"), cost_price=Decimal("8"),
                       current_stock=Decimal("100"), tenant_id=mgr.tenant_id,
                       is_active=True)
        db.session.add_all([cust, prod])
        db.session.flush()
        sale = Sale(sale_number=f"RT-{tag}", customer_id=cust.id, seller_id=mgr.id,
                    tenant_id=mgr.tenant_id, currency="ILS", exchange_rate=Decimal("1"),
                    subtotal=Decimal("100"), tax_amount=Decimal("0"),
                    total_amount=Decimal("100"), amount_base=Decimal("100"),
                    paid_amount=Decimal("0"), balance_due=Decimal("100"),
                    status="confirmed")
        db.session.add(sale)
        db.session.flush()
        line = SaleLine(sale_id=sale.id, product_id=prod.id, quantity=Decimal("10"),
                        unit_price=Decimal("10"), line_total=Decimal("100"),
                        cost_price=Decimal("8"), tenant_id=mgr.tenant_id)
        db.session.add(line)
        db.session.commit()
        sid, lid, pid = sale.id, line.id, prod.id

    body = client.get(f"/sales/{sid}").get_data(as_text=True)
    assert "تسجيل مرتجع على هذه الفاتورة" in body
    assert f'data-return-line="{lid}"' in body

    resp = client.post("/returns/api/create", json={
        "sale_id": sid,
        "lines": [{"sale_line_id": lid, "quantity": 3, "condition": "good", "notes": ""}],
        "notes": "test return",
    })
    assert resp.status_code == 200, resp.get_data(as_text=True)[:200]
    assert resp.get_json().get("success") is True

    with app.app_context():
        qty = db.session.execute(text("SELECT current_stock FROM products WHERE id=:i"),
                                 {"i": pid}).scalar()
        assert float(qty) == 103.0
        bal = db.session.execute(text("""SELECT a.code, SUM(gl.debit-gl.credit)
            FROM gl_journal_lines gl JOIN gl_accounts a ON a.id=gl.account_id
            JOIN gl_journal_entries je ON je.id=gl.entry_id
            WHERE je.reference_type LIKE '%Return%' GROUP BY a.code""")).fetchall()
        by_code = {r[0]: float(r[1]) for r in bal}
        assert by_code["1140"] == 24.0  # inventory restored at unit cost 8
        assert by_code["5100"] == -24.0  # COGS reversed
