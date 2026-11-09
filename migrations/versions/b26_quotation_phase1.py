"""Quotation Phase 1 — per-line tax treatment, cost snapshot, inclusive/exclusive, status transitions, double-conversion guard.

Revision ID: b26_quotation_phase1
Revises: b25_partners
"""
from alembic import op
import sqlalchemy as sa

revision = 'b26_quotation_phase1'
down_revision = 'b25_partners'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) ترويسة عرض السعر — معاملة ضريبية + شاملة/إضافية + نشط + شروط + تحويل + صلاحية
    op.add_column('quotations', sa.Column('tax_inclusive', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('quotations', sa.Column('tax_treatment', sa.String(length=10), nullable=False, server_default='standard'))
    op.add_column('quotations', sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')))
    op.add_column('quotations', sa.Column('payment_terms', sa.Text(), nullable=True))
    op.add_column('quotations', sa.Column('terms_and_conditions', sa.Text(), nullable=True))
    op.add_column('quotations', sa.Column('validity_days', sa.Integer(), nullable=False, server_default='30'))
    op.add_column('quotations', sa.Column('converted_at', sa.DateTime(), nullable=True))

    # 2) أسطر عرض السعر — لقطة تكلفة + معاملة ضريبية
    op.add_column('quotation_lines', sa.Column('tax_treatment', sa.String(length=10), nullable=False, server_default='standard'))
    op.add_column('quotation_lines', sa.Column('cost_price', sa.Numeric(15, 3), nullable=True))


def downgrade() -> None:
    op.drop_column('quotation_lines', 'cost_price')
    op.drop_column('quotation_lines', 'tax_treatment')
    op.drop_column('quotations', 'converted_at')
    op.drop_column('quotations', 'validity_days')
    op.drop_column('quotations', 'terms_and_conditions')
    op.drop_column('quotations', 'payment_terms')
    op.drop_column('quotations', 'is_active')
    op.drop_column('quotations', 'tax_treatment')
    op.drop_column('quotations', 'tax_inclusive')
