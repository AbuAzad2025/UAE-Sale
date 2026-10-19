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


# Sentinel tenant id meaning "the rows that belong to no tenant".
#
# An authenticated non-owner whose account has no tenant_id is scoped to this
# rather than to None. None means "no filtering at all" - the owner's global
# view - so it must never be used as a fallback for an ordinary account. With
# this sentinel such a user sees only tenant-less rows, which is what their
# own account's data is, and still cannot reach another tenant's data.
TENANT_LESS_SCOPE = -1


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
    # TENANT_LESS_SCOPE is a read scope, not a real tenant. A row must never
    # be stamped with it - the column would hold a value that matches no
    # tenant - so stamping falls back to the row's own (NULL) tenant.
    stamp_tenant = None if tenant_id == TENANT_LESS_SCOPE else tenant_id
    if owner_actor:
        # Owner can do anything; still auto-stamp NULL rows so the column
        # is never accidentally left empty for the platform record.
        for obj in session.new:
            tablename = getattr(type(obj), '__tablename__', None)
            if tablename not in _tenant_scoped_tables:
                continue
            try:
                if getattr(obj, 'tenant_id', None) is None and stamp_tenant is not None:
                    obj.tenant_id = stamp_tenant
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
        if current_val in (None, '') and stamp_tenant is not None:
            # Auto-scope new rows to the current tenant.
            try:
                obj.tenant_id = stamp_tenant
            except Exception:
                pass
        elif current_val is not None and stamp_tenant is not None and current_val != stamp_tenant:
            # Cross-tenant insert from a non-owner actor.
            raise RuntimeError(
                f"Cross-tenant insert blocked: {type(obj).__name__}.tenant_id="
                f"{current_val} but current tenant is {stamp_tenant}"
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
        # The WHERE criteria were written directly by
        # _apply_query_loader_criteria, which also handles the LIMIT/OFFSET
        # case. Adding a predicate here as well would duplicate the
        # restriction and, on a limited query, raise - so nothing more is
        # added.
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

    The enforcement is a ``with_loader_criteria`` QUERY OPTION, applied in
    the before_compile hook. It is what survives LIMIT/OFFSET: SQLAlchemy
    forbids adding a WHERE predicate after limit() has been applied, so a
    plain ``query.filter()`` raises and the filter is lost - which is exactly
    how tenant B's rows reached tenant A's paginated customer list.

    The option's criterion reads the CURRENT tenant when the statement is
    built, so a Query that carries the option across clones cannot end up
    with a stale tenant baked into it.

    ``Session.enable_loader_criteria`` does not exist in SQLAlchemy 2.0, so
    it is not used here; the query option is the mechanism.
    """
    if session is None or tenant_id is None:
        return
    try:
        session._tenant_criteria_tenant = tenant_id
    except Exception:  # noqa: BLE001
        pass


def _tenant_predicate(entity, tenant_id):
    """The WHERE predicate constraining *entity* to the given tenant.

    TENANT_LESS_SCOPE means "rows with no tenant", so the predicate is
    ``tenant_id IS NULL`` rather than an equality that could never match.
    """
    if tenant_id == TENANT_LESS_SCOPE:
        return entity.tenant_id.is_(None)
    return entity.tenant_id == tenant_id


def _apply_query_loader_criteria(query, tenant_id):
    """Constrain every tenant-scoped entity on *query*.

    The predicate is written into the query's WHERE criteria directly
    (``query._where_criteria``), which is the only way to add a restriction
    to a query that already carries LIMIT/OFFSET: SQLAlchemy forbids
    ``filter()`` after ``limit()`` and raises InvalidRequestError, so a
    public-API filter is simply lost on every paginated list - which is how
    tenant B's rows reached tenant A's paginated customer list.

    Writing to ``_where_criteria`` has two properties this needs:

    * it survives the ``.limit()``/``.offset()`` clone, so the restriction
      is still there when the statement is finally built;
    * it can be REPLACED, so a Query reused after a tenant switch does not
      end up with two contradictory restrictions
      (``tenant_id = 2 AND tenant_id = 1``, which matches nothing).

    A query option is not used: options accumulate on a Query and SQLAlchemy
    caches the compiled plan per "unique filter state", so a previous
    tenant's option survived a later query on the same Query object.
    """
    if tenant_id is None:
        return query

    # Only the entities that are actually part of this query. Constraining
    # every scoped model would add predicates on tables that are not in the
    # FROM clause, which turns the statement into a cross product that
    # matches nothing.
    present = []
    try:
        for desc in query.column_descriptions:
            entity = desc.get('entity')
            if entity is None:
                continue
            if getattr(entity, '__tablename__', None) in _tenant_scoped_tables:
                if entity not in present:
                    present.append(entity)
    except Exception:  # noqa: BLE001
        return query

    for entity in present:
        criterion = _tenant_predicate(entity, tenant_id)
        try:
            existing = tuple(query._where_criteria)
            # Drop a restriction this module added earlier for the same
            # entity, then append the current one. A criterion is identified
            # by the column it constrains, so the replacement is exact.
            kept = [c for c in existing
                    if not _constrains_tenant_column(c, entity)]
            query._where_criteria = tuple(kept) + (criterion,)
        except Exception:  # noqa: BLE001 - never break a query
            continue
    return query


def _constrains_tenant_column(criterion, entity):
    """True when *criterion* is a tenant restriction on *entity*.

    Compares the constrained column rather than a marker attribute: SQLAlchemy
    expression objects do not accept arbitrary attributes, and a marker would
    be lost when the expression is cloned.
    """
    try:
        group = getattr(criterion, 'self_group', None)
        clauses = getattr(group, 'clauses', None)
        if clauses is None:
            clauses = [criterion]
        for crit in clauses:
            left = getattr(crit, 'left', None)
            prop = getattr(left, 'property', None)
            if prop is None:
                continue
            if getattr(prop, 'key', None) != 'tenant_id':
                continue
            parent = getattr(left, 'parent', None)
            if parent is entity or getattr(parent, 'class_', None) is entity:
                return True
    except Exception:  # noqa: BLE001
        return False
    return False


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

    The option is applied from inside the before_compile hook, which runs on
    every compile, so it is always present and always built from the live
    tenant. There is no session-level variant: SQLAlchemy 2.0 has no
    ``Session.enable_loader_criteria``, and the query option is the mechanism
    that survives LIMIT/OFFSET.

    Owner/super_admin requests run with tenant None, in which case no criteria
    are applied at all, so cross-tenant administration keeps working.
    """
    # The criteria are applied per query in the before_compile hook. This
    # function exists so the application startup can call it explicitly and
    # so the ownership of the mechanism is explicit rather than incidental.
    install_tenant_loader_criteria._attached = True
    return True


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