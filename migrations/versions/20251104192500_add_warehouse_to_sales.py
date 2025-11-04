"""add warehouse to sales

Revision ID: 20251104192500
Revises: cb30b5bc027f
Create Date: 2025-11-04 19:25:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20251104192500'
down_revision = 'cb30b5bc027f'
branch_labels = None
depends_on = None


def upgrade():
    # إضافة عمود warehouse_id إلى جدول sales
    # nullable=True للتوافق مع البيانات القديمة
    # SQLite-friendly approach - no batch operations
    
    # Step 1: Add column
    op.add_column('sales', 
        sa.Column('warehouse_id', sa.Integer(), nullable=True))
    
    # Step 2: Create index
    op.create_index(
        'idx_sales_warehouse', 
        'sales', 
        ['warehouse_id'],
        unique=False
    )
    
    # Note: SQLite doesn't enforce foreign keys in ALTER TABLE
    # The FK will be enforced by SQLAlchemy at the application level


def downgrade():
    # إزالة التعديلات عند الـ rollback
    op.drop_index('idx_sales_warehouse', table_name='sales')
    op.drop_column('sales', 'warehouse_id')

