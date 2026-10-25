from datetime import datetime, date, timezone
from decimal import Decimal, ROUND_HALF_UP
from extensions import db
from models.tenant_scope import TenantScopedMixin


def _parse_allocations(raw):
    """قراءة تخصيصات سند القبض (JSON) — تُرجع قائمة فارغة عند أي خطأ."""
    if not raw:
        return []
    try:
        import json
        data = json.loads(raw)
    except Exception:
        return []
    return data if isinstance(data, list) else []


def compute_sale_returns_base(sale_id, connection=None):
    """قيمة المرتجعات المعتمدة للفاتورة (بالعملة الأساسية).

    المرتجع المعتمد يُلغي قيمة الفاتورة (دائن للعميل) — فيجب أن يُخصم
    من رصيد الفاتورة وإلا ظهرت الفاتورة مستحقة بعد إرجاعها.
    """
    from sqlalchemy import select

    from models.product_return import ProductReturn

    if connection is None:
        connection = db.session.connection()

    rows = connection.execute(
        select(
            ProductReturn.__table__.c.refund_amount,
            ProductReturn.__table__.c.exchange_rate,
        ).where(
            ProductReturn.__table__.c.sale_id == sale_id,
            ProductReturn.__table__.c.status == 'approved',
        )
    ).fetchall()

    total = Decimal('0')
    for row in rows:
        rate = Decimal(str(row.exchange_rate or 1))
        total += Decimal(str(row.refund_amount or 0)) * rate
    return total


def compute_sale_paid_base(sale_id, connection=None):
    """المسدّد المؤكد للفاتورة بعملة الأساس (Core — آمن أثناء الـ flush).

    = Σ سندات الصرف المؤكدة − استردادات المرتجع
      + Σ تخصيصات سندات القبض المؤكدة (بعملة الأساس)
    """
    from sqlalchemy import select

    from models.payment import Payment, Receipt

    if connection is None:
        connection = db.session.connection()

    total = Decimal('0')

    payment_rows = connection.execute(
        select(
            Payment.__table__.c.amount_base,
            Payment.__table__.c.payment_confirmed,
            Payment.__table__.c.payment_type,
        ).where(Payment.__table__.c.sale_id == sale_id)
    ).fetchall()
    for row in payment_rows:
        if row.payment_confirmed is False:
            continue
        amount = Decimal(str(row.amount_base or 0))
        if (row.payment_type or '') == 'refund':
            total -= amount
        else:
            total += amount

    receipt_rows = connection.execute(
        select(
            Receipt.__table__.c.amount_base,
            Receipt.__table__.c.payment_confirmed,
            Receipt.__table__.c.allocations_json,
        ).where(Receipt.__table__.c.sale_id == sale_id)
    ).fetchall()
    for row in receipt_rows:
        if row.payment_confirmed is False:
            continue
        allocations = _parse_allocations(row.allocations_json)
        if allocations:
            for alloc in allocations:
                try:
                    if int(alloc.get('sale_id')) != int(sale_id):
                        continue
                except (TypeError, ValueError):
                    continue
                total += Decimal(str(alloc.get('amount_base') or 0))
        else:
            # سجل قديم بلا تخصيصات محفوظة: السند كاملاً كان يسدد الفاتورة
            total += Decimal(str(row.amount_base or 0))

    return total


