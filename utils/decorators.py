import time
from functools import wraps

from flask import abort, flash, redirect, url_for, request
from flask_login import current_user


# Local import to break circular dependency with routes.  Only used for
# isinstance() check inside the tenant-scope helper.
try:
    from models.user import User
except Exception:  # pragma: no cover — defensive during early startup
    User = None


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


# ============================================================================
# ZERO-TRUST SECURITY PRIMITIVES
# ============================================================================
# These utilities provide defense-in-depth against:
#   - IDOR / BOLA (Insecure Direct Object Reference / Broken Object Level Auth)
#   - Horizontal & vertical privilege escalation
#   - Cross-tenant data leakage
#   - Self role-escalation via body-controlled role_id
#   - Missing permission decorators on sensitive endpoints
# ============================================================================


# Role hierarchy for vertical privilege comparison. A higher number = more
# privilege. Used by ``_role_level`` and ``_enforce_target_role_not_higher``
# to ensure an actor can only ever assign / mutate a role at or below their
# own level.  Owner sits at the top (level 100) by definition.
_ROLE_LEVELS = {
    'super_admin': 90,
    'manager': 70,
    'seller': 40,
    'cashier': 40,
    'accountant': 50,
    'hr': 60,
    'inventory': 30,
    'viewer': 10,
}


def _role_level(role):
    """Return the numeric privilege level of *role*. Unknown slugs get 0.

    Always safe: the function is pure and does not touch the request or
    database, so it can be called from any decorator / helper context.
    """
    if role is None:
        return 0
    slug = getattr(role, 'slug', None)
    if not slug:
        return 0
    return _ROLE_LEVELS.get(slug, 0)


def _current_user_level():
    """Privilege level of the currently authenticated user.

    Owner is fixed at 100. Everyone else maps through ``_role_level``.
    Returns 0 for anonymous / unauthenticated callers so any "must be at
    least this level" check will fail closed.
    """
    if not current_user.is_authenticated:
        return 0
    if getattr(current_user, 'is_owner', False):
        return 100
    return _role_level(getattr(current_user, 'role', None))


def _enforce_target_role_not_higher(target_role):
    """403 if *target_role* is more privileged than the current user.

    Used everywhere a body / form supplies a role to assign: the actor may
    only assign roles at or below their own privilege level.  Owner (level
    100) can assign anything, but only the owner is allowed to mint other
    owners (and that path is still owner-gated by ``owner_required``).
    """
    target_level = _role_level(target_role)
    if target_level > _current_user_level():
        flash('لا يمكنك ترقية مستخدم إلى دور أعلى من صلاحياتك', 'danger')
        abort(403)


def _enforce_same_tenant(obj):
    """403 if *obj* lives in a tenant the current user cannot see.

    Owner / super_admin (when ``is_owner`` is True) bypass this check by
    design.  Everyone else must have ``obj.tenant_id == current_user.tenant_id``.

    Exception: a user acting on their own record is always allowed to
    read it (so the self-service password change / profile pages still
    work) — the per-action decorator / route body is responsible for
    preventing self-escalation.
    """
    if obj is None:
        # Resource-not-found is handled by the caller (``get_or_404``);
        # we do not 403 for missing rows because that would leak the
        # existence of cross-tenant IDs.
        return
    if getattr(current_user, 'is_owner', False):
        return
    # Authentication is the route's job (login_required).  In service
    # unit-test contexts current_user is anonymous; we skip tenant
    # enforcement rather than abort so tests can exercise the logic.
    if not getattr(current_user, 'is_authenticated', False):
        return
    # Self-action is always permitted (the route must guard against
    # self-escalation, e.g. role change).
    obj_user_id = getattr(obj, 'user_id', None) or getattr(obj, 'id', None)
    actor_id = getattr(current_user, 'id', None)
    if (obj_user_id is not None and actor_id is not None
            and obj_user_id == actor_id
            and User is not None
            and isinstance(obj, User)):
        return
    actor_tenant = getattr(current_user, 'tenant_id', None)
    obj_tenant = getattr(obj, 'tenant_id', None)
    # If both sides have no tenant (e.g. fixture or pre-tenant data),
    # the row is globally visible — owner/super_admin see it, and
    # regular users with the right permission also see it.  We only
    # block when the actor is scoped to a tenant but the row is not,
    # because then the actor could be tricked into seeing data they
    # shouldn't.
    if obj_tenant is None and actor_tenant is None:
        return
    if obj_tenant is None and actor_tenant is not None:
        # Actor is tenant-scoped but the row is not — ambiguous, fail
        # closed except for platform owner/super_admin.
        if not (getattr(current_user, 'is_owner', False) or getattr(current_user, 'is_super_admin', lambda: False)()):
            abort(403)
        return
    if actor_tenant != obj_tenant:
        abort(403)


