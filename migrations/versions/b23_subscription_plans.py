"""Subscription plans + tenant contract signing.

Revision ID: b23_subscription_plans
Revises: b22_compliance_credentials
"""

from alembic import op
import sqlalchemy as sa

revision = "b23_subscription_plans"
down_revision = "b22_compliance_credentials"
branch_labels = None
depends_on = None

DEFAULT_PLANS = [
    # slug, name_ar, name_en, price_year, price_month, max_users, max_products, max_customers, sort, is_public
    ("basic", "الباقة الأساسية", "Basic", "499.00", "49.00", 2, 300, 500, 10, True),
    (
        "pro",
        "الباقة الاحترافية",
        "Professional",
        "999.00",
        "99.00",
        8,
        5000,
        10000,
        20,
        True,
    ),
    (
        "enterprise",
        "باقة الشركات والمؤسسات",
        "Enterprise",
        "1999.00",
        "199.00",
        30,
        50000,
        100000,
        30,
        True,
    ),
]


def upgrade() -> None:
    op.create_table(
        "subscription_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(length=50), unique=True, nullable=False),
        sa.Column("name_ar", sa.String(length=120), nullable=False),
        sa.Column("name_en", sa.String(length=120)),
        sa.Column("price_year", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("price_month", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column(
            "currency", sa.String(length=3), nullable=False, server_default="AED"
        ),
        sa.Column("max_users", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("max_products", sa.Integer(), nullable=False, server_default="500"),
        sa.Column("max_customers", sa.Integer(), nullable=False, server_default="1000"),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("features_ar", sa.Text()),
        sa.Column("features_en", sa.Text()),
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
    )
    op.create_index(
        "ix_subscription_plans_slug", "subscription_plans", ["slug"], unique=True
    )

    op.add_column(
        "tenants", sa.Column("contract_signed_at", sa.DateTime(), nullable=True)
    )

    table = sa.table(
        "subscription_plans",
        sa.column("slug", sa.String),
        sa.column("name_ar", sa.String),
        sa.column("name_en", sa.String),
        sa.column("price_year", sa.Numeric),
        sa.column("price_month", sa.Numeric),
        sa.column("max_users", sa.Integer),
        sa.column("max_products", sa.Integer),
        sa.column("max_customers", sa.Integer),
        sa.column("sort_order", sa.Integer),
        sa.column("is_public", sa.Boolean),
    )
    rows = [
        {
            "slug": s,
            "name_ar": na,
            "name_en": ne,
            "price_year": py,
            "price_month": pm,
            "max_users": mu,
            "max_products": mp,
            "max_customers": mc,
            "sort_order": so,
            "is_public": pub,
        }
        for s, na, ne, py, pm, mu, mp, mc, so, pub in DEFAULT_PLANS
    ]
    op.bulk_insert(table, rows)


def downgrade() -> None:
    op.drop_column("tenants", "contract_signed_at")
    op.drop_index("ix_subscription_plans_slug", table_name="subscription_plans")
    op.drop_table("subscription_plans")
