"""Expense VAT controls: per-document tax treatment, recoverability, reverse charge.

Revision ID: b20_expense_tax
Revises: b19_ruleset_effective_dates
"""

from alembic import op
import sqlalchemy as sa

revision = "b20_expense_tax"
down_revision = "b19_ruleset_effective_dates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "expenses",
        sa.Column(
            "tax_treatment",
            sa.String(length=10),
            nullable=False,
            server_default="standard",
        ),
    )
    op.add_column(
        "expenses",
        sa.Column("tax_rate", sa.Numeric(5, 2), nullable=False, server_default="0"),
    )
    op.add_column(
        "expenses",
        sa.Column(
            "tax_inclusive", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "expenses",
        sa.Column(
            "vat_recoverable", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
    )
    op.add_column(
        "expenses",
        sa.Column(
            "reverse_charge", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "expenses",
        sa.Column("tax_amount", sa.Numeric(15, 3), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("expenses", "tax_amount")
    op.drop_column("expenses", "reverse_charge")
    op.drop_column("expenses", "vat_recoverable")
    op.drop_column("expenses", "tax_inclusive")
    op.drop_column("expenses", "tax_rate")
    op.drop_column("expenses", "tax_treatment")
