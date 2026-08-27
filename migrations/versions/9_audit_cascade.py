"""journal_entry_audits.entry_id -> ON DELETE CASCADE

Deleting draft journal entries was impossible on PostgreSQL once audit
rows existed (every created entry gets a 'create' audit): FK rejected
the delete. Audits of a deleted entry must survive as history.

Revision ID: 9_audit_cascade
Revises: 8_purchase_payment_tracking
"""
from alembic import op
import sqlalchemy as sa

revision = '9_audit_cascade'
down_revision = '8_purchase_payment_tracking'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return  # SQLite recreates schema from models (already CASCADE)
    # CASCADE history: DROP IF EXISTS يتجنب إجهاض المعاملة عند غياب القيد
    op.execute(sa.text(
        'ALTER TABLE journal_entry_audits '
        'DROP CONSTRAINT IF EXISTS journal_entry_audits_journal_entry_id_fkey'))
    op.execute(sa.text(
        'ALTER TABLE journal_entry_audits '
        'DROP CONSTRAINT IF EXISTS fk_jea_entry_cascade'))
    op.create_foreign_key(
        'fk_jea_entry_cascade', 'journal_entry_audits',
        'gl_journal_entries', ['journal_entry_id'], ['id'],
        ondelete='CASCADE',
    )


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return
    op.execute(sa.text(
        'ALTER TABLE journal_entry_audits '
        'DROP CONSTRAINT IF EXISTS fk_jea_entry_cascade'))
    op.execute(sa.text(
        'ALTER TABLE journal_entry_audits '
        'DROP CONSTRAINT IF EXISTS journal_entry_audits_journal_entry_id_fkey'))
    op.create_foreign_key(
        'journal_entry_audits_journal_entry_id_fkey',
        'journal_entry_audits', 'gl_journal_entries',
        ['journal_entry_id'], ['id'],
    )
