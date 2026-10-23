"""Add due_date indexes for sales and purchases.

The models declare `due_date` with `index=True` but the b1 migration
added the columns without creating the indexes. This migration adds them.
"""
import sqlalchemy as sa
from alembic import op

revision = 'b4_due_dates_indexes'
down_revision = 'b3_write_offs'
branch_labels = None
depends_on = None


def _has_index(conn, table, index_name):
    indexes = sa.inspect(conn).get_indexes(table)
    return any(idx['name'] == index_name for idx in indexes)


def upgrade():
    bind = op.get_bind()
    conn = bind

    if not _has_index(conn, 'sales', 'ix_sales_due_date'):
        op.create_index('ix_sales_due_date', 'sales', ['due_date'])

    if not _has_index(conn, 'purchases', 'ix_purchases_due_date'):
        op.create_index('ix_purchases_due_date', 'purchases', ['due_date'])


def downgrade():
    bind = op.get_bind()
    conn = bind

    if _has_index(conn, 'sales', 'ix_sales_due_date'):
        op.drop_index('ix_sales_due_date', 'sales')

    if _has_index(conn, 'purchases', 'ix_purchases_due_date'):
        op.drop_index('ix_purchases_due_date', 'purchases')