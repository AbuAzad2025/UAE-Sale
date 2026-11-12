"""Maintenance supplier payments (settlement of maintenance payables).

Revision ID: b36_maintenance_supplier_payments
Revises: b35_maintenance_return_quantities
"""

from alembic import op
import sqlalchemy as sa


revision = "b36_maintenance_supplier_payments"
down_revision = "b35_maintenance_return_quantities"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "maintenance_supplier_payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "supplier_id",
            sa.Integer(),
            sa.ForeignKey("suppliers.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "amount",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "payment_method",
            sa.String(length=20),
            nullable=False,
            server_default="cash",
        ),
        sa.Column("reference_number", sa.String(length=50), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "posted", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("posted_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_maintenance_supplier_payments_tenant_supplier",
        "maintenance_supplier_payments",
        ["tenant_id", "supplier_id"],
    )


def downgrade():
    op.drop_index(
        "ix_maintenance_supplier_payments_tenant_supplier",
        table_name="maintenance_supplier_payments",
    )
    op.drop_table("maintenance_supplier_payments")
