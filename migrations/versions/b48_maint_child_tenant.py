"""Add tenant_id to maintenance child tables and backfill from parent orders.

Revision ID: b48_maint_child_tenant
Revises: b47_roles_drop_name_unique
Create Date: 2026-11-17

These tables previously had no tenant_id and relied solely on parent-order
scoping, so direct queries (e.g. MaintenanceInvoice.query.all()) leaked rows
across tenants. This migration adds the column, backfills from the parent,
and creates the FK + index.
"""
from alembic import op
import sqlalchemy as sa

revision = "b48_maint_child_tenant"
down_revision = "b47_roles_drop_name_unique"
branch_labels = None
depends_on = None

# (child table, parent table used to resolve tenant_id, join column on child)
CHILD_TABLES = [
    ("maintenance_order_items", "maintenance_orders", "maintenance_order_id"),
    ("maintenance_order_services", "maintenance_orders", "maintenance_order_id"),
    ("maintenance_order_status_log", "maintenance_orders", "maintenance_order_id"),
    ("maintenance_receipts", "maintenance_orders", "maintenance_order_id"),
    ("maintenance_invoices", "maintenance_orders", "maintenance_order_id"),
    ("maintenance_returns", "maintenance_orders", "maintenance_order_id"),
    ("maintenance_return_lines", "maintenance_returns", "return_id"),
    ("maintenance_credit_notes", "maintenance_orders", "maintenance_order_id"),
]


def _column_exists(table, column):
    from sqlalchemy import inspect as _inspect
    return column in [c["name"] for c in _inspect(op.get_bind()).get_columns(table)]


def _table_exists(table):
    from sqlalchemy import inspect as _inspect
    return _inspect(op.get_bind()).has_table(table)


def upgrade():
    conn = op.get_bind()
    for table, parent, fk_col in CHILD_TABLES:
        if not _table_exists(table):
            continue
        if not _column_exists(table, "tenant_id"):
            op.add_column(table, sa.Column("tenant_id", sa.Integer(), nullable=True))
        # Backfill from the parent chain (direct parent, or grandparent for return lines)
        if table == "maintenance_return_lines":
            conn.execute(sa.text(
                "UPDATE maintenance_return_lines rl SET tenant_id = o.tenant_id "
                "FROM maintenance_returns r, maintenance_orders o "
                "WHERE rl.return_id = r.id AND r.maintenance_order_id = o.id "
                "AND rl.tenant_id IS NULL"
            ))
        else:
            conn.execute(sa.text(
                f"UPDATE {table} c SET tenant_id = p.tenant_id "
                f"FROM {parent} p WHERE c.{fk_col} = p.id AND c.tenant_id IS NULL"
            ))
        # Create FK + index if missing
        fks = [f["name"] for f in sa.inspect(conn).get_foreign_keys(table)]
        fk_name = f"fk_{table}_tenant_id_tenants"
        if fk_name not in fks:
            try:
                op.create_foreign_key(fk_name, table, "tenants", ["tenant_id"], ["id"])
            except Exception:
                pass
        idx_name = f"ix_{table}_tenant_id"
        indexes = [i["name"] for i in sa.inspect(conn).get_indexes(table)]
        if idx_name not in indexes:
            op.create_index(idx_name, table, ["tenant_id"])


def downgrade():
    for table, parent, fk_col in reversed(CHILD_TABLES):
        if not _table_exists(table):
            continue
        idx_name = f"ix_{table}_tenant_id"
        if idx_name in [i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)]:
            op.drop_index(idx_name, table)
        if _column_exists(table, "tenant_id"):
            op.drop_column(table, "tenant_id")
