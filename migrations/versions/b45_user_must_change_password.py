"""Add must_change_password column to users table.

Revision ID: b45_user_must_change_password
Revises: b44_product_return_tenant_id
Create Date: 2026-11-13
"""
from alembic import op
import sqlalchemy as sa

revision = "b45_user_must_change_password"
down_revision = "b44_product_return_tenant_id"
branch_labels = None
depends_on = None


def upgrade():
    from sqlalchemy import inspect as _inspect

    conn = op.get_bind()
    inspector = _inspect(conn)
    cols = [c["name"] for c in inspector.get_columns("users")]
    if "must_change_password" not in cols:
        op.add_column(
            "users",
            sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade():
    op.drop_column("users", "must_change_password")