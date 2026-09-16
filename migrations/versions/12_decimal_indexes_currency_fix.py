"""Decimal precision, missing FK indexes, and currency default fix.

- packages.price: Float -> Numeric(15,3)
- package_purchases.amount_paid: Float -> Numeric(15,3)
- expenses.currency: default 'AED' -> 'ILS'
- Missing indexes on high-cardinality FK join columns

Revision ID: 12_decimal_indexes_currency_fix
Revises: 11_f01_f03_f04_f05_invariants
Create Date: 2026-09-01
"""
from alembic import op
import sqlalchemy as sa


revision = '12_decimal_indexes_currency_fix'
down_revision = '11_f01_f03_f04_f05_invariants'
branch_labels = None
depends_on = None


def _inspector_has_table(bind, table_name):
    """Alembic-style portable table existence check (copied from migration 11)."""
    try:
        inspector = sa.inspect(bind)
        return table_name in inspector.get_table_names()
    except Exception:
        return False


def upgrade():
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == 'sqlite'

    # ------------------------------------------------------------------
    # 1.  packages.price  → Numeric(15,3)
    # ------------------------------------------------------------------
    if _inspector_has_table(bind, 'packages'):
        if is_sqlite:
            with op.batch_alter_table('packages', schema=None) as batch_op:
                batch_op.alter_column(
                    'price',
                    existing_type=sa.REAL() if hasattr(sa, 'REAL') else sa.Float(),
                    type_=sa.Numeric(15, 3),
                    existing_nullable=False,
                )
        else:
            op.alter_column(
                'packages',
                'price',
                existing_type=sa.REAL() if hasattr(sa, 'REAL') else sa.Float(),
                type_=sa.Numeric(15, 3),
                existing_nullable=False,
            )

    # ------------------------------------------------------------------
    # 2.  package_purchases.amount_paid → Numeric(15,3)
    # ------------------------------------------------------------------
    if _inspector_has_table(bind, 'package_purchases'):
        if is_sqlite:
            with op.batch_alter_table('package_purchases', schema=None) as batch_op:
                batch_op.alter_column(
                    'amount_paid',
                    existing_type=sa.REAL() if hasattr(sa, 'REAL') else sa.Float(),
                    type_=sa.Numeric(15, 3),
                    existing_nullable=False,
                )
        else:
            op.alter_column(
                'package_purchases',
                'amount_paid',
                existing_type=sa.REAL() if hasattr(sa, 'REAL') else sa.Float(),
                type_=sa.Numeric(15, 3),
                existing_nullable=False,
            )

    # ------------------------------------------------------------------
    # 3.  expenses.currency default  AED  →  ILS
    # ------------------------------------------------------------------
    if _inspector_has_table(bind, 'expenses'):
        # SQLite does not support ALTER TABLE to change DEFAULT via batch_alter.
        # For SQLite we handle this at application/model level (already fixed
        # in models/expense.py). For PostgreSQL we can issue a server default.
        if not is_sqlite:
            op.execute("""
                ALTER TABLE expenses
                ALTER COLUMN currency SET DEFAULT 'ILS';
            """)
            # Update existing rows that carry the old wrong default AED
            op.execute("""
                UPDATE expenses SET currency = 'ILS'
                WHERE currency = 'AED'
                  AND created_at IS NOT NULL;
            """)

    # ------------------------------------------------------------------
    # 4.  Missing indexes on FK columns used in JOINs / lookups
    # ------------------------------------------------------------------
    index_targets = [
        # (table_name, index_name, columns, unique)
        ('sales', 'ix_sales_seller', ['seller_id'], False),
        ('sale_lines', 'ix_sale_lines_product', ['product_id'], False),
        ('purchase_lines', 'ix_purchase_lines_product', ['product_id'], False),
        ('purchases', 'ix_purchases_user', ['user_id'], False),
        ('gl_journal_lines', 'ix_gl_lines_cost_center', ['cost_center_id'], False),
        ('cheques', 'ix_cheques_gl_clearing', ['gl_clearing_entry_id'], False),
        ('cheques', 'ix_cheques_gl_bounce', ['gl_bounce_entry_id'], False),
        ('login_history', 'ix_login_history_user', ['user_id'], False),
    ]

    for table, idx_name, columns, unique in index_targets:
        if _inspector_has_table(bind, table):
            # SQLite and PostgreSQL both accept op.create_index
            try:
                op.create_index(idx_name, table, columns, unique=unique)
            except Exception:
                # Index may already exist on some dialects
                pass


def downgrade():
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == 'sqlite'

    # 1. Downgrade indexes
    index_targets = [
        ('login_history', 'ix_login_history_user'),
        ('cheques', 'ix_cheques_gl_bounce'),
        ('cheques', 'ix_cheques_gl_clearing'),
        ('gl_journal_lines', 'ix_gl_lines_cost_center'),
        ('purchases', 'ix_purchases_user'),
        ('purchase_lines', 'ix_purchase_lines_product'),
        ('sale_lines', 'ix_sale_lines_product'),
        ('sales', 'ix_sales_seller'),
    ]
    for table, idx_name in index_targets:
        if _inspector_has_table(bind, table):
            try:
                op.drop_index(idx_name, table_name=table)
            except Exception:
                pass

    # 2. Downgrade expenses default
    if _inspector_has_table(bind, 'expenses') and not is_sqlite:
        op.execute("""
            ALTER TABLE expenses
            ALTER COLUMN currency SET DEFAULT 'AED';
        """)

    # 3. Downgrade columns (Float is never exact but restores schema shape)
    if _inspector_has_table(bind, 'package_purchases'):
        if is_sqlite:
            with op.batch_alter_table('package_purchases', schema=None) as batch_op:
                batch_op.alter_column('amount_paid', type_=sa.Float(), existing_nullable=False)
        else:
            op.alter_column('package_purchases', 'amount_paid', type_=sa.Float(), existing_nullable=False)

    if _inspector_has_table(bind, 'packages'):
        if is_sqlite:
            with op.batch_alter_table('packages', schema=None) as batch_op:
                batch_op.alter_column('price', type_=sa.Float(), existing_nullable=False)
        else:
            op.alter_column('packages', 'price', type_=sa.Float(), existing_nullable=False)
