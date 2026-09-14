"""Tests for /owner/error-logs journal page + resolve triage."""


def _seed(db):
    from extensions import db as _db
    from models.error_log import ErrorLog
    rows = [
        ErrorLog(category='backend', severity='error', source='http-404',
                 username='ali', user_role='seller', method='GET',
                 path='/nope', message='404 /nope', resolved=False),
        ErrorLog(category='frontend', severity='error', source='js-onerror',
                 username='sara', method='GET', path='/sales/',
                 message='boom', resolved=True),
        ErrorLog(category='programming', severity='critical',
                 source='flask-500', username='ali', method='POST',
                 path='/sales/create', message='kaboom',
                 traceback_text='Traceback ...', resolved=False),
    ]
    _db.session.add_all(rows)
    _db.session.commit()
    return rows


def test_owner_sees_journal(client, login_owner, db):
    _seed(db)
    resp = client.get('/owner/error-logs')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'سجل الأخطاء' in html
    assert 'ali' in html
    assert 'sara' in html
    assert 'name="category"' in html
    assert 'Traceback' in html


def test_filter_category(client, login_owner, db):
    _seed(db)
    html = client.get('/owner/error-logs?category=frontend').get_data(as_text=True)
    assert 'sara' in html
    assert 'kaboom' not in html


def test_filter_status(client, login_owner, db):
    _seed(db)
    html = client.get('/owner/error-logs?status=resolved').get_data(as_text=True)
    assert 'sara' in html
    assert 'kaboom' not in html
    html = client.get('/owner/error-logs?status=open').get_data(as_text=True)
    assert 'kaboom' in html
    assert 'sara' not in html


def test_search_q(client, login_owner, db):
    _seed(db)
    html = client.get('/owner/error-logs?q=sara').get_data(as_text=True)
    assert 'sara' in html
    assert 'kaboom' not in html


def test_resolve_toggle(client, login_owner, db):
    from extensions import db as _db
    from models.error_log import ErrorLog
    rows = _seed(db)
    target = [r for r in rows if r.username == 'ali' and not r.resolved][0]
    resp = client.post('/owner/error-logs/%d/resolve' % target.id)
    assert resp.status_code == 302
    _db.session.expire_all()
    assert ErrorLog.query.get(target.id).resolved is True
    assert ErrorLog.query.get(target.id).resolved_by_id is not None
    client.post('/owner/error-logs/%d/resolve' % target.id)
    _db.session.expire_all()
    assert ErrorLog.query.get(target.id).resolved is False


def test_anonymous_redirected(client, db):
    assert client.get('/owner/error-logs').status_code == 302


def test_seller_blocked(client, login_seller, seller_user, db):
    assert client.get('/owner/error-logs').status_code == 302