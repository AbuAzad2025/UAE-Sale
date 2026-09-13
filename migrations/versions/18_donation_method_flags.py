"""Per-method donation switches controlled from the owner panel.

Until now every payment method (crypto / card / PayPal / bank) was always
shown on the public donation page, with no way to close one: availability
was neither flaggable nor derived from configuration. These four booleans
(default True = preserve current behaviour) let the owner close any method;
the public page hides closed methods and offers WhatsApp contact instead.

Revision ID: 18_donation_method_flags (26 chars — must stay <= 32 for the
alembic_version VARCHAR(32) column on legacy databases).
Revises: 17_audit_trail_survives
"""
from alembic import op
import sqlalchemy as sa

revision = '18_donation_method_flags'
down_revision = '17_audit_trail_survives'
branch_labels = None
depends_on = None

COLUMNS = (
    'crypto_enabled',
    'card_enabled',
    'paypal_enabled',
    'bank_enabled',
)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {c['name'] for c in inspector.get_columns('payment_vault')}
    with op.batch_alter_table('payment_vault', schema=None) as batch_op:
        for col in COLUMNS:
            if col not in existing:
                batch_op.add_column(
                    sa.Column(col, sa.Boolean(), nullable=False,
                              server_default=sa.true()))


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        for col in COLUMNS:
            op.execute(sa.text(
                'ALTER TABLE payment_vault DROP COLUMN IF EXISTS %s' % col))
    else:
        with op.batch_alter_table('payment_vault', schema=None) as batch_op:
            for col in COLUMNS:
                try:
                    batch_op.drop_column(col)
                except Exception:
                    pass
