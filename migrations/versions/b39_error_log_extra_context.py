"""Add extra_context column to error_logs table.

Revision ID: b39_error_log_extra_context
Revises: b38_maintenance_multi_currency
Create Date: 2026-11-13
"""

from alembic import op
import sqlalchemy as sa

revision = "b39_error_log_extra_context"
down_revision = "b38_maintenance_multi_currency"
branch_labels = None
depends_on = None


def upgrade():
    # Idempotent: skip if column already exists
    from sqlalchemy import inspect as _inspect

    conn = op.get_bind()
    inspector = _inspect(conn)
    cols = [c["name"] for c in inspector.get_columns("error_logs")]
    if "extra_context" not in cols:
        op.add_column(
            "error_logs", sa.Column("extra_context", sa.Text(), nullable=True)
        )


def downgrade():
    op.drop_column("error_logs", "extra_context")