def recompute_sale_settlement(sale_id, connection=None):
    """F1/F2: إعادة احتساب تسوية الفاتورة (مدفوع/رصيد/حالة) عبر Core.

    آمن للاستدعاء أثناء الـ flush (المستمعات) لأنه لا يستعمل ORM.
    """
    from sqlalchemy import select

    if connection is None:
        connection = db.session.connection()

    row = connection.execute(
        select(
            Sale.__table__.c.amount_base,
            Sale.__table__.c.exchange_rate,
            Sale.__table__.c.currency,
        ).where(Sale.__table__.c.id == sale_id)
    ).first()
    if row is None:
        return None

    paid_base = compute_sale_paid_base(sale_id, connection=connection).quantize(
        Decimal('0.001'), rounding=ROUND_HALF_UP)
    returns_base = compute_sale_returns_base(sale_id, connection=connection).quantize(
        Decimal('0.001'), rounding=ROUND_HALF_UP)
    amount_base = Decimal(str(row.amount_base or 0))
    # الرصيد المتبقي = قيمة الفاتورة − المدفوع المؤكد − المرتجعات المعتمدة
    balance_due = (amount_base - paid_base - returns_base).quantize(
        Decimal('0.001'), rounding=ROUND_HALF_UP)
    if balance_due < Decimal('0'):
        balance_due = Decimal('0')

    if balance_due <= Decimal('0.01'):
        payment_status = 'paid'
        balance_due = Decimal('0')
    elif paid_base > Decimal('0'):
        payment_status = 'partial'
    else:
        payment_status = 'unpaid'

    try:
        from services.currency_service import CurrencyService
        _base = CurrencyService.get_base_currency()
    except Exception:
        _base = 'ILS'
    rate = Decimal(str(row.exchange_rate or 1))
    if (row.currency or _base) == _base:
        paid_amount = paid_base
    else:
        paid_amount = (paid_base / rate).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)

    connection.execute(
        Sale.__table__.update().where(Sale.__table__.c.id == sale_id).values(
            paid_amount=paid_amount,
            paid_amount_base=paid_base,
            balance_due=balance_due,
            payment_status=payment_status,
        )
    )

    # مزامنة ذاكرة هوية الجلسة (expire_on_commit=False)
    try:
        from sqlalchemy.orm.attributes import set_committed_value
        from sqlalchemy.orm.util import identity_key

        # db is imported at module level. Re-importing it HERE would make it
        # a local name for the whole function, and the connection lookup
        # above (db.session.connection()) would raise UnboundLocalError.
        session = db.session()
        instance = session.identity_map.get(identity_key(Sale, sale_id))
        if instance is not None:
            set_committed_value(instance, 'paid_amount', paid_amount)
            set_committed_value(instance, 'paid_amount_base', paid_base)
            set_committed_value(instance, 'balance_due', balance_due)
            set_committed_value(instance, 'payment_status', payment_status)
    except Exception:
        pass

    return paid_base


