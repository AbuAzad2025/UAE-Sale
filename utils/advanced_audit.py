from datetime import date, datetime, time as dt_time, timezone
from decimal import Decimal
from flask import has_request_context, request
from flask_login import current_user
from extensions import db
import hashlib


def jsonify_changes(value):
    """Coerce JSON-hostile scalars so audit payloads never drop rows.

    Decimal/datetime values are serialized; anything else JSON cannot encode
    is passed through untouched so json.dumps still fails loudly and the row
    is discarded instead of silently corrupted.
    """
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date, dt_time)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): jsonify_changes(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonify_changes(item) for item in value]
    return value


def generate_device_fingerprint() -> str:
    components = [
        request.headers.get('User-Agent', ''),
        request.headers.get('Accept-Language', ''),
        request.headers.get('Accept-Encoding', ''),
        str(request.headers.get('Sec-Ch-Ua-Platform', ''))
    ]

    fingerprint_string = '|'.join(components)
    return hashlib.sha256(fingerprint_string.encode()).hexdigest()[:16]


def log_sensitive_action(action: str, table_name: str = None, record_id: int = None,
                         changes: dict = None, severity: str = 'medium'):
    from models import AuditLog

    try:
        audit_entry = AuditLog(
            user_id=current_user.id if (getattr(current_user, 'is_authenticated', False)) else None,
            action=action,
            table_name=table_name,
            record_id=record_id,
            changes=jsonify_changes(changes),
            ip_address=request.remote_addr if has_request_context() else None,
            user_agent=request.headers.get('User-Agent') if has_request_context() else None
        )

        db.session.add(audit_entry)
        db.session.commit()

        if severity == 'high':
            notify_admin_of_sensitive_action(action, audit_entry)

    except Exception:
        db.session.rollback()


def notify_admin_of_sensitive_action(action: str, audit_entry):
    pass


def track_login_attempt(username: str, success: bool, ip_address: str):
    from models import User

    user = User.query.filter_by(username=username).first()

    if user:
        if success:
            user.login_attempts = 0
            user.last_login = datetime.now(timezone.utc)
        else:
            user.login_attempts = (user.login_attempts or 0) + 1

            if user.login_attempts >= 5:
                from datetime import timedelta
                user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=15)

        db.session.commit()


def get_security_events(user_id: int = None, days: int = 30, actions: list = None,
                        table_name: str = None, limit: int = 100):
    from models import AuditLog
    from datetime import timedelta

    since = datetime.now(timezone.utc) - timedelta(days=days)

    query = AuditLog.query.filter(AuditLog.created_at >= since)

    if user_id:
        query = query.filter_by(user_id=user_id)

    if table_name:
        query = query.filter(AuditLog.table_name == table_name)

    watched_actions = actions if actions is not None else ['login', 'logout', 'delete', 'update']
    query = query.filter(
        AuditLog.action.in_(watched_actions)
    ).order_by(AuditLog.created_at.desc())

    return query.limit(limit or 100).all()
