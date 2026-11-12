"""Add multi-currency support to maintenance module.

Revision ID: b38_maintenance_multi_currency
Revises: b37_maintenance_credit_notes
"""

from alembic import op
import sqlalchemy as sa


revision = "b38_maintenance_multi_currency"
down_revision = "b37_maintenance_credit_notes"
branch_labels = None
depends_on = None


def upgrade():
    # ===== MaintenanceOrder: currency fields =====
    op.add_column(
        "maintenance_orders",
        sa.Column(
            "currency", sa.String(length=3), nullable=False, server_default="AED"
        ),
    )
    op.add_column(
        "maintenance_orders",
        sa.Column(
            "exchange_rate",
            sa.Numeric(precision=15, scale=6),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "maintenance_orders",
        sa.Column(
            "amount_base",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "maintenance_orders",
        sa.Column(
            "subtotal_base",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "maintenance_orders",
        sa.Column(
            "tax_amount_base",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "maintenance_orders",
        sa.Column(
            "total_amount_base",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "maintenance_orders",
        sa.Column(
            "paid_amount_base",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "maintenance_orders",
        sa.Column(
            "balance_due_base",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
    )

    # ===== MaintenanceOrderItem: currency fields =====
    op.add_column(
        "maintenance_order_items",
        sa.Column("currency", sa.String(length=3), nullable=True),
    )
    op.add_column(
        "maintenance_order_items",
        sa.Column("exchange_rate", sa.Numeric(precision=15, scale=6), nullable=True),
    )
    op.add_column(
        "maintenance_order_items",
        sa.Column("amount_base", sa.Numeric(precision=15, scale=3), nullable=True),
    )

    # ===== MaintenanceOrderService: currency fields =====
    op.add_column(
        "maintenance_order_services",
        sa.Column("currency", sa.String(length=3), nullable=True),
    )
    op.add_column(
        "maintenance_order_services",
        sa.Column("exchange_rate", sa.Numeric(precision=15, scale=6), nullable=True),
    )
    op.add_column(
        "maintenance_order_services",
        sa.Column("amount_base", sa.Numeric(precision=15, scale=3), nullable=True),
    )

    # ===== MaintenanceReceipt: currency fields =====
    op.add_column(
        "maintenance_receipts",
        sa.Column("currency", sa.String(length=3), nullable=True),
    )
    op.add_column(
        "maintenance_receipts",
        sa.Column("exchange_rate", sa.Numeric(precision=15, scale=6), nullable=True),
    )
    op.add_column(
        "maintenance_receipts",
        sa.Column("amount_base", sa.Numeric(precision=15, scale=3), nullable=True),
    )

    # ===== MaintenanceInvoice: currency fields =====
    op.add_column(
        "maintenance_invoices",
        sa.Column("currency", sa.String(length=3), nullable=True),
    )
    op.add_column(
        "maintenance_invoices",
        sa.Column("exchange_rate", sa.Numeric(precision=15, scale=6), nullable=True),
    )
    op.add_column(
        "maintenance_invoices",
        sa.Column("amount_base", sa.Numeric(precision=15, scale=3), nullable=True),
    )
    op.add_column(
        "maintenance_invoices",
        sa.Column(
            "subtotal_base",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "maintenance_invoices",
        sa.Column(
            "tax_amount_base",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "maintenance_invoices",
        sa.Column(
            "total_amount_base",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "maintenance_invoices",
        sa.Column(
            "paid_amount_base",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "maintenance_invoices",
        sa.Column(
            "balance_due_base",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
    )

    # ===== MaintenanceReturn: currency fields =====
    op.add_column(
        "maintenance_returns", sa.Column("currency", sa.String(length=3), nullable=True)
    )
    op.add_column(
        "maintenance_returns",
        sa.Column("exchange_rate", sa.Numeric(precision=15, scale=6), nullable=True),
    )
    op.add_column(
        "maintenance_returns",
        sa.Column("amount_base", sa.Numeric(precision=15, scale=3), nullable=True),
    )
    op.add_column(
        "maintenance_returns",
        sa.Column(
            "total_value_base",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
    )

    # ===== MaintenanceCreditNote: currency fields =====
    op.add_column(
        "maintenance_credit_notes",
        sa.Column("currency", sa.String(length=3), nullable=True),
    )
    op.add_column(
        "maintenance_credit_notes",
        sa.Column("exchange_rate", sa.Numeric(precision=15, scale=6), nullable=True),
    )
    op.add_column(
        "maintenance_credit_notes",
        sa.Column("amount_base", sa.Numeric(precision=15, scale=3), nullable=True),
    )
    op.add_column(
        "maintenance_credit_notes",
        sa.Column(
            "total_value_base",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
    )

    # ===== MaintenanceSupplierPayment: currency fields =====
    op.add_column(
        "maintenance_supplier_payments",
        sa.Column("currency", sa.String(length=3), nullable=True),
    )
    op.add_column(
        "maintenance_supplier_payments",
        sa.Column("exchange_rate", sa.Numeric(precision=15, scale=6), nullable=True),
    )
    op.add_column(
        "maintenance_supplier_payments",
        sa.Column("amount_base", sa.Numeric(precision=15, scale=3), nullable=True),
    )


def downgrade():
    # Drop currency columns from maintenance_supplier_payments
    op.drop_column("maintenance_supplier_payments", "amount_base")
    op.drop_column("maintenance_supplier_payments", "exchange_rate")
    op.drop_column("maintenance_supplier_payments", "currency")

    # Drop currency columns from maintenance_credit_notes
    op.drop_column("maintenance_credit_notes", "total_value_base")
    op.drop_column("maintenance_credit_notes", "amount_base")
    op.drop_column("maintenance_credit_notes", "exchange_rate")
    op.drop_column("maintenance_credit_notes", "currency")

    # Drop currency columns from maintenance_returns
    op.drop_column("maintenance_returns", "total_value_base")
    op.drop_column("maintenance_returns", "amount_base")
    op.drop_column("maintenance_returns", "exchange_rate")
    op.drop_column("maintenance_returns", "currency")

    # Drop currency columns from maintenance_invoices
    op.drop_column("maintenance_invoices", "balance_due_base")
    op.drop_column("maintenance_invoices", "paid_amount_base")
    op.drop_column("maintenance_invoices", "total_amount_base")
    op.drop_column("maintenance_invoices", "tax_amount_base")
    op.drop_column("maintenance_invoices", "subtotal_base")
    op.drop_column("maintenance_invoices", "amount_base")
    op.drop_column("maintenance_invoices", "exchange_rate")
    op.drop_column("maintenance_invoices", "currency")

    # Drop currency columns from maintenance_receipts
    op.drop_column("maintenance_receipts", "amount_base")
    op.drop_column("maintenance_receipts", "exchange_rate")
    op.drop_column("maintenance_receipts", "currency")

    # Drop currency columns from maintenance_order_services
    op.drop_column("maintenance_order_services", "amount_base")
    op.drop_column("maintenance_order_services", "exchange_rate")
    op.drop_column("maintenance_order_services", "currency")

    # Drop currency columns from maintenance_order_items
    op.drop_column("maintenance_order_items", "amount_base")
    op.drop_column("maintenance_order_items", "exchange_rate")
    op.drop_column("maintenance_order_items", "currency")

    # Drop currency columns from maintenance_orders
    op.drop_column("maintenance_orders", "balance_due_base")
    op.drop_column("maintenance_orders", "paid_amount_base")
    op.drop_column("maintenance_orders", "total_amount_base")
    op.drop_column("maintenance_orders", "tax_amount_base")
    op.drop_column("maintenance_orders", "subtotal_base")
    op.drop_column("maintenance_orders", "amount_base")
    op.drop_column("maintenance_orders", "exchange_rate")
    op.drop_column("maintenance_orders", "currency")
