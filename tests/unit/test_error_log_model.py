"""Tests for models/error_log.py — structured error journal records."""


def _make_user(db, username='erruser'):
    from models import User, Role
    from extensions import db as _db
    role = Role(name='ErrRole', name_ar='دور', slug='err_role_%s' % username)
    _db.session.add(role)
    _db.session.flush()
    user = User(username=username, email=username + '@test.com',
                full_name='Err User', is_owner=False, is_active=True,
                role_id=role.id)
    user.set_password('Pass123!')
    _db.session.add(user)
    _db.session.commit()
    return user


def test_defaults_and_repr(db):
    from extensions import db as _db
    from models.error_log import ErrorLog
    entry = ErrorLog(category='backend', message='boom')
    _db.session.add(entry)
    _db.session.commit()
    assert entry.resolved is False
    assert entry.severity == 'error'
    assert entry.created_at is not None
    assert 'backend' in repr(entry)


def test_to_dict_shape(db):
    from extensions import db as _db
    from models.error_log import ErrorLog
    entry = ErrorLog(category='frontend', severity='warning', source='js-onerror',
                     username='visitor', user_role=None, method='GET',
                     path='/sales/', request_id='abc123', message='oops')
    _db.session.add(entry)
    _db.session.commit()
    data = ErrorLog.query.first().to_dict()
    assert data['category'] == 'frontend'
    assert data['severity'] == 'warning'
    assert data['username'] == 'visitor'
    assert data['path'] == '/sales/'
    assert data['request_id'] == 'abc123'
    assert data['resolved'] is False
    assert data['created_at'] is not None


def test_username_survives_user_deletion(db):
    from extensions import db as _db
    from models.error_log import ErrorLog
    from models import User
    user = _make_user(db, username='doomed')
    entry = ErrorLog(category='programming', severity='critical',
                     message='crash', user_id=user.id,
                     username=user.username, user_role='seller')
    _db.session.add(entry)
    _db.session.commit()
    entry_id = entry.id
    _db.session.delete(user)
    _db.session.commit()
    kept = ErrorLog.query.get(entry_id)
    assert kept is not None
    assert kept.username == 'doomed'
    assert kept.user_role == 'seller'


def test_resolve_toggle_persists(db):
    from extensions import db as _db
    from models.error_log import ErrorLog
    entry = ErrorLog(category='logic', message='rule violated')
    _db.session.add(entry)
    _db.session.commit()
    assert ErrorLog.query.filter_by(resolved=False).count() == 1
    entry.resolved = True
    _db.session.commit()
    assert ErrorLog.query.filter_by(resolved=False).count() == 0
    assert ErrorLog.query.filter_by(resolved=True).count() == 1