"""Durable and auditable storage for bot_core."""

from sqlalchemy import DDL, event

from extensions import db


class BotEvent(db.Model):
    __tablename__ = "bot_events"
    __table_args__ = (
        db.CheckConstraint("status IN ('queued','processing','completed','failed')", name="ck_bot_event_status"),
        db.Index("ix_bot_events_ready", "status", "available_at", "created_at"),
        db.Index("ix_bot_events_actor_order", "user_id", "tenant_id", "created_at", "id"),
    )

    id = db.Column(db.String(36), primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    tenant_id = db.Column(db.Integer)
    raw_input = db.Column(db.Text, nullable=False)
    normalized = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(16), nullable=False)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False)
    available_at = db.Column(db.DateTime, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    lease_token = db.Column(db.String(36))
    lease_until = db.Column(db.DateTime)
    result = db.Column(db.JSON)
    command = db.Column(db.JSON)
    command_kind = db.Column(db.String(40))


class BotEventAudit(db.Model):
    __tablename__ = "bot_event_audit"
    __table_args__ = (db.Index("ix_bot_event_audit_event", "event_id", "id"),)

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.String(36), nullable=False)
    user_id = db.Column(db.Integer, nullable=False)
    tenant_id = db.Column(db.Integer)
    outcome = db.Column(db.String(32), nullable=False)
    details = db.Column(db.JSON, nullable=False)
    recorded_at = db.Column(db.DateTime, nullable=False)


class BotConversation(db.Model):
    __tablename__ = "bot_conversations"

    scope_key = db.Column(db.String(64), primary_key=True)
    topic = db.Column(db.String(64), nullable=False)
    slots = db.Column(db.JSON, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)


# SQLite development startup builds tables from metadata instead of running Alembic.
for operation in ("UPDATE", "DELETE"):
    event.listen(
        BotEventAudit.__table__,
        "after_create",
        DDL(f"""
            CREATE TRIGGER bot_event_audit_reject_{operation.lower()}
            BEFORE {operation} ON bot_event_audit
            BEGIN SELECT RAISE(ABORT, 'bot_event_audit is append-only'); END
        """).execute_if(dialect="sqlite"),
    )
