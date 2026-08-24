"""Add tenant_id to all core business tables for row-level multi-tenant isolation.

Revision ID: 2b_add_tenant_scoping
Revises: 1a6dadd0ddb4
Create Date: 2026-08-24
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2b_add_tenant_scoping'
down_revision = '1a6dadd0ddb4'
branch_labels = None
depends_on = None


# Tables that need a tenant_id FK column
_TENANT_TABLES = [
    'sales',
    'sale_lines',
    'purchases',
    'purchase_lines',
    'payments',
    'receipts',
    'customers',
    'suppliers',
    'products',
    'stock_movements',
    'cheques',
    'gl_journal_entries',
]


def upgrade():
    """Add tenant_id (indexed FK) to each core business table, then backfill to default tenant."""

    # 1. Ensure a default tenant exists
    op.execute("""
        INSERT INTO tenants (name, name_ar, slug, business_type, is_active, created_at)
        VALUES ('Default Garage', 'كراج افتراضي', 'default', 'garage', TRUE, NOW())
        ON CONFLICT (name) DO NOTHING;
    """)

    # 2. Add tenant_id column to each table
    for table in _TENANT_TABLES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(
                sa.Column('tenant_id', sa.Integer(), nullable=True)
            )
            batch_op.create_index(
                f'ix_{table}_tenant_id',
                ['tenant_id'],
                unique=False
            )
            batch_op.create_foreign_key(
                f'fk_{table}_tenant_id',
                'tenants',
                ['tenant_id'],
                ['id'],
                ondelete='SET NULL'
            )

    # 3. Add tenant_id to users table
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('tenant_id', sa.Integer(), nullable=True)
        )
        batch_op.create_index('ix_users_tenant_id', ['tenant_id'], unique=False)
        batch_op.create_foreign_key(
            'fk_users_tenant_id',
            'tenants',
            ['tenant_id'],
            ['id'],
            ondelete='SET NULL'
        )

    # 4. Backfill: set all existing rows to the default tenant (id=1)
    for table in _TENANT_TABLES + ['users']:
        op.execute(f"""
            UPDATE {table} SET tenant_id = 1
            WHERE tenant_id IS NULL;
        """)


def downgrade():
    """Remove tenant_id columns from all tables."""

    for table in _TENANT_TABLES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_constraint(f'fk_{table}_tenant_id', type_='foreignkey')
            batch_op.drop_index(f'ix_{table}_tenant_id')
            batch_op.drop_column('tenant_id')

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_constraint('fk_users_tenant_id', type_='foreignkey')
        batch_op.drop_index('ix_users_tenant_id')
        batch_op.drop_column('tenant_id')
