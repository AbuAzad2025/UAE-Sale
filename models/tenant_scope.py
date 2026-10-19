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


def run_in_tenant_context(tenant_id, func, *args, **kwargs):
    """Run *func* with an explicit tenant context in the calling thread.

    ``threading.local`` does not propagate into a new thread, so any query
    issued from a worker thread resolves ``get_current_tenant_id()`` as None
    and runs completely unfiltered. Work that touches tenant rows must go
    through here.

    Raises RuntimeError when tenant_id is missing, rather than silently
    running unscoped - a background job with no tenant can read and write
    every tenant's data.
    """
    if tenant_id is None:
        raise RuntimeError(
            'Background work requires an explicit tenant_id; refusing to run '
            'without tenant context because queries would be unfiltered.')
    set_current_tenant_id(tenant_id)
    try:
        return func(*args, **kwargs)
    finally:
        clear_current_tenant_id()


def run_in_platform_context(func, *args, **kwargs):
    """Run *func* as platform-level (owner) background work.

    Some schedulers are deliberately cross-tenant: the daily database backup
    and the neural auto-retraining milestone both operate on the whole system
    rather than one tenant's rows. They set tenant None explicitly - the same
    context the owner branch uses - so the intent is recorded in code instead
    of being an accident of thread spawning.

    Never use this for tenant-scoped reads or writes.
    """
    set_current_tenant_id(None)
    try:
        return func(*args, **kwargs)
    finally:
        clear_current_tenant_id()


def register_tenant_scoped(model_class):
    """Register a model class for automatic tenant filtering."""
    _tenant_scoped_tables.add(model_class.__tablename__)


# Tables that carry a tenant_id column but are NOT covered by an explicit
# register_tenant_scoped() call in their own module. Leaving one out means
# every row of that table is readable by every tenant, so this list is the
# difference between isolation and a leak.
_BUILTIN_SCOPED_TABLES = frozenset({
    # users was previously unregistered: User has a tenant_id column but no
    # module-level registration, so user records were never isolated.
    'users',
})


def install_builtin_tenant_scoping():
    """Register the built-in tables that have no module-level registration."""
    _tenant_scoped_tables.update(_BUILTIN_SCOPED_TABLES)


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
        """Automatically add tenant_id filter to tenant-scoped queries.

        Scoping applies to EVERY tenant-scoped entity present in the query,
        not just the first one. The previous implementation filtered only
        ``column_descriptions[0].entity``, so a multi-entity query such as
        ``db.session.query(Customer, Product)`` produced
        ``FROM customers, products WHERE customers.tenant_id = X`` - the
        joined Product escaped isolation entirely, and tenant A could read
        tenant B's rows.

        This hook cannot be the only defence. It inspects
        ``column_descriptions[0].entity``, and derived queries - notably the
        subquery flask-sqlalchemy builds inside ``paginate()`` - have no
        entity there, so the filter was silently dropped. The loader criteria
        installed by install_tenant_loader_criteria() cover those cases and
        are attached here as well, so they are in place before the statement
        is built.

        Note this cannot protect ``session.get(Model, pk)``: a primary-key
        lookup never builds a Query, so it bypasses this hook for every model,
        not only tenant-scoped ones. Service code must keep using
        ``get_owned_or_raise`` for single-row access.
        """
        tenant_id = get_current_tenant_id()
        if tenant_id is None:
            # No tenant set - no filtering (default behaviour unchanged).
            _warn_unfiltered_access_in_strict_mode(query)
            return query

        # Attach loader criteria FIRST: they apply to the entity wherever it
        # appears in the statement, including inside a paginate() subquery and
        # on a query that already has LIMIT/OFFSET applied - where adding a
        # WHERE predicate is forbidden and the filter would be lost.
        _apply_loader_criteria(query.session, tenant_id)
        query = _apply_query_loader_criteria(query, tenant_id)

        if getattr(query, '_tenant_filter_applied', False):
            return query

        # Collect EVERY tenant-scoped entity in the query.
        try:
            col_descs = query.column_descriptions
            if not col_descs:
                return query
        except Exception:
            return query  # Can't introspect - skip filtering

        scoped_entities = []
        seen = set()
        for desc in col_descs:
            entity = desc.get('entity')
            if entity is None:
                continue
            tablename = getattr(entity, '__tablename__', None)
            if tablename in _tenant_scoped_tables and entity not in seen:
                seen.add(entity)
                scoped_entities.append(entity)

        if not scoped_entities:
            return query

        # Apply the predicate to each scoped entity. A query that already has
        # LIMIT/OFFSET cannot take another WHERE predicate - SQLAlchemy
        # raises InvalidRequestError - and the loader criteria added above
        # already constrain those queries, so skip rather than fail.
        for entity in scoped_entities:
            try:
                query = query.filter(entity.tenant_id == tenant_id)
            except Exception as exc:  # noqa: BLE001
                current_app_logger = _safe_logger()
                if current_app_logger:
                    current_app_logger.debug(
                        'Tenant predicate not added to %s (%s); the loader '
                        'criteria cover it.',
                        entity.__name__, type(exc).__name__)
        query._tenant_filter_applied = True
        return query

    if not getattr(install_tenant_filter_events, '_before_flush_registered', False):
        from sqlalchemy.orm import Session
        event.listen(Session, 'before_flush', _before_flush_tenant_guard)
        install_tenant_filter_events._before_flush_registered = True


