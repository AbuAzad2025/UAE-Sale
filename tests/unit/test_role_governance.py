"""Role hierarchy and unified-platform access regressions."""
import os
import re

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def test_maintenance_roles_have_explicit_privilege_levels():
    """Unlevelled maintenance roles could be granted by any account with
    manage_users, even though they carry maintenance write permissions."""
    src = _read("utils/decorators.py")
    for slug in ("maintenance_reception", "maintenance_engineer", "maintenance_cashier"):
        assert f'"{slug}"' in src


def test_no_subscription_gate_at_login():
    """A unified platform must not lock a tenant out for plan expiry."""
    src = _read("routes/auth.py")
    assert "is_subscription_active" not in src
    assert "انتهى اشتراك شركتك" not in src
    assert "Unified platform" in src


def test_role_resolution_rejects_another_tenants_role():
    src = _read("services/user_service.py")
    assert "الدور المختار لا يخص شركتك" in src
    assert "role.tenant_id != actor_tenant" in src


def test_viewer_role_is_read_only():
    src = _read("utils/system_init.py")
    start = src.index('"viewer": ("Viewer"')
    block = src[start : src.index("\n}", start)]
    codes = set(re.findall(r'"(view_[a-z_]+)"', block))
    assert codes == {"view_reports", "view_ledger", "view_products"}
    assert "manage_" not in block


def test_navbar_hides_links_the_user_cannot_open():
    """Visible sidebar links must match the route's actual permission gate."""
    src = _read("templates/base.html")
    manual = src[src.index("ledger.manual_entry") - 400 : src.index("ledger.manual_entry") + 200]
    assert "manage_ledger" in manual
    inv = src[src.index("reports.inventory_valuation") - 400 : src.index("reports.inventory_valuation") + 200]
    assert "can_see_costs" in inv
    recurring = src[src.index("erp_modules.recurring_expenses") - 400 : src.index("erp_modules.recurring_expenses") + 200]
    assert "manage_expenses" in recurring


def test_role_selector_is_ordered_and_level_limited():
    src = _read("routes/users.py")
    assert "_ROLE_LEVELS" in src
    assert "_role_level(r) <= level" in src
    assert "sorted(" in src


def test_role_escalation_guard_is_in_the_service():
    src = _read("services/user_service.py")
    assert "_role_level_of(role) > actor_level" in src
    assert "لا يمكنك منح دور أعلى من دورك" in src


def test_maintenance_role_consolidation_migration_exists():
    migrations = os.listdir(os.path.join(ROOT, "migrations", "versions"))
    assert any("maintenance_roles_consolidated" in m for m in migrations)
