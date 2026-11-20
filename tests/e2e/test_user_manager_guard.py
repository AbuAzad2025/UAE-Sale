"""Tenant managers can create/edit/toggle their own users, never other tenants'.
"""
import uuid

from sqlalchemy import text
from utils.transaction import atomic_transaction


def _make_user(db, tenant_id, actor, role_id, tag):
    from models import User
    from services.user_service import UserService

    with atomic_transaction():
        u = UserService.provision_user(
            username=f"ug_{tag}", email=f"ug_{tag}@example.test",
            password="Str0ng-Pass-2026!", role_id=role_id,
            full_name="Guard Test", tenant_id=tenant_id, actor=actor,
        )
    return u.id


def _seller_role_id(db, tenant_id):
    from models import Role

    row = db.session.execute(
        text("SELECT id FROM roles WHERE slug='seller' AND "
             "(tenant_id=:t OR tenant_id IS NULL) ORDER BY tenant_id DESC NULLS LAST LIMIT 1"),
        {"t": tenant_id}).first()
    if row:
        return row.id
    role = Role(slug="seller", name="Seller", name_ar="بائع", tenant_id=tenant_id,
                is_active=True)
    db.session.add(role)
    db.session.commit()
    return role.id


def test_manager_never_sees_or_grants_platform_roles(client, login_as, app, db):
    mgr = login_as("manager")
    tag = uuid.uuid4().hex[:8]
    with app.app_context():
        roles = dict(db.session.execute(
            text("SELECT slug, id FROM roles WHERE slug IN ('owner','super_admin','developer')")
        ).all())
        # Ensure the owner role exists so the attack path is really tested.
        if "owner" not in roles:
            from models import Role

            r = Role(slug="owner", name="Owner", is_active=True)
            db.session.add(r)
            db.session.commit()
            roles["owner"] = r.id
        rid = _seller_role_id(db, mgr.tenant_id)
        uid = _make_user(db, mgr.tenant_id, mgr, rid, tag)

    for path in ("/users/create", f"/users/{uid}/edit"):
        body = client.get(path).get_data(as_text=True)
        start = body.find('name="role_id"')
        assert start >= 0
        role_select = body[start:body.find("</select>", start)]
        for slug in ("owner", "super_admin", "developer"):
            assert f'value="{roles.get(slug, -1)}"' not in role_select, (path, slug)

    before = db.session.execute(text("SELECT COUNT(*) FROM users")).scalar()
    resp = client.post("/users/create", data={
        "username": f"atk_{tag}", "email": f"atk_{tag}@example.test",
        "password": "Str0ng-Pass-2026!", "role_id": str(roles["owner"]),
        "full_name": "Attack", "is_active": "1",
    }, follow_redirects=False)
    with app.app_context():
        after = db.session.execute(text("SELECT COUNT(*) FROM users")).scalar()
        created = db.session.execute(
            text("SELECT is_owner FROM users WHERE username=:u"),
            {"u": f"atk_{tag}"}).first()
    assert created is None or not created.is_owner
    assert after == before or created is None


def test_manager_can_edit_and_toggle_own_user(client, login_as, app, db):
    mgr = login_as("manager")
    tag = uuid.uuid4().hex[:8]
    with app.app_context():
        rid = _seller_role_id(db, mgr.tenant_id)
        uid = _make_user(db, mgr.tenant_id, mgr, rid, tag)

    resp = client.get(f"/users/{uid}/edit")
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]

    resp = client.post(f"/users/{uid}/edit", data={
        "email": f"edited-{tag}@example.test", "full_name": "Edited Name",
        "full_name_ar": "", "phone": "", "role_id": str(rid),
    }, follow_redirects=False)
    assert resp.status_code in (302, 303), resp.get_data(as_text=True)[:300]

    with app.app_context():
        row = db.session.execute(
            text("SELECT email, full_name, tenant_id FROM users WHERE id=:i"),
            {"i": uid}).first()
        assert row.email == f"edited-{tag}@example.test"
        assert row.tenant_id == mgr.tenant_id

    resp = client.post(f"/users/{uid}/toggle-active")
    assert resp.status_code in (302, 303)
    with app.app_context():
        active = db.session.execute(
            text("SELECT is_active FROM users WHERE id=:i"), {"i": uid}).scalar()
        assert not active


def test_manager_cannot_edit_foreign_user(client, login_as, app, db):
    mgr = login_as("manager")
    tag = uuid.uuid4().hex[:8]
    with app.app_context():
        from models import Tenant

        other = db.session.execute(
            text("SELECT id FROM tenants WHERE id != :t ORDER BY id LIMIT 1"),
            {"t": mgr.tenant_id}).first()
        if other is None:
            t = Tenant(name=f"O {tag}", name_ar=f"O {tag}", slug=f"o-{tag}", is_active=True)
            db.session.add(t)
            db.session.commit()
            other_tid = t.id
        else:
            other_tid = other.id
        rid = _seller_role_id(db, other_tid)
        foreign_uid = _make_user(db, other_tid, mgr, rid, tag)

    resp = client.get(f"/users/{foreign_uid}/edit")
    assert resp.status_code == 404
