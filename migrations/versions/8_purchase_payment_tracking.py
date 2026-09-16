"""Add purchase payment tracking columns (paid_amount, payment_status)

get_payables_aging() filtered on Purchase.payment_status / read paid_amount
which never existed — the whole payables aging report crashed on call.

Revision ID: 8_purchase_payment_tracking
Revises: 7_cheque_gl_links
"""
from alembic import op
import sqlalchemy as sa

revision = '8_purchase_payment_tracking'
down_revision = '7_cheque_gl_links'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('purchases') as batch:
        batch.add_column(sa.Column('paid_amount', sa.Numeric(15, 3),
                                   nullable=True, server_default='0'))
        batch.add_column(sa.Column('payment_status', sa.String(20),
                                   nullable=True, server_default='pending'))
    op.create_index('ix_purchases_payment_status', 'purchases', ['payment_status'])


def downgrade():
    op.drop_index('ix_purchases_payment_status', table_name='purchases')
    with op.batch_alter_table('purchases') as batch:
        batch.drop_column('payment_status')
        batch.drop_column('paid_amount')
