"""Update watermark settings with default values

Revision ID: update_watermark_settings
Revises: 4b866d5e4c3c
Create Date: 2025-10-23 12:32:00.000000

"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime

# revision identifiers, used by Alembic.
revision = 'update_watermark_settings'
down_revision = '4b866d5e4c3c'
branch_labels = None
depends_on = None


def upgrade():
    # تحديث إعدادات العلامة المائية للسجل الموجود
    op.execute("""
        UPDATE invoice_settings 
        SET 
            enable_watermark = 1,
            watermark_text = 'نسخة أصلية',
            updated_at = CURRENT_TIMESTAMP
        WHERE id = 1
    """)


def downgrade():
    # إرجاع التغييرات
    op.execute("""
        UPDATE invoice_settings 
        SET 
            enable_watermark = 0,
            watermark_text = NULL
        WHERE id = 1
    """)

