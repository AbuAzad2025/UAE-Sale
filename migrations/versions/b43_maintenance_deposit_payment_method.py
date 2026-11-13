"""Add deposit_payment_method column to maintenance_orders.

Revision ID: b43_maintenance_deposit_payment_method
Revises: b42_role_tenant_unique
Create Date: 2026-11-13
"""
from alembic import op
import sqlalchemy as sa

revision = "b43_maintenance_deposit_payment_method"
down_revision = "b42_role_tenant_unique"
branch_labels = None
depends_on = None


def upgrade():
    from sqlalchemy import inspect as _inspect

    conn = op.get_bind()
    inspector = _inspect(conn)
    cols = [c["name"] for c in inspector.get_columns("maintenance_orders")]
    if "deposit_payment_method" not in cols:
        op.add_column(
            "maintenance_orders",
            sa.Column("deposit_payment_method", sa.String(20), nullable=True),
        )


def downgrade():
    op.drop_column("maintenance_orders", "deposit_payment_method")