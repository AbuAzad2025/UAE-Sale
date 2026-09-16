"""add ERP extended modules

Revision ID: 4_erp_modules
Revises: 3_hr_module
Create Date: 2026-08-24
"""
from alembic import op
import sqlalchemy as sa


revision = '4_erp_modules'
down_revision = '3_hr_module'
branch_labels = None
depends_on = None


def upgrade():
    # ---- quotations ----
    op.create_table('quotations',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('quotation_number', sa.String(50), unique=True, nullable=False),
        sa.Column('customer_id', sa.Integer(), sa.ForeignKey('customers.id'), nullable=False),
        sa.Column('seller_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('warehouse_id', sa.Integer(), sa.ForeignKey('warehouses.id')),
        sa.Column('quotation_date', sa.Date(), nullable=False),
        sa.Column('valid_until', sa.Date(), nullable=False),
        sa.Column('expiry_date', sa.Date()),
        sa.Column('subtotal', sa.Numeric(15, 3), server_default='0'),
        sa.Column('discount_amount', sa.Numeric(15, 3), server_default='0'),
        sa.Column('shipping_cost', sa.Numeric(15, 3), server_default='0'),
        sa.Column('tax_rate', sa.Numeric(5, 2), server_default='0'),
        sa.Column('tax_amount', sa.Numeric(15, 3), server_default='0'),
        sa.Column('total_amount', sa.Numeric(15, 3), server_default='0'),
        sa.Column('currency', sa.String(3), server_default='AED'),
        sa.Column('exchange_rate', sa.Numeric(15, 6), server_default='1'),
        sa.Column('amount_aed', sa.Numeric(15, 3), server_default='0'),
        sa.Column('status', sa.String(20), server_default='draft'),
        sa.Column('converted_sale_id', sa.Integer(), sa.ForeignKey('sales.id')),
        sa.Column('notes', sa.Text()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_quotations_number', 'quotations', ['quotation_number'], unique=True)
    op.create_index('ix_quotations_status', 'quotations', ['status'])

    op.create_table('quotation_lines',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('quotation_id', sa.Integer(), sa.ForeignKey('quotations.id'), nullable=False),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=False),
        sa.Column('quantity', sa.Numeric(15, 3), nullable=False),
        sa.Column('unit_price', sa.Numeric(15, 3), nullable=False),
        sa.Column('discount_percent', sa.Numeric(5, 2), server_default='0'),
        sa.Column('line_total', sa.Numeric(15, 3), nullable=False),
        sa.Column('notes', sa.String(255)),
    )

    # ---- purchase orders ----
    op.create_table('purchase_orders',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('po_number', sa.String(50), unique=True, nullable=False),
        sa.Column('supplier_id', sa.Integer(), sa.ForeignKey('suppliers.id'), nullable=False),
        sa.Column('warehouse_id', sa.Integer(), sa.ForeignKey('warehouses.id')),
        sa.Column('requested_by_id', sa.Integer(), sa.ForeignKey('users.id')),
        sa.Column('po_date', sa.Date(), nullable=False),
        sa.Column('expected_delivery', sa.Date()),
        sa.Column('subtotal', sa.Numeric(15, 3), server_default='0'),
        sa.Column('tax_rate', sa.Numeric(5, 2), server_default='0'),
        sa.Column('tax_amount', sa.Numeric(15, 3), server_default='0'),
        sa.Column('total_amount', sa.Numeric(15, 3), server_default='0'),
        sa.Column('currency', sa.String(3), server_default='AED'),
        sa.Column('exchange_rate', sa.Numeric(15, 6), server_default='1'),
        sa.Column('status', sa.String(20), server_default='draft'),
        sa.Column('purchase_id', sa.Integer(), sa.ForeignKey('purchases.id')),
        sa.Column('notes', sa.Text()),
        sa.Column('approved_by_id', sa.Integer(), sa.ForeignKey('users.id')),
        sa.Column('approved_at', sa.DateTime()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_po_number', 'purchase_orders', ['po_number'], unique=True)
    op.create_index('ix_po_status', 'purchase_orders', ['status'])

    op.create_table('purchase_order_lines',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('order_id', sa.Integer(), sa.ForeignKey('purchase_orders.id'), nullable=False),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=False),
        sa.Column('quantity', sa.Numeric(15, 3), nullable=False),
        sa.Column('unit_cost', sa.Numeric(15, 3), nullable=False),
        sa.Column('discount_percent', sa.Numeric(5, 2), server_default='0'),
        sa.Column('line_total', sa.Numeric(15, 3), nullable=False),
        sa.Column('received_quantity', sa.Numeric(15, 3), server_default='0'),
        sa.Column('notes', sa.String(255)),
    )

    # ---- fiscal periods ----
    op.create_table('fiscal_periods',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('period_type', sa.String(20), server_default='annual'),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('is_closed', sa.Boolean(), server_default='0'),
        sa.Column('closed_by_id', sa.Integer(), sa.ForeignKey('users.id')),
        sa.Column('closed_at', sa.DateTime()),
        sa.Column('notes', sa.Text()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_fiscal_periods_year', 'fiscal_periods', ['year'])
    op.create_index('ix_fiscal_periods_end', 'fiscal_periods', ['end_date'])
    op.create_index('ix_fiscal_periods_closed', 'fiscal_periods', ['is_closed'])

    # ---- stock transfers ----
    op.create_table('stock_transfers',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('transfer_number', sa.String(50), unique=True, nullable=False),
        sa.Column('from_warehouse_id', sa.Integer(), sa.ForeignKey('warehouses.id'), nullable=False),
        sa.Column('to_warehouse_id', sa.Integer(), sa.ForeignKey('warehouses.id'), nullable=False),
        sa.Column('transfer_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(20), server_default='pending'),
        sa.Column('notes', sa.Text()),
        sa.Column('requested_by_id', sa.Integer(), sa.ForeignKey('users.id')),
        sa.Column('received_by_id', sa.Integer(), sa.ForeignKey('users.id')),
        sa.Column('received_at', sa.DateTime()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_stock_transfers_number', 'stock_transfers', ['transfer_number'], unique=True)
    op.create_index('ix_stock_transfers_status', 'stock_transfers', ['status'])

    op.create_table('stock_transfer_lines',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('transfer_id', sa.Integer(), sa.ForeignKey('stock_transfers.id'), nullable=False),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=False),
        sa.Column('quantity', sa.Numeric(15, 3), nullable=False),
        sa.Column('notes', sa.String(255)),
    )

    # ---- stock takes ----
    op.create_table('stock_takes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('stocktake_number', sa.String(50), unique=True, nullable=False),
        sa.Column('warehouse_id', sa.Integer(), sa.ForeignKey('warehouses.id'), nullable=False),
        sa.Column('stocktake_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(20), server_default='in_progress'),
        sa.Column('notes', sa.Text()),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id')),
        sa.Column('approved_by_id', sa.Integer(), sa.ForeignKey('users.id')),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('completed_at', sa.DateTime()),
    )
    op.create_index('ix_stock_takes_number', 'stock_takes', ['stocktake_number'], unique=True)
    op.create_index('ix_stock_takes_status', 'stock_takes', ['status'])

    op.create_table('stock_take_items',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('stocktake_id', sa.Integer(), sa.ForeignKey('stock_takes.id'), nullable=False),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=False),
        sa.Column('system_quantity', sa.Numeric(15, 3), nullable=False),
        sa.Column('counted_quantity', sa.Numeric(15, 3)),
        sa.Column('variance', sa.Numeric(15, 3), server_default='0'),
        sa.Column('notes', sa.String(255)),
    )
    op.create_index('ix_stock_take_items_st', 'stock_take_items', ['stocktake_id'])

    # ---- dunning letters ----
    op.create_table('dunning_letters',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('letter_number', sa.String(50), unique=True, nullable=False),
        sa.Column('customer_id', sa.Integer(), sa.ForeignKey('customers.id'), nullable=False),
        sa.Column('sale_id', sa.Integer(), sa.ForeignKey('sales.id')),
        sa.Column('level', sa.Integer(), server_default='1'),
        sa.Column('amount_due', sa.Numeric(15, 3), nullable=False),
        sa.Column('days_overdue', sa.Integer(), nullable=False),
        sa.Column('letter_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(20), server_default='draft'),
        sa.Column('sent_at', sa.DateTime()),
        sa.Column('notes', sa.Text()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_dunning_number', 'dunning_letters', ['letter_number'], unique=True)
    op.create_index('ix_dunning_customer', 'dunning_letters', ['customer_id'])

    # ---- recurring expenses ----
    op.create_table('recurring_expenses',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('category_id', sa.Integer(), sa.ForeignKey('expense_categories.id'), nullable=False),
        sa.Column('amount', sa.Numeric(15, 3), nullable=False),
        sa.Column('currency', sa.String(3), server_default='AED'),
        sa.Column('payment_method', sa.String(20), server_default='bank_transfer'),
        sa.Column('supplier_name', sa.String(200)),
        sa.Column('description', sa.Text()),
        sa.Column('frequency', sa.String(20), nullable=False),
        sa.Column('next_due_date', sa.Date(), nullable=False),
        sa.Column('last_generated_date', sa.Date()),
        sa.Column('is_active', sa.Boolean(), server_default='1'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_recurring_next', 'recurring_expenses', ['next_due_date'])
    op.create_index('ix_recurring_active', 'recurring_expenses', ['is_active'])

    # ---- product lots ----
    op.create_table('product_lots',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=False),
        sa.Column('lot_number', sa.String(50), nullable=False),
        sa.Column('warehouse_id', sa.Integer(), sa.ForeignKey('warehouses.id')),
        sa.Column('quantity', sa.Numeric(15, 3), nullable=False, server_default='0'),
        sa.Column('cost_price', sa.Numeric(15, 3), server_default='0'),
        sa.Column('manufacture_date', sa.Date()),
        sa.Column('expiry_date', sa.Date()),
        sa.Column('purchase_id', sa.Integer(), sa.ForeignKey('purchases.id')),
        sa.Column('is_active', sa.Boolean(), server_default='1'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_lots_number', 'product_lots', ['lot_number'])
    op.create_index('ix_lots_expiry', 'product_lots', ['expiry_date'])
    op.create_unique_constraint('uq_product_lot_warehouse', 'product_lots', ['product_id', 'lot_number', 'warehouse_id'])

    # ---- warehouse bins ----
    op.create_table('warehouse_bins',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('warehouse_id', sa.Integer(), sa.ForeignKey('warehouses.id'), nullable=False),
        sa.Column('code', sa.String(50), nullable=False),
        sa.Column('name', sa.String(100)),
        sa.Column('aisle', sa.String(20)),
        sa.Column('shelf', sa.String(20)),
        sa.Column('position', sa.String(20)),
        sa.Column('capacity', sa.Integer(), server_default='0'),
        sa.Column('is_active', sa.Boolean(), server_default='1'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_unique_constraint('uq_warehouse_bin_code', 'warehouse_bins', ['warehouse_id', 'code'])

    op.create_table('product_bins',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('bin_id', sa.Integer(), sa.ForeignKey('warehouse_bins.id'), nullable=False),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=False),
        sa.Column('stock_quantity', sa.Numeric(15, 3), server_default='0'),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_unique_constraint('uq_bin_product', 'product_bins', ['bin_id', 'product_id'])

    # ---- e-invoices ----
    op.create_table('e_invoices',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('invoice_number', sa.String(50), unique=True, nullable=False),
        sa.Column('sale_id', sa.Integer(), sa.ForeignKey('sales.id'), nullable=False),
        sa.Column('uuid', sa.String(100), unique=True),
        sa.Column('invoice_type', sa.String(30), server_default='standard'),
        sa.Column('invoice_date', sa.DateTime(), nullable=False),
        sa.Column('buyer_name', sa.String(200), nullable=False),
        sa.Column('buyer_trn', sa.String(50)),
        sa.Column('buyer_address', sa.Text()),
        sa.Column('total_amount', sa.Numeric(15, 3), nullable=False),
        sa.Column('tax_amount', sa.Numeric(15, 3), server_default='0'),
        sa.Column('total_with_tax', sa.Numeric(15, 3), nullable=False),
        sa.Column('currency', sa.String(3), server_default='AED'),
        sa.Column('status', sa.String(20), server_default='draft'),
        sa.Column('submitted_at', sa.DateTime()),
        sa.Column('accepted_at', sa.DateTime()),
        sa.Column('xml_payload', sa.Text()),
        sa.Column('json_payload', sa.Text()),
        sa.Column('fta_response', sa.Text()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_einvoices_number', 'e_invoices', ['invoice_number'], unique=True)
    op.create_index('ix_einvoices_sale', 'e_invoices', ['sale_id'])
    op.create_index('ix_einvoices_status', 'e_invoices', ['status'])


def downgrade():
    op.drop_table('e_invoices')
    op.drop_table('product_bins')
    op.drop_table('warehouse_bins')
    op.drop_table('product_lots')
    op.drop_table('recurring_expenses')
    op.drop_table('dunning_letters')
    op.drop_table('stock_take_items')
    op.drop_table('stock_takes')
    op.drop_table('stock_transfer_lines')
    op.drop_table('stock_transfers')
    op.drop_table('fiscal_periods')
    op.drop_table('purchase_order_lines')
    op.drop_table('purchase_orders')
    op.drop_table('quotation_lines')
    op.drop_table('quotations')
