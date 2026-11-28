"""Tax ruleset versioning + bank statement evidence.

The original (country_code, tenant_id) unique constraint — and the b18
platform-default partial index — made it impossible to keep more than one
dated version of a country's ruleset. Include effective_from in both so
historical and future versions can coexist.

Revision ID: c16_tax_ruleset_versioning
Revises: c15_persisted_notifications
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as _inspect

revision = "c16_tax_ruleset_versioning"
down_revision = "c15_persisted_notifications"
branch_labels = None
depends_on = None

_CONSTRAINT = "uq_tax_ruleset_country_tenant"
_DEFAULT_INDEX = "uq_tax_rulesets_default_country"


def _unique_constraint_names(table):
    return {
        c.get("name")
        for c in _inspect(op.get_bind()).get_unique_constraints(table)
    }


def _column_names(table):
    return {c["name"] for c in _inspect(op.get_bind()).get_columns(table)}


def _replace_default_index(include_effective):
    # b18 created this as raw SQL (Postgres-compatible); keep the same style.
    op.execute(f"DROP INDEX IF EXISTS {_DEFAULT_INDEX}")
    if include_effective:
        # COALESCE gives the undated "current" row a stable slot, so NULL
        # effective_from cannot be duplicated silently by SQL's NULL rules.
        op.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {_DEFAULT_INDEX} "
            "ON tax_rulesets (country_code, COALESCE(effective_from, '1970-01-01')) "
            "WHERE tenant_id IS NULL"
        )
    else:
        op.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {_DEFAULT_INDEX} "
            "ON tax_rulesets (country_code) WHERE tenant_id IS NULL"
        )


def upgrade():
    names = _unique_constraint_names("tax_rulesets")
    if _CONSTRAINT in names:
        with op.batch_alter_table("tax_rulesets") as batch:
            batch.drop_constraint(_CONSTRAINT, type_="unique")
        names.discard(_CONSTRAINT)
    if _CONSTRAINT not in names:
        with op.batch_alter_table("tax_rulesets") as batch:
            batch.create_unique_constraint(
                _CONSTRAINT, ["country_code", "tenant_id", "effective_from"]
            )
    _replace_default_index(include_effective=True)

    if "statement_reference" not in _column_names("bank_reconciliations"):
        op.add_column(
            "bank_reconciliations",
            sa.Column("statement_reference", sa.String(length=120), nullable=True),
        )


def downgrade():
    if "statement_reference" in _column_names("bank_reconciliations"):
        with op.batch_alter_table("bank_reconciliations") as batch:
            batch.drop_column("statement_reference")

    names = _unique_constraint_names("tax_rulesets")
    if _CONSTRAINT in names:
        with op.batch_alter_table("tax_rulesets") as batch:
            batch.drop_constraint(_CONSTRAINT, type_="unique")
        names.discard(_CONSTRAINT)
    if _CONSTRAINT not in names:
        with op.batch_alter_table("tax_rulesets") as batch:
            batch.create_unique_constraint(
                _CONSTRAINT, ["country_code", "tenant_id"]
            )
    _replace_default_index(include_effective=False)
