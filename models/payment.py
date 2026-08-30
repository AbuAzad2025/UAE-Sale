from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy.orm import validates
from sqlalchemy.exc import IntegrityError
from extensions import db
from models.tenant_scope import TenantScopedMixin


class Payment(TenantScopedMixin, db.Model):
    __tablename__ = 'payments'

    __table_args__ = (
        db.CheckConstraint('amount > 0', name='ck_payment_amount_positive'),
        db.CheckConstraint('amount_base > 0', name='ck_payment_amount_base_positive'),
        # F-05 invariant: outgoing payments MUST NOT link to a sale;
        # incoming payments MUST NOT link to a supplier.  We do NOT
        # require the corresponding FK to be set so that adjustments,
        # manual entries, and one-side-only audit rows remain legal.
        # The validator below enforces these rules at the Python
        # level; this CHECK is a defence-in-depth backstop.
        db.CheckConstraint(
            "(direction = 'incoming' AND supplier_id IS NULL) "
            "OR "
            "(direction = 'outgoing' AND sale_id IS NULL) "
            "OR "
            "direction NOT IN ('incoming', 'outgoing')",
            name='ck_payment_direction_fk',
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=True, index=True)
    payment_number = db.Column(db.String(50), unique=True, nullable=False, index=True)

    payment_type = db.Column(db.String(20), nullable=False, index=True)

    # اتجاه المدفوعات
    direction = db.Column(db.String(10), default='outgoing', index=True)  # incoming, outgoing

    sale_id = db.Column(db.Integer, db.ForeignKey('sales.id', ondelete='SET NULL'), nullable=True, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id', ondelete='SET NULL'), nullable=True, index=True)

    # معلومات المورد (لسندات الصرف)
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id', ondelete='SET NULL'), nullable=True, index=True)
    supplier_name = db.Column(db.String(200))

    amount = db.Column(db.Numeric(15, 3), nullable=False)
    currency = db.Column(db.String(3), default='AED', nullable=False)
    exchange_rate = db.Column(db.Numeric(15, 6), default=1)
    amount_base = db.Column(db.Numeric(15, 3), nullable=False)

    payment_method = db.Column(db.String(20), nullable=False)

    reference_number = db.Column(db.String(100))

    # معلومات الشيك (قديمة - للتوافق)
    cheque_number = db.Column(db.String(50))
    cheque_date = db.Column(db.Date)
    bank_name = db.Column(db.String(100))

    # ربط مع نموذج الشيك (جديد - للمحاسبة الدقيقة)
    cheque_id = db.Column(db.Integer, db.ForeignKey('cheques.id', use_alter=True), index=True)

    # حالة الدفعة - للشيكات فقط
    # confirmed: مؤكدة (الشيك صُرف)
    # pending: معلقة (الشيك لم يُصرف بعد)
    # rejected: مرفوضة (الشيك رُفض)
    payment_confirmed = db.Column(db.Boolean, default=True, index=True)  # True للنقد/بطاقة، False للشيكات المعلقة
    confirmation_date = db.Column(db.DateTime)  # تاريخ التأكيد
    rejection_reason = db.Column(db.String(500))  # سبب الرفض

    payment_date = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    notes = db.Column(db.Text)

    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    sale = db.relationship('Sale', back_populates='payments')
    customer = db.relationship('Customer')
    supplier = db.relationship('Supplier', foreign_keys=[supplier_id])
    user = db.relationship('User', foreign_keys=[user_id])
    cheque = db.relationship('Cheque', backref='payment_record', foreign_keys=[cheque_id])

    # ------------------------------------------------------------------
    # F-04 / F-05 validators: enforce direction-based FK invariants
    # ------------------------------------------------------------------

    @validates('direction')
    def _validate_direction(self, key, value):
        """Direction must be 'incoming' or 'outgoing'."""
        if value not in ('incoming', 'outgoing'):
            raise ValueError(
                f"Payment.direction must be 'incoming' or 'outgoing', got {value!r}")
        return value

    @validates('sale_id')
    def _validate_sale_id_for_direction(self, key, value):
        """sale_id is only valid for incoming payments."""
        if value is not None and getattr(self, 'direction', None) == 'outgoing':
            raise ValueError(
                "Payment.sale_id may only be set on incoming payments "
                "(outgoing payments must link to a supplier, not a sale).")
        return value

    @validates('supplier_id')
    def _validate_supplier_id_for_direction(self, key, value):
        """supplier_id is only valid for outgoing payments."""
        if value is not None and getattr(self, 'direction', None) == 'incoming':
            raise ValueError(
                "Payment.supplier_id may only be set on outgoing payments "
                "(incoming payments must link to a customer, not a supplier).")
        return value

    def __repr__(self):
        return f'<Payment {self.payment_number}>'

    def get_method_display(self, lang='ar'):
        methods = {
            'cash': {'ar': 'نقدي', 'en': 'Cash'},
            'card': {'ar': 'بطاقة', 'en': 'Card'},
            'bank_transfer': {'ar': 'تحويل بنكي', 'en': 'Bank Transfer'},
            'cheque': {'ar': 'شيك', 'en': 'Cheque'},
            'e_wallet': {'ar': 'محفظة إلكترونية', 'en': 'E-Wallet'},
        }
        return methods.get(self.payment_method, {}).get(lang, self.payment_method)

    def confirm_payment(self):
        """تأكيد الدفعة (بعد صرف الشيك)"""
        if not self.payment_confirmed:
            self.payment_confirmed = True
            self.confirmation_date = datetime.now(timezone.utc)

            # تحديث حالة الفاتورة
            if self.sale:
                self.sale.recalculate_payment_status()

    def reject_payment(self, reason):
        """رفض الدفعة (شيك مرتد)"""
        if self.payment_confirmed:
            self.payment_confirmed = False
            self.rejection_reason = reason

            # تحديث حالة الفاتورة (خصم المبلغ من المدفوع)
            if self.sale:
                self.sale.recalculate_payment_status()
                # تحديث رصيد العميل
                from decimal import Decimal
                amount_base = self.amount_base or Decimal('0')
                from models import Customer as _Cust
                customer = _Cust.query.get(self.sale.customer_id)
                if customer:
                    customer.balance = (customer.balance or Decimal('0')) + amount_base
                    customer.update_classification()

    @property
    def is_pending(self):
        """هل الدفعة معلقة (شيك لم يُصرف)"""
        return not self.payment_confirmed

    @property
    def status_ar(self):
        """حالة الدفعة بالعربي"""
        if self.payment_confirmed:
            return 'مؤكدة'
        else:
            return 'معلقة' if not self.rejection_reason else 'مرفوضة'

    @property
    def direction_ar(self):
        """اتجاه المدفوعة بالعربي"""
        directions = {
            'incoming': 'وارد',
            'outgoing': 'صادر'
        }
        return directions.get(self.direction, 'غير محدد')

    def to_dict(self):
        return {
            'id': self.id,
            'payment_number': self.payment_number,
            'payment_type': self.payment_type,
            'amount': float(self.amount),
            'currency': self.currency,
            'payment_method': self.payment_method,
            'payment_date': self.payment_date.isoformat(),
            'payment_confirmed': self.payment_confirmed,
            'status_ar': self.status_ar,
            'cheque_id': self.cheque_id,
        }


class Receipt(TenantScopedMixin, db.Model):
    __tablename__ = 'receipts'

    __table_args__ = (
        db.CheckConstraint('amount > 0', name='ck_receipt_amount_positive'),
        db.CheckConstraint('amount_base > 0', name='ck_receipt_amount_base_positive'),
        # F-01 invariant: a receipt links either to a sale OR to a
        # purchase, never both, never neither.  The polymorphic
        # source_type/source_id columns are kept for backward compat
        # (read-only on the Python side) but new code MUST use the
        # explicit FKs below.
        db.CheckConstraint(
            "(sale_id IS NOT NULL AND purchase_id IS NULL) "
            "OR "
            "(sale_id IS NULL AND purchase_id IS NOT NULL) "
            "OR "
            "(sale_id IS NULL AND purchase_id IS NULL)",
            name='ck_receipt_xor_parent',
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=True, index=True)
    receipt_number = db.Column(db.String(50), unique=True, nullable=False, index=True)

    # F-01: explicit FKs replace the polymorphic source_type/source_id.
    # sale_id for incoming customer payments, purchase_id for supplier
    # refunds / adjustments.  Exactly one is set (or neither for manual
    # adjustments, which the CHECK constraint above allows).
    sale_id = db.Column(
        db.Integer,
        db.ForeignKey('sales.id', ondelete='SET NULL'),
        nullable=True, index=True,
    )
    purchase_id = db.Column(
        db.Integer,
        db.ForeignKey('purchases.id', ondelete='SET NULL'),
        nullable=True, index=True,
    )

    # F-01: legacy polymorphic columns, kept read-only for backward
    # compatibility.  New code must use sale_id / purchase_id above.
    source_type = db.Column(db.String(20), default='sale', index=True)  # sale, manual, refund, etc.
    source_id = db.Column(db.Integer, index=True)  # ID of the source (sale_id, etc.)

    # اتجاه المدفوعات
    direction = db.Column(db.String(10), default='incoming', index=True)  # incoming, outgoing

    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False, index=True)

    amount = db.Column(db.Numeric(15, 3), nullable=False)
    currency = db.Column(db.String(3), default='AED', nullable=False)
    exchange_rate = db.Column(db.Numeric(15, 6), default=1)
    amount_base = db.Column(db.Numeric(15, 3), nullable=False)

    payment_method = db.Column(db.String(20), nullable=False)

    reference_number = db.Column(db.String(100))

    # معلومات الشيك (قديمة - للتوافق)
    cheque_number = db.Column(db.String(50))
    cheque_date = db.Column(db.Date)
    bank_name = db.Column(db.String(100))

    # ربط مع نموذج الشيك (جديد - للمحاسبة الدقيقة)
    cheque_id = db.Column(db.Integer, db.ForeignKey('cheques.id', use_alter=True), index=True)

    # حالة السند - للشيكات فقط
    payment_confirmed = db.Column(db.Boolean, default=True, index=True)
    confirmation_date = db.Column(db.DateTime)
    rejection_reason = db.Column(db.String(500))

    receipt_date = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    notes = db.Column(db.Text)

    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    customer = db.relationship('Customer', back_populates='receipts')
    user = db.relationship('User', foreign_keys=[user_id])
    cheque = db.relationship('Cheque', backref='receipt_record', foreign_keys=[cheque_id])
    sale = db.relationship('Sale', backref='receipts')
    purchase = db.relationship('Purchase', backref='receipts')

    # ------------------------------------------------------------------
    # F-01 / F-04 validators: enforce parent FK invariants
    # ------------------------------------------------------------------

    @validates('sale_id', 'purchase_id')
    def _validate_single_parent(self, key, value):
        """sale_id and purchase_id are mutually exclusive: at most one
        may be set on a given receipt.  Both may be NULL (manual /
        adjustment)."""
        other_key = 'purchase_id' if key == 'sale_id' else 'sale_id'
        other_value = getattr(self, other_key, None)
        if value is not None and other_value is not None:
            raise ValueError(
                f"Receipt.{key} and Receipt.{other_key} are mutually exclusive; "
                f"set one or neither, not both.")
        return value

    def __repr__(self):
        return f'<Receipt {self.receipt_number}>'

    def get_method_display(self, lang='ar'):
        methods = {
            'cash': {'ar': 'نقدي', 'en': 'Cash'},
            'card': {'ar': 'بطاقة', 'en': 'Card'},
            'bank_transfer': {'ar': 'تحويل بنكي', 'en': 'Bank Transfer'},
            'cheque': {'ar': 'شيك', 'en': 'Cheque'},
            'e_wallet': {'ar': 'محفظة إلكترونية', 'en': 'E-Wallet'},
        }
        return methods.get(self.payment_method, {}).get(lang, self.payment_method)

    def confirm_receipt(self):
        """تأكيد السند (بعد صرف الشيك)"""
        if not self.payment_confirmed:
            self.payment_confirmed = True
            self.confirmation_date = datetime.now(timezone.utc)

    def reject_receipt(self, reason):
        """رفض السند (شيك مرتد)"""
        if self.payment_confirmed:
            self.payment_confirmed = False
            self.rejection_reason = reason

            # تحديث حالة الفاتورة (خصم المبلغ من المدفوع)
            if self.sale:
                self.sale.recalculate_payment_status()
                # تحديث رصيد العميل
                from decimal import Decimal
                amount_base = self.amount_base or Decimal('0')
                from models import Customer as _Cust
                customer = _Cust.query.get(self.sale.customer_id)
                if customer:
                    customer.balance = (customer.balance or Decimal('0')) + amount_base
                    customer.update_classification()

    @property
    def is_pending(self):
        """هل السند معلق (شيك لم يُصرف)"""
        return not self.payment_confirmed

    @property
    def status_ar(self):
        """حالة السند بالعربي"""
        if self.payment_confirmed:
            return 'مؤكد'
        else:
            return 'معلق' if not self.rejection_reason else 'مرفوض'

    @property
    def source_type_ar(self):
        """نوع المصدر بالعربي"""
        source_types = {
            'sale': 'مبيعات',
            'manual': 'يدوي',
            'refund': 'استرداد',
            'adjustment': 'تسوية',
            'other': 'أخرى'
        }
        return source_types.get(self.source_type, 'غير محدد')

    @property
    def direction_ar(self):
        """اتجاه المدفوعة بالعربي"""
        directions = {
            'incoming': 'وارد',
            'outgoing': 'صادر'
        }
        return directions.get(self.direction, 'غير محدد')

    def get_source_info(self):
        """معلومات المصدر"""
        if self.source_type == 'sale' and self.source_id:
            from models import Sale
            sale = db.session.get(Sale, self.source_id)
            if sale:
                return {
                    'type': 'فاتورة بيع',
                    'number': sale.sale_number,
                    'date': sale.sale_date.strftime('%Y-%m-%d'),
                    'amount': float(sale.total_amount)
                }
        return None

    def to_dict(self):
        return {
            'id': self.id,
            'receipt_number': self.receipt_number,
            'customer': self.customer.name if self.customer else None,
            'amount': float(self.amount),
            'currency': self.currency,
            'payment_method': self.payment_method,
            'receipt_date': self.receipt_date.isoformat(),
            'payment_confirmed': self.payment_confirmed,
            'status_ar': self.status_ar,
            'cheque_id': self.cheque_id,
        }
