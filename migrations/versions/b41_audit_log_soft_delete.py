"""Add is_archived column to audit_logs for soft-delete retention.

Revision ID: b41_audit_log_soft_delete
Revises: b40_tenant_bilingual_fields
Create Date: 2026-11-13
"""
from alembic import op
import sqlalchemy as sa

revision = "b41_audit_log_soft_delete"
down_revision = "b40_tenant_bilingual_fields"
branch_labels = None
depends_on = None


def upgrade():
    from sqlalchemy import inspect as _inspect

    conn = op.get_bind()
    inspector = _inspect(conn)
    cols = [c["name"] for c in inspector.get_columns("audit_logs")]
    if "is_archived" not in cols:
        op.add_column(
            "audit_logs",
            sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade():
    op.drop_column("audit_logs", "is_archived")