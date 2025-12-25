"""add packages tables

Revision ID: add_packages
Revises: 
Create Date: 2025-01-24 22:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_packages'
down_revision = '020727b020e8'
branch_labels = None
depends_on = None


def upgrade():
    # Create packages table
    op.create_table('packages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name_ar', sa.String(length=100), nullable=False),
        sa.Column('name_en', sa.String(length=100), nullable=False),
        sa.Column('slug', sa.String(length=50), nullable=False),
        sa.Column('icon', sa.String(length=50), nullable=True),
        sa.Column('price', sa.Float(), nullable=False),
        sa.Column('currency', sa.String(length=10), nullable=True),
        sa.Column('description_ar', sa.Text(), nullable=True),
        sa.Column('description_en', sa.Text(), nullable=True),
        sa.Column('features', sa.JSON(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('is_featured', sa.Boolean(), nullable=True),
        sa.Column('badge_text', sa.String(length=50), nullable=True),
        sa.Column('badge_color', sa.String(length=20), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=True),
        sa.Column('support_duration_months', sa.Integer(), nullable=True),
        sa.Column('max_users', sa.Integer(), nullable=True),
        sa.Column('max_branches', sa.Integer(), nullable=True),
        sa.Column('has_ai', sa.Boolean(), nullable=True),
        sa.Column('has_whatsapp', sa.Boolean(), nullable=True),
        sa.Column('has_pos', sa.Boolean(), nullable=True),
        sa.Column('has_advanced_reports', sa.Boolean(), nullable=True),
        sa.Column('has_customization', sa.Boolean(), nullable=True),
        sa.Column('has_training', sa.Boolean(), nullable=True),
        sa.Column('has_priority_support', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug')
    )
    
    # Create package_purchases table
    op.create_table('package_purchases',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('package_id', sa.Integer(), nullable=False),
        sa.Column('customer_name', sa.String(length=200), nullable=False),
        sa.Column('customer_email', sa.String(length=200), nullable=False),
        sa.Column('customer_phone', sa.String(length=50), nullable=True),
        sa.Column('company_name', sa.String(length=200), nullable=True),
        sa.Column('payment_method', sa.String(length=50), nullable=False),
        sa.Column('payment_status', sa.String(length=50), nullable=True),
        sa.Column('amount_paid', sa.Float(), nullable=False),
        sa.Column('currency', sa.String(length=10), nullable=True),
        sa.Column('transaction_id', sa.String(length=200), nullable=True),
        sa.Column('payment_details', sa.JSON(), nullable=True),
        sa.Column('activation_status', sa.String(length=50), nullable=True),
        sa.Column('activation_date', sa.DateTime(), nullable=True),
        sa.Column('expiry_date', sa.DateTime(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['package_id'], ['packages.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('package_purchases')
    op.drop_table('packages')

