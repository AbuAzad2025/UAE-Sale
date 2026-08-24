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


def install_tenant_filter_events():
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

        # Check if the primary entity is tenant-scoped
        try:
            for desc in query.column_descriptions:
                entity = desc.get('entity')
                if entity is not None and hasattr(entity, '__tablename__'):
                    if entity.__tablename__ in _tenant_scoped_tables:
                        # Check if filter already applied to avoid duplicates
                        if not getattr(query, '_tenant_filter_applied', False):
                            # Only apply to the primary entity
                            if desc.get('name') == 'entity' or desc == query.column_descriptions[0]:
                                query = query.filter(entity.tenant_id == tenant_id)
                                query._tenant_filter_applied = True
                                break
        except (AttributeError, IndexError, TypeError):
            pass

        return query
