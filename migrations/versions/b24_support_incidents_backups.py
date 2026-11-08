"""Support tickets + incidents + backup verifications.

Revision ID: b24_support_incidents_backups
Revises: b23_subscription_plans
"""
from alembic import op
import sqlalchemy as sa

revision = 'b24_support_incidents_backups'
down_revision = 'b23_subscription_plans'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'support_tickets',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('author_user_id', sa.Integer(),
                  sa.ForeignKey('users.id'), nullable=False),
        sa.Column('subject', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('category', sa.String(length=24), nullable=False, server_default='other'),
        sa.Column('priority', sa.String(length=10), nullable=False, server_default='normal'),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='open'),
        sa.Column('resolution_notes', sa.Text()),
        sa.Column('resolved_at', sa.DateTime()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    )
    op.create_index('ix_support_tickets_tenant_id', 'support_tickets', ['tenant_id'])
    op.create_index('ix_support_tickets_status', 'support_tickets', ['status'])

    op.create_table(
        'incidents',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('title', sa.String(length=240), nullable=False),
        sa.Column('severity', sa.String(length=8), nullable=False, server_default='sev2'),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='open'),
        sa.Column('impact', sa.Text()),
        sa.Column('resolution_notes', sa.Text()),
        sa.Column('started_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('resolved_at', sa.DateTime()),
        sa.Column('created_by_user_id', sa.Integer(),
                  sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    )
    op.create_index('ix_incidents_status', 'incidents', ['status'])
    op.create_index('ix_incidents_severity', 'incidents', ['severity'])

    op.create_table(
        'backup_verifications',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('filename', sa.String(length=300), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('checksum', sa.String(length=64)),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='failed'),
        sa.Column('dialect', sa.String(length=32)),
        sa.Column('table_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('data_markers', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('checks_json', sa.Text()),
        sa.Column('error', sa.Text()),
        sa.Column('verified_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    )
    op.create_index('ix_backup_verifications_status', 'backup_verifications', ['status'])


def downgrade() -> None:
    op.drop_index('ix_backup_verifications_status', table_name='backup_verifications')
    op.drop_table('backup_verifications')
    op.drop_index('ix_incidents_severity', table_name='incidents')
    op.drop_index('ix_incidents_status', table_name='incidents')
    op.drop_table('incidents')
    op.drop_index('ix_support_tickets_status', table_name='support_tickets')
    op.drop_index('ix_support_tickets_tenant_id', table_name='support_tickets')
    op.drop_table('support_tickets')
