"""
Error Log Model
سجل الأخطاء المركزي — توثيق منظم لكل خلل في النظام

Every fault recorded here carries: when it happened, which layer
(backend / frontend / logic / programming), who was affected, where
it happened, and the full (sanitized) technical detail. The username
is denormalized on purpose: the record must survive user deletion,
exactly like journal audit entries survive journal deletion.
"""

from datetime import datetime, timezone
from extensions import db


class ErrorLog(db.Model):
    """سجل منظم لكل أخطاء النظام — باكند/فرونت/منطق/برمجة."""

    __tablename__ = 'error_logs'

    CATEGORY_BACKEND = 'backend'
    CATEGORY_FRONTEND = 'frontend'
    CATEGORY_LOGIC = 'logic'
    CATEGORY_PROGRAMMING = 'programming'
    CATEGORIES = (
        CATEGORY_BACKEND,
        CATEGORY_FRONTEND,
        CATEGORY_LOGIC,
        CATEGORY_PROGRAMMING,
    )

    SEVERITY_CRITICAL = 'critical'
    SEVERITY_ERROR = 'error'
    SEVERITY_WARNING = 'warning'
    SEVERITIES = (
        SEVERITY_CRITICAL,
        SEVERITY_ERROR,
        SEVERITY_WARNING,
    )

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc),
        nullable=False, index=True)
    category = db.Column(db.String(20), nullable=False, index=True)
    severity = db.Column(db.String(20), nullable=False, default='error',
                         index=True)
    source = db.Column(db.String(50))

    # Who was affected. username is denormalized so the record stays
    # readable even after the user row is deleted.
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'),
                        nullable=True, index=True)
    username = db.Column(db.String(150))
    user_role = db.Column(db.String(50))

    # Where it happened.
    method = db.Column(db.String(10))
    path = db.Column(db.String(500))
    endpoint = db.Column(db.String(150))

    # What happened (always sanitized before persist).
    message = db.Column(db.Text, nullable=False)
    traceback_text = db.Column(db.Text)

    # Correlation / forensics.
    request_id = db.Column(db.String(50), index=True)
    ip_address = db.Column(db.String(50))
    user_agent = db.Column(db.String(500))

    # Triage.
    resolved = db.Column(db.Boolean, default=False, nullable=False, index=True)
    resolved_at = db.Column(db.DateTime)
    resolved_by_id = db.Column(
        db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True)

    def __repr__(self):
        return '<ErrorLog %s [%s/%s] %s>' % (
            self.id, self.category, self.severity, self.path)

    def to_dict(self):
        """تحويل إلى dictionary."""
        return {
            'id': self.id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'category': self.category,
            'severity': self.severity,
            'source': self.source,
            'username': self.username,
            'user_role': self.user_role,
            'method': self.method,
            'path': self.path,
            'request_id': self.request_id,
            'resolved': bool(self.resolved),
        }
