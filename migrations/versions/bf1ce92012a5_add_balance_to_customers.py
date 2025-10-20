"""add_balance_to_customers

Revision ID: bf1ce92012a5
Revises: f9eeec607df9
Create Date: 2025-10-18 07:55:54.615947

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'bf1ce92012a5'
down_revision = 'f9eeec607df9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('customers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('balance', sa.Numeric(precision=15, scale=3), nullable=False, server_default='0'))


def downgrade():
    with op.batch_alter_table('customers', schema=None) as batch_op:
        batch_op.drop_column('balance')
