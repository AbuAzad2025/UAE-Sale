"""Persisted per-user notifications.

Revision ID: c15_persisted_notifications
Revises: c14_payroll_disbursement
"""
from alembic import op
import sqlalchemy as sa

revision = "c15_persisted_notifications"
down_revision = "c14_payroll_disbursement"
branch_labels = None
depends_on = None


def upgrade():
    from sqlalchemy import inspect as _inspect
    conn = op.get_bind()
    if "notifications" not in _inspect(conn).get_table_names():
        op.create_table(
            "notifications",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tenant_id", sa.Integer(), nullable=True),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("type", sa.String(20), nullable=False, server_default="info"),
            sa.Column("data_json", sa.Text(), nullable=True),
            sa.Column("read_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
        op.create_index("ix_notifications_tenant_id", "notifications", ["tenant_id"])
        op.create_index("ix_notifications_created_at", "notifications", ["created_at"])


def downgrade():
    op.drop_table("notifications")
