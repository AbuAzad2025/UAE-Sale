"""HR tenant scope.

Revision ID: b12_hr_tenant
Revises: b11_expense_tenant

Backfill note: prior installs carry nullable tenant rows; those rows stay
platform-owner-only and must be assigned a tenant manually before tenant
users can see them. Nullable is deliberate — there is no safe default.
"""

from alembic import op
import sqlalchemy as sa

revision = "b12_hr_tenant"
down_revision = "b11_expense_tenant"
branch_labels = None
depends_on = None

_TABLES = (
    "departments",
    "employees",
    "leave_types",
    "leave_requests",
    "payslips",
    "payslip_lines",
)


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column(
                "tenant_id",
                sa.Integer(),
                sa.ForeignKey("tenants.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.create_index(f"idx_{table}_tenant", table, ["tenant_id"])


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.drop_index(f"idx_{table}_tenant", table_name=table)
        op.drop_column(table, "tenant_id")
