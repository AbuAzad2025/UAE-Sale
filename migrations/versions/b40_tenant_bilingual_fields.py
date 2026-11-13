"""Add bilingual business_type and industry fields to tenants.

Revision ID: b40_tenant_bilingual_fields
Revises: b39_error_log_extra_context
Create Date: 2026-11-13
"""
from alembic import op
import sqlalchemy as sa

revision = "b40_tenant_bilingual_fields"
down_revision = "b39_error_log_extra_context"
branch_labels = None
depends_on = None


def upgrade():
    # Idempotent: skip if columns already exist
    from sqlalchemy import inspect as _inspect

    conn = op.get_bind()
    inspector = _inspect(conn)
    cols = [c["name"] for c in inspector.get_columns("tenants")]
    if "business_type_ar" not in cols:
        op.add_column("tenants", sa.Column("business_type_ar", sa.String(50), nullable=True))
    if "industry_ar" not in cols:
        op.add_column("tenants", sa.Column("industry_ar", sa.String(100), nullable=True))

    # Backfill defaults for existing rows
    op.execute(
        "UPDATE tenants SET business_type_ar = 'كراج' WHERE business_type = 'garage' AND business_type_ar IS NULL"
    )
    op.execute(
        "UPDATE tenants SET business_type_ar = 'ورشة' WHERE business_type = 'workshop' AND business_type_ar IS NULL"
    )
    op.execute(
        "UPDATE tenants SET business_type_ar = 'قطع غيار' WHERE business_type = 'spare_parts' AND business_type_ar IS NULL"
    )
    op.execute(
        "UPDATE tenants SET industry_ar = 'سيارات' WHERE industry = 'automotive' AND industry_ar IS NULL"
    )
    op.execute(
        "UPDATE tenants SET industry_ar = 'معدات ثقيلة' WHERE industry = 'heavy_equipment' AND industry_ar IS NULL"
    )


def downgrade():
    op.drop_column("tenants", "industry_ar")
    op.drop_column("tenants", "business_type_ar")