class Sale(TenantScopedMixin, db.Model):
    __tablename__ = 'sales'

    __table_args__ = (
        db.Index('idx_sale_customer_date', 'customer_id', 'sale_date'),
        db.Index('idx_sale_status_date', 'status', 'sale_date'),
        db.Index('idx_sale_payment_status', 'payment_status', 'customer_id'),
        db.CheckConstraint('total_amount >= 0', name='ck_sale_total_non_negative'),
        db.CheckConstraint('paid_amount_base >= 0', name='ck_sale_paid_non_negative'),
        db.CheckConstraint('balance_due >= 0', name='ck_sale_balance_non_negative'),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=True, index=True)
    sale_number = db.Column(db.String(50), unique=True, nullable=False, index=True)

    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id', ondelete='SET NULL'), nullable=False, index=True)
    seller_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=False)
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouses.id', ondelete='SET NULL'), nullable=True, index=True)
    shipment_id = db.Column(db.Integer, db.ForeignKey('shipments.id', ondelete='SET NULL'), nullable=True, index=True)

    sale_date = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    # تاريخ استحقاق الذمم المدينة — يُشتق من شروط دفع العميل أو يُحدَّد
    # صراحةً (services/due_date_service.py). بلا تاريخ استحقاق تُعامل
    # الفاتورة كأنها مستحقّة في تاريخها.
    due_date = db.Column(db.Date, nullable=True, index=True)

    subtotal = db.Column(db.Numeric(15, 3), default=0)
    discount_amount = db.Column(db.Numeric(15, 3), default=0)
    shipping_cost = db.Column(db.Numeric(15, 3), default=0)
    tax_rate = db.Column(db.Numeric(5, 2), default=0)
    tax_amount = db.Column(db.Numeric(15, 3), default=0)
    total_amount = db.Column(db.Numeric(15, 3), nullable=False)

    paid_amount = db.Column(db.Numeric(15, 3), default=0)
    balance_due = db.Column(db.Numeric(15, 3), default=0)

    currency = db.Column(db.String(3), default='ILS', nullable=False)
    exchange_rate = db.Column(db.Numeric(15, 6), default=1)
    amount_base = db.Column(db.Numeric(15, 3), nullable=False)
    paid_amount_base = db.Column(db.Numeric(15, 3), default=0)

    payment_status = db.Column(db.String(20), default='unpaid', index=True)
    status = db.Column(db.String(20), default='confirmed', index=True)

    # Active status for consistency with other models
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    notes = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    tenant = db.relationship('Tenant', foreign_keys=[tenant_id])
    customer = db.relationship('Customer', back_populates='sales')
    seller = db.relationship('User', back_populates='sales', foreign_keys=[seller_id])
    warehouse = db.relationship('Warehouse', foreign_keys=[warehouse_id])
    shipment = db.relationship('Shipment', foreign_keys=[shipment_id])
    lines = db.relationship('SaleLine', back_populates='sale', lazy='joined', cascade='all, delete-orphan')
    payments = db.relationship('Payment', back_populates='sale', lazy='dynamic')

    def __repr__(self):
        return f'<Sale {self.sale_number}>'

    @property
    def effective_due_date(self):
        """تاريخ الاستحقاق المعتمد — تاريخ الفاتورة إن لم يُحدَّد استحقاق."""
        from services.due_date_service import effective_due_date
        return effective_due_date(self.due_date, self.sale_date)

    @property
    def days_overdue(self):
        """أيام التأخير عن تاريخ الاستحقاق (0 = لم يتأخر بعد).

        المرجع هو تاريخ اليوم المحلي — نفس مرجع تحليل الأعمار
        (services/aging_analysis_service.py) ونفس مرجع دفتر الأستاذ،
        فتبقى الشرائح متطابقة في الشاشة وفي التقرير.
        """
        from services.due_date_service import overdue_days
        return overdue_days(self.effective_due_date, as_of=date.today())

    @property
    def overdue_bucket(self):
        """شريحة التأخير التي تقع فيها الفاتورة."""
        from services.due_date_service import bucket_for_overdue
        return bucket_for_overdue(self.days_overdue)

    def calculate_totals(self):
        """
        Calculate all financial totals with proper decimal precision
        Ensures accurate financial calculations with rounding
        """
        # Calculate subtotal from all lines - ensure Decimal type
        self.subtotal = sum((Decimal(str(line.line_total)) for line in self.lines), Decimal('0'))

        # Ensure all amounts are Decimal
        discount = Decimal(str(self.discount_amount)) if self.discount_amount else Decimal('0')
        shipping = Decimal(str(self.shipping_cost)) if self.shipping_cost else Decimal('0')
        tax_rate_decimal = Decimal(str(self.tax_rate)) if self.tax_rate else Decimal('0')
        exchange_rate_decimal = Decimal(str(self.exchange_rate)) if self.exchange_rate else Decimal('1')

        # Calculate taxable amount
        taxable_amount = self.subtotal - discount + shipping

        # Calculate tax with proper rounding (2 decimal places)
        self.tax_amount = (taxable_amount * (tax_rate_decimal / Decimal('100'))).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )

        # Calculate total amount with proper rounding
        self.total_amount = (taxable_amount + self.tax_amount).quantize(
            Decimal('0.001'), rounding=ROUND_HALF_UP
        )

        # Calculate amount in base currency (dynamic per tenant)
        try:
            from services.currency_service import CurrencyService
            _base = CurrencyService.get_base_currency()
        except Exception:
            _base = 'ILS'
        if (self.currency or _base) == _base:
            self.amount_base = self.total_amount
        else:
            self.amount_base = (self.total_amount * exchange_rate_decimal).quantize(
                Decimal('0.001'), rounding=ROUND_HALF_UP
            )

        # F2: paid_amount_base هو المرجع (يعملة الأساس) لأنه ناتج التخصيصات
        # بسعر السند الفعلي — لا يجوز إعادة اشتقاقه من paid_amount × سعر
        # الفاتورة (كان ذلك يمحو فرق العملة ويسبّب كسوراً من 0.001).
        paid_base = Decimal(str(self.paid_amount_base)) if self.paid_amount_base is not None else Decimal('0')
        if (self.currency or _base) == _base:
            self.paid_amount = paid_base
        else:
            self.paid_amount = (paid_base / exchange_rate_decimal).quantize(
                Decimal('0.001'), rounding=ROUND_HALF_UP
            )

        # Calculate balance consistently (always in base).
        # الفاتورة المدفوعة بالكامل قد يكون مدفوعها أكبر من قيمتها (دفعة
        # زائدة) → الرصيد صفر (لا سالب: قيد ck_sale_balance_non_negative)
        # والفرق يظهر كرصيد دائن للعميل في customer.balance.
        # المرتجعات المعتمدة تُخصم (تُلغي قيمة الفاتورة).
        returns_base = Decimal('0')
        if self.id:
            returns_base = compute_sale_returns_base(self.id)
        if (self.currency or _base) == _base:
            self.balance_due = (self.total_amount - paid_base - returns_base).quantize(
                Decimal('0.001'), rounding=ROUND_HALF_UP
            )
        else:
            self.balance_due = (self.amount_base - paid_base - returns_base).quantize(
                Decimal('0.001'), rounding=ROUND_HALF_UP
            )
        if self.balance_due < Decimal('0'):
            self.balance_due = Decimal('0')

        # Update payment status
        if self.balance_due <= Decimal('0'):
            self.payment_status = 'paid'
        elif paid_base > Decimal('0'):
            self.payment_status = 'partial'
        else:
            self.payment_status = 'unpaid'

    def recalculate_payment_status(self, connection=None):  # noqa: C901
        """
        Recalculate payment status based on CONFIRMED settlements only
        المعالجة المحاسبية الدقيقة: الشيكات المعلقة لا تُحسب!

        F2/F8: المدفوع يُحسب من المسدّدات المؤكدة:
            * سندات الصرف المرتبطة (Payment) المؤكدة (مخصومة استردادات المرتجع)
            * تخصيصات سندات القبض المرتبطة (Receipt) المؤكدة
        ويمر عبر Core (connection) ليعمل داخل الـ flush بأمان.
        """
        if connection is None:
            connection = db.session.connection()

        total_confirmed_paid_aed = compute_sale_paid_base(self.id, connection=connection)

        # Update paid amounts (confirmed only)
        self.paid_amount_base = total_confirmed_paid_aed
        try:
            ex = Decimal(str(self.exchange_rate)) if self.exchange_rate else Decimal('1')
            try:
                from services.currency_service import CurrencyService
                _base2 = CurrencyService.get_base_currency()
            except Exception:
                _base2 = 'ILS'
            if (self.currency or _base2) == _base2:
                self.paid_amount = total_confirmed_paid_aed
            else:
                self.paid_amount = (total_confirmed_paid_aed / ex).quantize(
                    Decimal('0.001'), rounding=ROUND_HALF_UP
                )
        except Exception:
            self.paid_amount = self.paid_amount or Decimal('0')

        # Calculate balance consistently (never negative — قيد قاعدة البيانات)
        # المرتجعات المعتمدة تُخصم (تُلغي قيمة الفاتورة).
        total_aed = Decimal(str(self.amount_base))
        returns_base = compute_sale_returns_base(self.id, connection=connection)
        self.balance_due = (total_aed - total_confirmed_paid_aed - returns_base).quantize(
            Decimal('0.001'), rounding=ROUND_HALF_UP)
        if self.balance_due < Decimal('0'):
            self.balance_due = Decimal('0')

        # Update payment status
        # ملاحظة: الشيكات المعلقة لا تُغير حالة الدفع إلى "مدفوع"
        if self.balance_due <= Decimal('0.01'):
            self.payment_status = 'paid'
            self.balance_due = Decimal('0')
        elif total_confirmed_paid_aed > Decimal('0'):
            self.payment_status = 'partial'
        else:
            # حتى لو كان هناك شيكات معلقة، الحالة تبقى "غير مدفوع"
            self.payment_status = 'unpaid'

    @property
    def pending_cheques_amount(self):
        """مبلغ الشيكات المعلقة (غير المؤكدة)"""
        try:
            total = Decimal('0')
            for p in self.payments:
                # التحقق من وجود payment_confirmed
                is_confirmed = getattr(p, 'payment_confirmed', True)
                if not is_confirmed and p.payment_method == 'cheque':
                    total += Decimal(str(p.amount_base))
            return total
        except Exception:
            return Decimal('0')

    @property
    def confirmed_payments_amount(self):
        """المدفوع الفعلي المؤكد فقط"""
        return self.paid_amount if self.paid_amount else Decimal('0')

    def get_profit(self):
        """Calculate total profit with proper decimal precision"""
        if not self.lines:
            return Decimal('0')
        return sum((Decimal(str(line.get_profit())) for line in self.lines), Decimal('0'))

    def to_dict(self, include_lines=False, include_cost=False):
        data = {
            'id': self.id,
            'sale_number': self.sale_number,
            'customer': self.customer.name if self.customer else None,
            'seller': self.seller.username if self.seller else None,
            'sale_date': self.sale_date.isoformat(),
            'due_date': self.due_date.isoformat() if self.due_date else None,
            'total_amount': float(self.total_amount),
            'paid_amount': float(self.paid_amount),
            'balance_due': float(self.balance_due),
            'currency': self.currency,
            'payment_status': self.payment_status,
            'status': self.status,
        }

        if include_lines:
            data['lines'] = [line.to_dict(include_cost=include_cost) for line in self.lines]

        if include_cost:
            data['profit'] = float(self.get_profit())

        return data


