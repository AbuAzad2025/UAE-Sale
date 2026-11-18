"""Feature gates are REAL controls, not display-only flags.

Proves that tenant enable_* flags actually block/allow access to their
feature blueprints (maintenance / reports / ledger) over HTTP, and that a
user who has the permission but whose tenant lacks the feature still gets 403.
"""
import pytest


def _make_tenant_with_manager(db, slug, flags):
    from models import Tenant, User, Role
    from extensions import db as _db

    t = Tenant.query.filter_by(slug=slug).first()
    if not t:
        t = Tenant(name=f"Gate Test {slug}", slug=slug, name_ar=slug, is_active=True, **flags)
        db.session.add(t)
        db.session.commit()
    # ensure a manager role + user for this tenant
    from utils.system_init import _ensure_permissions, _ensure_operational_roles_for_tenant
    _ensure_permissions()
    _ensure_operational_roles_for_tenant(t.id)
    db.session.commit()
    mgr_role = Role.query.filter_by(slug="manager", tenant_id=t.id).first()
    u = User.query.filter_by(tenant_id=t.id, role_id=mgr_role.id).first() if mgr_role else None
    if not u:
        from models import User as U
        u = U(username=f"{slug}_gate_mgr", tenant_id=t.id, role_id=mgr_role.id, is_active=True)
        u.set_password("Test-password-123!")
        u.must_change_password = False
        db.session.add(u)
        db.session.commit()
    else:
        u.must_change_password = False
        db.session.commit()
    return t, u


@pytest.mark.parametrize("ep,flag", [
    ("/maintenance/", "enable_maintenance"),
    ("/reports/", "enable_reports"),
    ("/ledger/", "enable_gl"),
])
def test_feature_gate_blocks_when_disabled(client, db, ep, flag):
    """A tenant with the permission but WITHOUT the feature is blocked (403)."""
    slug = "gate-off-" + flag.replace("enable_", "")
    flags = dict(enable_maintenance=True, enable_reports=True, enable_gl=True)
    flags[flag] = False
    t, u = _make_tenant_with_manager(db, slug, flags)

    client.post("/auth/login", data={"username": u.username, "password": "Test-password-123!"})
    resp = client.get(ep, follow_redirects=False)
    assert resp.status_code == 403, (
        f"{ep} must be 403 when {flag}=False for tenant {t.slug}, got {resp.status_code}"
    )


@pytest.mark.parametrize("ep", ["/maintenance/", "/reports/", "/ledger/"])
def test_feature_gate_allows_when_enabled(client, db, ep):
    """A tenant WITH all features and a manager permission can access."""
    t, u = _make_tenant_with_manager(
        db, "gate-on-all",
        dict(enable_maintenance=True, enable_reports=True, enable_gl=True),
    )
    client.post("/auth/login", data={"username": u.username, "password": "Test-password-123!"})
    resp = client.get(ep, follow_redirects=False)
    assert resp.status_code == 200, (
        f"{ep} must be 200 when all features enabled for {t.slug}, got {resp.status_code}"
    )
