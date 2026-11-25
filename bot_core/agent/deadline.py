"""Database deadlines interrupt queries before they can overrun a tool lease."""

from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from extensions import db

_cutoff: ContextVar[float | None] = ContextVar("erp_tool_cutoff", default=None)


def check_tool_deadline() -> None:
    cutoff = _cutoff.get()
    if cutoff is not None and monotonic() >= cutoff:
        raise TimeoutError("The ERP operation exceeded its deadline.")


@contextmanager
def sql_deadline(milliseconds: int):
    connection = db.session.connection()
    dialect = connection.dialect.name
    driver = connection.connection.driver_connection
    previous = None
    cutoff = monotonic() + milliseconds / 1000
    if dialect == "postgresql":
        previous = connection.execute(text("SELECT current_setting('statement_timeout'), current_setting('lock_timeout')")).one()
        connection.execute(text("SELECT set_config('statement_timeout', :statement, true), set_config('lock_timeout', :lock, true)"),
                           {"statement": f"{milliseconds}ms", "lock": f"{min(milliseconds, 3000)}ms"})
    elif dialect == "sqlite":
        driver.set_progress_handler(lambda: int(monotonic() >= cutoff), 1000)
    token = _cutoff.set(cutoff)
    try:
        yield
        check_tool_deadline()
        db.session.flush()
    except DBAPIError as error:
        pg_timeout = getattr(error.orig, "pgcode", None) in {"57014", "55P03"}
        sqlite_timeout = getattr(error.orig, "sqlite_errorname", None) == "SQLITE_INTERRUPT"
        if pg_timeout or sqlite_timeout:
            raise TimeoutError("The ERP query exceeded its deadline.") from error
        raise
    else:
        if previous is not None:
            connection.execute(text("SELECT set_config('statement_timeout', :statement, true), set_config('lock_timeout', :lock, true)"),
                               {"statement": previous[0], "lock": previous[1]})
    finally:
        _cutoff.reset(token)
        if dialect == "sqlite":
            driver.set_progress_handler(None, 0)
