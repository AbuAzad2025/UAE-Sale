"""Add tenant_id to invoice_settings so letterheads are tenant-isolated.

Revision ID: b50_invoice_settings_tenant
Revises: b49_alter_column_widths
Create Date: 2026-11-19

invoice_settings previously had a single shared row for all tenants, so every
tenant printed the same letterhead. This adds tenant_id, backfills orphan rows
to the default tenant, and creates the FK + index.
"""
from alembic import op
import sqlalchemy as sa

revision = "b50_invoice_settings_tenant"
down_revision = "b49_alter_column_widths"
branch_labels = None
depends_on = None


def _column_exists(table, column):
    from sqlalchemy import inspect as _inspect
    return column in [c["name"] for c in _inspect(op.get_bind()).get_columns(table)]


def upgrade():
    conn = op.get_bind()
    if not _column_exists("invoice_settings", "tenant_id"):
        op.add_column(
            "invoice_settings",
            sa.Column("tenant_id", sa.Integer(), nullable=True),
        )
    # Backfill any pre-existing shared row to the default tenant so it stays
    # reachable (fresh DBs have no rows here).
    default_id = conn.execute(
        sa.text("SELECT id FROM tenants WHERE slug='default' ORDER BY id LIMIT 1")
    ).scalar()
    if default_id is not None:
        conn.execute(
            sa.text(
                "UPDATE invoice_settings SET tenant_id = :tid WHERE tenant_id IS NULL"
            ),
            {"tid": default_id},
        )
    # Create FK + index defensively (named to be idempotent across DBs).
    try:
        op.create_foreign_key(
            "fk_invoice_settings_tenant",
            "invoice_settings", "tenants", ["tenant_id"], ["id"],
        )
    except Exception:
        pass
    try:
        op.create_index(
            "ix_invoice_settings_tenant_id", "invoice_settings", ["tenant_id"]
        )
    except Exception:
        pass


def downgrade():
    try:
        op.drop_index("ix_invoice_settings_tenant_id", "invoice_settings")
    except Exception:
        pass
    try:
        op.drop_constraint("fk_invoice_settings_tenant", "invoice_settings", type_="foreignkey")
    except Exception:
        pass
    if _column_exists("invoice_settings", "tenant_id"):
        op.drop_column("invoice_settings", "tenant_id")
