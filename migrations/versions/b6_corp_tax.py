"""Corporate tax per tenant (UAE 9% above threshold) + allowed currencies.

Revision ID: b6_corp_tax
Revises: b5_tax_per_tenant
"""

from alembic import op
import sqlalchemy as sa

revision = "b6_corp_tax"
down_revision = "b5_tax_per_tenant"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "corp_tax_enabled", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "corp_tax_rate", sa.Numeric(5, 2), server_default="9.00", nullable=True
        ),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "corp_tax_threshold",
            sa.Numeric(15, 2),
            server_default="375000.00",
            nullable=True,
        ),
    )
    op.add_column("tenants", sa.Column("allowed_currencies", sa.Text(), nullable=True))
    # A schema migration must not change an established accounting base
    # currency. Existing deployments that already ran the old migration need
    # a separate, reviewed investigation; do not silently reverse it here.


def downgrade() -> None:
    op.drop_column("tenants", "allowed_currencies")
    op.drop_column("tenants", "corp_tax_threshold")
    op.drop_column("tenants", "corp_tax_rate")
    op.drop_column("tenants", "corp_tax_enabled")
