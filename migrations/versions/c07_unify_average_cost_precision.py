"""Unify numeric precision: store average_cost with 6 decimals.

Revision ID: c07_unify_average_cost_precision
Revises: c06_leave_types_per_tenant

A 3-decimal unit cost multiplied by a large quantity (2,835 / 3,600 units)
accumulated a ~1.44 ILS valuation drift versus the GL control account.
Storing 6 decimals bounds that drift well below the 0.01 tolerance.

Existing values are NOT recomputed: replaying historical movements from the
available tables cannot reconstruct the exact VAT-restated cost flow and would
introduce a larger error than it fixes. This migration only widens the column
so all NEW costing updates keep full precision.
"""
from alembic import op
import sqlalchemy as sa

revision = "c07_unify_average_cost_precision"
down_revision = "c06_leave_types_per_tenant"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "products",
        "average_cost",
        existing_type=sa.Numeric(15, 3),
        type_=sa.Numeric(18, 6),
        existing_nullable=False,
        existing_server_default=sa.text("0"),
    )


def downgrade():
    op.alter_column(
        "products",
        "average_cost",
        existing_type=sa.Numeric(18, 6),
        type_=sa.Numeric(15, 3),
        existing_nullable=False,
        existing_server_default=sa.text("0"),
    )
