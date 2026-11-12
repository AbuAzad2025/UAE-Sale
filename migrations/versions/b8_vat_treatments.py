"""VAT treatments: product tax_treatment + sale snapshot.

Revision ID: b8_vat_treatments
Revises: b7_tenant_invoice_profile
standard = tenant default rate, zero = taxable at 0%, exempt = exempt.
Exempt is not synonymous with outside scope.
"""

from alembic import op
import sqlalchemy as sa

revision = "b8_vat_treatments"
down_revision = "b7_tenant_invoice_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column(
            "tax_treatment",
            sa.String(length=10),
            server_default="standard",
            nullable=False,
        ),
    )
    op.add_column(
        "sales",
        sa.Column(
            "tax_treatment",
            sa.String(length=10),
            server_default="standard",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("sales", "tax_treatment")
    op.drop_column("products", "tax_treatment")
