"""Maintenance Module Core Tables (M1).

Revision ID: b29_maintenance_core
Revises: b28_maintenance_prep
"""

from alembic import op
import sqlalchemy as sa

revision = "b29_maintenance_core"
down_revision = "b28_maintenance_prep"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # maintenance_orders — رأس أمر الصيانة
    # ------------------------------------------------------------------
    op.create_table(
        "maintenance_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "branch_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "order_no", sa.String(length=50), unique=True, nullable=False, index=True
        ),
        sa.Column(
            "customer_id",
            sa.Integer(),
            sa.ForeignKey("customers.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("device_brand", sa.String(length=100), nullable=True),
        sa.Column("device_model", sa.String(length=100), nullable=True),
        sa.Column("device_serial", sa.String(length=100), nullable=True, index=True),
        sa.Column("device_imei", sa.String(length=100), nullable=True),
        sa.Column("device_plate", sa.String(length=50), nullable=True),
        sa.Column("device_problem", sa.Text(), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="received",
            index=True,
        ),
        sa.Column(
            "priority", sa.String(length=20), nullable=False, server_default="normal"
        ),
        sa.Column("warranty_status", sa.String(length=20), nullable=True),
        sa.Column(
            "warranty_checked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "warranty_verified_by",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("warranty_checked_at", sa.DateTime(), nullable=True),
        sa.Column("warranty_notes", sa.Text(), nullable=True),
        sa.Column("color_tag", sa.String(length=20), nullable=True),
        sa.Column(
            "warranty_sale_id", sa.Integer(), sa.ForeignKey("sales.id"), nullable=True
        ),
        sa.Column(
            "received_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "engineer_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column(
            "service_advisor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column(
            "payment_mode", sa.String(length=20), nullable=False, server_default="cash"
        ),
        sa.Column(
            "deposit",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "tax_inclusive",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "subtotal",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "discount_line_total",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "discount_total_value",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "discount_total_percent",
            sa.Numeric(precision=5, scale=2),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "tax_amount",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_amount",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "paid_amount",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "balance_due",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "is_archived", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column(
            "archived_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            onupdate=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    # ------------------------------------------------------------------
    # maintenance_order_items — بنود القطع
    # ------------------------------------------------------------------
    op.create_table(
        "maintenance_order_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "maintenance_order_id",
            sa.Integer(),
            sa.ForeignKey("maintenance_orders.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "product_id",
            sa.Integer(),
            sa.ForeignKey("products.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "warehouse_id", sa.Integer(), sa.ForeignKey("warehouses.id"), nullable=True
        ),
        sa.Column(
            "quantity",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "unit_price",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "discount_percent",
            sa.Numeric(precision=5, scale=2),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "discount_value",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "line_discount_mode",
            sa.String(length=10),
            nullable=False,
            server_default="percent",
        ),
        sa.Column(
            "tax_rate",
            sa.Numeric(precision=5, scale=2),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "tax_amount",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "line_total",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "movement_id",
            sa.Integer(),
            sa.ForeignKey("stock_movements.id"),
            nullable=True,
        ),
    )

    # ------------------------------------------------------------------
    # maintenance_order_services — الخدمات (ميكانيك/كهرباء/جهد/أخرى)
    # ------------------------------------------------------------------
    op.create_table(
        "maintenance_order_services",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "maintenance_order_id",
            sa.Integer(),
            sa.ForeignKey("maintenance_orders.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("service_code", sa.String(length=50), nullable=True),
        sa.Column("service_name", sa.String(length=200), nullable=False),
        sa.Column("service_name_ar", sa.String(length=200), nullable=True),
        sa.Column(
            "unit_price",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
        sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "discount_percent",
            sa.Numeric(precision=5, scale=2),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "discount_value",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "tax_rate",
            sa.Numeric(precision=5, scale=2),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "tax_amount",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "line_total",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "engineer_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True
        ),
    )

    # ------------------------------------------------------------------
    # maintenance_order_status_log — سجل انتقال الحالات
    # ------------------------------------------------------------------
    op.create_table(
        "maintenance_order_status_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "maintenance_order_id",
            sa.Integer(),
            sa.ForeignKey("maintenance_orders.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("from_status", sa.String(length=20), nullable=True),
        sa.Column("to_status", sa.String(length=20), nullable=False),
        sa.Column(
            "changed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "changed_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("note", sa.Text(), nullable=True),
    )

    # ------------------------------------------------------------------
    # maintenance_receipts — سندات القبض (استقبال فقط)
    # ------------------------------------------------------------------
    op.create_table(
        "maintenance_receipts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "maintenance_order_id",
            sa.Integer(),
            sa.ForeignKey("maintenance_orders.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "receipt_no", sa.String(length=50), unique=True, nullable=False, index=True
        ),
        sa.Column(
            "amount",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
        sa.Column("payment_method", sa.String(length=20), nullable=False),
        sa.Column(
            "cashier_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("reference_type", sa.String(length=50), nullable=True),
        sa.Column("reference_id", sa.Integer(), nullable=True),
        sa.Column(
            "posted", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("posted_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    # ------------------------------------------------------------------
    # maintenance_invoices — فواتير الصيانة (مستقلة)
    # ------------------------------------------------------------------
    op.create_table(
        "maintenance_invoices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "maintenance_order_id",
            sa.Integer(),
            sa.ForeignKey("maintenance_orders.id"),
            nullable=False,
            index=True,
            unique=True,
        ),
        sa.Column(
            "invoice_no", sa.String(length=50), unique=True, nullable=False, index=True
        ),
        sa.Column(
            "subtotal",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "discount_total",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "tax_amount",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_amount",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "paid_amount",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "balance_due",
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

    # ------------------------------------------------------------------
    # maintenance_returns — مرتجعات الصيانة
    # ------------------------------------------------------------------
    op.create_table(
        "maintenance_returns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "maintenance_order_id",
            sa.Integer(),
            sa.ForeignKey("maintenance_orders.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "return_no", sa.String(length=50), unique=True, nullable=False, index=True
        ),
        sa.Column(
            "returned_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False
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
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    # ------------------------------------------------------------------
    # maintenance_return_lines — بنود المرتجعات
    # ------------------------------------------------------------------
    op.create_table(
        "maintenance_return_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "return_id",
            sa.Integer(),
            sa.ForeignKey("maintenance_returns.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "order_item_id",
            sa.Integer(),
            sa.ForeignKey("maintenance_order_items.id"),
            nullable=True,
        ),
        sa.Column(
            "order_service_id",
            sa.Integer(),
            sa.ForeignKey("maintenance_order_services.id"),
            nullable=True,
        ),
        sa.Column(
            "quantity",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "unit_price",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "line_total",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
    )

    # ------------------------------------------------------------------
    # maintenance_settings — إعدادات الصيانة لكل تينانت
    # ------------------------------------------------------------------
    op.create_table(
        "maintenance_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id"),
            nullable=False,
            index=True,
            unique=True,
        ),
        sa.Column(
            "default_warehouse_id",
            sa.Integer(),
            sa.ForeignKey("warehouses.id"),
            nullable=True,
        ),
        sa.Column("maintenance_ar_account_id", sa.Integer(), nullable=True),
        sa.Column("maintenance_revenue_account_id", sa.Integer(), nullable=True),
        sa.Column(
            "max_discount_percent",
            sa.Numeric(precision=5, scale=2),
            nullable=False,
            server_default="15",
        ),
        sa.Column(
            "max_discount_value",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="500",
        ),
        sa.Column(
            "require_warranty_check",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "color_warranty",
            sa.String(length=20),
            nullable=False,
            server_default="'#10b981'",
        ),
        sa.Column(
            "color_non_warranty",
            sa.String(length=20),
            nullable=False,
            server_default="'#ef4444'",
        ),
        sa.Column(
            "color_unknown",
            sa.String(length=20),
            nullable=False,
            server_default="'#f59e0b'",
        ),
        sa.Column(
            "allow_engineer_cancel_warranty",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "allow_engineer_restore_warranty",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            onupdate=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    # ------------------------------------------------------------------
    # maintenance_services — الخدمات الثابتة السعر (لوحة المشرف)
    # ------------------------------------------------------------------
    op.create_table(
        "maintenance_services",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("service_code", sa.String(length=20), nullable=False, index=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("name_ar", sa.String(length=200), nullable=True),
        sa.Column(
            "category", sa.String(length=20), nullable=False, server_default="other"
        ),
        sa.Column(
            "fixed_price",
            sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default="0",
        ),
        sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "tax_rate",
            sa.Numeric(precision=5, scale=2),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "requires_parts",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            onupdate=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_maintenance_services_tenant_code",
        "maintenance_services",
        ["tenant_id", "service_code"],
        unique=True,
    )

    # ------------------------------------------------------------------
    # maintenance_warranty_audit — تدقيق الكفالات
    # ------------------------------------------------------------------
    op.create_table(
        "maintenance_warranty_audit",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "maintenance_order_id",
            sa.Integer(),
            sa.ForeignKey("maintenance_orders.id"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=True
        ),
        sa.Column("serial_number", sa.String(length=100), nullable=True, index=True),
        sa.Column(
            "action", sa.String(length=20), nullable=False
        ),  # checked/voided/restored
        sa.Column(
            "performed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "performed_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("before_status", sa.String(length=20), nullable=True),
        sa.Column("after_status", sa.String(length=20), nullable=True),
    )

    # ------------------------------------------------------------------
    # maintenance_device_registry — سجل الأجهزة
    # ------------------------------------------------------------------
    op.create_table(
        "maintenance_device_registry",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "customer_id",
            sa.Integer(),
            sa.ForeignKey("customers.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=True
        ),
        sa.Column("serial_number", sa.String(length=100), nullable=True, index=True),
        sa.Column("imei", sa.String(length=100), nullable=True, index=True),
        sa.Column("plate", sa.String(length=50), nullable=True, index=True),
        sa.Column("brand", sa.String(length=100), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("purchase_date", sa.Date(), nullable=True),
        sa.Column("warranty_end_date", sa.Date(), nullable=True),
        sa.Column("warranty_type", sa.String(length=50), nullable=True),
        sa.Column(
            "is_under_warranty",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("warranty_notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            onupdate=sa.text("CURRENT_TIMESTAMP"),
        ),
    )


def downgrade() -> None:
    op.drop_table("maintenance_device_registry")
    op.drop_table("maintenance_warranty_audit")
    op.drop_index(
        "ix_maintenance_services_tenant_code", table_name="maintenance_services"
    )
    op.drop_table("maintenance_services")
    op.drop_table("maintenance_settings")
    op.drop_table("maintenance_return_lines")
    op.drop_table("maintenance_returns")
    op.drop_table("maintenance_invoices")
    op.drop_table("maintenance_receipts")
    op.drop_table("maintenance_order_status_log")
    op.drop_table("maintenance_order_services")
    op.drop_table("maintenance_order_items")
    op.drop_table("maintenance_orders")
