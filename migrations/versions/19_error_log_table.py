"""Structured error_log table for the centralized error journal.

Until now errors only existed as raw lines in logs/errors.log: no user,
no layer (backend/frontend/logic/programming), no triage state. This
table stores every captured fault with its actor, location, sanitized
detail and resolution state so the owner page can explain each failure.

Revision ID: 19_error_log_table (19 chars — must stay <= 32 for the
alembic_version VARCHAR(32) column on legacy databases).
Revises: 18_donation_method_flags
"""
from alembic import op
import sqlalchemy as sa


revision = '19_error_log_table'
down_revision = '18_donation_method_flags'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'error_logs' in inspector.get_table_names():
        return
    op.create_table(
        'error_logs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('category', sa.String(20), nullable=False),
        sa.Column('severity', sa.String(20), nullable=False,
                  server_default='error'),
        sa.Column('source', sa.String(50)),
        sa.Column('user_id', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('username', sa.String(150)),
        sa.Column('user_role', sa.String(50)),
        sa.Column('method', sa.String(10)),
        sa.Column('path', sa.String(500)),
        sa.Column('endpoint', sa.String(150)),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('traceback_text', sa.Text()),
        sa.Column('request_id', sa.String(50)),
        sa.Column('ip_address', sa.String(50)),
        sa.Column('user_agent', sa.String(500)),
        sa.Column('resolved', sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column('resolved_at', sa.DateTime()),
        sa.Column('resolved_by_id', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='SET NULL')),
    )
    op.create_index('ix_error_logs_created_at', 'error_logs', ['created_at'])
    op.create_index('ix_error_logs_category', 'error_logs', ['category'])
    op.create_index('ix_error_logs_severity', 'error_logs', ['severity'])
    op.create_index('ix_error_logs_user_id', 'error_logs', ['user_id'])
    op.create_index('ix_error_logs_request_id', 'error_logs', ['request_id'])
    op.create_index('ix_error_logs_resolved', 'error_logs', ['resolved'])


def downgrade():
    for name in ('ix_error_logs_resolved', 'ix_error_logs_request_id',
                 'ix_error_logs_user_id', 'ix_error_logs_severity',
                 'ix_error_logs_category', 'ix_error_logs_created_at'):
        try:
            op.drop_index(name, table_name='error_logs')
        except Exception:
            pass
    op.drop_table('error_logs')
