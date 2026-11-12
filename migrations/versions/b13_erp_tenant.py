"""ERP modules tenant scope.

Revision ID: b13_erp_tenant
Revises: b12_hr_tenant

Adds nullable tenant_id + index to all business-document tables in
erp_modules. Backfill policy: rows that were created before tenancy existed
stay NULL — platform owner only — and require manual tenant assignment.
"""

from alembic import op
import sqlalchemy as sa

revision = "b13_erp_tenant"
down_revision = "b12_hr_tenant"
branch_labels = None
depends_on = None

_TABLES = (
    "quotations",
    "quotation_lines",
    "purchase_orders",
    "purchase_order_lines",
    "stock_transfers",
    "stock_transfer_lines",
    "stock_takes",
    "stock_take_items",
    "dunning_letters",
    "recurring_expenses",
    "product_lots",
    "warehouse_bins",
    "product_bins",
    "e_invoices",
)


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column(
                "tenant_id",
                sa.Integer(),
                sa.ForeignKey("tenants.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.create_index(f"idx_{table}_tenant", table, ["tenant_id"])


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.drop_index(f"idx_{table}_tenant", table_name=table)
        op.drop_column(table, "tenant_id")
