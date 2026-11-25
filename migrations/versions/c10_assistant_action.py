"""Persist assistant action proposals and their idempotent outcomes."""

import sqlalchemy as sa
from alembic import op

revision = "c10_assistant_action"
down_revision = "c09_maintenance_roles_consolidated"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "assistant_actions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id")),
        sa.Column("tool", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("response", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_assistant_actions_expires_at", "assistant_actions", ["expires_at"])
    op.create_index(
        "ix_assistant_actions_scope", "assistant_actions",
        ["user_id", "tenant_id", "status", "expires_at"],
    )


def downgrade():
    op.drop_index("ix_assistant_actions_scope", table_name="assistant_actions")
    op.drop_index("ix_assistant_actions_expires_at", table_name="assistant_actions")
    op.drop_table("assistant_actions")
