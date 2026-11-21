"""Add idempotency_key to GL journal entries.

Revision ID: c02_gl_idempotency_key
Revises: c01_drop_package_system

Enables callers to post a financial journal exactly once for a given logical
operation (e.g. one payment -> one GL entry). Opt-in: NULL keys keep the
legacy multi-leg behaviour where several entries share a document reference.
"""
from alembic import op
import sqlalchemy as sa

revision = "c02_gl_idempotency_key"
down_revision = "c01_drop_package_system"
branch_labels = None
depends_on = None


def _has_column(table, column):
    return column in [c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)]


def upgrade():
    if not _has_column("gl_journal_entries", "idempotency_key"):
        with op.batch_alter_table("gl_journal_entries") as batch:
            batch.add_column(sa.Column("idempotency_key", sa.String(120), nullable=True))
            batch.create_index(
                "ix_gl_journal_entries_idempotency",
                ["tenant_id", "idempotency_key"],
                unique=False,
            )


def downgrade():
    if _has_column("gl_journal_entries", "idempotency_key"):
        with op.batch_alter_table("gl_journal_entries") as batch:
            batch.drop_index("ix_gl_journal_entries_idempotency")
            batch.drop_column("idempotency_key")
