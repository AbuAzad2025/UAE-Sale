"""Record the actual payroll disbursement independently of its schedule."""

import sqlalchemy as sa
from alembic import op

revision = "c14_payroll_disbursement"
down_revision = "c13_bot_context_memory"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("payslips", sa.Column("disbursed_on", sa.Date(), nullable=True))
    op.add_column("payslips", sa.Column("payment_method", sa.String(20), nullable=True))


def downgrade():
    with op.batch_alter_table("payslips") as batch:
        batch.drop_column("payment_method")
        batch.drop_column("disbursed_on")
