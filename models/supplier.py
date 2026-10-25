"""
🏪 Supplier Model - نموذج الموردين
==================================
نموذج منفصل لإدارة الموردين مع تتبع المشتريات والأرصدة

F6/F10: إحصائيات المورد (total_purchases_aed / total_paid_aed) لها الآن
صيغة واحدة مشتركة بين كل المستمعات (`derive_supplier_totals`)، وتضم:
  * إجمالي المشتريات المؤكدة (بالعملة الأساسية)
  * إجمالي المسدّد: ما سُدِّد على مستوى الفواتير (Purchase.paid_amount)
    + ما سُدِّد على مستوى المورد (سندات بلا purchase_id)
    − استردادات المورد (داخل = المورد يردّ لنا) لأن الاسترداد يزيد
      ما ندينه للمورد.
"""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from extensions import db
from models.tenant_scope import TenantScopedMixin

MONEY_Q = Decimal('0.001')


def _dec(value, default='0'):
    """تحويل أي قيمة حدّية إلى Decimal (لا float في المال)."""
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def derive_supplier_totals(supplier_id, connection=None):
    """المصدر الوحيد لإحصائيات المورد: (إجمالي المشتريات، إجمالي المسدّد).

    تُرجع tuple من قيمتين Decimal بعملة الأساس:
        total_purchases = Σ (amount_base أو total_amount كاحتياط) للمشتريات المؤكدة
        total_paid      = Σ Purchase.paid_amount
                          + Σ سندات صرف مؤكّدة بلا purchase_id
                          − Σ سندات قبض (استرداد) مؤكّدة
    """
    from sqlalchemy import select

    from extensions import db

    if connection is None:
        connection = db.session.connection()

    from models.purchase import Purchase
    from models.payment import Payment

    purchase_rows = connection.execute(
        select(
            Purchase.__table__.c.amount_base,
            Purchase.__table__.c.total_amount,
            Purchase.__table__.c.paid_amount,
        ).where(
            Purchase.__table__.c.supplier_id == supplier_id,
            Purchase.__table__.c.status == 'confirmed',
        )
    ).fetchall()

    total_purchases = Decimal('0')
    total_paid = Decimal('0')
    for row in purchase_rows:
        amount = row.amount_base
        if amount is None:
            # احتياط: بعض الفواتير القديمة بلا amount_base
            amount = row.total_amount
        total_purchases += _dec(amount)
        total_paid += _dec(row.paid_amount)

    # سندات الصرف على مستوى المورد (بلا ارتباط بفاتورة) + استردادات المورد.
    # السندات المرتبطة بفاتورة (purchase_id) محسوبة أعلاه عبر Purchase.paid_amount
    # فلا تُحتسب مرتين.
    payment_rows = connection.execute(
        select(Payment.__table__.c.amount_base, Payment.__table__.c.direction).where(
            Payment.__table__.c.supplier_id == supplier_id,
            Payment.__table__.c.purchase_id.is_(None),
            Payment.__table__.c.payment_confirmed.is_(True),
        )
    ).fetchall()
    for row in payment_rows:
        if row.direction == 'outgoing':
            # مسدّد على مستوى المورد فقط (المسدد على مستوى الفاتورة محسوب أعلاه)
            total_paid += _dec(row.amount_base)
        elif row.direction == 'incoming':
            # استرداد من المورد: يزيد ما ندينه له
            total_paid -= _dec(row.amount_base)

    return (
        total_purchases.quantize(MONEY_Q, rounding=ROUND_HALF_UP),
        total_paid.quantize(MONEY_Q, rounding=ROUND_HALF_UP),
    )


def recompute_supplier_totals(supplier_id, connection=None):
    """الكاتب الوحيد لإحصائيات المورد — يحسب ويكتب."""
    from extensions import db

    if supplier_id is None:
        return (Decimal('0'), Decimal('0'))

    total_purchases, total_paid = derive_supplier_totals(supplier_id, connection=connection)
    conn = connection if connection is not None else db.session.connection()
    conn.execute(
        Supplier.__table__.update().where(Supplier.__table__.c.id == supplier_id).values(
            total_purchases_aed=total_purchases,
            total_paid_aed=total_paid,
            updated_at=datetime.now(timezone.utc),
        )
    )
    _sync_session_supplier(supplier_id, total_purchases, total_paid)
    return (total_purchases, total_paid)


def _sync_session_supplier(supplier_id, total_purchases, total_paid):
    """مزامنة ذاكرة هوية الجلسة مع الكتابة على مستوى Core."""
    try:
        from sqlalchemy.orm.attributes import set_committed_value
        from sqlalchemy.orm.util import identity_key

        from extensions import db

        session = db.session()
        instance = session.identity_map.get(identity_key(Supplier, supplier_id))
        if instance is not None:
            set_committed_value(instance, 'total_purchases_aed', total_purchases)
            set_committed_value(instance, 'total_paid_aed', total_paid)
    except Exception:
        pass


