"""Drop FK constraint on error_logs.tenant_id to allow sentinel values (-1).

Revision ID: b46_error_log_drop_fk
Revises: b45_user_must_change_password
Create Date: 2026-11-14
"""
from alembic import op
import sqlalchemy as sa

revision = "b46_error_log_drop_fk"
down_revision = "b45_user_must_change_password"
branch_labels = None
depends_on = None


def upgrade():
    from sqlalchemy import inspect as _inspect

    conn = op.get_bind()
    inspector = _inspect(conn)

    # Drop the FK constraint if it exists
    fks = inspector.get_foreign_keys("error_logs")
    for fk in fks:
        if "tenant_id" in fk.get("constrained_columns", []):
            op.drop_constraint(fk["name"], "error_logs", type_="foreignkey")

    # Also update the model definition (remove FK from column)
    # This is handled by the model change below


def downgrade():
    op.create_foreign_key(
        "error_logs_tenant_id_fkey",
        "error_logs",
        "tenants",
        ["tenant_id"],
        ["id"],
    )
