"""Drop the retired multi-package/subscription-plan system.

Revision ID: c01_drop_package_system
Revises: b50_invoice_settings_tenant
Create Date: 2026-11-20

The platform now has ONE unified package.  The old packages /
package_purchases / subscription_plans tables and tenants.subscription_plan
are no longer part of the model metadata.
"""
from alembic import op
import sqlalchemy as sa

revision = "c01_drop_package_system"
down_revision = "b50_invoice_settings_tenant"
branch_labels = None
depends_on = None


def _has_table(name):
    return sa.inspect(op.get_bind()).has_table(name)


def _has_column(table, column):
    if not _has_table(table):
        return False
    return column in [c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)]


def upgrade():
    if _has_table("package_purchases"):
        try:
            op.drop_constraint(
                "fk_package_purchases_package_id_packages",
                "package_purchases",
                type_="foreignkey",
            )
        except Exception:
            pass
        op.drop_table("package_purchases")
    if _has_table("packages"):
        op.drop_table("packages")
    if _has_table("subscription_plans"):
        op.drop_table("subscription_plans")
    if _has_column("tenants", "subscription_plan"):
        with op.batch_alter_table("tenants") as batch:
            batch.drop_column("subscription_plan")


def downgrade():
    # Recreate the historical schema so migrations can be rolled back to base.
    if not _has_table("packages"):
        op.create_table(
            "packages",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name_ar", sa.String(100), nullable=False),
            sa.Column("name_en", sa.String(100), nullable=False),
            sa.Column("slug", sa.String(50), nullable=False, unique=True),
            sa.Column("price", sa.Numeric(15, 3), nullable=False),
            sa.Column("is_active", sa.Boolean(), default=True),
        )
    if not _has_table("package_purchases"):
        op.create_table(
            "package_purchases",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("package_id", sa.Integer(), sa.ForeignKey("packages.id")),
            sa.Column("customer_name", sa.String(200), nullable=False),
            sa.Column("customer_email", sa.String(200), nullable=False),
            sa.Column("amount_paid", sa.Numeric(15, 3), default=0),
            sa.Column("payment_status", sa.String(50)),
        )
    if not _has_table("subscription_plans"):
        op.create_table(
            "subscription_plans",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("slug", sa.String(50), nullable=False, unique=True),
            sa.Column("sort_order", sa.Integer(), default=100),
            sa.Column("is_active", sa.Boolean(), default=True),
        )
    if not _has_column("tenants", "subscription_plan"):
        with op.batch_alter_table("tenants") as batch:
            batch.add_column(sa.Column("subscription_plan", sa.String(50), default="basic"))
