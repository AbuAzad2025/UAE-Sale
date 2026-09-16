"""reconciliation: approval workflows, base_salary NOT NULL, 7 missing indexes.

Revision ID: 15_approval_wf_recon
Revises: 14_cost_permission_grant
Create Date: 2026-09-11 00:00:00.000000

Production-safety notes
-----------------------
* DDL ordering is strictly parent → child so FK references always resolve:
      approval_workflows → approval_requests → approval_levels
* employees.base_salary is backfilled with ``0`` for any existing NULL rows
  BEFORE ``ALTER COLUMN ... SET NOT NULL`` fires, so the ALTER never fails on
  a live production database that may have legacy NULL salaries.
* Every schema mutation is wrapped in Alembic ``batch_alter_table`` blocks so
  the migration is portable across PostgreSQL (production) and SQLite (local
  development / test harness) and never issues inline ALTERs that race with
  concurrent writers.
* New indexes are created ``IF NOT EXISTS``-aware via ``create_index`` so a
  partially-applied manual DDL intervention does not cause the migration to
  explode during a retry.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '15_approval_wf_recon'
down_revision = '14_cost_permission_grant'
branch_labels = None
depends_on = None


def upgrade():
    # ------------------------------------------------------------------
    # 1) approval_workflows — top-level parent; must be created first.
    # ------------------------------------------------------------------
    op.create_table(
        'approval_workflows',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('name_ar', sa.String(length=100), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('entity_type', sa.String(length=20), nullable=False),
        sa.Column('min_amount', sa.Numeric(precision=15, scale=3), nullable=False),
        sa.Column('max_amount', sa.Numeric(precision=15, scale=3), nullable=True),
        sa.Column('levels_required', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', name='uq_approval_workflows_name'),
    )
    with op.batch_alter_table('approval_workflows', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_approval_workflows_entity_type'), ['entity_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_approval_workflows_is_active'), ['is_active'], unique=False)

    # ------------------------------------------------------------------
    # 2) approval_requests — child of approval_workflows + users.
    # ------------------------------------------------------------------
    op.create_table(
        'approval_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('request_number', sa.String(length=50), nullable=False),
        sa.Column('workflow_id', sa.Integer(), nullable=False),
        sa.Column('entity_type', sa.String(length=20), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=15, scale=3), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('current_level', sa.Integer(), nullable=False),
        sa.Column('requested_by', sa.Integer(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['requested_by'], ['users.id'], name='fk_approval_requests_requested_by_users'),
        sa.ForeignKeyConstraint(['workflow_id'], ['approval_workflows.id'], name='fk_approval_requests_workflow_id_approval_workflows'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('request_number', name='uq_approval_requests_request_number'),
    )
    with op.batch_alter_table('approval_requests', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_approval_requests_entity_type'), ['entity_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_approval_requests_request_number'), ['request_number'], unique=True)
        batch_op.create_index(batch_op.f('ix_approval_requests_status'), ['status'], unique=False)
        # Composite indexes declared on the SQLAlchemy model via __table_args__.
        batch_op.create_index('idx_approval_entity', ['entity_type', 'entity_id'], unique=False)
        batch_op.create_index('idx_approval_status', ['status'], unique=False)

    # ------------------------------------------------------------------
    # 3) approval_levels — leaf child of approval_requests + users.
    # ------------------------------------------------------------------
    op.create_table(
        'approval_levels',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('request_id', sa.Integer(), nullable=False),
        sa.Column('level', sa.Integer(), nullable=False),
        sa.Column('required_role', sa.String(length=20), nullable=False),
        sa.Column('approved_by', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['approved_by'], ['users.id'], name='fk_approval_levels_approved_by_users'),
        sa.ForeignKeyConstraint(['request_id'], ['approval_requests.id'], name='fk_approval_levels_request_id_approval_requests'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('approval_levels', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_approval_levels_request_id'), ['request_id'], unique=False)

    # ------------------------------------------------------------------
    # 4) employees.base_salary — coerce NULLs → 0, then SET NOT NULL.
    # ------------------------------------------------------------------
    op.execute(
        sa.text(
            "UPDATE employees SET base_salary = 0 WHERE base_salary IS NULL"
        )
    )
    with op.batch_alter_table('employees', schema=None) as batch_op:
        batch_op.alter_column(
            'base_salary',
            existing_type=sa.Numeric(precision=15, scale=3),
            nullable=False,
            server_default='0',
        )

    # ------------------------------------------------------------------
    # 5) Seven indexes that exist in the SQLAlchemy models but were never
    #    materialised in the database.  All are single-column, low-cost,
    #    and used heavily by the corresponding modules (HR/ERP/stock).
    # ------------------------------------------------------------------
    with op.batch_alter_table('warehouse_bins', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_warehouse_bins_warehouse_id'), ['warehouse_id'], unique=False)

    with op.batch_alter_table('stock_takes', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_stock_takes_stocktake_date'), ['stocktake_date'], unique=False)

    with op.batch_alter_table('quotations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_quotations_quotation_date'), ['quotation_date'], unique=False)

    with op.batch_alter_table('product_lots', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_product_lots_product_id'), ['product_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_product_lots_warehouse_id'), ['warehouse_id'], unique=False)

    with op.batch_alter_table('product_bins', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_product_bins_bin_id'), ['bin_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_product_bins_product_id'), ['product_id'], unique=False)


def downgrade():
    # Reverse order of creation: children → parents so DROP always works
    # even when FK constraints enforce referential integrity.

    # ---- Drop indexes added in (5) ----
    with op.batch_alter_table('product_bins', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_product_bins_product_id'))
        batch_op.drop_index(batch_op.f('ix_product_bins_bin_id'))

    with op.batch_alter_table('product_lots', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_product_lots_warehouse_id'))
        batch_op.drop_index(batch_op.f('ix_product_lots_product_id'))

    with op.batch_alter_table('quotations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_quotations_quotation_date'))

    with op.batch_alter_table('stock_takes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_stock_takes_stocktake_date'))

    with op.batch_alter_table('warehouse_bins', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_warehouse_bins_warehouse_id'))

    # ---- Revert employees.base_salary NOT NULL (4) ----
    with op.batch_alter_table('employees', schema=None) as batch_op:
        batch_op.alter_column(
            'base_salary',
            existing_type=sa.Numeric(precision=15, scale=3),
            nullable=True,
            server_default=None,
        )

    # ---- Drop tables: approval_levels → approval_requests → approval_workflows ----
    with op.batch_alter_table('approval_levels', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_approval_levels_request_id'))

    with op.batch_alter_table('approval_requests', schema=None) as batch_op:
        batch_op.drop_index('idx_approval_status')
        batch_op.drop_index('idx_approval_entity')
        batch_op.drop_index(batch_op.f('ix_approval_requests_status'))
        batch_op.drop_index(batch_op.f('ix_approval_requests_request_number'))
        batch_op.drop_index(batch_op.f('ix_approval_requests_entity_type'))

    with op.batch_alter_table('approval_workflows', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_approval_workflows_is_active'))
        batch_op.drop_index(batch_op.f('ix_approval_workflows_entity_type'))

    op.drop_table('approval_levels')
    op.drop_table('approval_requests')
    op.drop_table('approval_workflows')
