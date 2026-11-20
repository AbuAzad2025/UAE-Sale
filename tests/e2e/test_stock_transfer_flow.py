"""Stock transfers must persist and adjust both warehouses on receive."""
import uuid
from decimal import Decimal

from sqlalchemy import text


def _make(db, cls, tenant_id, **kw):
    obj = cls(tenant_id=tenant_id, **kw)
    db.session.add(obj)
    db.session.commit()
    return obj


def test_transfer_create_send_receive_persists(client, login_as, app, db):
    from models import Product, Warehouse
    from models.erp_modules import StockTransfer, StockTransferLine

    mgr = login_as("manager")
    tag = uuid.uuid4().hex[:8]
    with app.app_context():
        w1 = _make(db, Warehouse, mgr.tenant_id, name=f"SRC-{tag}", is_active=True)
        w2 = _make(db, Warehouse, mgr.tenant_id, name=f"DST-{tag}", is_active=True)
        p = _make(db, Product, mgr.tenant_id, name=f"TR-{tag}", sku=f"TR-{tag}",
                  regular_price=Decimal("10"), cost_price=Decimal("8"),
                  current_stock=Decimal("100"), is_active=True)

    r = client.post("/erp/stock-transfers/create", data={
        "from_warehouse_id": str(w1.id), "to_warehouse_id": str(w2.id),
        "lines[0][product_id]": str(p.id), "lines[0][quantity]": "40",
        "notes": "test transfer",
    }, follow_redirects=False)
    assert r.status_code in (302, 303), r.get_data(as_text=True)[:300]

    with app.app_context():
        trow = db.session.execute(
            text("SELECT id, status, tenant_id FROM stock_transfers "
                 "WHERE notes='test transfer' ORDER BY id DESC LIMIT 1")).first()
        assert trow is not None, "transfer was not persisted"
        tid, status, tid_tenant = trow
        assert status == "pending"
        assert tid_tenant == mgr.tenant_id
        assert db.session.execute(
            text("SELECT COUNT(*) FROM stock_transfer_lines WHERE transfer_id=:i"),
            {"i": tid}).scalar() == 1

    assert client.post(f"/erp/stock-transfers/{tid}/send").status_code in (302, 303)
    assert client.post(f"/erp/stock-transfers/{tid}/receive").status_code in (302, 303)

    with app.app_context():
        st = db.session.execute(
            text("SELECT status FROM stock_transfers WHERE id=:i"), {"i": tid}).scalar()
        assert st == "received"
        moves = db.session.execute(
            text("SELECT warehouse_id, SUM(quantity) FROM stock_movements "
                 "WHERE product_id=:p AND notes LIKE :n GROUP BY warehouse_id"),
            {"p": p.id, "n": "%TRF%"}).fetchall()
        by_wh = {r[0]: float(r[1]) for r in moves}
        assert by_wh.get(w1.id) == -40.0
        assert by_wh.get(w2.id) == 40.0
