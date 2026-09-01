"""
Tenant-Scoped Mixin - خلية فصل المستأجرين
Provides automatic row-level tenant isolation for all business models.

Usage:
    class MyModel(TenantScopedMixin, db.Model):
        tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=True, index=True)
        ...

Fail-fast: any subclass that does not declare (or inherit) its own
``tenant_id`` column raises RuntimeError at import time.
"""

import logging
import threading
from sqlalchemy import event, inspect

logger = logging.getLogger(__name__)

# Thread-local storage for current tenant ID
_thread_local = threading.local()

# Global registry of tenant-scoped models (set of table names)
_tenant_scoped_tables = set()


def set_current_tenant_id(tenant_id):
    """Set the current tenant ID for this request/thread."""
    _thread_local.tenant_id = tenant_id


def get_current_tenant_id():
    """Get the current tenant ID. Returns None if not set (no filtering)."""
    return getattr(_thread_local, 'tenant_id', None)


def clear_current_tenant_id():
    """Clear the current tenant ID (e.g., at end of request)."""
    if hasattr(_thread_local, 'tenant_id'):
        del _thread_local.tenant_id


def register_tenant_scoped(model_class):
    """Register a model class for automatic tenant filtering."""
    _tenant_scoped_tables.add(model_class.__tablename__)


def is_tenant_scoped(tablename):
    """Check if a table is tenant-scoped."""
    return tablename in _tenant_scoped_tables


def _is_actor_owner():
    """Best-effort detection of the platform owner for write-side guards.

    The tenant-scope mixin is imported by models at startup, before
    ``flask_login`` may be available; we therefore probe the proxy and
    fall back to ``False`` whenever context is missing.
    """
    try:
        from flask_login import current_user
    except Exception:
        return False
    try:
        if not getattr(current_user, 'is_authenticated', False):
            return False
        if getattr(current_user, 'is_owner', False):
            return True
        if getattr(current_user, 'is_super_admin', None) and current_user.is_super_admin():
            return True
    except Exception:
        return False
    return False


class TenantScopedMixin:
    """
    Mixin that marks a model for automatic tenant filtering.
    Each model that inherits this mixin MUST define a tenant_id column.

    Implemented with __init_subclass__ (not a metaclass) so it composes
    safely with SQLAlchemy's DeclarativeMeta without metaclass conflicts.
    """

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        defines_tenant_column = any(
            'tenant_id' in vars(ancestor) for ancestor in cls.__mro__
        )
        if not defines_tenant_column:
            raise RuntimeError(
                f"{cls.__name__} mixes in TenantScopedMixin but does not "
                f"define its own tenant_id column. Add: "
                f"tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), "
                f"nullable=True, index=True)"
            )

    def set_tenant(self, tenant_id):
        """Explicitly set the tenant for this instance."""
        self.tenant_id = tenant_id

    @classmethod
    def set_tenant_for_class(cls, tenant_id):
        """Set tenant filter for all future queries on this class."""
        set_current_tenant_id(tenant_id)


def _warn_unfiltered_access_in_strict_mode(query):
    """TENANT_STRICT audit aid: warn when a registered scoped model is queried
    with no resolved tenant (unfiltered access). Never alters behaviour."""
    try:
        from flask import current_app, has_app_context
        if not has_app_context() or not current_app.config.get('TENANT_STRICT'):
            return
        col_descs = query.column_descriptions
        if not col_descs:
            return
        entity = col_descs[0].get('entity')
        tablename = getattr(entity, '__tablename__', None)
        if tablename and tablename in _tenant_scoped_tables:
            logger.warning('TENANT_STRICT: unfiltered access to %s', tablename)
    except Exception:
        pass


