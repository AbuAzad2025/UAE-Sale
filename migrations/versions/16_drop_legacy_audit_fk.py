"""Drop legacy restrictive audit FK left over by 9_audit_cascade.

Migration 9 added ``fk_jea_entry_cascade`` (ON DELETE CASCADE) but dropped
the wrong legacy name (``journal_entry_audits_journal_entry_id_fkey``),
while the initial migration had created the constraint as
``fk_journal_entry_audits_journal_entry_id_gl_journal_entries`` (restrictive).
Migration-built databases therefore carry BOTH constraints and draft-entry
deletes are still rejected at DB level by the legacy one.

This migration drops the legacy name IF EXISTS (safe no-op on
create_all-built test schemas, which never had it). The CASCADE behavior
itself is unchanged.

Revision ID: 16_drop_legacy_audit_fk (24 chars — must stay <= 32 for the
alembic_version VARCHAR(32) column on legacy databases).
Revises: 15_approval_wf_recon
"""
from alembic import op
import sqlalchemy as sa

revision = '16_drop_legacy_audit_fk'
down_revision = '15_approval_wf_recon'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return  # SQLite test schemas are built from models (already clean)
    op.execute(sa.text(
        'ALTER TABLE journal_entry_audits '
        'DROP CONSTRAINT IF EXISTS '
        'fk_journal_entry_audits_journal_entry_id_gl_journal_entries'))


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return
    # Restores the pre-16 state (restrictive FK alongside the CASCADE one).
    op.execute(sa.text(
        'ALTER TABLE journal_entry_audits '
        'DROP CONSTRAINT IF EXISTS '
        'fk_journal_entry_audits_journal_entry_id_gl_journal_entries'))
    op.create_foreign_key(
        'fk_journal_entry_audits_journal_entry_id_gl_journal_entries',
        'journal_entry_audits', 'gl_journal_entries',
        ['journal_entry_id'], ['id'],
    )
