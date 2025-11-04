"""add warehouse to purchases

Revision ID: 20251104194500
Revises: 20251104192500
Create Date: 2025-11-04 19:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '20251104194500'
down_revision = '20251104192500'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('purchases', 
        sa.Column('warehouse_id', sa.Integer(), nullable=True))
    
    op.create_index(
        'idx_purchases_warehouse', 
        'purchases', 
        ['warehouse_id'],
        unique=False
    )


def downgrade():
    op.drop_index('idx_purchases_warehouse', table_name='purchases')
    op.drop_column('purchases', 'warehouse_id')

