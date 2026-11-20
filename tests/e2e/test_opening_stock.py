"""Opening stock must post a balanced, idempotent, tenant-scoped GL entry."""
import uuid
from decimal import Decimal

from sqlalchemy import text


def _product_with_opening(db, tenant_id, tag, qty="10", cost="8"):
    from models import Product, StockMovement, Warehouse

    wh = Warehouse(name=f"OSW-{tag}", tenant_id=tenant_id, is_active=True)
    db.session.add(wh)
    db.session.flush()
    p = Product(name=f"OS-{tag}", sku=f"OS-{tag}", regular_price=Decimal("10"),
                cost_price=Decimal(cost), current_stock=Decimal(qty),
                tenant_id=tenant_id, is_active=True)
    db.session.add(p)
    db.session.flush()
    m = StockMovement(product_id=p.id, quantity=Decimal(qty),
                      movement_type="adjustment", reference_type="Product Creation",
                      reference_id=p.id, warehouse_id=wh.id, tenant_id=tenant_id,
                      notes="opening")
    db.session.add(m)
    db.session.commit()
    return p.id, m.id


def test_opening_stock_posts_balanced_gl_once(client, login_as, app, db):
    mgr = login_as("manager")
    tag = uuid.uuid4().hex[:8]
    with app.app_context():
        _, mid = _product_with_opening(db, mgr.tenant_id, tag)

    page = client.get("/warehouse/opening-stock")
    assert page.status_code == 200
    assert "ترحيل الرصيد الافتتاحي" in page.get_data(as_text=True)

    resp = client.post("/warehouse/opening-stock/post")
    assert resp.status_code in (302, 303)

    with app.app_context():
        rows = db.session.execute(
            text("SELECT a.code, gl.debit, gl.credit FROM gl_journal_lines gl "
                 "JOIN gl_journal_entries je ON je.id=gl.entry_id "
                 "JOIN gl_accounts a ON a.id=gl.account_id "
                 "WHERE je.reference_type='OpeningStock' AND je.reference_id=:i"),
            {"i": mid}).all()
        assert len(rows) == 2
        by_code = {r[0]: (float(r[1]), float(r[2])) for r in rows}
        assert by_code["1140"][0] == 80.0 and by_code["1140"][1] == 0.0
        assert by_code["3100"][1] == 80.0 and by_code["3100"][0] == 0.0

    # Idempotent: a second post must not create another entry.
    client.post("/warehouse/opening-stock/post")
    with app.app_context():
        count = db.session.execute(
            text("SELECT COUNT(*) FROM gl_journal_entries "
                 "WHERE reference_type='OpeningStock' AND reference_id=:i"),
            {"i": mid}).scalar()
        assert count == 1
