"""Tests for POST /api/client-errors — browser error beacon."""


def _post(client, payload, origin='http://localhost'):
    headers = {}
    if origin is not None:
        headers['Origin'] = origin
    return client.post('/api/client-errors', json=payload, headers=headers)


def test_anonymous_report_persisted(client, db):
    from models.error_log import ErrorLog
    resp = _post(client, {'message': 'boom', 'stack': 'at x (y:1:2)',
                          'page': '/sales/create', 'kind': 'onerror'})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['success'] is True
    assert isinstance(body['report_id'], int)
    stored = ErrorLog.query.first()
    assert stored.category == 'frontend'
    assert stored.username == 'anonymous'
    assert stored.path == '/sales/create'
    assert stored.source == 'js-onerror'


def test_logged_in_username_recorded(client, db, login_owner):
    from models.error_log import ErrorLog
    resp = _post(client, {'message': 'boom2', 'kind': 'unhandledrejection'})
    assert resp.status_code == 200
    stored = ErrorLog.query.filter_by(message='boom2').first()
    assert stored is not None
    assert stored.username == 'testowner'
    assert stored.source == 'js-unhandledrejection'


def test_non_json_rejected(client, db):
    resp = client.post('/api/client-errors', data='x',
                       content_type='text/plain')
    assert resp.status_code == 400


def test_missing_message_rejected(client, db):
    resp = _post(client, {'stack': 'at x'})
    assert resp.status_code == 400


def test_oversized_message_truncated(client, db):
    from models.error_log import ErrorLog
    resp = _post(client, {'message': 'A' * 5000})
    assert resp.status_code == 200
    stored = ErrorLog.query.first()
    assert len(stored.message) <= 2012
    assert stored.message.endswith('[truncated]')
    assert 'A' * 100 in stored.message


def test_foreign_origin_rejected(client, db):
    resp = _post(client, {'message': 'x'}, origin='http://evil.example')
    assert resp.status_code == 403


def test_beacon_secrets_redacted(client, db):
    from models.error_log import ErrorLog
    resp = _post(client, {'message': 'oops password=hunter2'})
    assert resp.status_code == 200
    stored = ErrorLog.query.first()
    assert 'hunter2' not in stored.message
    assert '***REDACTED***' in stored.message