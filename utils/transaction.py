"""Atomic transaction boundary helpers for azad_erp.

Services must NOT call db.session.commit()/rollback() directly. Instead they
perform business logic and db.session.flush(), and the routing layer wraps the
call in `atomic_transaction()` (or the `@atomic` decorator) which owns the
commit/rollback boundary.

Usage::

    from utils.transaction import atomic_transaction

    with atomic_transaction():
        result = SomeService.do_work(...)

    @atomic_transaction
    def my_route():
        ...
"""

from contextlib import contextmanager
from extensions import db
from flask import current_app


class TransactionError(Exception):
    """Raised when a transaction cannot be committed."""


@contextmanager
def atomic_transaction():
    """Own the commit/rollback boundary for a unit of work.

    Services inside this block must only ``flush()``; they must never
    ``commit()`` or ``rollback()``. On clean exit the transaction is
    committed; on any exception it is rolled back and the exception
    re-raised.
    """
    try:
        yield
        db.session.commit()
    except Exception as exc:  # noqa: BLE001
        try:
            db.session.rollback()
        except Exception:  # noqa: BLE001
            pass
        current_app.logger.exception("Transaction rolled back: %s", exc)
        raise


def atomic(func):
    """Decorator form of `atomic_transaction` for route handlers."""
    from functools import wraps

    @wraps(func)
    def wrapper(*args, **kwargs):
        with atomic_transaction():
            return func(*args, **kwargs)

    return wrapper
