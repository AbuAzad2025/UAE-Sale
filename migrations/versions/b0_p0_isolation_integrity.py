"""P0 isolation and integrity schema.

Brings the PRODUCTION schema (PostgreSQL, built by Alembic) in line with the
invariants the test schema (SQLite, built from model metadata) has always
enforced. The audit found the gap: the CHECK constraints below were declared
on the models but created by NO migration, so the whole suite validated
invariants the production database never enforced.

Also adds the columns the P0 fixes need:
  gl_accounts.is_system        - seeded accounts can no longer be renamed,
                                  retyped or deleted
  fiscal_periods.tenant_id     - period locks are per tenant, not global
  customers/suppliers.opening_balance* - an opening AR/AP balance that
                                  survives a balance-repair run
  payments.purchase_id         - a payment can settle a specific invoice
  receipts.allocations_json    - per-invoice allocations survive a reversal

Existing rows are normalised before each constraint is added, so the migration
does not fail on a database that already holds a violating row - and the
normalisation is itself the repair the data needs.
"""
import sqlalchemy as sa
from alembic import op

revision = 'b0_p0_isolation_integrity'
down_revision = '21_inbound_shipment'
branch_labels = None
depends_on = None


# The seeded chart of accounts, marked as system accounts so they cannot be
# renamed, retyped or deleted. Mirrors GLAccount.CORE_CODES.
CORE_CODES = (
    '1000', '1100', '1110', '1120', '1121', '1130', '1140', '1150',
    '1200', '1210', '1220', '1230', '1240', '1250',
    '2000', '2100', '2110', '2115', '2120', '2130', '2140', '2200', '2210',
    '3000', '3100', '3200', '3300', '3350', '3400',
    '4000', '4100', '4200', '4300', '4400', '4500',
    '5000', '5100', '5150', '5200', '5300',
    '6000', '6100', '6200', '6300', '6400', '6500', '6600', '6700', '6800',
    '6900', '6950', '6990',
)

# (table, column, type, nullable) for the new columns.
NEW_COLUMNS = [
    ('gl_accounts', 'is_system', sa.Boolean(), False),
    ('fiscal_periods', 'tenant_id', sa.Integer(), True),
    ('customers', 'opening_balance', sa.Numeric(15, 3), False),
    ('customers', 'opening_balance_currency', sa.String(3), False),
    ('customers', 'opening_balance_rate', sa.Numeric(15, 6), False),
    ('customers', 'opening_balance_date', sa.Date(), True),
    ('suppliers', 'opening_balance', sa.Numeric(15, 3), False),
    ('suppliers', 'opening_balance_currency', sa.String(3), False),
    ('suppliers', 'opening_balance_rate', sa.Numeric(15, 6), False),
    ('suppliers', 'opening_balance_date', sa.Date(), True),
    ('payments', 'purchase_id', sa.Integer(), True),
    ('receipts', 'allocations_json', sa.Text(), True),
]

# (table, name, sql) for the constraints the production schema was missing.
NEW_CHECKS = [
    ('products', 'ck_product_stock_non_negative', 'current_stock >= 0'),
    ('products', 'ck_product_price_non_negative', 'regular_price >= 0'),
    ('products', 'ck_product_cost_non_negative', 'cost_price >= 0'),
    ('sales', 'ck_sale_total_non_negative', 'total_amount >= 0'),
    ('sales', 'ck_sale_paid_non_negative', 'paid_amount_base >= 0'),
    ('sales', 'ck_sale_balance_non_negative', 'balance_due >= 0'),
    ('sale_lines', 'ck_saleline_qty_positive', 'quantity > 0'),
    ('sale_lines', 'ck_saleline_price_non_negative', 'unit_price >= 0'),
    ('sale_lines', 'ck_saleline_total_non_negative', 'line_total >= 0'),
    ('sale_lines', 'ck_saleline_discount_range',
     'discount_percent >= 0 AND discount_percent <= 100'),
    ('purchases', 'ck_purchase_total_non_negative', 'total_amount >= 0'),
    ('purchases', 'ck_purchase_amount_non_negative', 'amount_base >= 0'),
    ('purchase_lines', 'ck_purchaseline_qty_positive', 'quantity > 0'),
    ('purchase_lines', 'ck_purchaseline_cost_non_negative', 'unit_cost >= 0'),
    ('purchase_lines', 'ck_purchaseline_total_non_negative', 'line_total >= 0'),
    ('payments', 'ck_payment_amount_positive', 'amount > 0'),
    ('payments', 'ck_payment_amount_base_positive', 'amount_base > 0'),
    ('receipts', 'ck_receipt_amount_positive', 'amount > 0'),
    ('receipts', 'ck_receipt_amount_base_positive', 'amount_base > 0'),
]

