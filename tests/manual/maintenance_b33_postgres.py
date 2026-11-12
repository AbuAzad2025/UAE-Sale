"""Exercise b33 on temporary PostgreSQL tables; never touch real audit rows.

Run from the repository root: python tests/manual/maintenance_b33_postgres.py
The transaction is always rolled back. The script checks only this migration,
not the rest of the Alembic chain or the database owner's ability to bypass it.
"""

from pathlib import Path
import sys

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
url = dotenv_values(ROOT / ".env").get("DATABASE_URL")
if not url:
    raise SystemExit("DATABASE_URL is missing in .env")
parsed = make_url(url)
if (
    parsed.get_backend_name() != "postgresql"
    or parsed.database != "ERP-lite"
    or parsed.host not in ("localhost", "127.0.0.1", "::1")
    or {"dbname", "service"} & set(parsed.query)
):
    raise SystemExit("Refusing an unexpected or non-local database target")

tables = ("maintenance_order_status_log", "maintenance_warranty_audit")
engine = create_engine(url)
script = ScriptDirectory.from_config(Config(str(ROOT / "migrations" / "alembic.ini")))
with engine.connect() as connection:
    try:
        connection.execute(
            text(
                "CREATE TEMP TABLE audit_test_parent (id integer PRIMARY KEY) ON COMMIT DROP"
            )
        )
        connection.execute(text("INSERT INTO pg_temp.audit_test_parent VALUES (1)"))
        for table in tables:
            connection.execute(
                text(
                    f"CREATE TEMP TABLE {table} (id integer PRIMARY KEY, value text, "
                    "parent_id integer REFERENCES audit_test_parent(id)) ON COMMIT DROP"
                )
            )
            connection.execute(
                text(f"INSERT INTO pg_temp.{table} VALUES (1, 'original', 1)")
            )
        connection.execute(
            text(
                "CREATE TEMP TABLE alembic_version (version_num varchar(64) PRIMARY KEY) ON COMMIT DROP"
            )
        )
        connection.execute(
            text(
                "INSERT INTO pg_temp.alembic_version VALUES ('b32_maintenance_order_notes')"
            )
        )
        connection.execute(text("SET LOCAL search_path = pg_temp"))
        for table in tables + ("alembic_version",):
            assert connection.execute(
                text(
                    f"SELECT '{table}'::regclass::oid = 'pg_temp.{table}'::regclass::oid"
                )
            ).scalar_one()

        def run_revision(target, fn):
            context = MigrationContext.configure(
                connection,
                opts={
                    "fn": lambda heads, ctx: fn(target, heads),
                    "version_table_column_length": 64,
                },
            )
            with Operations.context(context):
                context.run_migrations()
            assert (
                connection.execute(
                    text("SELECT version_num FROM pg_temp.alembic_version")
                ).scalar_one()
                == target
            )

        run_revision("b33_maintenance_audit_guard", script._upgrade_revs)
        for table in tables:
            for statement in (
                f"UPDATE {table} SET value='changed' WHERE id=1",
                f"DELETE FROM {table} WHERE id=1",
                f"TRUNCATE TABLE {table}",
            ):
                savepoint = connection.begin_nested()
                try:
                    connection.execute(text(statement))
                except DBAPIError as exc:
                    assert getattr(exc.orig, "pgcode", None) == "55000"
                    savepoint.rollback()
                else:
                    savepoint.rollback()
                    raise AssertionError(f"{table}: audit mutation was not blocked")
            assert (
                connection.execute(
                    text(f"SELECT value FROM {table} WHERE id=1")
                ).scalar_one()
                == "original"
            )
            connection.execute(text(f"INSERT INTO {table} VALUES (2, 'new audit', 1)"))

        savepoint = connection.begin_nested()
        try:
            connection.execute(text("TRUNCATE TABLE audit_test_parent CASCADE"))
        except DBAPIError as exc:
            assert getattr(exc.orig, "pgcode", None) == "55000"
            savepoint.rollback()
        else:
            savepoint.rollback()
            raise AssertionError("Cascade truncate unexpectedly removed audit records")

        run_revision("b32_maintenance_order_notes", script._downgrade_revs)
        for table in tables:
            connection.execute(text(f"UPDATE {table} SET value='changed' WHERE id=1"))
            connection.execute(text(f"DELETE FROM {table} WHERE id=2"))
        print(
            "b33 upgrade, append-only enforcement and downgrade passed on temporary PostgreSQL tables"
        )
    finally:
        connection.rollback()
        engine.dispose()
