"""Support tickets — قناة الدعم لكل مستأجر (tenant)."""

from datetime import datetime, timezone

from extensions import db
from models.tenant_scope import TenantScopedMixin

PRIORITIES = ("low", "normal", "high", "urgent")
STATUSES = ("open", "in_progress", "resolved", "closed")
CATEGORIES = ("bug", "billing", "howto", "feature_request", "other")


class SupportTicket(TenantScopedMixin, db.Model):
    __tablename__ = "support_tickets"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    author_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    subject = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)

    category = db.Column(db.String(24), nullable=False, default="other")
    priority = db.Column(db.String(10), nullable=False, default="normal")
    status = db.Column(db.String(16), nullable=False, default="open", index=True)

    resolution_notes = db.Column(db.Text)
    resolved_at = db.Column(db.DateTime)

    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    author = db.relationship("User", foreign_keys=[author_user_id])

    def sla_status(self):
        """simple SLA flags: overdue vs active tickets vs resolved."""
        from datetime import datetime as _dt

        if self.status in ("resolved", "closed"):
            return "done"
        sla_hours = {"urgent": 4, "high": 24, "normal": 72, "low": 168}.get(
            self.priority, 72
        )
        created = self.created_at
        if created is None:
            return "ok"
        if created.tzinfo is not None:
            created = created.replace(tzinfo=None)
        age = (_dt.utcnow() - created).total_seconds() / 3600
        return "breached" if age > sla_hours else "ok"

    def __repr__(self):
        return f"<SupportTicket #{self.id} {self.status}>"
