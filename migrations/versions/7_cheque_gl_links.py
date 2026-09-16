"""Add cheque GL entry linkage columns (receive/clear/bounce journal refs)

Revision ID: 7_cheque_gl_links
Revises: 6_rename_amount_base
"""
from alembic import op
import sqlalchemy as sa

revision = '7_cheque_gl_links'
down_revision = '6_rename_amount_base'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('cheques') as batch:
        batch.add_column(sa.Column('gl_journal_entry_id', sa.Integer(),
                                   sa.ForeignKey('gl_journal_entries.id'), nullable=True))
        batch.add_column(sa.Column('gl_clearing_entry_id', sa.Integer(),
                                   sa.ForeignKey('gl_journal_entries.id'), nullable=True))
        batch.add_column(sa.Column('gl_bounce_entry_id', sa.Integer(),
                                   sa.ForeignKey('gl_journal_entries.id'), nullable=True))
    op.create_index('ix_cheques_gl_journal_entry_id', 'cheques', ['gl_journal_entry_id'])


def downgrade():
    with op.batch_alter_table('cheques') as batch:
        batch.drop_column('gl_bounce_entry_id')
        batch.drop_column('gl_clearing_entry_id')
        batch.drop_column('gl_journal_entry_id')
