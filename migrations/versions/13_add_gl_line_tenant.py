"""Add tenant_id to gl_journal_lines for full row-level isolation.

GLJournalLine previously had no tenant_id column; isolation relied solely on
always reaching lines through a tenant-scoped GLJournalEntry (JOIN) or the
relationship ``entry``. This migration adds an explicit tenant_id (indexed,
nullable FK) mirroring the parent GLJournalEntry tenant, so that direct queries
on gl_journal_lines are auto-filtered by the tenant-scope guard just like every
other registered business table. Existing rows are backfilled from their parent
entry (gl_journal_entries.tenant_id).

Revision ID: 13_add_gl_line_tenant
Revises: 12_decimal_indexes_currency_fix
Create Date: 2026-09-03
"""
from alembic import op
import sqlalchemy as sa


revision = '13_add_gl_line_tenant'
down_revision = '12_decimal_indexes_currency_fix'
branch_labels = None
depends_on = None


def _inspector_has_table(bind, table_name):
    """Alembic-style portable table existence check (matches migrations 11/12)."""
    try:
        inspector = sa.inspect(bind)
        return table_name in inspector.get_table_names()
    except Exception:
        return False


def _column_exists(bind, table_name, column_name):
    """Return True if a column already exists on the given table."""
    try:
        inspector = sa.inspect(bind)
        cols = {c['name'] for c in inspector.get_columns(table_name)}
        return column_name in cols
    except Exception:
        return False


def upgrade():
    bind = op.get_bind()
    if not _inspector_has_table(bind, 'gl_journal_lines'):
        return

    # 1. Add tenant_id (indexed, nullable FK) if not already present.
    if not _column_exists(bind, 'gl_journal_lines', 'tenant_id'):
        with op.batch_alter_table('gl_journal_lines', schema=None) as batch_op:
            batch_op.add_column(sa.Column(
                'tenant_id', sa.Integer(),
                sa.ForeignKey('tenants.id', ondelete='SET NULL'),
                nullable=True))
            batch_op.create_index('ix_gl_journal_lines_tenant_id', ['tenant_id'], unique=False)

    # 2. Backfill: copy tenant_id from each line's parent journal entry.
    #    Any line whose entry has a NULL tenant stays NULL (platform-level row);
    #    rows without a parent are left untouched to avoid orphaning data.
    op.execute("""
        UPDATE gl_journal_lines AS l
        SET tenant_id = e.tenant_id
        FROM gl_journal_entries AS e
        WHERE l.entry_id = e.id
          AND l.tenant_id IS NULL
    """)


def downgrade():
    bind = op.get_bind()
    if not _inspector_has_table(bind, 'gl_journal_lines'):
        return
    if not _column_exists(bind, 'gl_journal_lines', 'tenant_id'):
        return

    with op.batch_alter_table('gl_journal_lines', schema=None) as batch_op:
        batch_op.drop_index('ix_gl_journal_lines_tenant_id')
        batch_op.drop_column('tenant_id')