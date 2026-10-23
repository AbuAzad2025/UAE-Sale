"""Moving weighted average inventory cost.

The stock was valued at `products.cost_price`, which is the price of the
LAST purchase. The inventory control account, on the other hand, carries the
amounts actually paid (net of the document discount). The two therefore
diverge by construction, and the inventory valuation report could never
agree with the balance sheet.

`products.average_cost` is the running weighted average cost per unit in
base currency:

    new_avg = (old_qty * old_avg + qty * line_cost) / (old_qty + qty)

and the stock is valued at `current_stock * average_cost`. The average only
moves on an inward movement (purchase, stock-in) and is snapshotted onto the
sale line at the moment of sale, so the cost of goods sold is the cost at
the time of sale and not the cost after it.

Existing products are seeded with their last known cost, which is the best
weighted average that can be computed without the purchase history.
"""
import sqlalchemy as sa
from alembic import op

revision = 'b2_inventory_costing'
down_revision = 'b1_due_dates'
branch_labels = None
depends_on = None


def _has_column(conn, table, column):
    cols = sa.inspect(conn).get_columns(table)
    return bool(cols) and any(c['name'] == column for c in cols)


def _has_table(conn, table):
    return table in sa.inspect(conn).get_table_names()


def upgrade():
    bind = op.get_bind()
    conn = bind

    if _has_table(conn, 'products') and \
            not _has_column(conn, 'products', 'average_cost'):
        op.add_column(
            'products',
            sa.Column('average_cost', sa.Numeric(15, 3), nullable=False,
                      server_default='0'))

    # Seed from the last known cost, never below zero.
    if _has_table(conn, 'products') and \
            _has_column(conn, 'products', 'average_cost'):
        op.execute(
            'UPDATE products SET average_cost = cost_price '
            'WHERE average_cost = 0 AND cost_price IS NOT NULL '
            'AND cost_price > 0')
        op.execute(
            'UPDATE products SET average_cost = 0 WHERE average_cost < 0')

    if _has_table(conn, 'products'):
        op.create_check_constraint(
            'ck_product_average_cost_non_negative', 'products',
            'average_cost >= 0')


def downgrade():
    bind = op.get_bind()
    conn = bind
    if _has_table(conn, 'products') and \
            _has_column(conn, 'products', 'average_cost'):
        op.drop_constraint('ck_product_average_cost_non_negative', 'products',
                           type_='check')
        op.drop_column('products', 'average_cost')
