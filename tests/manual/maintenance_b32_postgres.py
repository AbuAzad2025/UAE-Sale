"""Exercise migration b32 on a PostgreSQL temporary table, never user tables.

Run from the repository root: python tests/manual/maintenance_b32_postgres.py
The script refuses any database other than ERP-lite. All DDL targets a
connection-local temporary table and the transaction is always rolled back.
It does NOT migrate the real database or verify the rest of the Alembic chain.
"""

from pathlib import Path
import sys

from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.config import Config
from alembic.script import ScriptDirectory
from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


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

engine = create_engine(url)
script = ScriptDirectory.from_config(Config(str(ROOT / "migrations" / "alembic.ini")))
with engine.connect() as connection:
    try:
        connection.execute(
            text(
                "CREATE TEMP TABLE maintenance_orders (id integer PRIMARY KEY) ON COMMIT DROP"
            )
        )
        connection.execute(
            text(
                "CREATE TEMP TABLE alembic_version (version_num varchar(64) PRIMARY KEY) ON COMMIT DROP"
            )
        )
        connection.execute(
            text(
                "INSERT INTO pg_temp.alembic_version VALUES ('b31_maintenance_cost_fields')"
            )
        )
        connection.execute(text("SET LOCAL search_path = pg_temp"))
        assert connection.execute(
            text(
                "SELECT 'maintenance_orders'::regclass::oid = 'pg_temp.maintenance_orders'::regclass::oid"
            )
        ).scalar_one()
        column_exists = text(
            "SELECT EXISTS (SELECT 1 FROM pg_attribute "
            "WHERE attrelid = 'pg_temp.maintenance_orders'::regclass "
            "AND attname = 'notes' AND NOT attisdropped)"
        )
        assert connection.execute(
            text(
                "SELECT 'alembic_version'::regclass::oid = 'pg_temp.alembic_version'::regclass::oid"
            )
        ).scalar_one()
        for direction in ("upgrade", "downgrade"):
            target = (
                "b32_maintenance_order_notes"
                if direction == "upgrade"
                else "b31_maintenance_cost_fields"
            )
            fn = (
                script._upgrade_revs
                if direction == "upgrade"
                else script._downgrade_revs
            )
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
            if direction == "upgrade":
                assert connection.execute(column_exists).scalar_one()
            else:
                assert not connection.execute(column_exists).scalar_one()
        print("b32 upgrade and downgrade passed on a temporary PostgreSQL table")
    finally:
        connection.rollback()
        engine.dispose()
