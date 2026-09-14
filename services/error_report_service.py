"""
Central error reporting — classify, sanitize, persist.

Contract:
- Categories are fixed: backend / frontend / logic / programming.
- Every stored string passes through the log sanitizer (no passwords,
  tokens, card numbers or IBANs ever persist).
- Persistence NEVER raises: on DB failure the report falls back to a
  local file and the function returns None. Unknown categories raise
  ValueError immediately (programmer error must fail fast, never
  silently misfile).
"""

import logging
import os
import traceback
import uuid

from flask import g, has_app_context, has_request_context, request
from flask_login import current_user

from extensions import db
from models import ErrorLog
from utils.log_sanitizer import sanitize_log_message

logger = logging.getLogger(__name__)

CATEGORY_BACKEND = ErrorLog.CATEGORY_BACKEND
CATEGORY_FRONTEND = ErrorLog.CATEGORY_FRONTEND
CATEGORY_LOGIC = ErrorLog.CATEGORY_LOGIC
CATEGORY_PROGRAMMING = ErrorLog.CATEGORY_PROGRAMMING
CATEGORIES = ErrorLog.CATEGORIES

MAX_MESSAGE_LEN = 2000
MAX_TRACE_LEN = 8000
MAX_PATH_LEN = 500
MAX_UA_LEN = 500
MAX_USERNAME_LEN = 150

FALLBACK_FILE = os.path.join('logs', 'error_report_fallback.log')


def classify_http_status(status_code):
    """Map an HTTP status to (category, severity).

    5xx means our code broke -> programming / critical.
    4xx means a bad request arrived -> backend / warning.
    """
    try:
        code = int(status_code)
    except (TypeError, ValueError):
        return CATEGORY_BACKEND, ErrorLog.SEVERITY_WARNING
    if 500 <= code <= 599:
        return CATEGORY_PROGRAMMING, ErrorLog.SEVERITY_CRITICAL
    return CATEGORY_BACKEND, ErrorLog.SEVERITY_WARNING


def _actor_snapshot(user=None):
    """Who was affected: (user_id, username, role). Never raises."""
    try:
        person = user
        if person is None:
            if not has_request_context():
                return None, 'system', None
            person = current_user
        if person is None or not getattr(person, 'is_authenticated', False):
            return None, 'anonymous', None
        role = getattr(person, 'role', None)
        role_slug = getattr(role, 'slug', None)
        if not role_slug and getattr(person, 'is_owner', False):
            role_slug = 'owner'
        return (getattr(person, 'id', None),
                (getattr(person, 'username', None) or 'unknown')[:MAX_USERNAME_LEN],
                role_slug)
    except Exception:
        return None, 'unknown', None


def _request_snapshot(path=None, method=None):
    """Where it happened: method/path/endpoint/ip/agent/request_id."""
    snapshot = {'method': method, 'path': path, 'endpoint': None,
                'ip_address': None, 'user_agent': None, 'request_id': None}
    try:
        if has_request_context():
            if snapshot['method'] is None:
                snapshot['method'] = request.method
            if snapshot['path'] is None:
                snapshot['path'] = request.path
            try:
                snapshot['endpoint'] = request.endpoint
            except Exception:
                pass
            snapshot['ip_address'] = request.remote_addr
            ua = request.headers.get('User-Agent', '')
            snapshot['user_agent'] = ua[:MAX_UA_LEN] if ua else None
            try:
                snapshot['request_id'] = g.get('request_id')
            except Exception:
                pass
    except Exception:
        pass
    if not snapshot['request_id']:
        snapshot['request_id'] = uuid.uuid4().hex
    if snapshot['path']:
        snapshot['path'] = snapshot['path'][:MAX_PATH_LEN]
    return snapshot


def _clean(text, limit):
    if not text:
        return None
    cleaned = sanitize_log_message(str(text))
    if len(cleaned) > limit:
        cleaned = cleaned[:limit] + '…[truncated]'
    return cleaned


def _fallback_to_file(payload):
    try:
        os.makedirs(os.path.dirname(FALLBACK_FILE) or '.', exist_ok=True)
        with open(FALLBACK_FILE, 'a', encoding='utf-8', errors='replace') as f:
            f.write(payload + '\n')
    except Exception:
        pass


def report_error(category, message, *, severity='error', traceback_text=None,
                 source='manual', user=None, path=None, method=None):
    """Persist one structured error record. Returns ErrorLog or None.

    Raises ValueError for unknown category/severity (programmer error).
    Never raises for persistence problems (DB down, no app context…):
    falls back to a local file and returns None.
    """
    if category not in CATEGORIES:
        raise ValueError('Unknown error category: %r' % (category,))
    if severity not in ErrorLog.SEVERITIES:
        raise ValueError('Unknown error severity: %r' % (severity,))

    clean_message = _clean(message, MAX_MESSAGE_LEN) or '(empty error message)'
    clean_trace = _clean(traceback_text, MAX_TRACE_LEN)
    user_id, username, role = _actor_snapshot(user)
    snap = _request_snapshot(path=path, method=method)

    entry = ErrorLog(
        category=category,
        severity=severity,
        source=(source or 'manual')[:50],
        user_id=user_id,
        username=username,
        user_role=role,
        method=snap['method'],
        path=snap['path'],
        endpoint=snap['endpoint'],
        message=clean_message,
        traceback_text=clean_trace,
        request_id=snap['request_id'],
        ip_address=snap['ip_address'],
        user_agent=snap['user_agent'],
    )
    try:
        if not has_app_context():
            raise RuntimeError('no app context for error persistence')
        db.session.add(entry)
        db.session.commit()
        return entry
    except Exception as exc:
        try:
            db.session.rollback()
        except Exception:
            pass
        try:
            logger.warning('error-log persist failed (%s); using file fallback',
                           type(exc).__name__)
        except Exception:
            pass
        _fallback_to_file('[%s/%s] %s | %s | %s' % (
            category, severity, username, snap['path'], clean_message))
        return None


def report_logic_error(message, **kwargs):
    """Business-rule violation (logic layer). Severity defaults to warning."""
    kwargs.setdefault('severity', ErrorLog.SEVERITY_WARNING)
    return report_error(CATEGORY_LOGIC, message, **kwargs)


def report_exception(exc=None, *, source='flask-500', **kwargs):
    """Uncaught exception (programming layer). Severity critical."""
    if exc is None:
        tb_text = traceback.format_exc()
        message = tb_text.strip().splitlines()[-1] if tb_text.strip() else 'Unknown error'
    else:
        tb_text = ''.join(traceback.format_exception(
            type(exc), exc, exc.__traceback__))
        message = '%s: %s' % (type(exc).__name__, exc)
    kwargs.setdefault('severity', ErrorLog.SEVERITY_CRITICAL)
    return report_error(CATEGORY_PROGRAMMING, message,
                        traceback_text=tb_text, source=source, **kwargs)
