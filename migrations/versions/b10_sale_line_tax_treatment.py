"""Sale line tax treatment snapshot (standard / zero / exempt).

Revision ID: b10_sale_line_tax_treatment
Revises: b9_purchase_tax_treatment
"""
from alembic import op
import sqlalchemy as sa

revision = 'b10_sale_line_tax_treatment'
down_revision = 'b9_purchase_tax_treatment'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('sale_lines', sa.Column(
        'tax_treatment', sa.String(length=10),
        server_default='standard', nullable=False))


def downgrade() -> None:
    op.drop_column('sale_lines', 'tax_treatment')
