"""Partner profit-sharing — product-scoped and company-scoped.

Revision ID: b25_partners
Revises: b24_support_incidents_backups
"""
from alembic import op
import sqlalchemy as sa

revision = 'b25_partners'
down_revision = 'b24_support_incidents_backups'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) خيارات الشريك على العميل لتتبع النوع على مستوى الشركات:
    #    'none' (الوضع الافتراضي) | 'product' | 'company'
    op.add_column(
        'customers',
        sa.Column('partner_scope', sa.String(length=16),
                  nullable=False, server_default='none'),
    )
    # نسبة مشاركة شريك الشركة (مثلاً 30% = 30.000)
    op.add_column(
        'customers',
        sa.Column('partner_share', sa.Numeric(6, 3), nullable=True),
    )

    # 2) ربط سطور GL بمعرّف الشريك (Customer) لتتبع جار الشريك بدقة
    op.add_column(
        'gl_journal_lines',
        sa.Column('party_id', sa.Integer(), nullable=True),
    )
    op.create_index(
        'ix_gl_journal_lines_party_id',
        'gl_journal_lines', ['party_id'],
    )
    op.create_foreign_key(
        'fk_gl_journal_lines_party_id',
        'gl_journal_lines', 'customers',
        ['party_id'], ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_gl_journal_lines_party_id', 'gl_journal_lines', type_='foreignkey')
    op.drop_index('ix_gl_journal_lines_party_id', table_name='gl_journal_lines')
    op.drop_column('gl_journal_lines', 'party_id')
    op.drop_column('customers', 'partner_share')
    op.drop_column('customers', 'partner_scope')
