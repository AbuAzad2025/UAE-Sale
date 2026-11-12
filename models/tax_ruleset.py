"""ضريبة الشركات والقيمة المضافة — نموذج ديناميكي لكل دولة.

كل دولة لها صف قاعدة (country_code='AE' ...) تُخزَّن في قاعدة البيانات وتُعدّلها
الإدارة. يستخدمها `services/tax_engine.py` لاستخراج معدل ضريبة الافتراضي عندما
لا يضبط المستخدم معدلًا صريحًا على نفس الفاتورة. حقل `tenant_id=NULL` يعني
قاعدة الدولة نفسها، وفي المستقبل يمكن إضافة صفوف خاصة بكل شركة.
"""

from datetime import datetime, timezone
from decimal import Decimal

from extensions import db


class TaxRuleset(db.Model):
    """قاعدة ضريبة لكل دولة — قابلة للتعديل من لوحة المالك."""

    __tablename__ = "tax_rulesets"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    country_code = db.Column(db.String(2), nullable=False, index=True)
    country_name = db.Column(db.String(80), nullable=False)

    vat_rate = db.Column(db.Numeric(5, 2), nullable=False, default=Decimal("0.00"))
    vat_label = db.Column(db.String(80), nullable=False, default="VAT")
    vat_enabled_default = db.Column(db.Boolean, nullable=False, default=True)

    corp_tax_rate = db.Column(db.Numeric(5, 2), nullable=False, default=Decimal("0.00"))
    corp_tax_threshold = db.Column(
        db.Numeric(15, 2), nullable=False, default=Decimal("0")
    )
    corp_tax_enabled_default = db.Column(db.Boolean, nullable=False, default=False)

    # تبعات الامتثال الإلكتروني التي تتطلب تكاملًا مع سلطة حكومية: يبقى 'manual' حتى
    # تُعتمد التكامل الحقيقي. لا تُزعم هذه أبدًا كـ 'approved' من الكود.
    einvoice_required = db.Column(db.Boolean, nullable=False, default=False)
    einvoice_status = db.Column(db.String(20), nullable=False, default="manual")
    authority_name = db.Column(db.String(160))
    authority_portal_url = db.Column(db.String(500))
    authority_notes = db.Column(db.Text)
    compliance_notes = db.Column(db.Text)

    # سريان بتوقيت — مثلاً ضريبة السعودية 5% حتى 2020/2020-07-01 ثم 15% بعدها.
    # NULL للبداية/النهاية = بلا حدود (القاعدة دائمة). عند وجود أكثر من صف مسنود،
    # يُختار الأحدث effective_from ≤ تاريخ اليوم ثم الأكبر id.
    effective_from = db.Column(db.Date, nullable=True)
    effective_until = db.Column(db.Date, nullable=True)

    is_active = db.Column(db.Boolean, nullable=False, default=True)

    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        db.UniqueConstraint(
            "country_code", "tenant_id", name="uq_tax_ruleset_country_tenant"
        ),
    )

    def __repr__(self):
        return f"<TaxRuleset {self.country_code} {self.vat_rate}%>"


