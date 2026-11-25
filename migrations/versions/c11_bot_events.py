"""Create the ERP agent's durable queue, conversation state, and append-only audit."""

import sqlalchemy as sa
from alembic import op

revision = "c11_bot_events"
down_revision = "c10_assistant_action"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "bot_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer()),
        sa.Column("raw_input", sa.Text(), nullable=False),
        sa.Column("normalized", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("lease_token", sa.String(36)),
        sa.Column("lease_until", sa.DateTime()),
        sa.Column("result", sa.JSON()),
        sa.CheckConstraint("status IN ('queued','processing','completed','failed')", name="ck_bot_event_status"),
    )
    op.create_index("ix_bot_events_ready", "bot_events", ["status", "available_at", "created_at"])
    op.create_index("ix_bot_events_actor_order", "bot_events", ["user_id", "tenant_id", "created_at", "id"])
    op.create_table(
        "bot_conversations",
        sa.Column("scope_key", sa.String(64), primary_key=True),
        sa.Column("topic", sa.String(64), nullable=False),
        sa.Column("slots", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "bot_event_audit",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer()),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_bot_event_audit_event", "bot_event_audit", ["event_id", "id"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION bot_event_audit_reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'bot_event_audit is append-only';
            END;
            $$
        """)
        op.execute("""
            CREATE TRIGGER bot_event_audit_append_only
            BEFORE UPDATE OR DELETE OR TRUNCATE ON bot_event_audit
            FOR EACH STATEMENT EXECUTE FUNCTION bot_event_audit_reject_mutation()
        """)
    elif op.get_bind().dialect.name == "sqlite":
        for operation in ("UPDATE", "DELETE"):
            op.execute(f"""
                CREATE TRIGGER bot_event_audit_reject_{operation.lower()}
                BEFORE {operation} ON bot_event_audit
                BEGIN SELECT RAISE(ABORT, 'bot_event_audit is append-only'); END
            """)


def downgrade():
    op.drop_table("bot_event_audit")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION bot_event_audit_reject_mutation()")
    op.drop_table("bot_conversations")
    op.drop_table("bot_events")
