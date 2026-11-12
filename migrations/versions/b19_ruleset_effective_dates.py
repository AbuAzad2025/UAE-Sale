"""Effective-dated tax rulesets (rate changes apply from a document date).

Revision ID: b19_ruleset_effective_dates
Revises: b18_taxruleset_unique_defaults
"""

from alembic import op
import sqlalchemy as sa

revision = "b19_ruleset_effective_dates"
down_revision = "b18_taxruleset_unique_defaults"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tax_rulesets", sa.Column("effective_from", sa.Date(), nullable=True))
    op.add_column(
        "tax_rulesets", sa.Column("effective_until", sa.Date(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("tax_rulesets", "effective_until")
    op.drop_column("tax_rulesets", "effective_from")
