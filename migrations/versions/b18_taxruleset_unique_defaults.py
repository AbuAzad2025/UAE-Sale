"""Unique partial index: one platform-default ruleset per country.

Revision ID: b18_taxruleset_unique_defaults
Revises: b17_purchase_vat_features
"""

from alembic import op

revision = "b18_taxruleset_unique_defaults"
down_revision = "b17_purchase_vat_features"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rulesets for tenant_id IS NULL are the country defaults — two of them for the
    # same country would silently shadow each other; the registry must be unique.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_tax_rulesets_default_country "
        "ON tax_rulesets (country_code) WHERE tenant_id IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_tax_rulesets_default_country")
