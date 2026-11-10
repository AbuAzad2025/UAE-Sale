"""Maintenance Module Preparation — tenant flag + maintenance warehouse flag + movement types.

Revision ID: b28_maintenance_prep
Revises: b27_quotation_phase2
"""
from alembic import op
import sqlalchemy as sa

revision = 'b28_maintenance_prep'
down_revision = 'b27_quotation_phase2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Tenant feature flag: enable_maintenance
    op.add_column(
        'tenants',
        sa.Column('enable_maintenance', sa.Boolean(), nullable=False, server_default=sa.text('true')),
    )

    # Warehouse flag: is_maintenance_warehouse
    op.add_column(
        'warehouses',
        sa.Column('is_maintenance_warehouse', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    )


def downgrade() -> None:
    op.drop_column('warehouses', 'is_maintenance_warehouse')
    op.drop_column('tenants', 'enable_maintenance')
