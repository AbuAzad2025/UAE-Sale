from functools import wraps
from flask import abort, flash, redirect, url_for
from flask_login import current_user


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