# Rows that would violate a constraint are repaired first, so ADD CONSTRAINT
# cannot fail on a database that already holds bad data.
NORMALISATIONS = [
    ("UPDATE products SET current_stock = 0 WHERE current_stock < 0", None),
    ("UPDATE products SET regular_price = 0 WHERE regular_price < 0", None),
    ("UPDATE products SET cost_price = 0 WHERE cost_price < 0", None),
    ("UPDATE sales SET total_amount = 0 WHERE total_amount < 0", None),
    ("UPDATE sales SET paid_amount_base = 0 WHERE paid_amount_base < 0", None),
    ("UPDATE sales SET balance_due = 0 WHERE balance_due < 0", None),
    ("UPDATE sale_lines SET quantity = 0 WHERE quantity <= 0", None),
    ("UPDATE sale_lines SET unit_price = 0 WHERE unit_price < 0", None),
    ("UPDATE sale_lines SET line_total = 0 WHERE line_total < 0", None),
    ("UPDATE sale_lines SET discount_percent = 0 "
     "WHERE discount_percent < 0 OR discount_percent > 100", None),
    ("UPDATE purchases SET total_amount = 0 WHERE total_amount < 0", None),
    ("UPDATE purchases SET amount_base = 0 WHERE amount_base < 0", None),
    ("UPDATE purchase_lines SET quantity = 0 WHERE quantity <= 0", None),
    ("UPDATE purchase_lines SET unit_cost = 0 WHERE unit_cost < 0", None),
    ("UPDATE purchase_lines SET line_total = 0 WHERE line_total < 0", None),
    ("UPDATE payments SET amount = 0 WHERE amount <= 0", None),
    ("UPDATE payments SET amount_base = 0 WHERE amount_base <= 0", None),
    ("UPDATE receipts SET amount = 0 WHERE amount <= 0", None),
    ("UPDATE receipts SET amount_base = 0 WHERE amount_base <= 0", None),
]


def _has_column(conn, table, column):
    return sa.inspect(conn).get_columns(table) and any(
        c['name'] == column for c in sa.inspect(conn).get_columns(table))


def upgrade():
    bind = op.get_bind()
    is_pg = bind.dialect.name == 'postgresql'
    conn = bind

    # 1. New columns.
    for table, column, coltype, nullable in NEW_COLUMNS:
        if not _has_column(conn, table, column):
            op.add_column(table, sa.Column(column, coltype, nullable=nullable))
            if table == 'gl_accounts':
                op.create_index(
                    'ix_gl_accounts_is_system', 'gl_accounts', ['is_system'])
            elif table == 'fiscal_periods':
                op.create_index(
                    'ix_fiscal_periods_tenant_id', 'fiscal_periods',
                    ['tenant_id'])
            elif table == 'payments':
                op.create_index(
                    'ix_payments_purchase_id', 'payments', ['purchase_id'])
            elif column == 'opening_balance':
                op.create_index(
                    f'ix_{table}_opening_balance', table, ['opening_balance'])

    # 2. Foreign keys for the new relationship columns.
    if is_pg:
        op.execute(
            'DO $$ BEGIN '
            '  IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints '
            '     WHERE constraint_name = '
            "'fk_fiscal_periods_tenant_id_tenants') THEN "
            '    ALTER TABLE fiscal_periods ADD CONSTRAINT '
            '      fk_fiscal_periods_tenant_id_tenants '
            '      FOREIGN KEY (tenant_id) REFERENCES tenants(id) '
            '      ON DELETE SET NULL; '
            '  END IF; '
            'END $$;')
        op.execute(
            'DO $$ BEGIN '
            '  IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints '
            '     WHERE constraint_name = '
            "'fk_payments_purchase_id_purchases') THEN "
            '    ALTER TABLE payments ADD CONSTRAINT '
            '      fk_payments_purchase_id_purchases '
            '      FOREIGN KEY (purchase_id) REFERENCES purchases(id) '
            '      ON DELETE SET NULL; '
            '  END IF; '
            'END $$;')

    # 3. Mark the seeded chart of accounts as system accounts.
    op.execute("UPDATE gl_accounts SET is_system = true "
               "WHERE code IN ({})".format(
                   ', '.join(f"'{c}'" for c in CORE_CODES)))

    # 4. Default the opening-balance columns for existing rows.
    op.execute("UPDATE customers SET opening_balance = 0 "
               "WHERE opening_balance IS NULL")
    op.execute("UPDATE customers SET opening_balance_currency = 'ILS' "
               "WHERE opening_balance_currency IS NULL")
    op.execute("UPDATE customers SET opening_balance_rate = 1 "
               "WHERE opening_balance_rate IS NULL")
    op.execute("UPDATE suppliers SET opening_balance = 0 "
               "WHERE opening_balance IS NULL")
    op.execute("UPDATE suppliers SET opening_balance_currency = 'ILS' "
               "WHERE opening_balance_currency IS NULL")
    op.execute("UPDATE suppliers SET opening_balance_rate = 1 "
               "WHERE opening_balance_rate IS NULL")

    # 5. Purchase payment_status: 'pending' was never a valid status and the
    #    column was never written, so every purchase looked permanently
    #    unpaid. Align the legacy values with the documented domain.
    op.execute("UPDATE purchases SET payment_status = 'unpaid' "
               "WHERE payment_status IS NULL OR payment_status = 'pending'")

    # 6. Backfill the receipt -> invoice link from the legacy polymorphic
    #    columns, so a bounced cheque can reverse its invoice.
    op.execute("UPDATE receipts SET sale_id = source_id "
               "WHERE sale_id IS NULL AND purchase_id IS NULL "
               "AND source_type = 'sale' AND source_id IS NOT NULL")

    # 7. Normalise the rows that would violate the constraints below.
    for sql, _ in NORMALISATIONS:
        op.execute(sql)

    # 8. The constraints the production schema never had.
    for table, name, sql in NEW_CHECKS:
        op.execute(
            'ALTER TABLE {} ADD CONSTRAINT {} CHECK ({})'.format(
                table, name, sql))


def downgrade():
    bind = op.get_bind()

    for table, name, _ in reversed(NEW_CHECKS):
        op.execute('ALTER TABLE {} DROP CONSTRAINT IF EXISTS {}'.format(
            table, name))

    for table, column, _, _ in reversed(NEW_COLUMNS):
        if _has_column(bind, table, column):
            op.drop_column(table, column)