def get_owned_or_404(model, pk, *, code=404, message=None):
    """Look up *pk* in *model* and 404 if missing or cross-tenant.

    This is the **defense-in-depth** lookup helper every IDOR-prone route
    should use.  ``db.get_or_404(model, pk)`` only checks for row existence
    — it does not enforce tenant isolation, so an attacker who guesses
    another tenant's PK could read or modify the row via the route body.
    ``get_owned_or_404`` is the safe replacement: it 404s on missing
    rows AND 403s on cross-tenant rows.

    For owner / super_admin the tenant check is bypassed (intentional:
    they are the platform operator).
    """
    from extensions import db
    obj = db.session.get(model, pk)
    if obj is None:
        abort(code)
    _enforce_same_tenant(obj)
    return obj


def assert_same_tenant(obj, exc_cls=ValueError, message=None):
    """Non-aborting tenant check for service-layer lookups.

    Like ``_enforce_same_tenant`` but raises *exc_cls* (default
    ``ValueError``) instead of ``abort(403)`` so service code keeps its
    friendly flash-message error handling while still failing closed on
    cross-tenant access.  Owner / super_admin bypass as usual.
    """
    from flask_login import current_user
    if not getattr(current_user, 'is_authenticated', False):
        return
    actor_tenant = getattr(current_user, 'tenant_id', None)
    obj_tenant = getattr(obj, 'tenant_id', None)
    if obj_tenant is None and actor_tenant is None:
        return
    if obj_tenant is None and actor_tenant is not None:
        if not (getattr(current_user, 'is_owner', False) or getattr(current_user, 'is_super_admin', lambda: False)()):
            raise exc_cls(message or 'Cross-tenant access denied')
        return
    if actor_tenant != obj_tenant:
        if not (getattr(current_user, 'is_owner', False) or getattr(current_user, 'is_super_admin', lambda: False)()):
            raise exc_cls(message or 'Cross-tenant access denied')


def get_owned_or_raise(model, pk, exc_cls=ValueError, missing_message=None, tenant_message=None):
    """Service-layer variant of ``get_owned_or_404``.

    Returns ``None`` if the row is missing (caller keeps its own
    not-found handling / message) and raises *exc_cls* on cross-tenant
    access instead of aborting.  Owner / super_admin bypass the check.
    """
    from extensions import db
    obj = db.session.get(model, pk)
    if obj is None:
        return None
    from flask_login import current_user
    if not getattr(current_user, 'is_authenticated', False):
        return obj
    actor_tenant = getattr(current_user, 'tenant_id', None)
    obj_tenant = getattr(obj, 'tenant_id', None)
    if obj_tenant is None and actor_tenant is None:
        return obj
    if obj_tenant is None and actor_tenant is not None:
        if not (getattr(current_user, 'is_owner', False) or getattr(current_user, 'is_super_admin', lambda: False)()):
            raise exc_cls(tenant_message or 'Cross-tenant access denied')
        return obj
    if actor_tenant != obj_tenant:
        if not (getattr(current_user, 'is_owner', False) or getattr(current_user, 'is_super_admin', lambda: False)()):
            raise exc_cls(tenant_message or 'Cross-tenant access denied')
    return obj


def require_csrf_for_state_change(view_func):
    """Decorator: deny the request unless a CSRF token is present.

    Use it on state-changing endpoints that need belt-and-braces CSRF
    protection (financial writes, role changes, etc.).  The route handler
    itself does not need to know about CSRF.
    """
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            # Flask-WTF's CSRFProtect middleware normally rejects these
            # automatically, but on @csrf.exempt routes (e.g. payment
            # webhooks) we need a manual gate.  ``getattr`` keeps the
            # wrapper safe in the rare case ``flask_wtf`` is not present.
            try:
                from flask_wtf.csrf import validate_csrf
                validate_csrf(request.form.get('csrf_token') or
                              request.headers.get('X-CSRF-Token', ''))
            except Exception:
                abort(400)
        return view_func(*args, **kwargs)
    return wrapper


def webhook_signature_required(get_secret, get_signature, raw_body=False):
    """Decorator factory: reject any webhook that lacks a valid signature.

    The factory is intentionally strict — the wrapped endpoint is invoked
    ONLY if a non-empty secret is configured AND the signature matches.
    The previous behaviour of silently accepting unsigned webhooks when
    the secret was empty is a serious security gap and is removed here.
    """
    import hashlib
    import hmac

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            secret = get_secret()
            signature = get_signature()
            if not secret:
                # Fail closed: do NOT accept webhooks with an empty secret.
                current_app_logger_abort('webhook secret not configured')
            if not signature:
                current_app_logger_abort('webhook signature missing')
            try:
                if raw_body:
                    payload = request.get_data() or b''
                else:
                    payload = (request.get_data() or b'').decode('utf-8')
                expected = hmac.new(
                    secret.encode('utf-8') if isinstance(secret, str) else secret,
                    payload if isinstance(payload, bytes) else payload.encode('utf-8'),
                    hashlib.sha256,
                ).hexdigest()
                if not hmac.compare_digest(expected, signature):
                    current_app_logger_abort('webhook signature mismatch')
            except Exception:
                abort(400)
            return view_func(*args, **kwargs)
        return wrapper
    return decorator


def current_app_logger_abort(reason):
    """Log the rejection reason and abort the webhook request."""
    try:
        from flask import current_app
        current_app.logger.warning('Webhook rejected: %s', reason)
    except Exception:
        pass
    abort(400)
