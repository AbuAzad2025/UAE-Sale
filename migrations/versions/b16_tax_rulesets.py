"""Dynamic tax rulesets per country (dynamic compliance configuration).

Revision ID: b16_tax_rulesets
Revises: b15_shipment_lines_tenant
"""

from alembic import op
import sqlalchemy as sa

revision = "b16_tax_rulesets"
down_revision = "b15_shipment_lines_tenant"
branch_labels = None
depends_on = None

DEFAULT_RULESETS = [
    (
        "AE",
        "الإمارات العربية المتحدة",
        (5.00, "VAT", 9.00, 375000.00, False, "manual", "Federal Tax Authority (FTA)"),
    ),
    (
        "SA",
        "المملكة العربية السعودية",
        (
            15.00,
            "ضريبة القيمة المضافة",
            0.00,
            0.00,
            True,
            "zatca_pending",
            "الهيئة العامة للزكاة والدخل / ZATCA",
        ),
    ),
    (
        "EG",
        "جمهورية مصر العربية",
        (14.00, "VAT", 0.00, 0.00, True, "eta_pending", "مصلحة الضرائب المصرية / ETA"),
    ),
    (
        "JO",
        "المملكة الأردنية الهاشمية",
        (16.00, "VAT", 0.00, 0.00, True, "manual", "دائرة ضريبة الدخل والمبيعات"),
    ),
    (
        "TR",
        "تركيا",
        (20.00, "KDV", 0.00, 0.00, True, "manual", "Gelir İdaresi Başkanlığı / GİB"),
    ),
    (
        "GB",
        "المملكة المتحدة",
        (20.00, "VAT", 25.00, 0.00, True, "manual", "HM Revenue and Customs / HMRC"),
    ),
    (
        "DE",
        "ألمانيا",
        (
            19.00,
            "MwSt",
            15.00,
            0.00,
            True,
            "manual",
            "Bundeszentralamt für Steuern / BZSt",
        ),
    ),
    (
        "OM",
        "سلطنة عمان",
        (5.00, "VAT", 0.00, 0.00, True, "manual", "Oman Tax Authority"),
    ),
    (
        "BH",
        "مملكة البحرين",
        (10.00, "VAT", 0.00, 0.00, True, "manual", "NBR هيأة الضرائب"),
    ),
    (
        "KW",
        "دولة الكويت",
        (0.00, "VAT", 0.00, 0.00, False, "none", "لم تُفعّل حتى اليوم"),
    ),
    ("QA", "دولة قطر", (0.00, "VAT", 0.00, 0.00, False, "none", "لم تُفعّل حتى اليوم")),
]


def upgrade() -> None:
    op.create_table(
        "tax_rulesets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("country_name", sa.String(length=80), nullable=False),
        sa.Column("vat_rate", sa.Numeric(5, 2), nullable=False, server_default="0.00"),
        sa.Column(
            "vat_label", sa.String(length=80), nullable=False, server_default="VAT"
        ),
        sa.Column(
            "vat_enabled_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "corp_tax_rate", sa.Numeric(5, 2), nullable=False, server_default="0.00"
        ),
        sa.Column(
            "corp_tax_threshold", sa.Numeric(15, 2), nullable=False, server_default="0"
        ),
        sa.Column(
            "corp_tax_enabled_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "einvoice_required", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "einvoice_status",
            sa.String(length=20),
            nullable=False,
            server_default="manual",
        ),
        sa.Column("authority_name", sa.String(length=160)),
        sa.Column("authority_portal_url", sa.String(length=500)),
        sa.Column("authority_notes", sa.Text()),
        sa.Column("compliance_notes", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
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
            "country_code", "tenant_id", name="uq_tax_ruleset_country_tenant"
        ),
    )
    op.create_index("ix_tax_rulesets_country_code", "tax_rulesets", ["country_code"])
    op.create_index("ix_tax_rulesets_tenant_id", "tax_rulesets", ["tenant_id"])

    table = sa.table(
        "tax_rulesets",
        sa.column("country_code", sa.String),
        sa.column("country_name", sa.String),
        sa.column("vat_rate", sa.Numeric),
        sa.column("vat_label", sa.String),
        sa.column("corp_tax_rate", sa.Numeric),
        sa.column("corp_tax_threshold", sa.Numeric),
        sa.column("einvoice_required", sa.Boolean),
        sa.column("einvoice_status", sa.String),
        sa.column("authority_name", sa.String),
    )
    rows = [
        {
            "country_code": c,
            "country_name": n,
            "vat_rate": r[0],
            "vat_label": r[1],
            "corp_tax_rate": r[2],
            "corp_tax_threshold": r[3],
            "einvoice_required": r[4],
            "einvoice_status": r[5],
            "authority_name": r[6],
        }
        for c, n, r in DEFAULT_RULESETS
    ]
    op.bulk_insert(table, rows)


def downgrade() -> None:
    op.drop_index("ix_tax_rulesets_tenant_id", table_name="tax_rulesets")
    op.drop_index("ix_tax_rulesets_country_code", table_name="tax_rulesets")
    op.drop_table("tax_rulesets")
