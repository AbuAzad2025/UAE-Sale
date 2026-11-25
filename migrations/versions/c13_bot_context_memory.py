"""Persist scoped references for local agent conversations."""

import sqlalchemy as sa
from alembic import op

revision = "c13_bot_context_memory"
down_revision = "c12_bot_commands"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "bot_context_memory",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("references", sa.JSON(), nullable=False),
        sa.Column("last_tool", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table("bot_context_memory")
