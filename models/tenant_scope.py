"""
Tenant-Scoped Mixin — خلية فصل المستأجرين
Provides automatic row-level tenant isolation for all business models.

Usage:
    class MyModel(TenantScopedMixin, db.Model):
        ...
"""

import threading
from sqlalchemy import event

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


class TenantScopedMixin:
    """
    Mixin that marks a model for automatic tenant filtering.
    Each model that inherits this mixin should define a tenant_id column.
    """

    def set_tenant(self, tenant_id):
        """Explicitly set the tenant for this instance."""
        self.tenant_id = tenant_id

    @classmethod
    def set_tenant_for_class(cls, tenant_id):
        """Set tenant filter for all future queries on this class."""
        set_current_tenant_id(tenant_id)


def install_tenant_filter_events():  # noqa: C901
    """
    Install SQLAlchemy events to auto-filter tenant-scoped queries.
    Called once during app initialization.
    """
    from sqlalchemy.orm import Query

    @event.listens_for(Query, 'before_compile', retval=True)
    def _auto_tenant_filter(query):
        """Automatically add tenant_id filter to tenant-scoped queries."""
        tenant_id = get_current_tenant_id()
        if tenant_id is None:
            return query  # No tenant set — no filtering

        # Skip DDL, system, and subqueries
        try:
            col_descs = query.column_descriptions
            if not col_descs:
                return query
        except Exception:
            return query  # Can't introspect — skip filtering

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
                    query = query.filter(entity.tenant_id == tenant_id)
                    query._tenant_filter_applied = True
        except (AttributeError, IndexError, TypeError, KeyError):
            pass

        return query
