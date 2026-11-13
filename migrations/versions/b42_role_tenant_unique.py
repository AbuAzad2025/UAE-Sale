"""Fix roles unique constraint: replace global slug unique with composite (tenant_id, slug).

Revision ID: b42_role_tenant_unique
Revises: b41_audit_log_soft_delete
Create Date: 2026-11-13
"""
from alembic import op
import sqlalchemy as sa

revision = "b42_role_tenant_unique"
down_revision = "b41_audit_log_soft_delete"
branch_labels = None
depends_on = None


def upgrade():
    from sqlalchemy import inspect as _inspect

    conn = op.get_bind()
    inspector = _inspect(conn)

    # Drop the old global unique index on slug if it exists
    existing_indexes = [idx["name"] for idx in inspector.get_indexes("roles")]
    if "ix_roles_slug" in existing_indexes:
        # Check if it's unique
        for idx in inspector.get_indexes("roles"):
            if idx["name"] == "ix_roles_slug" and idx.get("unique"):
                op.drop_index("ix_roles_slug", table_name="roles")
                op.create_index("ix_roles_slug", "roles", ["slug"], unique=False)
                break

    # Add composite unique constraint if not exists
    existing_constraints = [c["name"] for c in inspector.get_unique_constraints("roles")]
    if "uq_role_tenant_slug" not in existing_constraints:
        op.create_unique_constraint("uq_role_tenant_slug", "roles", ["tenant_id", "slug"])


def downgrade():
    op.drop_constraint("uq_role_tenant_slug", "roles", type_="unique")
    op.drop_index("ix_roles_slug", table_name="roles")
    op.create_index("ix_roles_slug", "roles", ["slug"], unique=True)