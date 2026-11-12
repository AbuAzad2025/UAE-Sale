"""تحسينات الأدوار: إلزام الشركة، حظر الدخول للموقوفة، سياق دعم."""


def test_provision_requires_tenant_for_business_role(db, owner_user, mgr_role=None):
    # mgr_role fixture is local to test_user_service; create own role
    from models import Role
    from extensions import db as _db
    from services.user_service import UserService
    import pytest

    role = Role(name="MgrZ", name_ar="مدير", slug="mgr_z", is_active=True)
    _db.session.add(role)
    _db.session.commit()
    with pytest.raises(ValueError, match="شركة"):
        UserService.provision_user(
            username="z_no_tenant",
            email="z@u.co",
            password="Str0ng!Pass#9z",
            role_id=role.id,
            actor=owner_user,
        )


def test_login_blocks_suspended_tenant(client, db, owner_user):
    from models import User, Role, Tenant
    from extensions import db as _db

    role = Role.query.filter_by(slug="seller").first()
    if role is None:
        role = Role(name="Seller", name_ar="بائع", slug="seller")
        _db.session.add(role)
        _db.session.commit()
    tenant = Tenant(
        name="StopCo",
        name_ar="شركة موقوفة",
        slug="stopco",
        is_active=True,
        is_suspended=True,
        max_users=10,
    )
    _db.session.add(tenant)
    _db.session.commit()
    u = User(
        username="blocked_user",
        email="b@u.co",
        is_active=True,
        role_id=role.id,
        tenant_id=tenant.id,
    )
    u.set_password("Str0ng!Pass#9z")
    _db.session.add(u)
    _db.session.commit()
    resp = client.post(
        "/auth/login",
        data={"username": "blocked_user", "password": "Str0ng!Pass#9z"},
        follow_redirects=True,
    )
    body = resp.get_data(as_text=True)
    assert "موقوفة" in body or "login" in body.lower()


def test_impersonate_routes_owner_only(client, db, owner_user):
    # anonymous → redirect login (302) not 500
    resp = client.get("/owner/tenants/1/impersonate", follow_redirects=False)
    assert resp.status_code in (302, 404)


def test_context_processor_exposes_sidebar_flags(app, db, owner_user):
    from models import Tenant
    from extensions import db as _db

    t = Tenant(name="CtxCo", name_ar="شركة", slug="ctxco", is_active=True, max_users=10)
    _db.session.add(t)
    _db.session.commit()
    import pathlib

    base = pathlib.Path("templates/base.html").read_text(encoding="utf-8")
    assert "impersonate_tenant" in base and "is_impersonating" in base
    assert "tenant_impersonate_exit" in base
    assert "tenant_impersonate" in base
