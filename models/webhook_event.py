"""Processed webhook event ledger (replay protection).

Payment providers retransmit IPNs until they receive an acknowledgement, and
may legitimately send the same event more than once. Persisting a unique key
per provider/event makes processing idempotent across processes and restarts
(an in-memory set would not).
"""

from datetime import datetime, timezone

from extensions import db


class ProcessedWebhookEvent(db.Model):
    __tablename__ = "processed_webhook_events"

    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(50), nullable=False, index=True)
    event_id = db.Column(db.String(255), nullable=False, index=True)
    processed_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        db.UniqueConstraint(
            "provider", "event_id", name="uq_processed_webhook_provider_event"
        ),
    )

    def __repr__(self):
        return f"<ProcessedWebhookEvent {self.provider}:{self.event_id}>"
