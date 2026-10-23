"""Bad debt write-offs.

A receivable that is never going to be collected could not be written off:
there was no entity for it, so the balance simply stayed on the books
forever as if it were still collectible. Bad debt is a real, expected
operating cost and it has to reach the general ledger.

`write_offs` records the decision - who wrote it off, why, against which
customer and which invoice - and posts the double entry:

    Dr 6960  Bad debt expense      (BAD_DEBT_EXPENSE role)
    Cr 1130  Accounts receivable   (AR_CONTROL role)

The row is linked to the journal entry it created, so the write-off and its
accounting cannot drift apart, and the amount is stored in both the
transaction currency and the base currency so the entry can be reversed at
the original rate.

Account 6960 is seeded here so the PRODUCTION chart of accounts contains the
expense account the posting needs, exactly as `ensure_core_accounts` does
for every other core account.
"""
import sqlalchemy as sa
from alembic import op

revision = 'b3_write_offs'
down_revision = 'b2_inventory_costing'
branch_labels = None
depends_on = None


BAD_DEBT_CODE = '6960'
BAD_DEBT_NAME = 'Bad debt expense'
BAD_DEBT_NAME_AR = 'مديونية مشطوبة'


def _has_table(conn, table):
    return table in sa.inspect(conn).get_table_names()


def _has_column(conn, table, column):
    cols = sa.inspect(conn).get_columns(table)
    return bool(cols) and any(c['name'] == column for c in cols)


def upgrade():
    bind = op.get_bind()
    conn = bind

    if not _has_table(conn, 'write_offs'):
        op.create_table(
            'write_offs',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('tenant_id', sa.Integer(), nullable=False),
            sa.Column('customer_id', sa.Integer(), nullable=False),
            sa.Column('sale_id', sa.Integer(), nullable=True),
            sa.Column('amount', sa.Numeric(15, 3), nullable=False),
            sa.Column('currency', sa.String(3), nullable=False),
            sa.Column('amount_base', sa.Numeric(15, 3), nullable=False),
            sa.Column('reason', sa.String(500), nullable=False),
            sa.Column('status', sa.String(20), nullable=False,
                      server_default='posted'),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('created_by', sa.Integer(), nullable=True),
            sa.Column('gl_entry_id', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('posted_at', sa.DateTime(), nullable=True),
            sa.Column('voided_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'],
                                    name='fk_write_offs_tenant_id_tenants'),
            sa.ForeignKeyConstraint(['customer_id'], ['customers.id'],
                                    name='fk_write_offs_customer_id_customers'),
            sa.ForeignKeyConstraint(['sale_id'], ['sales.id'],
                                    name='fk_write_offs_sale_id_sales'),
            sa.CheckConstraint('amount > 0',
                               name='ck_writeoff_amount_positive'),
            sa.CheckConstraint('amount_base > 0',
                               name='ck_writeoff_amount_base_positive'),
            sa.CheckConstraint(
                "status IN ('draft', 'posted', 'void')",
                name='ck_writeoff_status_valid'),
        )
        op.create_index('ix_write_offs_tenant_id', 'write_offs',
                        ['tenant_id'])
        op.create_index('ix_write_offs_customer_id', 'write_offs',
                        ['customer_id'])
        op.create_index('ix_write_offs_sale_id', 'write_offs', ['sale_id'])
        op.create_index('ix_write_offs_status', 'write_offs', ['status'])

    if not _has_table(conn, 'gl_accounts'):
        return

    # Seed the bad debt expense account, and mark it a system account so it
    # cannot be renamed, retyped or deleted out from under the posting.
    account = sa.table(
        'gl_accounts',
        sa.column('code', sa.String(20)),
        sa.column('name', sa.String(200)),
        sa.column('name_ar', sa.String(200)),
        sa.column('type', sa.String(20)),
        sa.column('currency', sa.String(3)),
        sa.column('is_active', sa.Boolean()),
        sa.column('is_header', sa.Boolean()),
        sa.column('is_system', sa.Boolean()),
        sa.column('level', sa.Integer()),
        sa.column('created_at', sa.DateTime()),
    )
    exists = conn.execute(
        sa.select(sa.func.count()).select_from(account)
        .where(account.c.code == BAD_DEBT_CODE)).scalar()
    if not exists:
        conn.execute(account.insert().values(
            code=BAD_DEBT_CODE,
            name=BAD_DEBT_NAME,
            name_ar=BAD_DEBT_NAME_AR,
            type='expense',
            currency='ILS',
            is_active=True,
            is_header=False,
            is_system=True,
            level=0,
            created_at=sa.func.now(),
        ))

    if _has_column(conn, 'gl_accounts', 'is_system'):
        op.execute(
            f"UPDATE gl_accounts SET is_system = true "
            f"WHERE code = '{BAD_DEBT_CODE}'")


def downgrade():
    bind = op.get_bind()
    conn = bind
    if _has_table(conn, 'write_offs'):
        op.drop_table('write_offs')
    if _has_table(conn, 'gl_accounts'):
        op.execute(
            f"DELETE FROM gl_accounts WHERE code = '{BAD_DEBT_CODE}' "
            f"AND is_system = true")
