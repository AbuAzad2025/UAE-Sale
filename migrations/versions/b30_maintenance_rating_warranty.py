"""Maintenance M2b: Customer rating, warranty period fields.

Revision ID: b30_maintenance_rating_warranty
Revises: b29_maintenance_core
"""
from alembic import op
import sqlalchemy as sa

revision = 'b30_maintenance_rating_warranty'
down_revision = 'b29_maintenance_core'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('maintenance_orders', sa.Column('customer_rating', sa.Integer(), nullable=True))
    op.add_column('maintenance_orders', sa.Column('customer_comment', sa.Text(), nullable=True))
    op.add_column('maintenance_orders', sa.Column('rated_at', sa.DateTime(), nullable=True))
    op.add_column('maintenance_orders', sa.Column('warranty_period_days', sa.Integer(), nullable=True))
    op.add_column('maintenance_orders', sa.Column('warranty_period_notes', sa.Text(), nullable=True))
    op.add_column('maintenance_orders', sa.Column('warranty_period_start', sa.Date(), nullable=True))
    op.add_column('maintenance_orders', sa.Column('warranty_period_end', sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column('maintenance_orders', 'warranty_period_end')
    op.drop_column('maintenance_orders', 'warranty_period_start')
    op.drop_column('maintenance_orders', 'warranty_period_notes')
    op.drop_column('maintenance_orders', 'warranty_period_days')
    op.drop_column('maintenance_orders', 'rated_at')
    op.drop_column('maintenance_orders', 'customer_comment')
    op.drop_column('maintenance_orders', 'customer_rating')
