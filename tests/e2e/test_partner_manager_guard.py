"""A tenant manager can manage their own company partners/shares through the
neutral /settings/partners page, but never another tenant's partners.
"""
import uuid

from sqlalchemy import text


def _new_customer(db, tenant_id, tag):
    from models import Customer

    c = Customer(
        name=f"Partner {tag}",
        name_ar=f"شريك {tag}",
        customer_type="regular",
        tenant_id=tenant_id,
        is_active=True,
    )
    db.session.add(c)
    db.session.commit()
    return c


def test_manager_can_set_company_partner_share(client, login_as, app, db):
    mgr = login_as("manager")
    own_tid = mgr.tenant_id
    tag = uuid.uuid4().hex[:10]

    with app.app_context():
        cust = _new_customer(db, own_tid, tag)
        cid = cust.id

    resp = client.get("/settings/partners")
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]

    resp = client.post(
        "/settings/partners",
        data={"action": "set_scope", "customer_id": cid, "scope": "company", "share": "25"},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303), resp.get_data(as_text=True)[:300]

    with app.app_context():
        row = db.session.execute(
            text(
                "SELECT tenant_id, partner_scope, partner_share, customer_type "
                "FROM customers WHERE id = :i"
            ),
            {"i": cid},
        ).first()
        assert row.tenant_id == own_tid
        assert row.partner_scope == "company"
        assert row.customer_type == "partner"
        assert float(row.partner_share) == 25.0


def test_manager_cannot_set_foreign_partners_share(client, login_as, app, db):
    mgr = login_as("manager")
    own_tid = mgr.tenant_id
    tag = uuid.uuid4().hex[:10]

    with app.app_context():
        from models import Tenant

        other = db.session.execute(
            text("SELECT id FROM tenants WHERE id != :t ORDER BY id LIMIT 1"),
            {"t": own_tid},
        ).first()
        if other is None:
            foreign = Tenant(
                name=f"Other {tag}", name_ar=f"Other {tag}",
                slug=f"other-{tag}", is_active=True,
            )
            db.session.add(foreign)
            db.session.commit()
            other_tid = foreign.id
        else:
            other_tid = other.id
        foreign_cust = _new_customer(db, other_tid, tag)
        assert foreign_cust.tenant_id == other_tid, (
            f"test setup: customer stamped {foreign_cust.tenant_id}, "
            f"expected foreign {other_tid}"
        )
        foreign_cid = foreign_cust.id

    resp = client.post(
        "/settings/partners",
        data={
            "action": "set_scope",
            "customer_id": foreign_cid,
            "scope": "company",
            "share": "99",
        },
        follow_redirects=False,
    )
    with app.app_context():
        row = db.session.execute(
            text("SELECT partner_scope, partner_share FROM customers WHERE id = :i"),
            {"i": foreign_cid},
        ).first()
        assert row.partner_scope in (None, "none"), (
            f"foreign partner was modified: scope={row.partner_scope}"
        )
