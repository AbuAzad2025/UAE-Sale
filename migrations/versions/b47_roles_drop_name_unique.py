"""Drop global unique constraint on roles.name (allow tenant-scoped duplicate names).

Revision ID: b47_roles_drop_name_unique
Revises: b46_error_log_drop_fk
Create Date: 2026-11-15
"""
from alembic import op
import sqlalchemy as sa

revision = "b47_roles_drop_name_unique"
down_revision = "b46_error_log_drop_fk"
branch_labels = None
depends_on = None


def upgrade():
    from sqlalchemy import inspect as _inspect

    conn = op.get_bind()
    inspector = _inspect(conn)

    existing_constraints = [c["name"] for c in inspector.get_unique_constraints("roles")]
    if "roles_name_key" in existing_constraints:
        op.drop_constraint("roles_name_key", "roles", type_="unique")


def downgrade():
    op.create_unique_constraint("roles_name_key", "roles", ["name"])
