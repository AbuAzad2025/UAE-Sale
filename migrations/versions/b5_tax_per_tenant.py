"""Full tax per tenant/country: country preset + inclusive/exclusive.

Revision ID: b5_tax_per_tenant
Revises: b4_due_dates_indexes
Adds tenants.tax_country / tenants.tax_inclusive, sales.tax_inclusive,
purchases.tax_inclusive as invoice snapshots (history-preserving).
"""

from alembic import op
import sqlalchemy as sa

revision = "b5_tax_per_tenant"
down_revision = "b4_due_dates_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenants", sa.Column("tax_country", sa.String(length=2), nullable=True)
    )
    op.add_column(
        "tenants",
        sa.Column(
            "tax_inclusive", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
    )
    op.add_column(
        "sales",
        sa.Column(
            "tax_inclusive", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
    )
    op.add_column(
        "purchases",
        sa.Column(
            "tax_inclusive", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
    )
    op.execute("UPDATE tenants SET tax_country='AE' WHERE tax_country IS NULL")


def downgrade() -> None:
    op.drop_column("purchases", "tax_inclusive")
    op.drop_column("sales", "tax_inclusive")
    op.drop_column("tenants", "tax_inclusive")
    op.drop_column("tenants", "tax_country")
