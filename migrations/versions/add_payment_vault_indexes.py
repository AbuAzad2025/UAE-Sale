"""add_payment_vault_indexes

Revision ID: payment_vault_indexes
Create Date: 2025-10-24

تحسين الأداء بإضافة indexes لجداول الخزينة
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = 'payment_vault_indexes'
down_revision = 'payment_vault_columns'
branch_labels = None
depends_on = None


def upgrade():
    """إضافة indexes لتحسين الأداء"""
    
    # Indexes للخزينة
    try:
        op.create_index('idx_payment_vault_last_access', 'payment_vault', ['last_access'])
        op.create_index('idx_payment_vault_is_locked', 'payment_vault', ['is_locked'])
    except:
        pass
    
    # Indexes للتبرعات
    try:
        op.create_index('idx_donations_status', 'donations', ['status'])
        op.create_index('idx_donations_transaction_type', 'donations', ['transaction_type'])
        op.create_index('idx_donations_created_at', 'donations', ['created_at'])
        op.create_index('idx_donations_customer_email', 'donations', ['customer_email'])
        op.create_index('idx_donations_donor_email', 'donations', ['donor_email'])
    except:
        pass
    
    # Indexes للمشتريات
    try:
        op.create_index('idx_package_purchases_payment_status', 'package_purchases', ['payment_status'])
        op.create_index('idx_package_purchases_activation_status', 'package_purchases', ['activation_status'])
        op.create_index('idx_package_purchases_created_at', 'package_purchases', ['created_at'])
        op.create_index('idx_package_purchases_customer_email', 'package_purchases', ['customer_email'])
        op.create_index('idx_package_purchases_package_id', 'package_purchases', ['package_id'])
    except:
        pass
    
    # Indexes للبطاقات
    try:
        op.create_index('idx_card_payments_status', 'card_payments', ['status'])
        op.create_index('idx_card_payments_created_at', 'card_payments', ['created_at'])
        op.create_index('idx_card_payments_customer_email', 'card_payments', ['customer_email'])
    except:
        pass
    
    # Indexes لسجلات الدفع
    try:
        op.create_index('idx_payment_logs_created_at', 'payment_logs', ['created_at'])
        op.create_index('idx_payment_logs_action', 'payment_logs', ['action'])
        op.create_index('idx_payment_logs_level', 'payment_logs', ['level'])
    except:
        pass
    
    # Indexes للباقات
    try:
        op.create_index('idx_packages_is_active', 'packages', ['is_active'])
        op.create_index('idx_packages_slug', 'packages', ['slug'])
        op.create_index('idx_packages_sort_order', 'packages', ['sort_order'])
    except:
        pass


def downgrade():
    """إزالة indexes"""
    
    # Indexes للخزينة
    try:
        op.drop_index('idx_payment_vault_last_access', 'payment_vault')
        op.drop_index('idx_payment_vault_is_locked', 'payment_vault')
    except:
        pass
    
    # Indexes للتبرعات
    try:
        op.drop_index('idx_donations_status', 'donations')
        op.drop_index('idx_donations_transaction_type', 'donations')
        op.drop_index('idx_donations_created_at', 'donations')
        op.drop_index('idx_donations_customer_email', 'donations')
        op.drop_index('idx_donations_donor_email', 'donations')
    except:
        pass
    
    # Indexes للمشتريات
    try:
        op.drop_index('idx_package_purchases_payment_status', 'package_purchases')
        op.drop_index('idx_package_purchases_activation_status', 'package_purchases')
        op.drop_index('idx_package_purchases_created_at', 'package_purchases')
        op.drop_index('idx_package_purchases_customer_email', 'package_purchases')
        op.drop_index('idx_package_purchases_package_id', 'package_purchases')
    except:
        pass
    
    # Indexes للبطاقات
    try:
        op.drop_index('idx_card_payments_status', 'card_payments')
        op.drop_index('idx_card_payments_created_at', 'card_payments')
        op.drop_index('idx_card_payments_customer_email', 'card_payments')
    except:
        pass
    
    # Indexes لسجلات الدفع
    try:
        op.drop_index('idx_payment_logs_created_at', 'payment_logs')
        op.drop_index('idx_payment_logs_action', 'payment_logs')
        op.drop_index('idx_payment_logs_level', 'payment_logs')
    except:
        pass
    
    # Indexes للباقات
    try:
        op.drop_index('idx_packages_is_active', 'packages')
        op.drop_index('idx_packages_slug', 'packages')
        op.drop_index('idx_packages_sort_order', 'packages')
    except:
        pass