class SaleLine(TenantScopedMixin, db.Model):
    __tablename__ = 'sale_lines'

    __table_args__ = (
        db.CheckConstraint('quantity > 0', name='ck_saleline_qty_positive'),
        db.CheckConstraint('unit_price >= 0', name='ck_saleline_price_non_negative'),
        db.CheckConstraint('line_total >= 0', name='ck_saleline_total_non_negative'),
        db.CheckConstraint('discount_percent >= 0 AND discount_percent <= 100', name='ck_saleline_discount_range'),
        db.Index('idx_saleline_sale_product', 'sale_id', 'product_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=True, index=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)

    quantity = db.Column(db.Numeric(15, 3), nullable=False)
    unit_price = db.Column(db.Numeric(15, 3), nullable=False)
    discount_percent = db.Column(db.Numeric(5, 2), default=0)
    line_total = db.Column(db.Numeric(15, 3), nullable=False)

    cost_price = db.Column(db.Numeric(15, 3), default=0)

    notes = db.Column(db.String(255))

    sale = db.relationship('Sale', back_populates='lines')
    product = db.relationship('Product', back_populates='sale_lines')

    def __repr__(self):
        return f'<SaleLine {self.product_id} x {self.quantity}>'

    def calculate_line_total(self):
        """Calculate line total with proper decimal precision and rounding"""
        qty = Decimal(str(self.quantity)) if self.quantity else Decimal('0')
        price = Decimal(str(self.unit_price)) if self.unit_price else Decimal('0')
        discount = Decimal(str(self.discount_percent)) if self.discount_percent else Decimal('0')

        discount_multiplier = (Decimal('100') - discount) / Decimal('100')
        self.line_total = (qty * price * discount_multiplier).quantize(
            Decimal('0.001'), rounding=ROUND_HALF_UP
        )

    def get_profit(self):
        """Calculate line profit with proper decimal precision"""
        unit_price = Decimal(str(self.unit_price)) if self.unit_price else Decimal('0')
        cost_price = Decimal(str(self.cost_price)) if self.cost_price else Decimal('0')
        qty = Decimal(str(self.quantity)) if self.quantity else Decimal('0')
        discount = Decimal(str(self.discount_percent)) if self.discount_percent else Decimal('0')

        discount_multiplier = (Decimal('100') - discount) / Decimal('100')
        profit = (unit_price - cost_price) * qty * discount_multiplier
        return profit.quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)

    def to_dict(self, include_cost=False):
        data = {
            'id': self.id,
            'product': self.product.name if self.product else None,
            'quantity': float(self.quantity),
            'unit_price': float(self.unit_price),
            'discount_percent': float(self.discount_percent),
            'line_total': float(self.line_total),
        }

        if include_cost:
            data['cost_price'] = float(self.cost_price)
            data['profit'] = float(self.get_profit())

        return data
