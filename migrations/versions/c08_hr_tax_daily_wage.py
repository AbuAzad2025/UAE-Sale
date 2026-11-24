"""Add per-employee income tax and daily-wage fields.

Revision ID: c08_hr_tax_daily_wage
Revises: c07_unify_average_cost_precision

Payroll must withhold income tax (posted to TAX_PAYABLE) and support
daily-wage ("مياومة") workers paid per worked day.
"""
from alembic import op
import sqlalchemy as sa

revision = "c08_hr_tax_daily_wage"
down_revision = "c07_unify_average_cost_precision"
branch_labels = None
depends_on = None

COLUMNS = [
    ("income_tax_rate", sa.Numeric(5, 2), "0"),
    ("tax_exemption", sa.Numeric(15, 3), "0"),
    ("is_daily_wage", sa.Boolean, "false"),
    ("daily_wage_rate", sa.Numeric(15, 3), "0"),
]


def _existing():
    return [c["name"] for c in sa.inspect(op.get_bind()).get_columns("employees")]


def upgrade():
    have = _existing()
    with op.batch_alter_table("employees") as batch:
        for name, typ, default in COLUMNS:
            if name not in have:
                batch.add_column(
                    sa.Column(name, typ, nullable=False, server_default=default)
                )


def downgrade():
    have = _existing()
    with op.batch_alter_table("employees") as batch:
        for name, _t, _d in reversed(COLUMNS):
            if name in have:
                batch.drop_column(name)
