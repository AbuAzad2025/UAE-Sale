import time
from functools import wraps

from flask import abort, flash, redirect, url_for
from flask_login import current_user


def _report_tx_duration(function_name, duration_ms, outcome):
    """Report transaction timing through monitoring hooks.

    Defensive import: monitoring pulls Flask/DB machinery, so it is loaded
    lazily and any failure degrades to plain logging (or silence outside an
    app context) instead of breaking the wrapped operation.
    """
    try:
        from utils.monitoring import MetricsCollector

        MetricsCollector.record_metric(
            'tx_duration_ms',
            round(duration_ms, 2),
            {'function': function_name, 'outcome': outcome},
        )
        return
    except Exception:
        pass

    try:
        from flask import current_app

        current_app.logger.info(f'TX {function_name} {outcome} in {round(duration_ms, 2)}ms')
    except Exception:
        pass


def tx(f):
    """Atomic transaction boundary: commit on success, rollback + re-raise on failure.

    Nested-safe: when an outer tx() already owns the session transaction,
    inner tx() calls participate in it and never commit/rollback themselves;
    only the outermost owner finalizes, so a late outer failure discards all
    inner work atomically.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        from extensions import db

        session = db.session
        owns = not session.info.get('_tx_owned')
        started = time.perf_counter()

        if not owns:
            try:
                return f(*args, **kwargs)
            finally:
                _report_tx_duration(f.__name__, (time.perf_counter() - started) * 1000, 'nested')

        session.info['_tx_owned'] = True
        outcome = 'commit'
        try:
            result = f(*args, **kwargs)
            session.commit()
            return result
        except Exception:
            session.rollback()
            outcome = 'rollback'
            raise
        finally:
            session.info.pop('_tx_owned', None)
            _report_tx_duration(f.__name__, (time.perf_counter() - started) * 1000, outcome)

    return wrapper


def permission_required(permission_code):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash('الرجاء تسجيل الدخول أولاً', 'warning')
                return redirect(url_for('auth.login'))

            if not current_user.has_permission(permission_code):
                flash('ليس لديك صلاحية للوصول لهذه الصفحة', 'danger')
                abort(403)

            return f(*args, **kwargs)
        return decorated_function
    return decorator


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('الرجاء تسجيل الدخول أولاً', 'warning')
            return redirect(url_for('auth.login'))

        if not (current_user.is_owner or current_user.is_super_admin()):
            flash('هذه الصفحة للإدارة فقط', 'danger')
            abort(403)

        return f(*args, **kwargs)
    return decorated_function


def seller_or_above(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('الرجاء تسجيل الدخول أولاً', 'warning')
            return redirect(url_for('auth.login'))

        # Owner and super_admin always pass
        if current_user.is_owner or current_user.is_super_admin():
            return f(*args, **kwargs)

        # Manager and seller roles are allowed
        if current_user.is_manager() or current_user.is_seller():
            return f(*args, **kwargs)

        flash('ليس لديك صلاحية للوصول لهذه الصفحة', 'danger')
        abort(403)
    return decorated_function


def super_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('الرجاء تسجيل الدخول أولاً', 'warning')
            return redirect(url_for('auth.login'))

        if not (current_user.is_owner or current_user.is_super_admin()):
            flash('هذه الصفحة للسوبر أدمن فقط', 'danger')
            abort(403)

        return f(*args, **kwargs)
    return decorated_function


def owner_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(404)

        if not (current_user.is_owner or (getattr(current_user, 'role', None) and getattr(current_user.role, 'slug', None) == 'developer')):
            abort(404)

        return f(*args, **kwargs)
    return decorated_function
