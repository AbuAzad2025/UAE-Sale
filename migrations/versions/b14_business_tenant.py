"""Shared business-data tables tenant scope.

Revision ID: b14_business_tenant
Revises: b13_erp_tenant
"""
from alembic import op
import sqlalchemy as sa

revision = 'b14_business_tenant'
down_revision = 'b13_erp_tenant'
branch_labels = None
depends_on = None

_TABLES = ('customs_taxes', 'advanced_expenses', 'tax_calculation_rules',
           'approval_workflows', 'approval_requests', 'approval_levels',
           'bank_reconciliations', 'bank_reconciliation_items',
           'budgets', 'budget_lines', 'cost_centers',
           'fixed_assets', 'depreciation_schedules',
           'archived_records', 'audit_logs', 'journal_entry_audits')


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