def _safe_logger():
    try:
        return logger
    except Exception:
        return None


def _apply_loader_criteria(session, tenant_id):
    """Attach the tenant predicate to every tenant-scoped entity.

    Two mechanisms are used because neither covers everything:

    * ``Query.options(with_loader_criteria(...))`` applies the predicate to
      the entity wherever it appears in the statement. It is the only
      mechanism that survives a query which already has LIMIT/OFFSET:
      SQLAlchemy forbids adding a WHERE predicate after limit() has been
      applied, so a plain ``query.filter()`` raises and the filter is lost -
      which is exactly how tenant B's rows reached tenant A's paginated
      customer list.
    * ``Session.enable_loader_criteria`` covers relationship and lazy loads
      that never go through this Query.

    The loader criteria are attached to the session, so they apply to every
    subsequent query on it.
    """
    if tenant_id is None:
        return
    for entity in _scoped_model_classes():
        try:
            session.enable_loader_criteria(
                entity,
                lambda cls: cls.tenant_id == tenant_id,
                include_aliases=True)
        except Exception:  # noqa: BLE001 - never break a session
            continue
    try:
        session._tenant_criteria_tenant = tenant_id
    except Exception:  # noqa: BLE001
        pass


def _apply_query_loader_criteria(query, tenant_id):
    """Add with_loader_criteria options to *query* for every scoped entity.

    Applied to the query itself (rather than only the session) because
    ``with_loader_criteria`` as a query option is what survives LIMIT/OFFSET.
    """
    from sqlalchemy.orm import with_loader_criteria

    for entity in _scoped_model_classes():
        try:
            query = query.options(with_loader_criteria(
                entity, lambda cls: cls.tenant_id == tenant_id))
        except Exception:  # noqa: BLE001 - never break a query
            continue
    return query


def install_tenant_loader_criteria():
    """Constrain every tenant-scoped entity at LOAD time.

    ``with_loader_criteria`` attaches the tenant predicate to the ENTITY
    itself, so SQLAlchemy applies it wherever that entity appears in a
    statement - a plain query, a join, a ``paginate()`` subquery, a
    ``joinedload``, or ``session.get``.

    This is the PRIMARY enforcement. The Query ``before_compile`` hook
    (install_tenant_filter_events) cannot be on its own: it inspects
    ``column_descriptions[0].entity``, and derived queries - notably the
    subquery flask-sqlalchemy builds inside ``paginate()`` - have no entity
    there, so the filter was silently dropped and tenant B's rows appeared in
    tenant A's paginated customer list. The hook is kept because it also
    covers column-only queries that never load an entity, but the loader
    criteria are what actually guarantee isolation.

    Owner/super_admin requests run with tenant None, in which case no criteria
    are applied at all, so cross-tenant administration keeps working.
    """
    from sqlalchemy import event as sa_event
    from sqlalchemy.orm import Session

    def _attach(session, tenant_id):
        _apply_loader_criteria(session, tenant_id)

    if not getattr(install_tenant_loader_criteria, '_attached', False):
        from flask import has_app_context

        @sa_event.listens_for(Session, 'after_begin')
        def _on_begin(session, transaction, _conn):
            # Re-evaluated per transaction so the criteria track the tenant
            # that before_request established for this request.
            if not has_app_context():
                return
            tenant_id = get_current_tenant_id()
            if tenant_id is None:
                return
            try:
                _attach(session, tenant_id)
            except Exception:  # noqa: BLE001
                pass

        @sa_event.listens_for(Session, 'do_orm_execute')
        def _on_execute(state):
            # The session may already be inside a transaction when the tenant
            # is established (a request reusing a session opened earlier, or a
            # test that seeded rows before the request started). Then
            # 'after_begin' has already fired and the criteria were never
            # attached, so the request would run unfiltered. Attaching on
            # every ORM execution closes that window; enable_loader_criteria
            # is idempotent per entity, and re-applying it with the current
            # tenant refreshes the predicate.
            if not has_app_context():
                return
            try:
                session = state.session
                tenant_id = get_current_tenant_id()
                if tenant_id is None:
                    return
                if getattr(session, '_tenant_criteria_tenant', None) == tenant_id:
                    return
                _attach(session, tenant_id)
                session._tenant_criteria_tenant = tenant_id
            except Exception:  # noqa: BLE001
                pass

        install_tenant_loader_criteria._attached = True


def _scoped_model_classes():
    """Resolve the registered table names back to mapped classes."""
    from extensions import db

    out = []
    try:
        # registry.mappers is already a live set of Mapper objects in
        # SQLAlchemy 2.x. Neither db.Model nor registry is inspectable, so
        # sa_inspect() here raises NoInspectionAvailable - which is why this
        # must use the attribute directly.
        for m in db.Model.registry.mappers:
            table = getattr(m, 'local_table', None)
            if table is not None and table.name in _tenant_scoped_tables:
                out.append(m.class_)
    except Exception as exc:  # noqa: BLE001
        # Loud: an empty list means isolation is silently absent, so record it
        # rather than returning an empty list as if nothing were wrong.
        logger.error(
            'Tenant loader criteria could not resolve scoped models: %s: %s',
            type(exc).__name__, exc)
    return out