"""Store authenticated structured commands beside conversational events."""

import sqlalchemy as sa
from alembic import op

revision = "c12_bot_commands"
down_revision = "c11_bot_events"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("bot_events", sa.Column("command", sa.JSON()))
    op.add_column("bot_events", sa.Column("command_kind", sa.String(40)))


def downgrade():
    with op.batch_alter_table("bot_events") as batch:
        batch.drop_column("command")
        batch.drop_column("command_kind")
