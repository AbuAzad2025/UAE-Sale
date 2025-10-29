"""add_payment_vault_columns

Revision ID: payment_vault_columns
Create Date: 2025-10-24

إضافة الأعمدة المفقودة لجدول payment_vault
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers
revision = 'payment_vault_columns'
down_revision = 'add_packages'
branch_labels = None
depends_on = None


def upgrade():
    """إضافة الأعمدة المفقودة"""
    
    # التحقق من وجود الجدول أولاً
    conn = op.get_bind()
    result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='payment_vault'"))
    if not result.fetchone():
        # إنشاء الجدول إذا لم يكن موجوداً
        op.create_table('payment_vault',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('vault_password_hash', sa.String(length=255), nullable=False),
            sa.Column('vault_name', sa.String(length=100), nullable=True),
            sa.Column('is_locked', sa.Boolean(), nullable=True),
            sa.Column('last_access', sa.DateTime(), nullable=True),
            sa.Column('nowpayments_api_key', sa.String(length=255), nullable=True),
            sa.Column('nowpayments_ipn_secret', sa.String(length=255), nullable=True),
            sa.Column('bitcoin_address', sa.String(length=255), nullable=True),
            sa.Column('ethereum_address', sa.String(length=255), nullable=True),
            sa.Column('usdt_address', sa.String(length=255), nullable=True),
            sa.Column('paypal_client_id', sa.String(length=255), nullable=True),
            sa.Column('paypal_client_secret', sa.String(length=255), nullable=True),
            sa.Column('paypal_business_email', sa.String(length=200), nullable=True),
            sa.Column('paypal_mode', sa.String(length=20), nullable=True),
            sa.Column('bank_name', sa.String(length=200), nullable=True),
            sa.Column('bank_account_name', sa.String(length=200), nullable=True),
            sa.Column('bank_account_number', sa.String(length=100), nullable=True),
            sa.Column('bank_iban', sa.String(length=50), nullable=True),
            sa.Column('bank_swift_code', sa.String(length=20), nullable=True),
            sa.Column('bank_branch', sa.String(length=200), nullable=True),
            sa.Column('bank_country', sa.String(length=100), nullable=True),
            sa.Column('bank_currency', sa.String(length=10), nullable=True),
            sa.Column('stripe_publishable_key', sa.String(length=255), nullable=True),
            sa.Column('stripe_secret_key', sa.String(length=255), nullable=True),
            sa.Column('stripe_webhook_secret', sa.String(length=255), nullable=True),
            sa.Column('mollie_api_key', sa.String(length=255), nullable=True),
            sa.Column('square_access_token', sa.String(length=255), nullable=True),
            sa.Column('razorpay_key_id', sa.String(length=255), nullable=True),
            sa.Column('razorpay_key_secret', sa.String(length=255), nullable=True),
            sa.Column('min_donation_amount', sa.Numeric(precision=10, scale=2), nullable=True),
            sa.Column('max_donation_amount', sa.Numeric(precision=10, scale=2), nullable=True),
            sa.Column('daily_limit', sa.Numeric(precision=15, scale=2), nullable=True),
            sa.Column('require_2fa', sa.Boolean(), nullable=True),
            sa.Column('auto_lock_minutes', sa.Integer(), nullable=True),
            sa.Column('max_failed_attempts', sa.Integer(), nullable=True),
            sa.Column('failed_attempts', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id')
        )
    else:
        # إضافة الأعمدة المفقودة
        try:
            op.add_column('payment_vault', sa.Column('paypal_client_id', sa.String(length=255), nullable=True))
        except:
            pass
        
        try:
            op.add_column('payment_vault', sa.Column('paypal_client_secret', sa.String(length=255), nullable=True))
        except:
            pass
        
        try:
            op.add_column('payment_vault', sa.Column('paypal_business_email', sa.String(length=200), nullable=True))
        except:
            pass
        
        try:
            op.add_column('payment_vault', sa.Column('paypal_mode', sa.String(length=20), nullable=True))
        except:
            pass
        
        try:
            op.add_column('payment_vault', sa.Column('bank_name', sa.String(length=200), nullable=True))
        except:
            pass
        
        try:
            op.add_column('payment_vault', sa.Column('bank_account_name', sa.String(length=200), nullable=True))
        except:
            pass
        
        try:
            op.add_column('payment_vault', sa.Column('bank_account_number', sa.String(length=100), nullable=True))
        except:
            pass
        
        try:
            op.add_column('payment_vault', sa.Column('bank_iban', sa.String(length=50), nullable=True))
        except:
            pass
        
        try:
            op.add_column('payment_vault', sa.Column('bank_swift_code', sa.String(length=20), nullable=True))
        except:
            pass
        
        try:
            op.add_column('payment_vault', sa.Column('bank_branch', sa.String(length=200), nullable=True))
        except:
            pass
        
        try:
            op.add_column('payment_vault', sa.Column('bank_country', sa.String(length=100), nullable=True))
        except:
            pass
        
        try:
            op.add_column('payment_vault', sa.Column('bank_currency', sa.String(length=10), nullable=True))
        except:
            pass
        
        try:
            op.add_column('payment_vault', sa.Column('stripe_publishable_key', sa.String(length=255), nullable=True))
        except:
            pass
        
        try:
            op.add_column('payment_vault', sa.Column('stripe_secret_key', sa.String(length=255), nullable=True))
        except:
            pass
        
        try:
            op.add_column('payment_vault', sa.Column('stripe_webhook_secret', sa.String(length=255), nullable=True))
        except:
            pass


def downgrade():
    """إزالة الأعمدة المضافة وحذف الجدول إن لزم الأمر"""
    
    # حذف الأعمدة
    try:
        op.drop_column('payment_vault', 'stripe_webhook_secret')
    except:
        pass
    
    try:
        op.drop_column('payment_vault', 'stripe_secret_key')
    except:
        pass
    
    try:
        op.drop_column('payment_vault', 'stripe_publishable_key')
    except:
        pass
    
    try:
        op.drop_column('payment_vault', 'bank_currency')
    except:
        pass
    
    try:
        op.drop_column('payment_vault', 'bank_country')
    except:
        pass
    
    try:
        op.drop_column('payment_vault', 'bank_branch')
    except:
        pass
    
    try:
        op.drop_column('payment_vault', 'bank_swift_code')
    except:
        pass
    
    try:
        op.drop_column('payment_vault', 'bank_iban')
    except:
        pass
    
    try:
        op.drop_column('payment_vault', 'bank_account_number')
    except:
        pass
    
    try:
        op.drop_column('payment_vault', 'bank_account_name')
    except:
        pass
    
    try:
        op.drop_column('payment_vault', 'bank_name')
    except:
        pass
    
    try:
        op.drop_column('payment_vault', 'paypal_mode')
    except:
        pass
    
    try:
        op.drop_column('payment_vault', 'paypal_business_email')
    except:
        pass
    
    try:
        op.drop_column('payment_vault', 'paypal_client_secret')
    except:
        pass
    
    try:
        op.drop_column('payment_vault', 'paypal_client_id')
    except:
        pass
    
    # حذف الجدول إذا تم إنشاؤه في upgrade
    # ملاحظة: يُنفذ فقط إذا كان الجدول تم إنشاؤه بواسطة هذا الـ migration
    # يمكن تعطيل هذا إذا كان الجدول موجود من migration سابق
    try:
        from sqlalchemy import text
        conn = op.get_bind()
        # التحقق إذا الجدول فارغ قبل حذفه
        result = conn.execute(text("SELECT COUNT(*) FROM payment_vault"))
        count = result.scalar()
        if count == 0:
            op.drop_table('payment_vault')
    except:
        pass