class Supplier(TenantScopedMixin, db.Model):
    __tablename__ = 'suppliers'

    id = db.Column(db.Integer, primary_key=True)

    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=True, index=True)

    # معلومات أساسية
    name = db.Column(db.String(200), nullable=False, index=True)
    name_ar = db.Column(db.String(200))  # الاسم بالعربية
    name_en = db.Column(db.String(200))  # الاسم بالإنجليزية
    company_name = db.Column(db.String(200))

    # معلومات الاتصال
    phone = db.Column(db.String(30))
    phone2 = db.Column(db.String(30))
    email = db.Column(db.String(255))
    website = db.Column(db.String(200))

    # العنوان
    address = db.Column(db.Text)
    city = db.Column(db.String(100))
    country = db.Column(db.String(100), default='UAE')

    # معلومات ضريبية وقانونية
    tax_number = db.Column(db.String(50))
    commercial_registration = db.Column(db.String(50))

    # تصنيف المورد
    supplier_type = db.Column(db.String(50), default='parts')  # parts, equipment, services, materials
    rating = db.Column(db.Integer, default=3)  # 1-5 stars

    # الحد الائتماني والعملة
    credit_limit = db.Column(db.Numeric(15, 3), default=0)
    payment_terms_days = db.Column(db.Integer, default=30)  # شروط الدفع بالأيام
    preferred_currency = db.Column(db.String(3), default='ILS')

    # إحصائيات
    total_purchases_aed = db.Column(db.Numeric(15, 3), default=0)
    total_paid_aed = db.Column(db.Numeric(15, 3), default=0)
    last_purchase_date = db.Column(db.DateTime)

    # الرصيد الافتتاحي (F10) — رصيد مستحق للمورد قبل بدء استخدام النظام.
    # لم يعد يُخفى داخل total_purchases_aed (إحصائية مشتريات) الذي كان
    # يمسحه مستمع المشتريات عند أول فاتورة جديدة.
    opening_balance = db.Column(db.Numeric(15, 3), default=0, nullable=False)
    opening_balance_currency = db.Column(db.String(3), default='ILS', nullable=False)
    opening_balance_rate = db.Column(db.Numeric(15, 6), default=1, nullable=False)
    opening_balance_date = db.Column(db.Date, nullable=True)

    # معلومات إضافية
    notes = db.Column(db.Text)
    tags = db.Column(db.String(500))  # Comma-separated tags

    # الحالة
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    is_verified = db.Column(db.Boolean, default=False)  # مورد موثوق

    # Timestamps
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    # العلاقات
    purchases = db.relationship('Purchase', back_populates='supplier', lazy='dynamic')

    def __repr__(self):
        return f'<Supplier {self.name}>'

    def get_opening_balance_base(self):
        """الرصيد الافتتاحي محوّلاً إلى عملة الأساس."""
        return (_dec(self.opening_balance) * _dec(self.opening_balance_rate, '1')).quantize(
            MONEY_Q, rounding=ROUND_HALF_UP)

    def get_balance_aed(self):
        """حساب الرصيد المستحق للمورد = رصيد افتتاحي + مشتريات − مسدّد.

        المصدر الوحيد: derive_supplier_totals (نفس الصيغة التي تحدّثها
        المستمعات).
        """
        total_purchases, total_paid = derive_supplier_totals(self.id)
        return (total_purchases - total_paid + self.get_opening_balance_base()).quantize(
            MONEY_Q, rounding=ROUND_HALF_UP)

    def get_display_name(self, lang='ar'):
        """الحصول على الاسم حسب اللغة"""
        if lang == 'en' and self.name_en:
            return self.name_en
        return self.name

    def get_type_display(self):
        """عرض نوع المورد"""
        types = {
            'parts': 'قطع غيار',
            'equipment': 'معدات',
            'services': 'خدمات',
            'materials': 'مواد خام',
            'other': 'أخرى'
        }
        return types.get(self.supplier_type, self.supplier_type)

    def get_rating_stars(self):
        """عرض التقييم بنجوم"""
        stars = '⭐' * (self.rating or 0)
        return stars or '☆☆☆☆☆'

    def update_statistics(self):
        """تحديث إحصائيات المورد — نفس الصيغة المشتركة (F6)."""
        total_purchases, total_paid = derive_supplier_totals(self.id)
        self.total_purchases_aed = total_purchases
        self.total_paid_aed = total_paid

        confirmed_purchases = self.purchases.filter_by(status='confirmed').all()
        if confirmed_purchases:
            self.last_purchase_date = max(p.purchase_date for p in confirmed_purchases)

    def to_dict(self):
        """تحويل إلى قاموس للـ API"""
        return {
            'id': self.id,
            'name': self.name,
            'name_en': self.name_en,
            'company_name': self.company_name,
            'phone': self.phone,
            'email': self.email,
            'supplier_type': self.supplier_type,
            'type_display': self.get_type_display(),
            'rating': self.rating,
            'rating_stars': self.get_rating_stars(),
            'balance_aed': float(self.get_balance_aed()),
            'total_purchases_aed': float(self.total_purchases_aed or 0),
            'is_active': self.is_active,
            'is_verified': self.is_verified,
            'country': self.country,
            'city': self.city
        }
