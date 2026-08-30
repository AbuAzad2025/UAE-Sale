"""F-01/F-03/F-04/F-05 schema invariants.

Adds the new columns, constraints, and FK relationships that
enforce the application's data invariants at the database level
(so the constraints are honoured even when the application bypasses
its own Python-level validators, e.g. from another service or
direct SQL).

Revision ID: 11_f01_f03_f04_f05_invariants
Revises: 10_remove_depr_fk
Create Date: 2026-08-30 23:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '11_f01_f03_f04_f05_invariants'
down_revision = '10_remove_depr_fk'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    is_sqlite = bind.dialect.name == 'sqlite'

    # ------------------------------------------------------------------
    # F-03: Warehouse.tenant_id
    # ------------------------------------------------------------------
    if 'warehouses' in inspector.get_table_names():
        cols = {c['name'] for c in inspector.get_columns('warehouses')}
        if 'tenant_id' not in cols:
            with op.batch_alter_table('warehouses', schema=None) as batch_op:
                batch_op.add_column(sa.Column(
                    'tenant_id', sa.Integer(),
                    sa.ForeignKey('tenants.id', ondelete='SET NULL'),
                    nullable=True, index=True))

    # ------------------------------------------------------------------
    # F-01: Receipt.sale_id + Receipt.purchase_id + XOR CHECK
    # ------------------------------------------------------------------
    if 'receipts' in inspector.get_table_names():
        cols = {c['name'] for c in inspector.get_columns('receipts')}
        with op.batch_alter_table('receipts', schema=None) as batch_op:
            if 'sale_id' not in cols:
                batch_op.add_column(sa.Column(
                    'sale_id', sa.Integer(),
                    sa.ForeignKey('sales.id', ondelete='SET NULL'),
                    nullable=True, index=True))
            if 'purchase_id' not in cols:
                batch_op.add_column(sa.Column(
                    'purchase_id', sa.Integer(),
                    sa.ForeignKey('purchases.id', ondelete='SET NULL'),
                    nullable=True, index=True))
        # F-01 xor CHECK: at most one of sale_id / purchase_id is set
        _add_check_constraint(
            'receipts', 'ck_receipt_xor_parent',
            "((sale_id IS NOT NULL AND purchase_id IS NULL) "
            "OR (sale_id IS NULL AND purchase_id IS NOT NULL) "
            "OR (sale_id IS NULL AND purchase_id IS NULL))",
            is_sqlite)

    # ------------------------------------------------------------------
    # F-04: Cheque parent-doc CHECK (sum of NOT-NULL <= 1)
    # F-05: Payment direction CHECK
    # ------------------------------------------------------------------
    if 'cheques' in inspector.get_table_names():
        _add_check_constraint(
            'cheques', 'ck_cheque_single_parent_doc',
            "((CASE WHEN sale_id IS NULL THEN 0 ELSE 1 END) + "
            "(CASE WHEN purchase_id IS NULL THEN 0 ELSE 1 END) + "
            "(CASE WHEN expense_id IS NULL THEN 0 ELSE 1 END) + "
            "(CASE WHEN payment_id IS NULL THEN 0 ELSE 1 END) + "
            "(CASE WHEN receipt_id IS NULL THEN 0 ELSE 1 END)) <= 1",
            is_sqlite)

    if 'payments' in inspector.get_table_names():
        _add_check_constraint(
            'payments', 'ck_payment_direction_fk',
            "((direction = 'incoming' AND supplier_id IS NULL) "
            "OR (direction = 'outgoing' AND sale_id IS NULL) "
            "OR (direction NOT IN ('incoming', 'outgoing')))",
            is_sqlite)


def downgrade():
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == 'sqlite'

    if 'payments' in inspector_has_table(bind, 'payments'):
        _drop_check_constraint('payments', 'ck_payment_direction_fk', is_sqlite)
    if 'cheques' in inspector_has_table(bind, 'cheques'):
        _drop_check_constraint('cheques', 'ck_cheque_single_parent_doc', is_sqlite)
    if 'receipts' in inspector_has_table(bind, 'receipts'):
        _drop_check_constraint('receipts', 'ck_receipt_xor_parent', is_sqlite)
        with op.batch_alter_table('receipts', schema=None) as batch_op:
            batch_op.drop_column('purchase_id')
            batch_op.drop_column('sale_id')
    if 'warehouses' in inspector_has_table(bind, 'warehouses'):
        with op.batch_alter_table('warehouses', schema=None) as batch_op:
            batch_op.drop_column('tenant_id')


# ----------------------------------------------------------------------
# Helper functions for portable CHECK-constraint handling.
# ----------------------------------------------------------------------

def _add_check_constraint(table_name, constraint_name, clause, is_sqlite):
    """Add a CHECK constraint in a dialect-portable way.

    SQLite (the default test dialect) does not support
    ``CREATE CONSTRAINT`` via ALTER TABLE the way PostgreSQL does,
    so we use ``batch_alter_table`` to copy/recreate the table
    with the constraint baked in.
    """
    if is_sqlite:
        with op.batch_alter_table(table_name, recreate='always') as batch_op:
            batch_op.create_check_constraint(constraint_name, clause)
    else:
        op.create_check_constraint(constraint_name, table_name, clause)


def _drop_check_constraint(table_name, constraint_name, is_sqlite):
    if is_sqlite:
        with op.batch_alter_table(table_name, recreate='always') as batch_op:
            batch_op.drop_constraint(constraint_name, type_='check')
    else:
        op.drop_constraint(constraint_name, table_name, type_='check')


def inspector_has_table(bind, table_name):
    return table_name in sa.inspect(bind).get_table_names()
