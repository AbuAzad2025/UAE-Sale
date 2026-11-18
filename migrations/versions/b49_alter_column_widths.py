"""Widen columns to match model definitions (schema parity).

Revision ID: b49_alter_column_widths
Revises: b48_maint_child_tenant
Create Date: 2026-11-17

The test_schema_parity test compares `alembic upgrade head` output with
`db.create_all()` output. These columns were narrower in migrations than in
the models; align them so production matches the declared model types.
"""
from alembic import op
import sqlalchemy as sa

revision = "b49_alter_column_widths"
down_revision = "b48_maint_child_tenant"
branch_labels = None
depends_on = None

# (table, column, target_type)
WIDEN = [
    ("customers", "email", sa.String(255)),
    ("customers", "phone", sa.String(30)),
    ("employees", "emergency_contact_phone", sa.String(30)),
    ("suppliers", "email", sa.String(255)),
    ("suppliers", "phone", sa.String(30)),
    ("suppliers", "phone2", sa.String(30)),
    ("tenants", "bank_account_number", sa.String(100)),
    ("tenants", "bank_name", sa.String(200)),
    ("tenants", "iban", sa.String(100)),
    ("users", "email", sa.String(255)),
]


def _current_type(table, column):
    bind = op.get_bind()
    row = bind.execute(sa.text(
        "SELECT data_type, character_maximum_length FROM information_schema.columns "
        "WHERE table_name=:t AND column_name=:c"
    ), {"t": table, "c": column}).fetchone()
    return row


def upgrade():
    for table, column, target in WIDEN:
        row = _current_type(table, column)
        if not row:
            continue
        data_type, max_len = row
        target_len = target.length
        # Widen VARCHAR, or convert TEXT -> VARCHAR where the model says VARCHAR.
        if data_type == "character varying" and (max_len or 0) >= target_len:
            continue
        op.alter_column(table, column, type_=target, existing_type=sa.String(length=max_len) if max_len else sa.Text(),
                        existing_nullable=True)


def downgrade():
    # Narrowing back is unsafe if data was inserted in the wider columns; this
    # is a schema-alignment migration, so downgrade is a no-op for the widths.
    pass
