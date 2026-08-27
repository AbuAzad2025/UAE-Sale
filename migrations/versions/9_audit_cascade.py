"""journal_entry_audits.entry_id -> ON DELETE CASCADE

Deleting draft journal entries was impossible on PostgreSQL once audit
rows existed (every created entry gets a 'create' audit): FK rejected
the delete. Audits of a deleted entry must survive as history.

Revision ID: 9_audit_cascade
Revises: 8_purchase_payment_tracking
"""
from alembic import op

revision = '9_audit_cascade'
down_revision = '8_purchase_payment_tracking'
branch_labels = None
depends_on = None


def _find_fk(bind):
    q = bind.execute(
        "SELECT conname FROM pg_constraint "
        "WHERE conrelid = 'journal_entry_audits'::regclass "
        "AND contype = 'f' AND conkey @> ARRAY[(SELECT attnum FROM pg_attribute "
        "WHERE attrelid='journal_entry_audits'::regclass AND attname='journal_entry_id')]"
    )
    row = q.first()
    return row[0] if row else None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return  # SQLite recreates schema from models (already CASCADE)
    name = _find_fk(bind)
    if name:
        op.drop_constraint(name, 'journal_entry_audits', type_='foreignkey')
    op.create_foreign_key(
        'fk_jea_entry_cascade', 'journal_entry_audits',
        'gl_journal_entries', ['journal_entry_id'], ['id'],
        ondelete='CASCADE',
    )


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return
    try:
        op.drop_constraint('fk_jea_entry_cascade', 'journal_entry_audits',
                           type_='foreignkey')
    except Exception:
        pass
    op.create_foreign_key(
        'journal_entry_audits_journal_entry_id_fkey',
        'journal_entry_audits', 'gl_journal_entries',
        ['journal_entry_id'], ['id'],
    )
