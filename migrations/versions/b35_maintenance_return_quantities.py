"""Maintenance returns: returned quantities on items and services.

Revision ID: b35_maintenance_return_quantities
Revises: b34_maintenance_warranty_expense
"""

from alembic import op
import sqlalchemy as sa


revision = "b35_maintenance_return_quantities"
down_revision = "b34_maintenance_warranty_expense"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "maintenance_order_items",
        sa.Column(
            "returned_quantity",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "maintenance_order_services",
        sa.Column(
            "quantity",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "maintenance_order_services",
        sa.Column(
            "returned_quantity",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade():
    op.drop_column("maintenance_order_services", "returned_quantity")
    op.drop_column("maintenance_order_services", "quantity")
    op.drop_column("maintenance_order_items", "returned_quantity")
