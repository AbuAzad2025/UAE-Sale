"""Compliance credentials vault (encrypted, per tenant × authority).

Revision ID: b22_compliance_credentials
Revises: b21_vat_split_accounts
"""

from alembic import op
import sqlalchemy as sa

revision = "b22_compliance_credentials"
down_revision = "b21_vat_split_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "compliance_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("authority_key", sa.String(length=40), nullable=False),
        sa.Column("payload_encrypted", sa.Text()),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="configured"
        ),
        sa.Column("notes", sa.Text()),
        sa.Column("last_rotated_at", sa.DateTime()),
        sa.Column("verified_at", sa.DateTime()),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "authority_key",
            name="uq_compliance_credential_tenant_authority",
        ),
    )
    op.create_index(
        "ix_compliance_credentials_tenant_id", "compliance_credentials", ["tenant_id"]
    )
    op.create_index(
        "ix_compliance_credentials_authority_key",
        "compliance_credentials",
        ["authority_key"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_compliance_credentials_authority_key", table_name="compliance_credentials"
    )
    op.drop_index(
        "ix_compliance_credentials_tenant_id", table_name="compliance_credentials"
    )
    op.drop_table("compliance_credentials")
