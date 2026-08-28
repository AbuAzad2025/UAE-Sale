"""depreciation_schedules.journal_entry_id -> remove FK

The FK was too strict: post_depreciation creates the GL entry and
the schedule in the same transaction, but under PG the FK check
failed when the entry had not yet been flushed in some code paths.
Making it a plain Integer (no FK) matches the intended loose coupling
— the schedule references the entry id for audit, not for cascade.

Revision ID: 10_remove_depr_fk
Revises: 9_audit_cascade
"""
from alembic import op
import sqlalchemy as sa

revision = '10_remove_depr_fk'
down_revision = '9_audit_cascade'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        op.execute(sa.text(
            'ALTER TABLE depreciation_schedules '
            'DROP CONSTRAINT IF EXISTS depreciation_schedules_journal_entry_id_fkey'))
        # column stays Integer, no new FK


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        op.execute(sa.text(
            'ALTER TABLE depreciation_schedules DROP CONSTRAINT IF EXISTS '
            'depreciation_schedules_journal_entry_id_fkey'))
        op.create_foreign_key(
            'depreciation_schedules_journal_entry_id_fkey',
            'depreciation_schedules', 'gl_journal_entries',
            ['journal_entry_id'], ['id'],
        )
