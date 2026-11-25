"""Read-only production checks for the database used by the ERP agent."""

from argparse import ArgumentParser
from os import environ
from pathlib import Path

from alembic.script import ScriptDirectory
from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = {
    "tenants": "slug IN ('queue-load', 'agent-workflow')",
    "users": "username IN ('testowner', 'testmanager', 'testseller') OR username ~ '^bench-[0-9]+$'",
    "sales": "sale_number ~ '^BENCH-[0-9]+$'",
    "products": "part_number ~ '^BENCH-(1000|1001)-[0-9]+$'",
    "bot_events": "raw_input IN ('workbook-1000', 'workbook-1001', 'confirm workload workbook')",
}


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--before-migrate", action="store_true")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    if environ.get("APP_ENV") != "production" or environ.get("DEBUG", "0").lower() not in {"0", "false", "off", "no"}:
        parser.error("Production checks require APP_ENV=production and DEBUG=false")
    required = ("DATABASE_URL", "SECRET_KEY", "OWNER_PASSWORD", "CARD_ENCRYPTION_KEY", "MASTER_KEY_SEED")
    missing = [key for key in required if not environ.get(key, "").strip()]
    if missing:
        parser.error("Missing required environment variables: " + ", ".join(missing))
    url = make_url(environ["DATABASE_URL"])
    if url.drivername == "postgres":
        url = url.set(drivername="postgresql")
    if url.get_backend_name() != "postgresql" or not url.database:
        parser.error("An explicit PostgreSQL database is required")
    engine = create_engine(url, connect_args={"connect_timeout": 5})
    with engine.connect() as connection:
        connection.execute(text("SET TRANSACTION READ ONLY"))
        connection.execute(text("SET LOCAL statement_timeout = '15s'"))
        tables = set(inspect(connection).get_table_names())
        matches = [table for table, condition in FIXTURES.items() if table in tables and connection.scalar(
            text(f"SELECT EXISTS (SELECT 1 FROM {table} WHERE {condition})")
        )]
        if matches:
            parser.error("Known test fixtures detected in: " + ", ".join(matches))
        if not args.before_migrate:
            required_tables = {"alembic_version", "assistant_actions", "bot_events", "bot_conversations", "bot_context_memory", "bot_event_audit"}
            if not required_tables <= tables:
                parser.error("The ERP agent schema is incomplete")
            expected = set(ScriptDirectory(str(ROOT / "migrations")).get_heads())
            applied = set(connection.scalars(text("SELECT version_num FROM alembic_version")))
            if applied != expected:
                parser.error("Alembic has not reached the release head")
            print("PostgreSQL migration verified: " + ", ".join(sorted(applied)))
    print("No known test fixture markers found in the target database.")


if __name__ == "__main__":
    main()