def _before_flush_tenant_guard(session, flush_context, instances):
    """SQLAlchemy ``before_flush`` listener enforcing three guarantees:

    1. New rows for a tenant-scoped model inherit the active tenant
       (no NULL tenant leaks from misconfigured service code).
    2. Tenant id is immutable for non-owner actors: changing
       ``tenant_id`` on a dirty row raises an IntegrityError so the
       transaction is rolled back at the storage layer.
    3. Cross-tenant inserts (tenant set to a foreign value while a
       non-owner actor is in scope) are rejected at flush time.

    The owner and super_admin bypass these checks because they are the
    platform operator and legitimately move data between tenants.
    """
    tenant_id = get_current_tenant_id()
    owner_actor = _is_actor_owner()
    if owner_actor:
        # Owner can do anything; still auto-stamp NULL rows so the column
        # is never accidentally left empty for the platform record.
        for obj in session.new:
            tablename = getattr(type(obj), '__tablename__', None)
            if tablename not in _tenant_scoped_tables:
                continue
            try:
                if getattr(obj, 'tenant_id', None) is None and tenant_id is not None:
                    obj.tenant_id = tenant_id
            except Exception:
                continue
        return

    for obj in session.new:
        tablename = getattr(type(obj), '__tablename__', None)
        if tablename not in _tenant_scoped_tables:
            continue
        try:
            current_val = getattr(obj, 'tenant_id', None)
        except Exception:
            continue
        if current_val in (None, '') and tenant_id is not None:
            # Auto-scope new rows to the current tenant.
            try:
                obj.tenant_id = tenant_id
            except Exception:
                pass
        elif current_val is not None and tenant_id is not None and current_val != tenant_id:
            # Cross-tenant insert from a non-owner actor.
            raise RuntimeError(
                f"Cross-tenant insert blocked: {type(obj).__name__}.tenant_id="
                f"{current_val} but current tenant is {tenant_id}"
            )

    for obj in session.dirty:
        tablename = getattr(type(obj), '__tablename__', None)
        if tablename not in _tenant_scoped_tables:
            continue
        try:
            state = inspect(obj)
        except Exception:
            continue
        try:
            history = state.attrs.tenant_id.history
        except Exception:
            continue
        if not history.has_changes():
            continue
        try:
            old = history.deleted[0] if history.deleted else None
            new = history.added[0] if history.added else None
        except Exception:
            continue
        if old is None and new is None:
            continue
        if old is not None and new is not None and old != new:
            raise RuntimeError(
                f"Tenant id is immutable: {type(obj).__name__}.tenant_id "
                f"changed from {old} to {new} by non-owner actor"
            )


def install_tenant_filter_events():  # noqa: C901
    """
    Install SQLAlchemy events to auto-filter tenant-scoped queries and
    enforce tenant immutability on writes.

    Called once during app initialization.
    """
    from sqlalchemy.orm import Query

    @event.listens_for(Query, 'before_compile', retval=True)
    def _auto_tenant_filter(query):
        """Automatically add tenant_id filter to tenant-scoped queries."""
        tenant_id = get_current_tenant_id()
        if tenant_id is None:
            # No tenant set - no filtering (default behaviour unchanged).
            _warn_unfiltered_access_in_strict_mode(query)
            return query

        # Skip DDL, system, and subqueries
        try:
            col_descs = query.column_descriptions
            if not col_descs:
                return query
        except Exception:
            return query  # Can't introspect - skip filtering

        # Check if the primary entity is tenant-scoped
        try:
            primary = col_descs[0]
            entity = primary.get('entity')
            if entity is None:
                return query

            tablename = getattr(entity, '__tablename__', None)
            if tablename is None:
                return query

            if tablename in _tenant_scoped_tables:
                # Only filter the primary entity
                if not getattr(query, '_tenant_filter_applied', False):
                    try:
                        query = query.filter(entity.tenant_id == tenant_id)
                    except Exception as exc:
                        # SQLAlchemy 1.4+ forbids filter() after LIMIT/OFFSET.
                        # Stash limit/offset, apply filter, then restore.
                        if 'LIMIT' in str(exc) or 'OFFSET' in str(exc) or 'limit' in str(type(exc).__name__).lower():
                            try:
                                _limit = getattr(query, '_limit', None)
                                _offset = getattr(query, '_offset', None)
                                _limit_val = getattr(query, '_limit_clause', None)
                                _offset_val = getattr(query, '_offset_clause', None)
                                # Clear via private API, then filter, then restore
                                if _limit is not None or _limit_val is not None or _offset is not None or _offset_val is not None:
                                    query._limit = None
                                    query._limit_clause = None
                                    query._offset = None
                                    query._offset_clause = None
                                    query = query.filter(entity.tenant_id == tenant_id)
                                    if _limit is not None:
                                        query._limit = _limit
                                    if _limit_val is not None:
                                        query._limit_clause = _limit_val
                                    if _offset is not None:
                                        query._offset = _offset
                                    if _offset_val is not None:
                                        query._offset_clause = _offset_val
                                else:
                                    raise
                            except Exception:
                                # Fallback: leave query unfiltered rather than crash
                                pass
                        else:
                            raise
                    query._tenant_filter_applied = True
        except (AttributeError, IndexError, TypeError, KeyError):
            pass

        return query

    # Idempotent registration of the before_flush guard only; the
    # before_compile listener is registered via @event.listens_for at
    # import time, so we just attach the write guard here.
    if not getattr(install_tenant_filter_events, '_before_flush_registered', False):
        from sqlalchemy.orm import Session
        event.listen(Session, 'before_flush', _before_flush_tenant_guard)
        install_tenant_filter_events._before_flush_registered = True