"""Per-tenant invoice profile: bank/terms/footer/template.

Revision ID: b7_tenant_invoice_profile
Revises: b6_corp_tax
"""
from alembic import op
import sqlalchemy as sa

revision = 'b7_tenant_invoice_profile'
down_revision = 'b6_corp_tax'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('tenants', sa.Column('bank_name', sa.Text(), nullable=True))
    op.add_column('tenants', sa.Column('bank_account_number', sa.Text(), nullable=True))
    op.add_column('tenants', sa.Column('iban', sa.Text(), nullable=True))
    op.add_column('tenants', sa.Column('swift_code', sa.String(length=50), nullable=True))
    op.add_column('tenants', sa.Column('payment_terms_ar', sa.Text(), nullable=True))
    op.add_column('tenants', sa.Column('footer_text_ar', sa.Text(), nullable=True))
    op.add_column('tenants', sa.Column('default_invoice_note_ar', sa.Text(), nullable=True))
    op.add_column('tenants', sa.Column('active_template', sa.String(length=50), server_default='modern', nullable=False))


def downgrade() -> None:
    for c in ('active_template', 'default_invoice_note_ar', 'footer_text_ar',
              'payment_terms_ar', 'swift_code', 'iban', 'bank_account_number', 'bank_name'):
        op.drop_column('tenants', c)
