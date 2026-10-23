"""Due dates and customer payment terms.

The AR/AP ageing was computed from the invoice's AGE, not from what is
actually OVERDUE, because neither `sales` nor `purchases` had a due date at
all. A 30-day-old invoice that is not yet due and a 30-day-old invoice that
is 30 days late landed in the same bucket, and `payment_terms_days` (which
`suppliers` has always stored) was never honoured by anything.

  sales.due_date            - the date the receivable falls due
  purchases.due_date        - the date the payable falls due
  customers.payment_terms_days - the agreed terms, used to derive due_date

Existing rows are backfilled with the invoice's own date, so an invoice with
no stated terms is treated as due immediately. That is the conservative
reading: it never hides an overdue balance, whereas defaulting to a
30-day term would have hidden real arrears.
"""
import sqlalchemy as sa
from alembic import op

revision = 'b1_due_dates'
down_revision = 'b0_p0_isolation_integrity'
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

    # sales.due_date - nullable, no backfill needed (handled below)
    if not _has_column(conn, 'sales', 'due_date'):
        op.add_column('sales', sa.Column('due_date', sa.Date(), nullable=True))

    # purchases.due_date - nullable
    if not _has_column(conn, 'purchases', 'due_date'):
        op.add_column('purchases', sa.Column('due_date', sa.Date(), nullable=True))

    # customers.payment_terms_days - must be added nullable first, then backfilled, then NOT NULL
    if not _has_column(conn, 'customers', 'payment_terms_days'):
        op.add_column('customers', sa.Column('payment_terms_days', sa.Integer(), nullable=True))
        # Backfill existing rows to 0 (due immediately = conservative)
        op.execute('UPDATE customers SET payment_terms_days = 0 WHERE payment_terms_days IS NULL')
        # Now make it NOT NULL
        op.alter_column('customers', 'payment_terms_days', nullable=False)

    # Backfill: an invoice with no stated terms is due on its own date.
    if _has_table(conn, 'sales') and _has_column(conn, 'sales', 'due_date'):
        op.execute(
            'UPDATE sales SET due_date = CAST(sale_date AS DATE) '
            'WHERE due_date IS NULL')
    if _has_table(conn, 'purchases') and \
            _has_column(conn, 'purchases', 'due_date'):
        op.execute(
            'UPDATE purchases SET due_date = CAST(purchase_date AS DATE) '
            'WHERE due_date IS NULL')

    # The terms are a number of days, never negative.
    if _has_table(conn, 'customers'):
        op.execute(
            'UPDATE customers SET payment_terms_days = 0 '
            'WHERE payment_terms_days < 0')
        op.create_check_constraint(
            'ck_customer_payment_terms_non_negative', 'customers',
            'payment_terms_days >= 0')


def downgrade():
    bind = op.get_bind()
    conn = bind
    for table, column in [('sales', 'due_date'), ('purchases', 'due_date'), ('customers', 'payment_terms_days')]:
        if _has_column(conn, table, column):
            op.drop_column(table, column)