"""Quotation Phase 2 — versioning, email tracking, search optimization.

Revision ID: b27_quotation_phase2
Revises: b26_quotation_phase1
"""
from alembic import op
import sqlalchemy as sa

revision = 'b27_quotation_phase2'
down_revision = 'b26_quotation_phase1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Versioning fields on quotations
    op.add_column('quotations', sa.Column('version', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('quotations', sa.Column('parent_quotation_id', sa.Integer(), sa.ForeignKey('quotations.id'), nullable=True))
    op.add_column('quotations', sa.Column('is_latest_version', sa.Boolean(), nullable=False, server_default=sa.text('true')))
    op.add_column('quotations', sa.Column('version_notes', sa.Text(), nullable=True))

    # Email tracking
    op.add_column('quotations', sa.Column('email_sent_at', sa.DateTime(), nullable=True))
    op.add_column('quotations', sa.Column('email_sent_to', sa.String(255), nullable=True))

    # Index for version lookup
    op.create_index('ix_quotations_parent', 'quotations', ['parent_quotation_id'])


def downgrade() -> None:
    op.drop_index('ix_quotations_parent', table_name='quotations')
    op.drop_column('quotations', 'email_sent_to')
    op.drop_column('quotations', 'email_sent_at')
    op.drop_column('quotations', 'version_notes')
    op.drop_column('quotations', 'is_latest_version')
    op.drop_column('quotations', 'parent_quotation_id')
    op.drop_column('quotations', 'version')