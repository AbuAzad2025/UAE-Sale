"""Add the order notes column missing from the maintenance core migration.

Revision ID: b32_maintenance_order_notes
Revises: b31_maintenance_cost_fields
"""

from alembic import op
import sqlalchemy as sa

revision = "b32_maintenance_order_notes"
down_revision = "b31_maintenance_cost_fields"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("maintenance_orders", sa.Column("notes", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("maintenance_orders", "notes")
