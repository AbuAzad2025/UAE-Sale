"""add performance indexes

Revision ID: b5c15962b8a9
Revises: 78197ecf60d0
Create Date: 2025-10-17 20:18:45.651908

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b5c15962b8a9'
down_revision = '78197ecf60d0'
branch_labels = None
depends_on = None


def upgrade():
    """Add performance indexes to critical tables"""
    
    # Check and add indexes only if they don't exist
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    
    # Sales indexes
    existing_indexes = {idx['name'] for idx in inspector.get_indexes('sales')}
    if 'ix_sales_customer_id' not in existing_indexes:
        op.create_index('ix_sales_customer_id', 'sales', ['customer_id'])
    if 'ix_sales_sale_date' not in existing_indexes:
        op.create_index('ix_sales_sale_date', 'sales', ['sale_date'])
    
    # Purchases indexes
    existing_indexes = {idx['name'] for idx in inspector.get_indexes('purchases')}
    if 'ix_purchases_supplier_id' not in existing_indexes:
        op.create_index('ix_purchases_supplier_id', 'purchases', ['supplier_id'])
    if 'ix_purchases_purchase_date' not in existing_indexes:
        op.create_index('ix_purchases_purchase_date', 'purchases', ['purchase_date'])
    
    # Products indexes
    existing_indexes = {idx['name'] for idx in inspector.get_indexes('products')}
    if 'ix_products_category_id' not in existing_indexes:
        op.create_index('ix_products_category_id', 'products', ['category_id'])
    if 'ix_products_barcode' not in existing_indexes:
        op.create_index('ix_products_barcode', 'products', ['barcode'])
    
    # Customers indexes
    existing_indexes = {idx['name'] for idx in inspector.get_indexes('customers')}
    if 'ix_customers_customer_type' not in existing_indexes:
        op.create_index('ix_customers_customer_type', 'customers', ['customer_type'])
    if 'ix_customers_phone' not in existing_indexes:
        op.create_index('ix_customers_phone', 'customers', ['phone'])
    
    # Suppliers indexes
    try:
        existing_indexes = {idx['name'] for idx in inspector.get_indexes('suppliers')}
        if 'ix_suppliers_phone' not in existing_indexes:
            op.create_index('ix_suppliers_phone', 'suppliers', ['phone'])
    except:
        pass  # Table may not exist
    
    # Payments indexes
    existing_indexes = {idx['name'] for idx in inspector.get_indexes('payments')}
    if 'ix_payments_customer_id' not in existing_indexes:
        op.create_index('ix_payments_customer_id', 'payments', ['customer_id'])
    if 'ix_payments_payment_date' not in existing_indexes:
        op.create_index('ix_payments_payment_date', 'payments', ['payment_date'])
    if 'ix_payments_payment_method' not in existing_indexes:
        op.create_index('ix_payments_payment_method', 'payments', ['payment_method'])
    
    print("✅ Performance indexes created successfully")


def downgrade():
    """Remove performance indexes"""
    
    # Sales indexes
    try:
        op.drop_index('ix_sales_customer_id', 'sales')
        op.drop_index('ix_sales_sale_date', 'sales')
    except:
        pass
    
    # Purchases indexes
    try:
        op.drop_index('ix_purchases_supplier_id', 'purchases')
        op.drop_index('ix_purchases_purchase_date', 'purchases')
    except:
        pass
    
    # Products indexes
    try:
        op.drop_index('ix_products_category_id', 'products')
        op.drop_index('ix_products_barcode', 'products')
    except:
        pass
    
    # Customers indexes
    try:
        op.drop_index('ix_customers_customer_type', 'customers')
        op.drop_index('ix_customers_phone', 'customers')
    except:
        pass
    
    # Suppliers indexes
    try:
        op.drop_index('ix_suppliers_phone', 'suppliers')
    except:
        pass
    
    # Payments indexes
    try:
        op.drop_index('ix_payments_customer_id', 'payments')
        op.drop_index('ix_payments_payment_date', 'payments')
        op.drop_index('ix_payments_payment_method', 'payments')
    except:
        pass
    
    print("✅ Performance indexes removed")
