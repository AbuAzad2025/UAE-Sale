"""Inbound shipments — استقبال شحنات البضائع الواردة.

Lifecycle: in_transit → arrived → inspected → put_away → closed (or cancelled before closed).
Only put_away moves stock (StockMovement), per C1 contract (no P&L GL).

Revision ID: 21_inbound_shipment (19 chars ≤ 32)
Revises: 20_shipment_module
"""
from alembic import op
import sqlalchemy as sa


revision = '21_inbound_shipment'
down_revision = '20_shipment_module'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'inbound_shipments' in inspector.get_table_names():
        return

    op.create_table(
        'inbound_shipments',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id', ondelete='SET NULL')),
        sa.Column('shipment_number', sa.String(50), nullable=False, unique=True),
        sa.Column('supplier_id', sa.Integer(), sa.ForeignKey('suppliers.id', ondelete='SET NULL')),
        sa.Column('purchase_order_id', sa.Integer(), sa.ForeignKey('purchase_orders.id', ondelete='SET NULL')),
        sa.Column('warehouse_id', sa.Integer(), sa.ForeignKey('warehouses.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('carrier', sa.String(100)),
        sa.Column('tracking_number', sa.String(100)),
        sa.Column('expected_at', sa.Date()),
        sa.Column('arrived_at', sa.DateTime(timezone=True)),
        sa.Column('inspected_at', sa.DateTime(timezone=True)),
        sa.Column('put_away_at', sa.DateTime(timezone=True)),
        sa.Column('closed_at', sa.DateTime(timezone=True)),
        sa.Column('status', sa.String(20), nullable=False, server_default='in_transit'),
        sa.Column('total_quantity', sa.Numeric(15, 3), nullable=False, server_default='0'),
        sa.Column('total_value', sa.Numeric(15, 3), nullable=False, server_default='0'),
        sa.Column('notes', sa.Text()),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('assigned_to_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('in_transit','arrived','inspected','put_away','closed','cancelled')",
                           name='ck_inbound_status_valid'),
        sa.CheckConstraint('total_quantity >= 0', name='ck_inbound_qty_non_negative'),
        sa.CheckConstraint('total_value >= 0', name='ck_inbound_value_non_negative'),
    )
    op.create_index('ix_inbound_shipments_tenant_status', 'inbound_shipments', ['tenant_id', 'status'])
    op.create_index('ix_inbound_shipments_warehouse', 'inbound_shipments', ['warehouse_id'])
    op.create_index('ix_inbound_shipments_supplier', 'inbound_shipments', ['supplier_id'])
    op.create_index('ix_inbound_shipments_po', 'inbound_shipments', ['purchase_order_id'])
    op.create_index('ix_inbound_shipments_tracking', 'inbound_shipments', ['tracking_number'])
    op.create_index('ix_inbound_shipments_status', 'inbound_shipments', ['status'])
    op.create_index('ix_inbound_shipments_tenant_id', 'inbound_shipments', ['tenant_id'])

    op.create_table(
        'inbound_shipment_lines',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('inbound_shipment_id', sa.Integer(), sa.ForeignKey('inbound_shipments.id', ondelete='CASCADE'), nullable=False),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('quantity_expected', sa.Numeric(15, 3), nullable=False),
        sa.Column('quantity_received', sa.Numeric(15, 3), nullable=False, server_default='0'),
        sa.Column('quantity_accepted', sa.Numeric(15, 3), nullable=False, server_default='0'),
        sa.Column('unit_cost', sa.Numeric(15, 3), nullable=False, server_default='0'),
        sa.Column('line_total', sa.Numeric(15, 3), nullable=False, server_default='0'),
        sa.Column('warehouse_bin_id', sa.Integer(), sa.ForeignKey('warehouse_bins.id', ondelete='SET NULL')),
        sa.Column('lot_id', sa.Integer(), sa.ForeignKey('product_lots.id', ondelete='SET NULL')),
        sa.Column('notes', sa.String(255)),
        sa.CheckConstraint('quantity_expected > 0', name='ck_inbound_line_expected_positive'),
        sa.CheckConstraint('quantity_received >= 0', name='ck_inbound_line_received_non_negative'),
        sa.CheckConstraint('quantity_accepted >= 0', name='ck_inbound_line_accepted_non_negative'),
        sa.CheckConstraint('unit_cost >= 0', name='ck_inbound_line_cost_non_negative'),
    )
    op.create_index('ix_inbound_lines_shipment', 'inbound_shipment_lines', ['inbound_shipment_id'])
    op.create_index('ix_inbound_lines_product', 'inbound_shipment_lines', ['product_id'])
    op.create_index('ix_inbound_lines_bin', 'inbound_shipment_lines', ['warehouse_bin_id'])


def downgrade():
    for name in ('ix_inbound_lines_bin', 'ix_inbound_lines_product', 'ix_inbound_lines_shipment'):
        try:
            op.drop_index(name, table_name='inbound_shipment_lines')
        except Exception:
            pass
    try:
        op.drop_table('inbound_shipment_lines')
    except Exception:
        pass
    for name in ('ix_inbound_shipments_tenant_id', 'ix_inbound_shipments_status', 'ix_inbound_shipments_tracking',
                 'ix_inbound_shipments_po', 'ix_inbound_shipments_supplier', 'ix_inbound_shipments_warehouse',
                 'ix_inbound_shipments_tenant_status'):
        try:
            op.drop_index(name, table_name='inbound_shipments')
        except Exception:
            pass
    try:
        op.drop_table('inbound_shipments')
    except Exception:
        pass
