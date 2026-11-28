"""Webhook replay ledger + NOT NULL payment confirmation.

- Adds ``processed_webhook_events`` with a UNIQUE (provider, event_id) key so
  a retransmitted IPN cannot update the same donation/payment twice.
- Backfills NULL payment_confirmed values with true and makes the column
  NOT NULL with a DEFAULT true in both ``payments`` and ``receipts``. The
  backfill is safe: no application path writes NULL (cheques use explicit
  false), so NULL can only be legacy/uninitialised data.

Revision ID: c17_webhook_replay_and_payment_confirmation
Revises: c16_tax_ruleset_versioning
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as _inspect

revision = "c17_webhook_replay_and_payment_confirmation"
down_revision = "c16_tax_ruleset_versioning"
branch_labels = None
depends_on = None

_TABLE = "processed_webhook_events"
_UNIQUE = "uq_processed_webhook_provider_event"
_CONFIRM_TABLES = ("payments", "receipts")


def _tables():
    return set(_inspect(op.get_bind()).get_table_names())


def _columns(table):
    return {c["name"] for c in _inspect(op.get_bind()).get_columns(table)}


def _unconfirm_nulls(table):
    col = sa.column("payment_confirmed", sa.Boolean())
    op.execute(
        sa.table(table, col)
        .update()
        .where(col.is_(None))
        .values(payment_confirmed=True)
    )


def upgrade():
    if _TABLE not in _tables():
        op.create_table(
            _TABLE,
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("provider", sa.String(length=50), nullable=False),
            sa.Column("event_id", sa.String(length=255), nullable=False),
            sa.Column("processed_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("provider", "event_id", name=_UNIQUE),
        )
        op.create_index(
            "ix_processed_webhook_events_provider", _TABLE, ["provider"]
        )
        op.create_index(
            "ix_processed_webhook_events_event_id", _TABLE, ["event_id"]
        )

    for table in _CONFIRM_TABLES:
        if table not in _tables() or "payment_confirmed" not in _columns(table):
            continue
        _unconfirm_nulls(table)
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                "payment_confirmed",
                existing_type=sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
                existing_nullable=True,
            )


def downgrade():
    for table in _CONFIRM_TABLES:
        if table not in _tables() or "payment_confirmed" not in _columns(table):
            continue
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                "payment_confirmed",
                existing_type=sa.Boolean(),
                nullable=True,
                server_default=None,
                existing_nullable=False,
            )

    if _TABLE in _tables():
        op.drop_index("ix_processed_webhook_events_event_id", table_name=_TABLE)
        op.drop_index("ix_processed_webhook_events_provider", table_name=_TABLE)
        op.drop_table(_TABLE)
