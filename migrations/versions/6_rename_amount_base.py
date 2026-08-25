"""Rename *_aed columns to *_base (base-currency semantics, per-tenant aware)

Revision ID: 6_rename_amount_base
Revises: 5_add_missing_indexes
"""
from alembic import op
import sqlalchemy as sa

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


def column_exists(table, column):
    """Check if a column exists in a table."""
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :column"
        ),
        {'table': table, 'column': column}
    )
    return result.scalar() is not None


def constraint_exists(table, constraint):
    """Check if a constraint exists in a table."""
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE table_name = :table AND constraint_name = :constraint"
        ),
        {'table': table, 'constraint': constraint}
    )
    return result.scalar() is not None


def upgrade():
    for table, old, new in RENAMES:
        if column_exists(table, old):
            op.execute(f'ALTER TABLE {table} RENAME COLUMN {old} TO {new}')
        else:
            print(f"[migration] skip {table}.{old}: column does not exist")

    # Rename check constraints if they exist
    if constraint_exists('sales', 'ck_sale_paid_non_negative'):
        op.execute("""
            ALTER TABLE sales
            RENAME CONSTRAINT ck_sale_paid_non_negative TO ck_sale_paid_base_non_negative;
        """)

    if constraint_exists('sales', 'ck_sale_total_non_negative'):
        op.execute("""
            ALTER TABLE sales
            RENAME CONSTRAINT ck_sale_total_non_negative TO ck_sale_total_base_non_negative;
        """)

    if constraint_exists('sales', 'ck_sale_balance_non_negative'):
        op.execute("""
            ALTER TABLE sales
            RENAME CONSTRAINT ck_sale_balance_non_negative TO ck_sale_balance_base_non_negative;
        """)


def downgrade():
    for table, old, new in RENAMES:
        if column_exists(table, new):
            op.execute(f'ALTER TABLE {table} RENAME COLUMN {new} TO {old}')
        else:
            print(f"[migration downgrade] skip {table}.{new}: column does not exist")