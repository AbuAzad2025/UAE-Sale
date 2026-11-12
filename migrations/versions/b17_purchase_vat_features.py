"""Purchase VAT features: per-line tax treatment, recoverability flag, reverse charge.

Revision ID: b17_purchase_vat_features
Revises: b16_tax_rulesets
"""

from alembic import op
import sqlalchemy as sa

revision = "b17_purchase_vat_features"
down_revision = "b16_tax_rulesets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "purchase_lines",
        sa.Column(
            "tax_treatment",
            sa.String(length=10),
            nullable=False,
            server_default="standard",
        ),
    )
    op.add_column(
        "purchases",
        sa.Column(
            "vat_recoverable", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
    )
    op.add_column(
        "purchases",
        sa.Column(
            "reverse_charge", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    # كل بند يرث المعاملة من ترويسة الفاتورة — لا نرمي أي بند في 'standard' افتراضيًا
    op.execute(
        "UPDATE purchase_lines SET tax_treatment = COALESCE("
        "(SELECT tax_treatment FROM purchases WHERE purchases.id = purchase_lines.purchase_id),"
        " 'standard')"
    )


def downgrade() -> None:
    op.drop_column("purchases", "reverse_charge")
    op.drop_column("purchases", "vat_recoverable")
    op.drop_column("purchase_lines", "tax_treatment")
