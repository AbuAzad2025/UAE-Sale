"""Purchase tax treatment snapshot (standard / zero / exempt).

Revision ID: b9_purchase_tax_treatment
Revises: b8_vat_treatments
"""
from alembic import op
import sqlalchemy as sa

revision = 'b9_purchase_tax_treatment'
down_revision = 'b8_vat_treatments'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('purchases', sa.Column(
        'tax_treatment', sa.String(length=10),
        server_default='standard', nullable=False))


def downgrade() -> None:
    op.drop_column('purchases', 'tax_treatment')