DEFAULT_RULESETS = [
    # country_code, country_name, vat_rate, vat_label, corp_rate, corp_threshold, einvoice_required, einvoice_status, authority_name
    # النسب/العتبات الرسمية موضوعة فقط للرجوع؛ يجب مراجعة كل دولة مع محاسبها.
    (
        "AE",
        "الإمارات العربية المتحدة",
        Decimal("5.00"),
        "VAT",
        Decimal("9.00"),
        Decimal("375000.00"),
        False,
        "manual",
        "Federal Tax Authority (FTA)",
    ),
    (
        "SA",
        "المملكة العربية السعودية",
        Decimal("15.00"),
        "ضريبة القيمة المضافة",
        Decimal("0.00"),
        Decimal("0.00"),
        True,
        "zatca_pending",
        "الهيئة العامة للزكاة والدخل / ZATCA",
    ),
    (
        "EG",
        "جمهورية مصر العربية",
        Decimal("14.00"),
        "VAT",
        Decimal("0.00"),
        Decimal("0.00"),
        True,
        "eta_pending",
        "مصلحة الضرائب المصرية / ETA",
    ),
    (
        "JO",
        "المملكة الأردنية الهاشمية",
        Decimal("16.00"),
        "VAT",
        Decimal("0.00"),
        Decimal("0.00"),
        True,
        "manual",
        "دائرة ضريبة الدخل والمبيعات",
    ),
    (
        "TR",
        "تركيا",
        Decimal("20.00"),
        "KDV",
        Decimal("0.00"),
        Decimal("0.00"),
        True,
        "manual",
        "Gelir İdaresi Başkanlığı / GİB",
    ),
    (
        "GB",
        "المملكة المتحدة",
        Decimal("20.00"),
        "VAT",
        Decimal("25.00"),
        Decimal("0.00"),
        True,
        "manual",
        "HM Revenue and Customs / HMRC",
    ),
    (
        "DE",
        "ألمانيا",
        Decimal("19.00"),
        "MwSt",
        Decimal("15.00"),
        Decimal("0.00"),
        True,
        "manual",
        "Bundeszentralamt für Steuern / BZSt",
    ),
    (
        "OM",
        "سلطنة عمان",
        Decimal("5.00"),
        "VAT",
        Decimal("0.00"),
        Decimal("0.00"),
        True,
        "manual",
        "Oman Tax Authority",
    ),
    (
        "BH",
        "مملكة البحرين",
        Decimal("10.00"),
        "VAT",
        Decimal("0.00"),
        Decimal("0.00"),
        True,
        "manual",
        "NBR هيأة الضرائب",
    ),
    (
        "KW",
        "دولة الكويت",
        Decimal("0.00"),
        "VAT",
        Decimal("0.00"),
        Decimal("0.00"),
        False,
        "none",
        "لم تُفعّل حتى اليوم",
    ),
    (
        "QA",
        "دولة قطر",
        Decimal("0.00"),
        "VAT",
        Decimal("0.00"),
        Decimal("0.00"),
        False,
        "none",
        "لم تُفعّل حتى اليوم",
    ),
]


def seed_default_rulesets():
    """Seed default country rulesets (idempotent)."""
    for (
        code,
        name,
        vat,
        vat_label,
        corp,
        threshold,
        einvoice_req,
        einvoice_st,
        authority,
    ) in DEFAULT_RULESETS:
        exists = TaxRuleset.query.filter_by(
            country_code=code,
            tenant_id=None,
        ).first()
        if exists is None:
            row = TaxRuleset(
                country_code=code,
                country_name=name,
                vat_rate=vat,
                vat_label=vat_label,
                corp_tax_rate=corp,
                corp_tax_threshold=threshold,
                einvoice_required=einvoice_req,
                einvoice_status=einvoice_st,
                authority_name=authority,
            )
            db.session.add(row)
    db.session.commit()


def _windowed_pick(rows, on_date):
    """من قائمة الصفوف — اختر الأحدث النافذ في التاريخ (إن وُجد)."""
    rows = [r for r in rows if r is not None]
    if not rows:
        return None
    from datetime import date as _date

    scoped = sorted(
        rows,
        key=lambda r: (
            r.effective_from is not None,
            r.effective_from or _date.min,
            r.id,
        ),
        reverse=True,
    )
    for r in scoped:
        if r.effective_until and r.effective_until < on_date:
            continue
        if r.effective_from and r.effective_from > on_date:
            continue
        return r
    return None


def ruleset_for_tenant(tenant, on_date=None):
    """اختر القاعدة المطبقة على الشركة في تاريخ محدد (افتراضي اليوم).

    الترتيب: صف خاص بالتينانت أولاً (إن وُجد مسنود نافذ) ← صف الدولة
    الافتراضي (إن وُجد نافذ في ذلك التاريخ) ← None.
    السريان: `effective_from IS NULL OR effective_from <= date` و
    `effective_until IS NULL OR effective_until >= date`؛ يُرجح الأحدث.
    """
    from datetime import date as _date

    if tenant is None:
        return None
    code = (
        (getattr(tenant, "tax_country", None) or getattr(tenant, "country", None) or "")
        .strip()
        .upper()
    )
    if not code:
        return None
    on_date = on_date or _date.today()

    tid = getattr(tenant, "id", None)
    tenant_rows = (
        TaxRuleset.query.filter_by(
            country_code=code, tenant_id=tid, is_active=True
        ).all()
        if tid
        else []
    )
    row = _windowed_pick(tenant_rows, on_date)
    if row is not None:
        return row
    platform_rows = TaxRuleset.query.filter_by(
        country_code=code, tenant_id=None, is_active=True
    ).all()
    return _windowed_pick(platform_rows, on_date)
