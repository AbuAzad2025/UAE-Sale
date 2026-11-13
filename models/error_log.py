"""Error Log Model - comprehensive error tracking for the ERP system.

Every fault recorded here carries: when it happened, which layer
(backend / frontend / logic / programming / security / financial / database),
who was affected, where it happened, and the full (sanitized) technical detail.
The username is denormalized on purpose: the record must survive user deletion,
exactly like journal audit entries survive journal deletion.
"""

from datetime import datetime, timezone
from extensions import db


class ErrorLog(db.Model):
    """Structured error journal - backend/frontend/logic/programming/security/financial/database."""

    __tablename__ = "error_logs"

    # Categories
    CATEGORY_BACKEND = "backend"
    CATEGORY_FRONTEND = "frontend"
    CATEGORY_LOGIC = "logic"
    CATEGORY_PROGRAMMING = "programming"
    CATEGORY_SECURITY = "security"
    CATEGORY_FINANCIAL = "financial"
    CATEGORY_DATABASE = "database"
    CATEGORY_MIGRATION = "migration"
    CATEGORIES = (
        CATEGORY_BACKEND,
        CATEGORY_FRONTEND,
        CATEGORY_LOGIC,
        CATEGORY_PROGRAMMING,
        CATEGORY_SECURITY,
        CATEGORY_FINANCIAL,
        CATEGORY_DATABASE,
        CATEGORY_MIGRATION,
    )

    # Severities
    SEVERITY_CRITICAL = "critical"
    SEVERITY_ERROR = "error"
    SEVERITY_WARNING = "warning"
    SEVERITY_INFO = "info"
    SEVERITIES = (
        SEVERITY_CRITICAL,
        SEVERITY_ERROR,
        SEVERITY_WARNING,
        SEVERITY_INFO,
    )

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    category = db.Column(db.String(20), nullable=False, index=True)
    severity = db.Column(db.String(20), nullable=False, default="error", index=True)
    source = db.Column(db.String(50))

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    username = db.Column(db.String(150))
    user_role = db.Column(db.String(50))

    method = db.Column(db.String(10))
    path = db.Column(db.String(500))
    endpoint = db.Column(db.String(150))

    message = db.Column(db.Text, nullable=False)
    traceback_text = db.Column(db.Text)

    request_id = db.Column(db.String(50), index=True)
    ip_address = db.Column(db.String(50))
    user_agent = db.Column(db.String(500))

    resolved = db.Column(db.Boolean, default=False, nullable=False, index=True)
    resolved_at = db.Column(db.DateTime)
    resolved_by_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Extra context for security/financial/database events
    extra_context = db.Column(db.Text)

    def __repr__(self):
        return "<ErrorLog %s [%s/%s] %s>" % (
            self.id,
            self.category,
            self.severity,
            self.path,
        )

    def to_dict(self):
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "category": self.category,
            "severity": self.severity,
            "source": self.source,
            "username": self.username,
            "user_role": self.user_role,
            "method": self.method,
            "path": self.path,
            "request_id": self.request_id,
            "resolved": bool(self.resolved),
            "extra_context": self.extra_context,
        }
