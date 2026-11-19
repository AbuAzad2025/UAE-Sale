"""A tenant manager with manage_warehouse may create warehouses for their own
tenant only. Regression for create/delete being wrongly gated on @admin_required
(owner-only) even though the manager role already carries manage_warehouse.
"""
import uuid

from sqlalchemy import text


def _unique():
    return uuid.uuid4().hex[:10]


def test_manager_can_create_warehouse_in_own_tenant(client, login_as, app, db):
    mgr = login_as("manager")
    own_tid = mgr.tenant_id
    tag = _unique()
    name = f"WH-RAMALLAH-{tag}"
    code = f"WH{tag}"

    # The form used to answer 403 for every non-owner.
    resp = client.get("/warehouse/create")
    assert resp.status_code == 200

    resp = client.post(
        "/warehouse/create",
        data={
            "name": name,
            "name_ar": name,
            "code": code,
            "location": "Ramallah - Palestine",
            "is_main": "on",
        },
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303), resp.get_data(as_text=True)[:300]

    with app.app_context():
        row = db.session.execute(
            text("SELECT tenant_id, name FROM warehouses WHERE code = :c"),
            {"c": code},
        ).first()
        assert row is not None, "warehouse was not persisted"
        assert row.tenant_id == own_tid, (
            f"warehouse stamped to tenant {row.tenant_id}, expected {own_tid}"
        )


def test_manager_cannot_delete_other_tenants_warehouse(client, login_as, app, db):
    mgr = login_as("manager")
    own_tid = mgr.tenant_id
    tag = _unique()

    with app.app_context():
        other = db.session.execute(
            text("SELECT id FROM tenants WHERE id != :t ORDER BY id LIMIT 1"),
            {"t": own_tid},
        ).first()
        if other is None:
            # SQLite-based test fixtures seed a single tenant. Create a second
            # one via the ORM so timestamp defaults are applied.
            from models import Tenant

            foreign = Tenant(
                name=f"Other {tag}",
                name_ar=f"Other {tag}",
                slug=f"other-{tag}",
                is_active=True,
            )
            db.session.add(foreign)
            db.session.commit()
            foreign_tid = foreign.id
        else:
            foreign_tid = other.id
        cur = db.session.execute(
            text(
                "INSERT INTO warehouses (name, code, location, tenant_id, is_active) "
                "VALUES (:n, :c, :l, :t, true) RETURNING id"
            ),
            {
                "n": f"FOREIGN-WH-{tag}",
                "c": f"FW{tag}",
                "l": "Other tenant",
                "t": foreign_tid,
            },
        )
        foreign_id = cur.scalar()
        db.session.commit()

    resp = client.post(f"/warehouse/{foreign_id}/delete")
    assert resp.status_code == 404, (
        f"manager received {resp.status_code} deleting a foreign warehouse"
    )

    with app.app_context():
        still = db.session.execute(
            text("SELECT tenant_id FROM warehouses WHERE id = :i"),
            {"i": foreign_id},
        ).first()
        assert still is not None and still.tenant_id == foreign_tid
