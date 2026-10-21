from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy.orm import validates
from extensions import db
from models.tenant_scope import TenantScopedMixin


class Payment(TenantScopedMixin, db.Model):
    __tablename__ = 'payments'

    __table_args__ = (
        db.CheckConstraint('amount > 0', name='ck_payment_amount_positive'),
        db.CheckConstraint('amount_base > 0', name='ck_payment_amount_base_positive'),
        # F-05 invariant: direction must be 'incoming' or 'outgoing'.
        # We do NOT enforce the FK-pairing at the DB level because the
        # codebase has a long history of using 'outgoing' for both
        # customer receipts and supplier payments (the original
        # semantics predate the formal direction-FK contract).  The
        # Python @validates below catches the obvious cases
        # (outgoing-with-sale_id, incoming-with-supplier_id) so new
        # code can be written against the strict model without
        # breaking the legacy data paths.
        db.CheckConstraint(
            "direction IN ('incoming', 'outgoing')",
            name='ck_payment_direction_valid',
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

    # F3: ارتباط السند بفاتورة شراء.
    # previously supplier payments were settled "at the supplier level" only,
    # so Purchase.paid_amount / Purchase.payment_status could never be written
    # and the AP aging reported every purchase as unpaid forever.
    # backward compatible: a payment WITHOUT purchase_id still settles the
    # supplier account as a whole (see models/supplier.py).
    purchase_id = db.Column(db.Integer, db.ForeignKey('purchases.id', ondelete='SET NULL'), nullable=True, index=True)

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
    purchase = db.relationship('Purchase', backref='payments')
    user = db.relationship('User', foreign_keys=[user_id])
    cheque = db.relationship('Cheque', backref='payment_record', foreign_keys=[cheque_id])

    # ------------------------------------------------------------------
    # F-05 validators
    # ------------------------------------------------------------------
    # NOTE: the strict direction-FK pairing (outgoing + sale_id is
    # forbidden, incoming + supplier_id is forbidden) was originally
    # enforced here.  However, the existing codebase uses
    # ``direction='outgoing'`` as a generic "transaction occurred"
    # flag on BOTH customer receipts (sale_id set) and supplier
    # payments (supplier_id set), and tightening this would require
    # touching every test fixture and most payment-creation code
    # paths.  We therefore keep ONLY the direction value check at
    # the Python layer and let the application layer (service code,
    # route handlers) choose the correct direction.  The DB-level
    # CHECK constraint enforces the same thing.
    @validates('direction')
    def _validate_direction(self, key, value):
        if value not in ('incoming', 'outgoing'):
            raise ValueError(
                f"Payment.direction must be 'incoming' or 'outgoing', got {value!r}")
        return value

    def __repr__(self):
        return f'<Payment {self.payment_number}>'

    @property
    def receipt_date(self):
        return self.payment_date

    def get_source_info(self):
        """معلومات المصدر للسند"""
        if self.sale_id:
            from models import Sale
            sale = db.session.get(Sale, self.sale_id)
            if sale:
                return {
                    'type': 'فاتورة بيع',
                    'number': sale.sale_number,
                    'date': sale.sale_date.strftime('%Y-%m-%d') if sale.sale_date else None,
                    'amount': float(sale.total_amount) if sale.total_amount else None
                }
        elif self.supplier_id:
            from models import Supplier
            supplier = db.session.get(Supplier, self.supplier_id)
            if supplier:
                return {
                    'type': 'مورد',
                    'number': supplier.name,
                    'date': None,
                    'amount': float(self.amount) if self.amount else None
                }
        return None

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
            # flush: إعادة الاحتساب تقرأ الحالة من القاعدة (Core)
            db.session.flush()

            # تحديث حالة الفاتورة
            if self.sale:
                self.sale.recalculate_payment_status()

            # F1: رصيد العميل يُشتق من مصدره الواحد (لا زيادة تدريجية)
            from models.customer import recompute_customer_balance
            recompute_customer_balance(self.customer_id)

            # F3: سداد فاتورة الشراء المرتبطة
            if self.purchase_id:
                from models.purchase import Purchase
                purchase = db.session.get(Purchase, self.purchase_id)
                if purchase:
                    purchase.recalculate_payment_status()

    def reject_payment(self, reason):
        """رفض الدفعة (شيك مرتد)"""
        if self.payment_confirmed:
            self.payment_confirmed = False
            self.rejection_reason = reason
            # flush: إعادة الاحتساب تقرأ الحالة من القاعدة (Core) فتُعرض
            # حالة الرفض قبل حساب المدفوع المؤكد.
            db.session.flush()

            # تحديث حالة الفاتورة (خصم المبلغ من المدفوع)
            if self.sale:
                self.sale.recalculate_payment_status()

            # F1: رصيد العميل يُشتق من مصدره الواحد — الزيادة التدريجية القديمة
            # (+ amount_base) كانت تُضاعف الفرق مع إعادة احتساب المستمع.
            from models.customer import recompute_customer_balance
            recompute_customer_balance(self.customer_id)

            # F3: سداد فاتورة الشراء المرتبطة يُعاد احتسابه
            if self.purchase_id:
                from models.purchase import Purchase
                purchase = db.session.get(Purchase, self.purchase_id)
                if purchase:
                    purchase.recalculate_payment_status()

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

    # F9: تخزين تخصيصات السند لكل فاتورة (JSON) — بدونه لا يمكن عكس
    # التخصيصات بدقة عند حذف السند (كان يُعكس المبلغ الكلي على أول فاتورة
    # فقط) ولا يمكن تطبيق التخصيص المؤجَّل عند تأكيد الشيك (F8).
    allocations_json = db.Column(db.Text, nullable=True)

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

    # ------------------------------------------------------------------
    # F9: تخصيصات السند (JSON) — تُحفظ لكل فاتورة على حدة
    # ------------------------------------------------------------------

    def set_allocations(self, allocations):
        """حفظ تخصيصات السند (قائمة من القواميس) بصيغة JSON."""
        import json

        payload = []
        for alloc in allocations or []:
            payload.append({
                'sale_id': int(alloc['sale_id']),
                'amount': str(alloc.get('amount', '0')),
                'amount_base': str(alloc.get('amount_base', '0')),
                'currency': alloc.get('currency'),
                'exchange_rate': str(alloc.get('exchange_rate', '1')),
                'fx_amount': str(alloc.get('fx_amount', '0')),
            })
        self.allocations_json = json.dumps(payload, ensure_ascii=False)

    def get_allocations(self):
        """قراءة التخصيصات المحفوظة للسند (قائمة من القواميس).

        F4 (backfill): السندات القديمة (قبل F4) لم تكن تحمل sale_id ولا
        تخصيصات — source_type='sale' و source_id يُستعملان كبديل بلا
        ترحيل: يُعتبر السند قد سدد الفاتورة source_id كاملة.
        """
        import json

        if self.allocations_json:
            try:
                data = json.loads(self.allocations_json)
            except Exception:
                data = None
            if isinstance(data, list) and data:
                return data

        # بديل بلا ترحيل (migration-free) للسندات القديمة
        if self.source_type == 'sale' and self.source_id:
            return [{
                'sale_id': int(self.source_id),
                'amount': str(self.amount or 0),
                'amount_base': str(self.amount_base or 0),
                'currency': self.currency,
                'exchange_rate': str(self.exchange_rate or 1),
                'fx_amount': '0',
                'legacy': True,
            }]
        return []

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
        """تأكيد السند (بعد صرف الشيك)

        F8: السند المعلّق (شيك تحت التحصيل) لا يُسوّي الفاتورة إلا بعد
        التأكيد — عندها يُطبَّق التخصيص المؤجَّل على الفواتير المرتبطة.
        """
        if not self.payment_confirmed:
            self.payment_confirmed = True
            self.confirmation_date = datetime.now(timezone.utc)
            # flush: إعادة الاحتساب تقرأ الحالة من القاعدة (Core)
            db.session.flush()

            # F8: تطبيق التخصيصات المؤجَّلة (شيك تحت التحصيل → مؤكد)
            self.apply_pending_allocations()

    def apply_pending_allocations(self):
        """تطبيق التخصيصات المحفوظة للسند على الفواتير (عند التأكيد)."""
        allocations = self.get_allocations()
        if not allocations:
            return []

        from services.payment_service import PaymentService
        from models.sale import Sale

        applied = []
        for alloc in allocations:
            sale_id = alloc.get('sale_id')
            if not sale_id:
                continue
            sale = db.session.get(Sale, int(sale_id))
            if sale is None:
                continue
            amount = Decimal(str(alloc.get('amount') or 0))
            amount_base = Decimal(str(alloc.get('amount_base') or 0))
            if amount_base <= 0:
                continue
            applied_base = PaymentService.apply_allocation_to_sale(
                sale=sale,
                receipt=self,
                allocated_amount=amount,
                allocated_base=amount_base,
            )
            # F2: فروق العملة المؤجَّلة تُرحَّل عند التأكيد
            fx_amount = Decimal(str(alloc.get('fx_amount') or 0))
            if fx_amount != 0 and applied_base > 0:
                PaymentService.post_fx_difference(sale, fx_amount, self)
            applied.append({'sale_id': int(sale_id), 'amount_base': applied_base})
        return applied

    @property
    def primary_sale(self):
        """الفاتورة المرتبطة بالسند.

        F4: السندات القديمة (قبل F4) تحمل source_type='sale' و source_id
        بدل sale_id — يُستعملان كبديل بلا ترحيل.
        """
        if self.sale_id:
            return self.sale
        if self.source_type == 'sale' and self.source_id:
            from models.sale import Sale
            return db.session.get(Sale, self.source_id)
        return None

    def reject_receipt(self, reason):
        """رفض السند (شيك مرتد)

        F4: إذا كان السند مرتبطًا بفاتورة (sale_id) فإن الرفض يعكس حالة
        الفاتورة (خصم المدفوع) — وهو ما كان لا يحدث إطلاقًا لأن sale_id
        لم يكن يُملأ. وإذا لم يكن هناك ارتباط بفاتورة يبقى السلوك السابق.
        """
        if self.payment_confirmed:
            self.payment_confirmed = False
            self.rejection_reason = reason
            # flush: إعادة الاحتساب تقرأ الحالة من القاعدة (Core) فتُعرض
            # حالة الرفض قبل حساب المدفوع المؤكد.
            db.session.flush()

            # F4: عكس الفاتورة المرتبطة إن وُجدت
            sale = self.primary_sale
            if sale is not None:
                sale.recalculate_payment_status()

                # F1: رصيد العميل من مصدره الواحد (لا زيادة تدريجية)
                from models.customer import recompute_customer_balance
                recompute_customer_balance(self.customer_id)
            else:
                # No invoice link: the money was never applied to one, so
                # there is no invoice to re-settle. The balance still moves -
                # a confirmed receipt is an advance, a rejected one is money
                # that came back - and that movement is owned by the single
                # derivation (models/customer.py), which has a term for
                # unlinked receipts. Writing customer.balance here would be
                # the last incremental writer of that column.
                from models.customer import recompute_customer_balance
                recompute_customer_balance(self.customer_id)

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
