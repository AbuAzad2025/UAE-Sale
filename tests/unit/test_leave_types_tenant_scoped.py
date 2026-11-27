"""Leave types must be seedable independently per tenant (no global name clash)."""

from decimal import Decimal  # noqa: F401  (kept for consistency with suite)


def test_default_leave_types_seed_per_tenant(db):
    from models import set_current_tenant_id
    from models.hr import LeaveType
    from services.hr_service import HRService

    from models import Tenant

    for slug in ("leave-a", "leave-b"):
        tenant = Tenant(name_ar=slug, name=slug, slug=slug)
        db.session.add(tenant)
        db.session.flush()
        set_current_tenant_id(tenant.id)
        HRService.ensure_default_leave_types()
        assert LeaveType.query.filter_by(code="annual").count() == 1
        assert LeaveType.query.count() == 6


def test_migration_makes_leave_types_tenant_scoped():
    import os

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    path = os.path.join(root, "migrations", "versions", "c06_leave_types_per_tenant.py")
    assert os.path.isfile(path)
    src = open(path, encoding="utf-8").read()
    assert "tenant_id" in src and "uq_leave_types_tenant_name" in src
