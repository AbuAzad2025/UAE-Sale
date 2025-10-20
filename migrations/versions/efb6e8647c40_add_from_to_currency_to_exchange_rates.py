"""add_from_to_currency_to_exchange_rates

Revision ID: efb6e8647c40
Revises: 719f414aaa04
Create Date: 2025-10-17 22:14:28.659219

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'efb6e8647c40'
down_revision = '719f414aaa04'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('exchange_rates', schema=None) as batch_op:
        batch_op.add_column(sa.Column('from_currency', sa.String(length=3), nullable=True))
        batch_op.add_column(sa.Column('to_currency', sa.String(length=3), nullable=True))
        batch_op.create_index('ix_exchange_from_currency', ['from_currency'])
        batch_op.create_index('ix_exchange_to_currency', ['to_currency'])


def downgrade():
    with op.batch_alter_table('exchange_rates', schema=None) as batch_op:
        batch_op.drop_index('ix_exchange_to_currency')
        batch_op.drop_index('ix_exchange_from_currency')
        batch_op.drop_column('to_currency')
        batch_op.drop_column('from_currency')
