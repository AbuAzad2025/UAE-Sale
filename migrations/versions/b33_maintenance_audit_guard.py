"""Protect maintenance status and warranty audit records from alteration.

Revision ID: b33_maintenance_audit_guard
Revises: b32_maintenance_order_notes
"""

from alembic import op
import sqlalchemy as sa


revision = "b33_maintenance_audit_guard"
down_revision = "b32_maintenance_order_notes"
branch_labels = None
depends_on = None

TABLES = ("maintenance_order_status_log", "maintenance_warranty_audit")
FUNCTION_NAME = "azadexa_maintenance_audit_guard_b33"


def _postgres_function_name(bind):
    schema = bind.execute(sa.text("SELECT current_schema()")).scalar_one()
    if not schema:
        raise RuntimeError(
            "A target schema is required for the maintenance audit guard"
        )
    return f"{bind.dialect.identifier_preparer.quote_schema(schema)}.{FUNCTION_NAME}"


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        function = _postgres_function_name(bind)
        # Do not replace a pre-existing function that could belong to another
        # migration or the operator: a name collision must fail the upgrade.
        op.execute(f"""
            CREATE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'Maintenance audit records are append-only'
                    USING ERRCODE = '55000';
            END;
            $$
        """)
        for table in TABLES:
            op.execute(
                f"CREATE TRIGGER trg_{table}_immutable_b33 "
                f"BEFORE UPDATE OR DELETE ON {table} "
                f"FOR EACH ROW EXECUTE FUNCTION {function}()"
            )
            op.execute(
                f"CREATE TRIGGER trg_{table}_no_truncate_b33 "
                f"BEFORE TRUNCATE ON {table} "
                f"FOR EACH STATEMENT EXECUTE FUNCTION {function}()"
            )
    elif bind.dialect.name == "sqlite":
        for table in TABLES:
            for action in ("UPDATE", "DELETE"):
                op.execute(
                    f"CREATE TRIGGER IF NOT EXISTS trg_{table}_{action.lower()}_b33 "
                    f"BEFORE {action} ON {table} BEGIN "
                    "SELECT RAISE(ABORT, 'Maintenance audit records are append-only'); END"
                )
    else:
        raise RuntimeError("Maintenance audit protection requires PostgreSQL or SQLite")


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in TABLES:
            op.execute(f"DROP TRIGGER trg_{table}_no_truncate_b33 ON {table}")
            op.execute(f"DROP TRIGGER trg_{table}_immutable_b33 ON {table}")
        op.execute(f"DROP FUNCTION {_postgres_function_name(bind)}()")
    elif bind.dialect.name == "sqlite":
        for table in TABLES:
            for action in ("UPDATE", "DELETE"):
                op.execute(f"DROP TRIGGER trg_{table}_{action.lower()}_b33")
    else:
        raise RuntimeError("Maintenance audit protection requires PostgreSQL or SQLite")
