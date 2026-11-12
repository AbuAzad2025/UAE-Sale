"""Subscription plans — باقات المنتج (أسعار تحددها الإدارة، لا يُعدّلها الكود).

المواصفات على مستوى الشركة:
* كل باقة لها slug فريد بالإنجليزية لتطابق tenant.subscription_plan.
* الحدود (users/products/customers) للمراقبة فقط — لا تُفرض قبل موافقة المالك.
* is_public = تظهر في /pricing؛ التعديل من /owner/plans فقط.
"""

from datetime import datetime, timezone
from decimal import Decimal

from extensions import db


class SubscriptionPlan(db.Model):
    __tablename__ = "subscription_plans"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name_ar = db.Column(db.String(120), nullable=False)
    name_en = db.Column(db.String(120))

    price_year = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    price_month = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    currency = db.Column(db.String(3), nullable=False, default="AED")

    max_users = db.Column(db.Integer, nullable=False, default=3)
    max_products = db.Column(db.Integer, nullable=False, default=500)
    max_customers = db.Column(db.Integer, nullable=False, default=1000)

    is_public = db.Column(db.Boolean, nullable=False, default=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    sort_order = db.Column(db.Integer, nullable=False, default=100)

    features_ar = db.Column(db.Text)  # سطور ميزات عربية
    features_en = db.Column(db.Text)  # سطور ميزات إنجليزية

    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def price_per_month_equivalent(self):
        if self.price_year and self.price_year > 0:
            return (self.price_year / 12).quantize(Decimal("0.01"))
        return self.price_month

    def __repr__(self):
        return f"<SubscriptionPlan {self.slug}>"
