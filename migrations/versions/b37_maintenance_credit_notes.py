"""Maintenance credit notes — reverse invoice and allow returns after billing.

Revision ID: b37_maintenance_credit_notes
Revises: b36_maintenance_supplier_payments
"""

from alembic import op
import sqlalchemy as sa


revision = "b37_maintenance_credit_notes"
down_revision = "b36_maintenance_supplier_payments"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "maintenance_credit_notes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "maintenance_order_id",
            sa.Integer(),
            sa.ForeignKey("maintenance_orders.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "credit_note_no",
            sa.String(length=50),
            unique=True,
            nullable=False,
            index=True,
        ),
        sa.Column(
            "created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "total_value",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "posted", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("posted_at", sa.DateTime(), nullable=True),
        sa.Column(
            "gl_posted", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )


def downgrade():
    op.drop_table("maintenance_credit_notes")
