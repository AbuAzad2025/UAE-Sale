"""Expense tenant scope.

Revision ID: b11_expense_tenant
Revises: b10_sale_line_tax_treatment

Backfill is deliberately manual: every existing expense row is assigned to no
tenant (NULL) — it stays visible to the platform owner only, and cannot be
printed as a tenant document until assigned. Running this on a live install
must be paired with a tenant assignment pass for historical data.
"""
from alembic import op
import sqlalchemy as sa

revision = 'b11_expense_tenant'
down_revision = 'b10_sale_line_tax_treatment'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('expenses', sa.Column(
        'tenant_id', sa.Integer(),
        sa.ForeignKey('tenants.id', ondelete='SET NULL'), nullable=True))
    op.create_index('idx_expenses_tenant', 'expenses', ['tenant_id'])


def downgrade() -> None:
    op.drop_index('idx_expenses_tenant', table_name='expenses')
    op.drop_column('expenses', 'tenant_id')
