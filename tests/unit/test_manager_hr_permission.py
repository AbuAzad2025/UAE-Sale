"""Manager is the tenant admin: HR is in scope, owner/platform screens are not."""
from utils.system_init import OPERATIONAL_ROLES


def test_manager_role_includes_manage_hr():
    codes = OPERATIONAL_ROLES["manager"][2]
    assert "manage_hr" in codes


def test_manager_role_has_full_tenant_permissions():
    codes = OPERATIONAL_ROLES["manager"][2]
    assert "manage_ledger" in codes
    for code in (
        "manage_sales", "manage_purchases", "manage_products",
        "manage_customers", "manage_suppliers", "manage_payments",
        "manage_expenses", "manage_warehouse", "manage_users",
        "manage_settings", "manage_approvals", "manage_budget",
        "manage_hr", "view_ledger", "view_reports", "view_costs",
    ):
        assert code in codes, code


def test_manager_role_still_excludes_platform_admin():
    codes = OPERATIONAL_ROLES["manager"][2]
    assert "admin" not in codes
    assert "manage_backups" not in codes


def test_migration_backfills_existing_manager_roles():
    import os

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    for name, code in (
        ("c04_manager_hr_permission.py", "manage_hr"),
        ("c05_manager_ledger_permission.py", "manage_ledger"),
    ):
        path = os.path.join(root, "migrations", "versions", name)
        assert os.path.isfile(path)
        src = open(path, encoding="utf-8").read()
        assert code in src and "role_permissions" in src
