"""Field sales shipments — الإرسالية الميدانية.

Each shipment moves goods from any warehouse (company/branch) to a field site
for direct selling. Lifecycle: draft → in_transit → arrived → selling → closed
(and cancelled from any non-closed state). Linked optionally to sales via
sales.shipment_id for the full chain: shipment → sale → payment → receipt → invoice.

Revision ID: 20_shipment_module (17 chars — must stay <= 32).
Revises: 19_error_log_table
"""
from alembic import op
import sqlalchemy as sa


revision = '20_shipment_module'
down_revision = '19_error_log_table'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'shipments' in inspector.get_table_names():
        return

    op.create_table(
        'shipments',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id', ondelete='SET NULL')),
        sa.Column('shipment_number', sa.String(50), nullable=False, unique=True),
        sa.Column('from_warehouse_id', sa.Integer(), sa.ForeignKey('warehouses.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('destination_warehouse_id', sa.Integer(), sa.ForeignKey('warehouses.id', ondelete='SET NULL')),
        sa.Column('destination_name', sa.String(200), nullable=False),
        sa.Column('destination_type', sa.String(20), nullable=False, server_default='site'),
        sa.Column('status', sa.String(20), nullable=False, server_default='draft'),
        sa.Column('total_value', sa.Numeric(15, 3), nullable=False, server_default='0'),
        sa.Column('total_quantity', sa.Numeric(15, 3), nullable=False, server_default='0'),
        sa.Column('notes', sa.Text()),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('assigned_to_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('shipped_at', sa.DateTime(timezone=True)),
        sa.Column('arrived_at', sa.DateTime(timezone=True)),
        sa.Column('closed_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('draft','in_transit','arrived','selling','closed','cancelled')",
                           name='ck_shipments_status_valid'),
        sa.CheckConstraint('total_value >= 0', name='ck_shipments_total_non_negative'),
    )
    op.create_index('ix_shipments_tenant_status', 'shipments', ['tenant_id', 'status'])
    op.create_index('ix_shipments_warehouse', 'shipments', ['from_warehouse_id'])
    op.create_index('ix_shipments_destination', 'shipments', ['destination_warehouse_id'])
    op.create_index('ix_shipments_status', 'shipments', ['status'])
    op.create_index('ix_shipments_tenant_id', 'shipments', ['tenant_id'])

    op.create_table(
        'shipment_lines',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('shipment_id', sa.Integer(), sa.ForeignKey('shipments.id', ondelete='CASCADE'), nullable=False),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('quantity', sa.Numeric(15, 3), nullable=False),
        sa.Column('unit_cost', sa.Numeric(15, 3), nullable=False, server_default='0'),
        sa.Column('unit_price', sa.Numeric(15, 3), nullable=False, server_default='0'),
        sa.Column('line_total', sa.Numeric(15, 3), nullable=False, server_default='0'),
        sa.Column('notes', sa.String(255)),
        sa.CheckConstraint('quantity > 0', name='ck_shipmentline_qty_positive'),
        sa.CheckConstraint('unit_cost >= 0', name='ck_shipmentline_cost_non_negative'),
        sa.CheckConstraint('line_total >= 0', name='ck_shipmentline_total_non_negative'),
    )
    op.create_index('ix_shipment_lines_shipment', 'shipment_lines', ['shipment_id'])
    op.create_index('ix_shipment_lines_product', 'shipment_lines', ['product_id'])

    # Link sales to their originating shipment (nullable, for the shipment→sale→payment→invoice chain)
    # Native PostgreSQL ALTER TABLE — no batch mode.
    cols = [c['name'] for c in sa.inspect(bind).get_columns('sales')]
    if 'shipment_id' not in cols:
        op.add_column('sales', sa.Column('shipment_id', sa.Integer(), sa.ForeignKey('shipments.id', ondelete='SET NULL'), nullable=True))
        op.create_index('ix_sales_shipment_id', 'sales', ['shipment_id'])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = [c['name'] for c in inspector.get_columns('sales')] if 'sales' in inspector.get_table_names() else []
    if 'shipment_id' in cols:
        try:
            op.drop_index('ix_sales_shipment_id', table_name='sales')
        except Exception:
            pass
        try:
            op.drop_column('sales', 'shipment_id')
        except Exception:
            pass
    for name in ('ix_shipment_lines_product', 'ix_shipment_lines_shipment'):
        try:
            op.drop_index(name, table_name='shipment_lines')
        except Exception:
            pass
    try:
        op.drop_table('shipment_lines')
    except Exception:
        pass
    for name in ('ix_shipments_tenant_id', 'ix_shipments_status',
                 'ix_shipments_destination', 'ix_shipments_warehouse', 'ix_shipments_tenant_status'):
        try:
            op.drop_index(name, table_name='shipments')
        except Exception:
            pass
    try:
        op.drop_table('shipments')
    except Exception:
        pass
