"""Make leave-type uniqueness tenant-scoped.

Revision ID: c06_leave_types_per_tenant
Revises: c05_manager_ledger_permission

The global UNIQUE(name)/UNIQUE(code) on leave_types made it impossible for a
second tenant to seed its own "Annual Leave" — ensure_default_leave_types()
raised IntegrityError (500 on /hr/leave-types, /hr/leave/create).
"""
from alembic import op
import sqlalchemy as sa

revision = "c06_leave_types_per_tenant"
down_revision = "c05_manager_ledger_permission"
branch_labels = None
depends_on = None


def _names():
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("leave_types")}


def _constraints():
    return {c["name"] for c in sa.inspect(op.get_bind()).get_unique_constraints("leave_types")}


def upgrade():
    cons = _constraints()
    if "leave_types_name_key" in cons:
        op.drop_constraint("leave_types_name_key", "leave_types", type_="unique")
    if "leave_types_code_key" in cons:
        op.drop_constraint("leave_types_code_key", "leave_types", type_="unique")
    if "uq_leave_types_tenant_name" not in _constraints():
        op.create_unique_constraint(
            "uq_leave_types_tenant_name", "leave_types", ["tenant_id", "name"]
        )
    if "uq_leave_types_tenant_code" not in _constraints():
        op.create_unique_constraint(
            "uq_leave_types_tenant_code", "leave_types", ["tenant_id", "code"]
        )


def downgrade():
    cons = _constraints()
    for name in ("uq_leave_types_tenant_code", "uq_leave_types_tenant_name"):
        if name in cons:
            op.drop_constraint(name, "leave_types", type_="unique")
    op.create_unique_constraint("leave_types_name_key", "leave_types", ["name"])
    op.create_unique_constraint("leave_types_code_key", "leave_types", ["code"])
