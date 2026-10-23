"""
نموذج العميل - Customer Model
===========================
هذا الملف هو **المصدر الوحيد** لصيغة رصيد العميل (Customer.balance).

F1: كان رصيد العميل يُكتب من 13 كاتباً بصيغتين مختلفتين (إعادة احتساب /
زيادة تدريجية) فكانت النتيجة غير حتمية: آخر كاتب يكتب هو الفائز.
الحل: دالة اشتقاق واحدة `derive_customer_balance` + كاتب واحد
`recompute_customer_balance`، وكل مسارات الكتابة تستدعيهما.

صيغة الرصيد (بالعملة الأساسية فقط — Base Currency):

    balance = الرصيد الافتتاحي (opening_balance × opening_balance_rate)
            + Σ (amount_base − paid_amount_base) لفاتورة بيع (confirmed + active)
            − Σ (refund_amount × exchange_rate) لمرتجع معتمد (approved)
            − Σ amount_base لسند صرف/استرداد عميل غير مرتبط بفاتورة
            + Σ تعديلات الشيكات Legacy (شيكات وارد غير مرتبطة بسند/فاتورة)
            − Σ سندات قبض غير مرتبطة بفاتورة (مؤكّدة = دفع مقدّم)
            − Σ المشاطرات المنفذة (posted write-offs, amount_base)

كل المبالغ Decimal مع تقريب ROUND_HALF_UP.
"""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from extensions import db
from models.tenant_scope import TenantScopedMixin

# تقريب المبالغ (3 منازل عشرية) — نفس أعمدة Money في قاعدة البيانات
MONEY_Q = Decimal('0.001')


