"""Maintenance M3: Cost fields for items, services, and orders.

Revision ID: b31_maintenance_cost_fields
Revises: b30_maintenance_rating_warranty
"""

from alembic import op
import sqlalchemy as sa

revision = "b31_maintenance_cost_fields"
down_revision = "b30_maintenance_rating_warranty"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Cost fields on order items
    op.add_column(
        "maintenance_order_items",
        sa.Column(
            "cost_price",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "maintenance_order_items",
        sa.Column(
            "cost_source",
            sa.String(length=50),
            nullable=False,
            server_default="inventory",
        ),
    )

    # Cost fields on order services
    op.add_column(
        "maintenance_order_services",
        sa.Column(
            "cost_price",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "maintenance_order_services",
        sa.Column(
            "cost_source", sa.String(length=50), nullable=False, server_default="labor"
        ),
    )

    # Cost fields on orders
    op.add_column(
        "maintenance_orders",
        sa.Column(
            "cost_price_total",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "maintenance_orders",
        sa.Column(
            "selling_price_total",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "maintenance_orders", sa.Column("technician_notes", sa.Text(), nullable=True)
    )
    op.add_column(
        "maintenance_orders",
        sa.Column(
            "quality_check_passed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "maintenance_orders",
        sa.Column(
            "quality_check_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True
        ),
    )
    op.add_column(
        "maintenance_orders",
        sa.Column("quality_check_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "maintenance_orders",
        sa.Column(
            "completion_time_hours", sa.Numeric(precision=10, scale=2), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("maintenance_orders", "completion_time_hours")
    op.drop_column("maintenance_orders", "quality_check_at")
    op.drop_column("maintenance_orders", "quality_check_by")
    op.drop_column("maintenance_orders", "quality_check_passed")
    op.drop_column("maintenance_orders", "technician_notes")
    op.drop_column("maintenance_orders", "selling_price_total")
    op.drop_column("maintenance_orders", "cost_price_total")
    op.drop_column("maintenance_order_services", "cost_source")
    op.drop_column("maintenance_order_services", "cost_price")
    op.drop_column("maintenance_order_items", "cost_source")
    op.drop_column("maintenance_order_items", "cost_price")
