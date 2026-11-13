"""
Tenant Model - Multi-Tenant System
نموذج المستأجر - نظام متعدد المستأجرين
"""

from datetime import datetime, timezone
from extensions import db
from decimal import Decimal


class Tenant(db.Model):
    """
    معلومات الكراج/الشركة المستأجرة للنظام
    """

    __tablename__ = "tenants"

    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(200), nullable=False, unique=True)
    name_ar = db.Column(db.String(200), nullable=False)
    name_en = db.Column(db.String(200))
    slug = db.Column(db.String(100), unique=True, nullable=False, index=True)

    business_type = db.Column(
        db.String(50), default="garage"
    )  # garage, workshop, spare_parts, etc. (English/default)
    business_type_ar = db.Column(db.String(50))  # Arabic label
    industry = db.Column(db.String(100))  # automotive, heavy_equipment, etc. (English/default)
    industry_ar = db.Column(db.String(100))  # Arabic label

    address_ar = db.Column(db.Text)
    address_en = db.Column(db.Text)
    city = db.Column(db.String(100))
    country = db.Column(db.String(100), default="UAE")

    phone_1 = db.Column(db.String(50))
    phone_2 = db.Column(db.String(50))
    mobile = db.Column(db.String(50))
    email = db.Column(db.String(120))
    website = db.Column(db.String(200))

    tax_number = db.Column(db.String(100), index=True)  # TRN
    commercial_register = db.Column(db.String(100))
    license_number = db.Column(db.String(100))
    license_expiry = db.Column(db.Date)

    bank_name = db.Column(db.String(200))
    bank_account_number = db.Column(db.String(100))
    iban = db.Column(db.String(100))
    swift_code = db.Column(db.String(50))
    payment_terms_ar = db.Column(db.Text)
    footer_text_ar = db.Column(db.Text)
    default_invoice_note_ar = db.Column(db.Text)
    active_template = db.Column(db.String(50), default="modern")

    logo_url = db.Column(db.String(500))
    logo_dark_url = db.Column(db.String(500))
    favicon_url = db.Column(db.String(500))
    brand_color_primary = db.Column(db.String(20), default="#007A3D")
    brand_color_secondary = db.Column(db.String(20), default="#D4AF37")

    subscription_plan = db.Column(
        db.String(50), default="basic"
    )  # basic, pro, enterprise
    contract_signed_at = db.Column(db.DateTime, nullable=True)
    subscription_start = db.Column(db.DateTime)
    subscription_end = db.Column(db.DateTime)
    is_trial = db.Column(db.Boolean, default=False)
    trial_days_remaining = db.Column(db.Integer, default=0)

    max_users = db.Column(db.Integer, default=5)
    max_products = db.Column(db.Integer, default=1000)
    max_customers = db.Column(db.Integer, default=500)
    max_storage_mb = db.Column(db.Integer, default=1024)  # 1GB

    enable_multi_warehouse = db.Column(db.Boolean, default=True)
    enable_multi_currency = db.Column(db.Boolean, default=True)
    enable_gl = db.Column(db.Boolean, default=True)
    enable_ai = db.Column(db.Boolean, default=True)
    enable_reports = db.Column(db.Boolean, default=True)
    enable_api = db.Column(db.Boolean, default=False)
    enable_maintenance = db.Column(db.Boolean, default=True)

    default_currency = db.Column(db.String(3), default="AED")
    default_language = db.Column(db.String(10), default="ar")
    timezone = db.Column(db.String(50), default="Asia/Dubai")
    date_format = db.Column(db.String(20), default="%Y-%m-%d")
    time_format = db.Column(db.String(20), default="%H:%M")

    fiscal_year_start = db.Column(db.Integer, default=1)  # Month: 1-12
    enable_tax = db.Column(db.Boolean, default=True)
    default_tax_rate = db.Column(db.Numeric(5, 2), default=Decimal("5.00"))
    tax_country = db.Column(db.String(2), default="AE")
    tax_inclusive = db.Column(db.Boolean, default=False)
    corp_tax_enabled = db.Column(db.Boolean, default=False)
    corp_tax_rate = db.Column(db.Numeric(5, 2), default=Decimal("9.00"))
    corp_tax_threshold = db.Column(db.Numeric(15, 2), default=Decimal("375000.00"))
    allowed_currencies = db.Column(db.Text)

    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    is_suspended = db.Column(db.Boolean, default=False)
    suspension_reason = db.Column(db.Text)

    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    created_by = db.Column(
        db.Integer, db.ForeignKey("users.id", use_alter=True), nullable=True
    )

    def __repr__(self):
        return f"<Tenant {self.name}>"

    @staticmethod
    def get_current():
        """Get current tenant (single tenant for now, multi-tenant ready)"""
        tenant = Tenant.query.filter_by(is_active=True).first()
        if not tenant:
            tenant = Tenant(
                name="Default Garage",
                name_ar="كراج افتراضي",
                slug="default",
                business_type="garage",
            )
            db.session.add(tenant)
            db.session.commit()
        return tenant

    def is_subscription_active(self):
        """Check if subscription is active"""
        if self.subscription_end:
            return datetime.now(timezone.utc) < self.subscription_end
        return True

    def get_remaining_days(self):
        """Get remaining subscription days"""
        if self.subscription_end:
            delta = self.subscription_end - datetime.now(timezone.utc)
            return max(0, delta.days)
        return 9999

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "name_ar": self.name_ar,
            "slug": self.slug,
            "business_type": self.business_type,
            "business_type_ar": self.business_type_ar,
            "industry": self.industry,
            "industry_ar": self.industry_ar,
            "country": self.country,
            "default_currency": self.default_currency,
            "is_active": self.is_active,
            "subscription_plan": self.subscription_plan,
        }

    def get_business_type(self, lang="ar"):
        if lang == "ar" and self.business_type_ar:
            return self.business_type_ar
        return self.business_type or ""

    def get_industry(self, lang="ar"):
        if lang == "ar" and self.industry_ar:
            return self.industry_ar
        return self.industry or ""