def _dec(value, default='0'):
    """تحويل أي قيمة حدّية إلى Decimal (لا تُستخدم float أبدًا في المال)."""
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def derive_customer_balance(customer_id, connection=None):  # noqa: C901
    """اشتقاق رصيد العميل من مستنداته المصدرية (بالعملة الأساسية).

    هذه الدالة هي **مرجع واحد** للرصيد: كل مكان يحتاج رصيد عميل
    (المستمعات، خدمة الدفع، فاحص الأرصدة، شاشات العملاء) يجب أن يستدعيها
    أو `recompute_customer_balance` — لاصيغ بديلة.

    Args:
        customer_id: معرّف العميل.
        connection: اتصال SQLAlchemy اختياري (مطلوب داخل المستمعات التي
            تعمل أثناء الـ flush حتى لا تُطلق استعلامات ORM جديدة).

    Returns:
        Decimal: الرصيد بعملة الأساس.
    """
    from sqlalchemy import select

    from extensions import db

    if connection is None:
        connection = db.session.connection()

    # ---- 1) الرصيد الافتتاحي (F10) -------------------------------------
    cust_row = connection.execute(
        select(
            Customer.__table__.c.opening_balance,
            Customer.__table__.c.opening_balance_rate,
        ).where(Customer.__table__.c.id == customer_id)
    ).first()

    total = Decimal('0')
    if cust_row is not None:
        total += _dec(cust_row.opening_balance) * _dec(cust_row.opening_balance_rate, '1')

    # ---- 2) الفواتير (confirmed + active) ------------------------------
    from models.sale import Sale

    sale_rows = connection.execute(
        select(Sale.__table__.c.amount_base, Sale.__table__.c.paid_amount_base).where(
            Sale.__table__.c.customer_id == customer_id,
            Sale.__table__.c.status == 'confirmed',
            Sale.__table__.c.is_active.is_(True),
        )
    ).fetchall()
    for row in sale_rows:
        total += _dec(row.amount_base) - _dec(row.paid_amount_base)

    # ---- 3) المرتجعات المعتمدة (دائن للعميل) ---------------------------
    from models.product_return import ProductReturn

    return_rows = connection.execute(
        select(
            ProductReturn.__table__.c.refund_amount,
            ProductReturn.__table__.c.exchange_rate,
        ).where(
            ProductReturn.__table__.c.customer_id == customer_id,
            ProductReturn.__table__.c.status == 'approved',
        )
    ).fetchall()
    for row in return_rows:
        total -= _dec(row.refund_amount) * _dec(row.exchange_rate, '1')

    # ---- 4) استردادات/سحوبات العميل غير المرتبطة بفاتورة ---------------
    # (سند صرف direction='outgoing' بدون sale_id: يردّ للعميل مبلغًا نقديًا
    #  فينقص الذمم المدينة — F11)
    from models.payment import Payment

    refund_rows = connection.execute(
        select(Payment.__table__.c.amount_base).where(
            Payment.__table__.c.customer_id == customer_id,
            Payment.__table__.c.direction == 'outgoing',
            Payment.__table__.c.sale_id.is_(None),
            Payment.__table__.c.payment_confirmed.is_(True),
        )
    ).fetchall()
    for row in refund_rows:
        total -= _dec(row.amount_base)

    # ---- 5) تعديلات الشيكات Legacy (شيكات وارد بلا سند/فاتورة) ---------
    # الشيك المرتد يزيد الرصيد، والملغى/المؤرشف ينقصه (سلوك models/cheque.py
    # التاريخي). الشيكات المرتبطة بسند/فاتورة يتأثر أثرها بحالة الفاتورة
    # نفسها فلا تُحتسب هنا (وإلا احتُسبت مرتين).
    from models.cheque import Cheque

    cheque_rows = connection.execute(
        select(Cheque.__table__.c.amount_base, Cheque.__table__.c.status,
               Cheque.__table__.c.is_active).where(
            Cheque.__table__.c.customer_id == customer_id,
            Cheque.__table__.c.receipt_id.is_(None),
            Cheque.__table__.c.payment_id.is_(None),
            Cheque.__table__.c.sale_id.is_(None),
        )
    ).fetchall()
    for row in cheque_rows:
        amount = _dec(row.amount_base)
        status = row.status
        if status == 'bounced':
            total += amount
        elif status == 'cancelled':
            total -= amount
        elif not row.is_active and status in ('pending', 'deposited', 'under_collection'):
            total -= amount

    # ---- 6) سندات قبض غير مرتبطة بفاتورة (Legacy) -------------------------
    # سند قبض بلا فاتورة: لم يُخصم من فاتورة، فإذا كان مؤكَّداً فقد دفع
    # العميل مقدماً (ينقص رصيده) وإذا رُفض فعادت إليه (يزيد رصيده).
    # بدون هذا البند كان models/payment.py يكتب customer.balance يدوياً،
    # وهو آخر كاتب تزايدي للرصيد.
    from models.payment import Receipt

    receipt_rows = connection.execute(
        select(Receipt.__table__.c.amount_base,
               Receipt.__table__.c.payment_confirmed,
               Receipt.__table__.c.rejection_reason).where(
            Receipt.__table__.c.customer_id == customer_id,
            Receipt.__table__.c.sale_id.is_(None),
            Receipt.__table__.c.purchase_id.is_(None),
        )
    ).fetchall()
    for row in receipt_rows:
        amount = _dec(row.amount_base)
        if row.rejection_reason:
            # مرفوض: لم يُخصم فيقبل، فعادت القيمة للعميل.
            total += amount
        elif row.payment_confirmed:
            # مؤكد بلا فاتورة: دفع مقدماً.
            total -= amount

    # ---- 7) المشاطرات المنفذة (Bad Debt Write-Offs) -------------------------
    # قيد المشاطرة (Dr Bad Debt / Cr AR Control) ينقص رصيد العميل في العملة
    # الأساسية — يساوي المبلغ المنفّذ (posted) فقط، لا المسودات.
    from models.write_off import WriteOff

    woff_rows = connection.execute(
        select(WriteOff.__table__.c.amount_base).where(
            WriteOff.__table__.c.customer_id == customer_id,
            WriteOff.__table__.c.status == 'posted',
        )
    ).fetchall()
    for row in woff_rows:
        total -= _dec(row.amount_base)

    return total.quantize(MONEY_Q, rounding=ROUND_HALF_UP)


def _sync_session_balance(customer_id, value):
    """مزامنة ذاكرة هوية الجلسة (identity map) مع القيمة المكتوبة في القاعدة.

    expire_on_commit=False (extensions.py) يعني أن قيمة Customer.balance
    في الذاكرة لا تُحدَّث تلقائيًا بعد الكتابة بـ Core UPDATE — فتقرأ
    الواجهة قيمة قديمة. هنا نضبط القيمة كأنها قُرئت من القاعدة (بلا dirty
    flag) لأن الكتابة الفعلية تتم عبر UPDATE على مستوى Core.
    """
    try:
        from sqlalchemy.orm.attributes import set_committed_value
        from sqlalchemy.orm.util import identity_key

        from extensions import db

        session = db.session()
        key = identity_key(Customer, customer_id)
        instance = session.identity_map.get(key)
        if instance is not None:
            set_committed_value(instance, 'balance', value)
    except Exception:
        # لا نُفشل العملية بسبب مزامنة الذاكرة فقط
        pass


def recompute_customer_balance(customer_id, connection=None):
    """الكاتب الوحيد لـ Customer.balance — يحسب ويكتب.

    يُستدعى من مستمعات النماذج (بعد insert/update) ومن خدمات الدفع
    والصرف. معامل `connection` يسمح بالاستدعاء أثناء الـ flush.
    """
    from extensions import db

    if customer_id is None:
        return Decimal('0')

    value = derive_customer_balance(customer_id, connection=connection)
    conn = connection if connection is not None else db.session.connection()
    conn.execute(
        Customer.__table__.update().where(Customer.__table__.c.id == customer_id).values(
            balance=value,
            updated_at=datetime.now(timezone.utc),
        )
    )
    _sync_session_balance(customer_id, value)
    return value


