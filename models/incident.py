"""Incidents — سجل الحوادث التشغيلية لمالك المنصة."""

from datetime import datetime, timezone

from extensions import db

SEVERITIES = ("sev1", "sev2", "sev3")
STATUSES = ("open", "monitoring", "resolved")


class Incident(db.Model):
    __tablename__ = "incidents"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(240), nullable=False)
    severity = db.Column(db.String(8), nullable=False, default="sev2", index=True)
    status = db.Column(db.String(16), nullable=False, default="open", index=True)

    impact = db.Column(db.Text)
    resolution_notes = db.Column(db.Text)

    started_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    resolved_at = db.Column(db.DateTime)

    created_by_user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False
    )
    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    created_by = db.relationship("User", foreign_keys=[created_by_user_id])

    def __repr__(self):
        return f"<Incident #{self.id} {self.severity} {self.status}>"
