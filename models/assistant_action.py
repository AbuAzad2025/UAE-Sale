from datetime import datetime, timezone

from extensions import db


class AssistantAction(db.Model):
    """A durable proposal and the result of its at-most-once confirmation."""

    __tablename__ = "assistant_actions"
    __table_args__ = (
        db.Index("ix_assistant_actions_scope", "user_id", "tenant_id", "status", "expires_at"),
    )

    id = db.Column(db.String(36), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id"), nullable=True)
    tool = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(20), nullable=False)
    request_hash = db.Column(db.String(64), nullable=False)
    payload = db.Column(db.JSON, nullable=False)
    response = db.Column(db.Text, nullable=False)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
