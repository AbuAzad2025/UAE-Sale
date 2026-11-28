"""Persisted, per-user notifications (replaces the in-memory list)."""
from datetime import datetime, timezone
from extensions import db


class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id"), nullable=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False, default="")
    type = db.Column(db.String(20), nullable=False, default="info")
    data_json = db.Column(db.Text, nullable=True)
    read_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False,
                           default=lambda: datetime.now(timezone.utc), index=True)

    def to_dict(self):
        import json
        try:
            data = json.loads(self.data_json or "{}")
        except Exception:
            data = {}
        return {
            "id": self.id,
            "title": self.title,
            "message": self.body,
            "type": self.type,
            "data": data,
            "timestamp": self.created_at.isoformat() if self.created_at else None,
            "read": bool(self.read_at),
        }
