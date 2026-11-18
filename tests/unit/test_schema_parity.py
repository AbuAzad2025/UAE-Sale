"""Schema parity: Alembic migrations must produce the same schema as the models.

Without this test, adding a column to a model without a matching migration goes
unnoticed: the test suite builds its schema with ``db.create_all()`` (straight
from model metadata), while production uses ``alembic upgrade head``. Drift
between the two only surfaces in production.

This test builds BOTH schemas in turn (in a disposable database) and fails if
any table, column, or column type differs.
"""
from pathlib import Path

import pytest

MIGRATIONS_INI = Path(__file__).resolve().parents[2] / "migrations" / "alembic.ini"


def _reset_schema(app):
    from extensions import db
    from sqlalchemy import text

    with app.app_context():
        if db.engine.dialect.name == "postgresql":
            db.session.execute(text("SET statement_timeout = 0"))
            db.session.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
            db.session.execute(text("SET statement_timeout = 5000"))
        else:
            db.drop_all()
        db.session.commit()
        db.session.remove()


def _snapshot(app):
    """Return {table: {column: normalized_type}} for the current schema."""
    from extensions import db
    from sqlalchemy import inspect

    with app.app_context():
        inspector = inspect(db.engine)
        result = {}
        for table in sorted(inspector.get_table_names()):
            if table == "alembic_version":
                continue
            columns = {}
            for col in inspector.get_columns(table):
                columns[col["name"]] = str(col["type"]).upper()
            result[table] = columns
        return result


@pytest.mark.skipif(
    __import__("os").environ.get("DATABASE_URL", "").startswith("sqlite"),
    reason="Schema parity check targets the PostgreSQL (production) dialect",
)
def test_alembic_schema_matches_model_metadata(app):
    from alembic import command
    from alembic.config import Config
    from extensions import db

    # 1) Build the schema from migrations (production path).
    _reset_schema(app)
    cfg = Config(str(MIGRATIONS_INI))
    with app.app_context():
        # Replicate app.py's boot sequence: it pre-creates/widens the version
        # table to VARCHAR(64) before upgrading, because some revision ids are
        # longer than Alembic's 32-char default. Without this a bare upgrade
        # fails on `alembic_version`, unrelated to actual schema drift.
        if db.engine.dialect.name == "postgresql":
            from sqlalchemy import text
            db.session.execute(text(
                "CREATE TABLE IF NOT EXISTS alembic_version "
                "(version_num VARCHAR(64) NOT NULL PRIMARY KEY)"
            ))
            db.session.execute(text(
                "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(64)"
            ))
            db.session.commit()
        command.upgrade(cfg, "head")
    alembic_schema = _snapshot(app)

    # 2) Build the schema from model metadata (test-suite path).
    _reset_schema(app)
    with app.app_context():
        db.create_all()
    metadata_schema = _snapshot(app)

    # 3) Compare precisely.
    errors = []
    a_tables, m_tables = set(alembic_schema), set(metadata_schema)

    for table in sorted(m_tables - a_tables):
        errors.append(f"TABLE MISSING FROM MIGRATIONS: '{table}' (exists in models)")
    for table in sorted(a_tables - m_tables):
        errors.append(f"TABLE MISSING FROM MODELS: '{table}' (created by a migration)")

    for table in sorted(a_tables & m_tables):
        a_cols = alembic_schema[table]
        m_cols = metadata_schema[table]
        for col in sorted(set(m_cols) - set(a_cols)):
            errors.append(f"COLUMN MISSING FROM MIGRATIONS: {table}.{col}")
        for col in sorted(set(a_cols) - set(m_cols)):
            errors.append(f"COLUMN MISSING FROM MODELS: {table}.{col} (created by a migration)")
        for col in sorted(set(a_cols) & set(m_cols)):
            if a_cols[col] != m_cols[col]:
                errors.append(
                    f"TYPE MISMATCH {table}.{col}: migrations={a_cols[col]!r} "
                    f"models={m_cols[col]!r}"
                )
    # NOTE: index/unique-constraint drift is intentionally NOT a hard failure:
    # migrations legitimately create extra performance indexes and some unique
    # constraints were deliberately dropped for multi-tenancy. The tables/
    # columns/types parity above is the check that prevents production outages.

    assert not errors, "SCHEMA DRIFT DETECTED:\n" + "\n".join(errors)
