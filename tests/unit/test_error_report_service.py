"""Tests for services/error_report_service.py — classify/sanitize/persist."""
import pytest


def test_classify_http_status():
    from services.error_report_service import classify_http_status
    assert classify_http_status(404) == ('backend', 'warning')
    assert classify_http_status(403) == ('backend', 'warning')
    assert classify_http_status(405) == ('backend', 'warning')
    assert classify_http_status(429) == ('backend', 'warning')
    assert classify_http_status(500) == ('programming', 'critical')
    assert classify_http_status(502) == ('programming', 'critical')
    assert classify_http_status(503) == ('programming', 'critical')
    assert classify_http_status('nope') == ('backend', 'warning')


def test_unknown_category_and_severity_raise():
    from services.error_report_service import report_error
    with pytest.raises(ValueError):
        report_error('nope', 'msg')
    with pytest.raises(ValueError):
        report_error('backend', 'msg', severity='nope')


def test_report_persists_request_snapshot(app, db):
    from models.error_log import ErrorLog
    from services.error_report_service import report_error
    with app.test_request_context('/x?y=1', method='POST',
                                  headers={'User-Agent': 'UA-1'},
                                  environ_base={'REMOTE_ADDR': '9.9.9.9'}):
        entry = report_error('backend', 'boom happened')
    assert entry is not None
    assert entry.id is not None
    stored = ErrorLog.query.first()
    assert stored.method == 'POST'
    assert stored.path == '/x'
    assert stored.ip_address == '9.9.9.9'
    assert stored.user_agent == 'UA-1'
    assert stored.username == 'anonymous'
    assert stored.request_id is not None
    assert len(stored.request_id) == 32


def test_report_redacts_secrets(db):
    from models.error_log import ErrorLog
    from services.error_report_service import report_error
    entry = report_error(
        'programming', 'login failed password=hunter2 card 4111 1111 1111 1111')
    assert entry is not None
    stored = ErrorLog.query.first()
    assert 'hunter2' not in stored.message
    assert '4111' not in stored.message
    assert '***REDACTED***' in stored.message


def test_report_truncates_long_message(db):
    from models.error_log import ErrorLog
    from services.error_report_service import report_error
    entry = report_error('backend', 'A' * 5000)
    stored = ErrorLog.query.first()
    assert len(stored.message) <= 2012
    assert stored.message.endswith('[truncated]')
    assert entry is not None


def test_report_db_failure_falls_back_without_raising(app, db, monkeypatch):
    import os
    from extensions import db as _db
    from services import error_report_service as svc
    from services.error_report_service import report_error
    fallback = os.path.join('logs', 'error_report_fallback.log')
    if os.path.exists(fallback):
        os.remove(fallback)

    def _boom():
        raise RuntimeError('db is down')

    monkeypatch.setattr(_db.session, 'commit', _boom)
    try:
        with app.test_request_context('/down'):
            entry = report_error('backend', 'persist me')
        assert entry is None
        assert os.path.exists(fallback)
        with open(fallback, encoding='utf-8') as f:
            assert 'persist me' in f.read()
    finally:
        if os.path.exists(fallback):
            os.remove(fallback)


def test_report_logic_error_defaults_warning(db):
    from models.error_log import ErrorLog
    from services.error_report_service import report_logic_error
    entry = report_logic_error('rule violated', source='test')
    assert entry is not None
    stored = ErrorLog.query.first()
    assert stored.category == 'logic'
    assert stored.severity == 'warning'


def test_report_exception_captures_traceback(db):
    from models.error_log import ErrorLog
    from services.error_report_service import report_exception
    try:
        raise ValueError('kaput')
    except ValueError:
        entry = report_exception(source='test')
    assert entry is not None
    stored = ErrorLog.query.first()
    assert stored.category == 'programming'
    assert stored.severity == 'critical'
    assert 'ValueError: kaput' in stored.message
    assert 'Traceback' in (stored.traceback_text or '')