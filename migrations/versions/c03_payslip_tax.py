"""Add tax_deduction to payslips.

Revision ID: c03_payslip_tax
Revises: c02_gl_idempotency_key

Payroll must withhold income tax and credit it to TAX_PAYABLE (2130) rather
than treating all deductions as salary payable.
"""
from alembic import op
import sqlalchemy as sa

revision = "c03_payslip_tax"
down_revision = "c02_gl_idempotency_key"
branch_labels = None
depends_on = None


def _has_column(table, column):
    return column in [c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)]


def upgrade():
    if not _has_column("payslips", "tax_deduction"):
        with op.batch_alter_table("payslips") as batch:
            batch.add_column(
                sa.Column("tax_deduction", sa.Numeric(15, 3), nullable=False, server_default="0")
            )


def downgrade():
    if _has_column("payslips", "tax_deduction"):
        with op.batch_alter_table("payslips") as batch:
            batch.drop_column("tax_deduction")
