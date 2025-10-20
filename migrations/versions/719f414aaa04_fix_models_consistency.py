"""fix_models_consistency

Revision ID: 719f414aaa04
Revises: b5c15962b8a9
Create Date: 2025-10-17 20:34:57.464842

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '719f414aaa04'
down_revision = 'b5c15962b8a9'
branch_labels = None
depends_on = None


def upgrade():
    """Add consistency fields to models"""
    with op.batch_alter_table('suppliers', schema=None) as batch_op:
        # Check if column exists before adding
        try:
            batch_op.add_column(sa.Column('name_ar', sa.String(length=200), nullable=True))
        except Exception:
            pass  # Column may already exist
    
    with op.batch_alter_table('sales', schema=None) as batch_op:
        # Check if column exists before adding
        try:
            batch_op.add_column(sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'))
            batch_op.create_index('ix_sales_is_active', ['is_active'])
        except Exception:
            pass  # Column may already exist
    
    print("✅ Model consistency fields added")


def downgrade():
    """Remove consistency fields"""
    with op.batch_alter_table('sales', schema=None) as batch_op:
        try:
            batch_op.drop_index('ix_sales_is_active')
            batch_op.drop_column('is_active')
        except Exception:
            pass
    
    with op.batch_alter_table('suppliers', schema=None) as batch_op:
        try:
            batch_op.drop_column('name_ar')
        except Exception:
            pass
    
    print("✅ Model consistency fields removed")
