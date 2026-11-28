"""
نموذج الموازنة التخطيطية - Budget Model
"""

from datetime import datetime, timezone
from extensions import db
from models.tenant_scope import TenantScopedMixin
from decimal import Decimal, ROUND_HALF_EVEN, ROUND_HALF_UP

# Money columns are Numeric(18, 3): quantize actuals/variance once, HALF_UP,
# so a DB round-trip cannot disagree with the variance shown to the user.
MONEY_Q = Decimal("0.001")
# Percentage columns are Numeric(_, 2); the default Decimal quantize mode is
# HALF_EVEN, so state it explicitly rather than relying on an implicit mode.
PERCENT_Q = Decimal("0.01")


def _dec(value, default="0"):
    """Safe Decimal conversion for budget amounts (never float arithmetic)."""
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (TypeError, ValueError, ArithmeticError):
        return Decimal(default)


class Budget(TenantScopedMixin, db.Model):
    """
    الموازنة السنوية/الشهرية
    """

    __tablename__ = "budgets"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(
        db.Integer, db.ForeignKey("tenants.id"), nullable=True, index=True
    )
    budget_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name_ar = db.Column(db.String(200), nullable=False)
    name_en = db.Column(db.String(200))

    fiscal_year = db.Column(db.Integer, nullable=False, index=True)  # 2025, 2026
    period_type = db.Column(
        db.String(20), default="annual"
    )  # annual, quarterly, monthly
    period_start = db.Column(db.Date, nullable=False)
    period_end = db.Column(db.Date, nullable=False)

    total_budgeted = db.Column(db.Numeric(18, 3), default=0)
    total_actual = db.Column(db.Numeric(18, 3), default=0)
    total_variance = db.Column(db.Numeric(18, 3), default=0)
    variance_percentage = db.Column(db.Numeric(5, 2), default=0)

    status = db.Column(
        db.String(20), default="draft", index=True
    )  # draft, active, closed

    notes = db.Column(db.Text)

    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    approved_at = db.Column(db.DateTime)

    lines = db.relationship(
        "BudgetLine", back_populates="budget", cascade="all, delete-orphan"
    )
    creator = db.relationship("User", foreign_keys=[created_by])
    approver = db.relationship("User", foreign_keys=[approved_by])

    def __repr__(self):
        return f"<Budget {self.budget_number} - {self.fiscal_year}>"

    @property
    def status_ar(self):
        """الحالة بالعربي"""
        statuses = {"draft": "مسودة", "active": "نشطة", "closed": "مغلقة"}
        return statuses.get(self.status, self.status)

    @property
    def period_type_ar(self):
        """نوع الفترة بالعربي"""
        types = {"annual": "سنوية", "quarterly": "ربع سنوية", "monthly": "شهرية"}
        return types.get(self.period_type, self.period_type)

    def update_actuals(self):
        """تحديث الأرقام الفعلية من دفتر الأستاذ"""
        from sqlalchemy import func
        from models import GLJournalLine, GLJournalEntry

        total_actual = Decimal("0")
        total_variance = Decimal("0")

        for line in self.lines:
            # Only POSTED, non-reversed entries count as actuals. Drafts and
            # reversal pairs must never inflate the budget variance.
            debit_sum = db.session.query(func.sum(GLJournalLine.debit)).filter(
                GLJournalLine.account_id == line.account_id
            ).join(GLJournalEntry).filter(
                GLJournalEntry.is_posted.is_(True),
                GLJournalEntry.is_reversed.is_(False),
                func.date(GLJournalEntry.entry_date).between(
                    self.period_start, self.period_end
                )
            ).scalar() or Decimal("0")

            credit_sum = db.session.query(func.sum(GLJournalLine.credit)).filter(
                GLJournalLine.account_id == line.account_id
            ).join(GLJournalEntry).filter(
                GLJournalEntry.is_posted.is_(True),
                GLJournalEntry.is_reversed.is_(False),
                func.date(GLJournalEntry.entry_date).between(
                    self.period_start, self.period_end
                )
            ).scalar() or Decimal("0")

            actual = (
                debit_sum - credit_sum
                if line.account.type in ["asset", "expense"]
                else credit_sum - debit_sum  # liability, equity, revenue
            )
            line.actual_amount = _dec(actual).quantize(MONEY_Q, rounding=ROUND_HALF_UP)
            line.variance = _dec(line.actual_amount - _dec(line.budgeted_amount)).quantize(
                MONEY_Q, rounding=ROUND_HALF_UP
            )

            budgeted = _dec(line.budgeted_amount)
            line.variance_percentage = (
                ((line.variance / budgeted) * 100).quantize(
                    PERCENT_Q, rounding=ROUND_HALF_EVEN
                )
                if budgeted != 0
                else Decimal("0")
            )

            total_actual += _dec(line.actual_amount)
            total_variance += _dec(line.variance)

        self.total_actual = total_actual.quantize(MONEY_Q, rounding=ROUND_HALF_UP)
        self.total_variance = total_variance.quantize(MONEY_Q, rounding=ROUND_HALF_UP)

        total_budgeted = _dec(self.total_budgeted)
        self.variance_percentage = (
            ((self.total_variance / total_budgeted) * 100).quantize(
                PERCENT_Q, rounding=ROUND_HALF_EVEN
            )
            if total_budgeted != 0
            else Decimal("0")
        )

        db.session.commit()

    def activate(self):
        """تفعيل الموازنة"""
        if self.status != "draft":
            raise ValueError("الموازنة نشطة مسبقاً")

        self.status = "active"
        db.session.commit()

    def close(self):
        """إغلاق الموازنة"""
        if self.status != "active":
            raise ValueError("يجب أن تكون الموازنة نشطة لإغلاقها")

        self.update_actuals()

        self.status = "closed"
        db.session.commit()


class BudgetLine(TenantScopedMixin, db.Model):
    """
    سطور الموازنة - حساب واحد
    """

    __tablename__ = "budget_lines"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(
        db.Integer, db.ForeignKey("tenants.id"), nullable=True, index=True
    )
    budget_id = db.Column(db.Integer, db.ForeignKey("budgets.id"), nullable=False, index=True)
    account_id = db.Column(db.Integer, db.ForeignKey("gl_accounts.id"), nullable=False, index=True)

    budgeted_amount = db.Column(db.Numeric(18, 3), nullable=False)

    actual_amount = db.Column(db.Numeric(18, 3), default=0)

    variance = db.Column(db.Numeric(18, 3), default=0)
    variance_percentage = db.Column(db.Numeric(8, 2), default=0)

    notes = db.Column(db.Text)

    budget = db.relationship("Budget", back_populates="lines")
    account = db.relationship("GLAccount")

    def __repr__(self):
        return f"<BudgetLine {self.account.code} - {self.budgeted_amount}>"

    @property
    def variance_status(self):
        """حالة الانحراف"""
        if abs(self.variance_percentage) < 5:
            return "good"  # ضمن الحدود
        elif abs(self.variance_percentage) < 15:
            return "warning"  # تحذير
        else:
            return "danger"  # خطر

    @property
    def variance_status_ar(self):
        """حالة الانحراف بالعربي"""
        statuses = {"good": "ممتاز", "warning": "يحتاج متابعة", "danger": "انحراف كبير"}
        return statuses.get(self.variance_status, "-")
