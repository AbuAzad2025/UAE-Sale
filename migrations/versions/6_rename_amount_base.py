"""Rename *_aed columns to *_base (base-currency semantics, per-tenant aware)

Revision ID: 6_rename_amount_base
Revises: 5_add_missing_indexes
"""
from alembic import op

revision = '6_rename_amount_base'
down_revision = '5_add_missing_indexes'
branch_labels = None
depends_on = None

RENAMES = [
    ('sales', 'amount_aed', 'amount_base'),
    ('sales', 'paid_amount_aed', 'paid_amount_base'),
    ('payments', 'amount_aed', 'amount_base'),
    ('receipts', 'amount_aed', 'amount_base'),
    ('gl_journal_lines', 'amount_aed', 'amount_base'),
    ('cheques', 'amount_aed', 'amount_base'),
    ('cheques', 'actual_amount_aed', 'actual_amount_base'),
    ('purchases', 'amount_aed', 'amount_base'),
    ('expenses', 'amount_aed', 'amount_base'),
    ('product_returns', 'amount_aed', 'amount_base'),
    ('quotations', 'amount_aed', 'amount_base'),
    ('customs_taxes', 'amount_aed', 'amount_base'),
    ('advanced_expenses', 'amount_aed', 'amount_base'),
]


def upgrade():
    for table, old, new in RENAMES:
        try:
            with op.batch_alter_table(table) as batch_op:
                batch_op.alter_column(column_name=old, new_column_name=new)
        except Exception as e:
            # Column may not exist in older schemas; log and continue
            print(f"[migration] skip {table}.{old}: {e}")


def downgrade():
    for table, old, new in RENAMES:
        try:
            with op.batch_alter_table(table) as batch_op:
                batch_op.alter_column(column_name=new, new_column_name=old)
        except Exception as e:
            print(f"[migration downgrade] skip {table}.{new}: {e}")
