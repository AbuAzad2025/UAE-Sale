from alembic import op
import sqlalchemy as sa
from datetime import datetime, timezone

revision = 'add_owner_features_tables'
down_revision = 'payment_vault_indexes'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'login_history',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('username', sa.String(50), nullable=False),
        sa.Column('ip_address', sa.String(50)),
        sa.Column('user_agent', sa.String(500)),
        sa.Column('login_time', sa.DateTime(), default=lambda: datetime.now(timezone.utc)),
        sa.Column('logout_time', sa.DateTime()),
        sa.Column('success', sa.Boolean(), default=True),
        sa.Column('failure_reason', sa.String(200)),
        sa.Column('device_type', sa.String(50)),
        sa.Column('browser', sa.String(100)),
        sa.Column('location', sa.String(200))
    )
    
    op.create_table(
        'security_alerts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('alert_type', sa.String(50), nullable=False),
        sa.Column('severity', sa.String(20), default='medium'),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('ip_address', sa.String(50)),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id')),
        sa.Column('username', sa.String(50)),
        sa.Column('url', sa.String(500)),
        sa.Column('method', sa.String(10)),
        sa.Column('status_code', sa.Integer()),
        sa.Column('created_at', sa.DateTime(), default=lambda: datetime.now(timezone.utc)),
        sa.Column('is_resolved', sa.Boolean(), default=False),
        sa.Column('resolved_at', sa.DateTime()),
        sa.Column('resolved_by', sa.Integer(), sa.ForeignKey('users.id'))
    )
    
    op.create_table(
        'api_keys',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('key', sa.String(64), unique=True, nullable=False),
        sa.Column('secret', sa.String(128)),
        sa.Column('service', sa.String(50), nullable=False),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('created_at', sa.DateTime(), default=lambda: datetime.now(timezone.utc)),
        sa.Column('last_used', sa.DateTime()),
        sa.Column('usage_count', sa.Integer(), default=0),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'))
    )

def downgrade():
    op.drop_table('api_keys')
    op.drop_table('security_alerts')
    op.drop_table('login_history')

