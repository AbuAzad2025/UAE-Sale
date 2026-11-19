"""The supplier statement uses manage_suppliers, not owner-only admin.
A manager sees their own tenant's supplier statement and gets 404 on another
tenant's supplier.
"""
import uuid

from sqlalchemy import text


def _supplier(db, tenant_id, tag):
    from models import Supplier

    s = Supplier(name=f"ST-{tag}", supplier_type="materials",
                 tenant_id=tenant_id, is_active=True)
    db.session.add(s)
    db.session.commit()
    return s.id


def test_manager_can_open_own_supplier_statement(client, login_as, app, db):
    mgr = login_as("manager")
    with app.app_context():
        sid = _supplier(db, mgr.tenant_id, uuid.uuid4().hex[:8])

    resp = client.get(f"/suppliers/{sid}/statement")
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]


def test_manager_cannot_open_foreign_supplier_statement(client, login_as, app, db):
    mgr = login_as("manager")
    with app.app_context():
        from models import Tenant

        other = db.session.execute(
            text("SELECT id FROM tenants WHERE id != :t ORDER BY id LIMIT 1"),
            {"t": mgr.tenant_id}).first()
        if other is None:
            tag = uuid.uuid4().hex[:8]
            t = Tenant(name=f"O {tag}", name_ar=f"O {tag}", slug=f"o-{tag}", is_active=True)
            db.session.add(t)
            db.session.commit()
            other_tid = t.id
        else:
            other_tid = other.id
        sid = _supplier(db, other_tid, uuid.uuid4().hex[:8])

    resp = client.get(f"/suppliers/{sid}/statement")
    assert resp.status_code == 404