class Customer(TenantScopedMixin, db.Model):
    __tablename__ = 'customers'

    __table_args__ = (
        db.Index('idx_customer_active_type', 'is_active', 'customer_type'),
        db.Index('idx_customer_balance', 'balance'),
        db.CheckConstraint('payment_terms_days >= 0',
                           name='ck_customer_payment_terms_non_negative'),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=True, index=True)
    name = db.Column(db.String(200), nullable=False, index=True)
    name_ar = db.Column(db.String(200))

    customer_type = db.Column(db.String(20), nullable=False, default='regular', index=True)

    customer_classification = db.Column(db.String(20), default='regular', index=True)

    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    address = db.Column(db.Text)
    tax_number = db.Column(db.String(50))

    preferred_currency = db.Column(db.String(3), default='ILS')

    # شروط الدفع المتفق عليها (بالأيام) — تُستخدم لاشتقاق تاريخ استحقاق
    # الفاتورة (services/due_date_service.py). 0 = استحقاق فوري.
    payment_terms_days = db.Column(db.Integer, default=0, nullable=False)

    credit_limit = db.Column(db.Numeric(15, 3), default=0)
    total_purchases = db.Column(db.Numeric(15, 3), default=0)

    # Customer balance (receivables)
    balance = db.Column(db.Numeric(15, 3), default=0, nullable=False)

    # الرصيد الافتتاحي (F10) — يُدخل عند ترحيل عميل له رصيد سابق.
    # opening_balance_rc = opening_balance × opening_balance_rate (عملة الأساس)
    opening_balance = db.Column(db.Numeric(15, 3), default=0, nullable=False)
    opening_balance_currency = db.Column(db.String(3), default='ILS', nullable=False)
    opening_balance_rate = db.Column(db.Numeric(15, 6), default=1, nullable=False)
    opening_balance_date = db.Column(db.Date, nullable=True)

    notes = db.Column(db.Text)

    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    sales = db.relationship('Sale', back_populates='customer', lazy='dynamic')
    receipts = db.relationship('Receipt', back_populates='customer', lazy='dynamic')

    def __repr__(self):
        return f'<Customer {self.name}>'

    def get_balance(self):
        """رصيد العميل (عملة الأساس) — المصدر الوحيد: derive_customer_balance."""
        return derive_customer_balance(self.id)

    def get_balance_aed(self):
        """نفس get_balance (alias تاريخي) — كل الحسابات بعملة الأساس."""
        return self.get_balance()

    def get_opening_balance_base(self):
        """الرصيد الافتتاحي محوّلاً إلى عملة الأساس."""
        return (_dec(self.opening_balance) * _dec(self.opening_balance_rate, '1')).quantize(
            MONEY_Q, rounding=ROUND_HALF_UP)

    def get_display_name(self, lang='ar'):
        if lang == 'ar' and self.name_ar:
            return self.name_ar
        return self.name

    def get_type_display(self, lang='ar'):
        types = {
            'regular': {'ar': 'عادي', 'en': 'Regular'},
            'merchant': {'ar': 'تاجر', 'en': 'Merchant'},
            'partner': {'ar': 'شريك', 'en': 'Partner'},
        }
        return types.get(self.customer_type, {}).get(lang, self.customer_type)

    def get_classification_display(self, lang='ar'):
        classifications = {
            'vip': {'ar': 'VIP - عميل مميز', 'en': 'VIP'},
            'premium': {'ar': 'ممتاز', 'en': 'Premium'},
            'regular': {'ar': 'عادي', 'en': 'Regular'},
            'inactive': {'ar': 'غير نشط', 'en': 'Inactive'},
        }
        return classifications.get(self.customer_classification, {}).get(lang, self.customer_classification)

    def update_classification(self):
        from decimal import Decimal
        total = self.total_purchases or Decimal('0')

        if total >= Decimal('100000'):
            self.customer_classification = 'vip'
        elif total >= Decimal('50000'):
            self.customer_classification = 'premium'
        else:
            self.customer_classification = 'regular'

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'name_ar': self.name_ar,
            'customer_type': self.customer_type,
            'customer_classification': self.customer_classification,
            'phone': self.phone,
            'email': self.email,
            'balance': float(self.get_balance()),
            'balance_aed': float(self.get_balance_aed()),
            'total_purchases': float(self.total_purchases or 0),
            'is_active': self.is_active,
        }
