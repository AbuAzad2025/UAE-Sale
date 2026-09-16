"""Let deletion audits survive their entry (drop entry FK enforcement).

Design correction honoring migration 9's stated intent ("audits of a
deleted entry must survive as history") and the delete unit test, which
pins that the 'delete' audit row keeps its journal_entry_id after the
entry row is gone.

History so far:
* initial migration created a RESTRICTIVE FK -> draft deletes blocked
  once any audit row existed;
* migration 9 added ``fk_jea_entry_cascade`` (CASCADE) but dropped the
  wrong legacy name, leaving both constraints;
* migration 16 removed the legacy restrictive name.

Even with a single CASCADE FK, the trail is destroyed with the entry —
the opposite of an audit log's purpose. The reference therefore becomes
FK-free: the ORM mapping keeps the column as a historical Integer and
``passive_deletes`` so session.delete(entry) never nulls/touches audit
rows. This migration drops the remaining CASCADE constraint on
migration-built databases (safe no-op on create_all-built test schemas).

Revision ID: 17_audit_trail_survives (23 chars — must stay <= 32 for the
alembic_version VARCHAR(32) column on legacy databases).
Revises: 16_drop_legacy_audit_fk
"""
from alembic import op
import sqlalchemy as sa

revision = '17_audit_trail_survives'
down_revision = '16_drop_legacy_audit_fk'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return  # SQLite test schemas are built from models (already FK-free)
    op.execute(sa.text(
        'ALTER TABLE journal_entry_audits '
        'DROP CONSTRAINT IF EXISTS fk_jea_entry_cascade'))
    op.execute(sa.text(
        'ALTER TABLE journal_entry_audits '
        'DROP CONSTRAINT IF EXISTS '
        'fk_journal_entry_audits_journal_entry_id_gl_journal_entries'))


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return
    # Restores the pre-17 state (CASCADE FK). Historical audit rows that
    # outlived their entries would violate it on re-creation only if such
    # orphans exist — acceptable for a downgrade path.
    op.create_foreign_key(
        'fk_jea_entry_cascade', 'journal_entry_audits',
        'gl_journal_entries', ['journal_entry_id'], ['id'],
        ondelete='CASCADE',
    )
