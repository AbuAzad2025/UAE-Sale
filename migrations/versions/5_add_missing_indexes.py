"""add missing performance indexes on HR and ERP tables

Revision ID: 5_add_missing_indexes
Revises: 4_erp_modules
Create Date: 2026-08-24
"""
from alembic import op


revision = '5_add_missing_indexes'
down_revision = '4_erp_modules'
branch_labels = None
depends_on = None


def upgrade():
    # ---- Quotations ----
    op.create_index('ix_quotations_customer', 'quotations', ['customer_id'])
    op.create_index('ix_quotations_valid_until', 'quotations', ['valid_until'])

    # ---- Purchase Orders ----
    op.create_index('ix_po_supplier', 'purchase_orders', ['supplier_id'])
    op.create_index('ix_po_date', 'purchase_orders', ['po_date'])
    op.create_index('ix_po_expected_delivery', 'purchase_orders', ['expected_delivery'])

    # ---- Fiscal Periods ----
    op.create_index('ix_fiscal_periods_date_range', 'fiscal_periods', ['start_date', 'end_date'])

    # ---- Stock Transfers ----
    op.create_index('ix_stock_transfers_from_wh', 'stock_transfers', ['from_warehouse_id'])
    op.create_index('ix_stock_transfers_to_wh', 'stock_transfers', ['to_warehouse_id'])
    op.create_index('ix_stock_transfers_date', 'stock_transfers', ['transfer_date'])

    # ---- Stock Take Items ----
    op.create_index('ix_stock_take_items_product', 'stock_take_items', ['product_id'])

    # ---- Dunning Letters ----
    op.create_index('ix_dunning_sale', 'dunning_letters', ['sale_id'])
    op.create_index('ix_dunning_status_level', 'dunning_letters', ['status', 'level'])
    op.create_index('ix_dunning_date', 'dunning_letters', ['letter_date'])

    # ---- Product Lots ----
    op.create_index('ix_lots_product_warehouse', 'product_lots', ['product_id', 'warehouse_id'])
    op.create_index('ix_lots_active', 'product_lots', ['is_active'])

    # ---- Recurring Expenses ----
    op.create_index('ix_recurring_category', 'recurring_expenses', ['category_id'])
    op.create_index('ix_recurring_frequency', 'recurring_expenses', ['frequency'])

    # ---- E-Invoices ----
    op.create_index('ix_einvoices_uuid', 'e_invoices', ['uuid'])

    # ---- Leave Requests (composite for overlap checks) ----
    op.create_index('ix_leave_requests_emp_status', 'leave_requests', ['employee_id', 'status'])
    op.create_index('ix_leave_requests_dates', 'leave_requests', ['start_date', 'end_date'])

    # ---- Employees (hire date for tenure queries) ----
    op.create_index('ix_employees_hire_date', 'employees', ['hire_date'])

    # ---- Payslips (composite for duplicate check) ----
    op.create_index('ix_payslips_emp_period', 'payslips', ['employee_id', 'pay_period_start', 'pay_period_end'])


def downgrade():
    op.drop_index('ix_payslips_emp_period')
    op.drop_index('ix_employees_hire_date')
    op.drop_index('ix_leave_requests_dates')
    op.drop_index('ix_leave_requests_emp_status')
    op.drop_index('ix_einvoices_uuid')
    op.drop_index('ix_recurring_frequency')
    op.drop_index('ix_recurring_category')
    op.drop_index('ix_lots_active')
    op.drop_index('ix_lots_product_warehouse')
    op.drop_index('ix_dunning_date')
    op.drop_index('ix_dunning_status_level')
    op.drop_index('ix_dunning_sale')
    op.drop_index('ix_stock_take_items_product')
    op.drop_index('ix_stock_transfers_date')
    op.drop_index('ix_stock_transfers_to_wh')
    op.drop_index('ix_stock_transfers_from_wh')
    op.drop_index('ix_fiscal_periods_date_range')
    op.drop_index('ix_po_expected_delivery')
    op.drop_index('ix_po_date')
    op.drop_index('ix_po_supplier')
    op.drop_index('ix_quotations_valid_until')
    op.drop_index('ix_quotations_customer')
