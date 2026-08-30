"""Cross-model validators for the UAE-Sale ERP.

Centralised so every model that links to a User / Customer /
Supplier / Sale / Purchase / Cheque / Payment / Receipt / etc. can
enforce the same invariants without duplicating logic.

F-04: at most ONE parent document FK per record (Cheque, Receipt,
Payment, etc.)
F-05: direction-based parent FK invariants (e.g. outgoing Payment
must link to a supplier, incoming must link to a customer).
F-03: tenant_id must match the linked parent's tenant_id.
"""


def single_parent_validator(*fk_columns):
    """Class decorator factory: produces an SQLAlchemy ``@validates``
    that enforces at most one of the given FK columns is set at a
    time.

    Use as a method-level @validates, e.g.::

        @single_parent_validator('sale_id', 'purchase_id')
        def _validate_single_parent(self, key, value):
            return value

    The decorator works by introspecting ``self`` for the other
    columns and rejecting the assignment if any of them is already
    set.
    """
    def decorator(method):
        def wrapper(self, key, value):
            if value is None:
                return value
            for other in fk_columns:
                if other == key:
                    continue
                if getattr(self, other, None) is not None:
                    raise ValueError(
                        f"{type(self).__name__}.{key} and "
                        f"{type(self).__name__}.{other} are mutually "
                        f"exclusive parent-document references; at most "
                        f"one may be set on a single record.")
            return value
        return wrapper
    return decorator


def direction_fk_validator(*, for_direction, required_fk, forbidden_fk):
    """Validate direction-based parent FK invariants.

    :param for_direction: the direction value this rule applies to
        ('incoming' or 'outgoing').
    :param required_fk: the FK column that MUST be set when the
        direction matches.
    :param forbidden_fk: the FK column that MUST be NULL when the
        direction matches.
    """
    def decorator(method):
        def wrapper(self, key, value):
            if getattr(self, 'direction', None) != for_direction:
                return value
            if key == forbidden_fk and value is not None:
                raise ValueError(
                    f"{type(self).__name__}.{forbidden_fk} must be NULL "
                    f"when direction='{for_direction}'.")
            if key == required_fk and value is None:
                raise ValueError(
                    f"{type(self).__name__}.{required_fk} must be set "
                    f"when direction='{for_direction}'.")
            return value
        return wrapper
    return decorator


def tenant_consistency_validator(parent_fk_attr='id', tenant_fk_attr='tenant_id'):
    """Class decorator factory: ensures a row's tenant_id matches the
    tenant_id of the row referenced by ``parent_fk_attr``.

    F-03: the linked parent's tenant must equal the row's tenant.
    """
    def decorator(method):
        def wrapper(self, key, value):
            # Triggered on tenant_id change OR on the parent FK change.
            if key == tenant_fk_attr:
                child_tenant = value
                parent_id = getattr(self, parent_fk_attr, None)
            elif key == parent_fk_attr:
                child_tenant = getattr(self, tenant_fk_attr, None)
                parent_id = value
            else:
                return value
            if child_tenant is None or parent_id is None:
                return value
            # Resolve the parent's tenant dynamically.  The model
            # that owns the parent FK must expose a relationship
            # named after ``parent_fk_attr`` for this to work.
            rel = getattr(type(self), parent_fk_attr, None)
            if rel is None or not hasattr(rel, 'property'):
                return value
            mapper_arg = rel.property.mapper.class_
            parent = mapper_arg.query.get(parent_id)
            if parent is None:
                return value
            parent_tenant = getattr(parent, tenant_fk_attr, None)
            if parent_tenant is not None and parent_tenant != child_tenant:
                raise ValueError(
                    f"{type(self).__name__}.tenant_id ({child_tenant}) "
                    f"must match parent.tenant_id ({parent_tenant}); "
                    f"cross-tenant linkage is not allowed.")
            return value
        return wrapper
    return decorator
