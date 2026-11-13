"""Add tenant_id column to product_returns and product_return_lines.

Revision ID: b44_product_return_tenant_id
Revises: b43_maintenance_deposit_payment_method
Create Date: 2026-11-13
"""
from alembic import op
import sqlalchemy as sa

revision = "b44_product_return_tenant_id"
down_revision = "b43_maintenance_deposit_payment_method"
branch_labels = None
depends_on = None


def upgrade():
    from sqlalchemy import inspect as _inspect

    conn = op.get_bind()
    inspector = _inspect(conn)

    # product_returns
    cols = [c["name"] for c in inspector.get_columns("product_returns")]
    if "tenant_id" not in cols:
        op.add_column(
            "product_returns",
            sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=True),
        )
        op.create_index("ix_product_returns_tenant_id", "product_returns", ["tenant_id"])

    # product_return_lines
    cols = [c["name"] for c in inspector.get_columns("product_return_lines")]
    if "tenant_id" not in cols:
        op.add_column(
            "product_return_lines",
            sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=True),
        )
        op.create_index("ix_product_return_lines_tenant_id", "product_return_lines", ["tenant_id"])


def downgrade():
    op.drop_index("ix_product_return_lines_tenant_id", table_name="product_return_lines")
    op.drop_column("product_return_lines", "tenant_id")
    op.drop_index("ix_product_returns_tenant_id", table_name="product_returns")
    op.drop_column("product_returns", "tenant_id")