"""Shipment and inbound shipment lines tenant scope.

Revision ID: b15_shipment_lines_tenant
Revises: b14_business_tenant
"""
from alembic import op
import sqlalchemy as sa

revision = 'b15_shipment_lines_tenant'
down_revision = 'b14_business_tenant'
branch_labels = None
depends_on = None

_TABLES = ('shipment_lines', 'inbound_shipment_lines')


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column(
            'tenant_id', sa.Integer(),
            sa.ForeignKey('tenants.id', ondelete='SET NULL'), nullable=True))
        op.create_index(f'idx_{table}_tenant', table, ['tenant_id'])


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.drop_index(f'idx_{table}_tenant', table_name=table)
        op.drop_column(table, 'tenant_id')
