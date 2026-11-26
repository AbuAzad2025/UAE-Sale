"""
نموذج الشيكات - Cheque Model
إدارة شاملة للشيكات الواردة والصادرة
"""

from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from flask import current_app
from sqlalchemy.orm import validates

from extensions import db
from models.tenant_scope import TenantScopedMixin

from services.account_resolution import AccountResolver, AccountRole


def _resolve_account(role_value, tenant_id):
    """Resolve the configured account for this cheque's tenant."""
    return AccountResolver.resolve(AccountRole(role_value), tenant_id=tenant_id)


class Cheque(TenantScopedMixin, db.Model):
    """
    نموذج الشيكات - وارد وصادر
    """

    __tablename__ = "cheques"

    id = db.Column(db.Integer, primary_key=True)

    tenant_id = db.Column(
        db.Integer, db.ForeignKey("tenants.id"), nullable=True, index=True
    )

    cheque_number = db.Column(db.String(50), nullable=False, unique=True, index=True)
    cheque_bank_number = db.Column(db.String(50), nullable=False)  # رقم الشيك من البنك

    cheque_type = db.Column(
        db.String(20), nullable=False, index=True
    )  # incoming, outgoing

    bank_name = db.Column(db.String(200), nullable=False)
    bank_branch = db.Column(db.String(200))
    account_number = db.Column(db.String(100))

    amount = db.Column(db.Numeric(15, 2), nullable=False)
    currency = db.Column(db.String(10), default="ILS")
    exchange_rate = db.Column(
        db.Numeric(15, 6), default=Decimal("1.0")
    )  # سعر الصرف عند الإنشاء
    clearance_exchange_rate = db.Column(db.Numeric(15, 6))  # سعر الصرف عند الصرف الفعلي
    amount_base = db.Column(db.Numeric(15, 2))  # المبلغ بالدرهم عند الإنشاء
    actual_amount_base = db.Column(db.Numeric(15, 2))  # المبلغ الفعلي بالدرهم عند الصرف
    currency_gain_loss = db.Column(
        db.Numeric(15, 2), default=Decimal("0")
    )  # ربح/خسارة فرق العملة

    issue_date = db.Column(db.Date, nullable=False)  # تاريخ الإصدار
    due_date = db.Column(db.Date, nullable=False, index=True)  # تاريخ الاستحقاق
    deposit_date = db.Column(db.Date)  # تاريخ الإيداع في البنك
    clearance_date = db.Column(db.Date)  # تاريخ الصرف الفعلي (تأكيد البنك)
    cleared_date = db.Column(db.Date)  # تاريخ الصرف (alias for clearance_date)

    status = db.Column(db.String(20), default="pending", index=True)

    drawer_name = db.Column(db.String(200))  # اسم الساحب (للوارد)
    drawer_id_number = db.Column(db.String(50))  # رقم الهوية
    payee_name = db.Column(db.String(200))  # اسم المستفيد (للصادر)

    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), index=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"), index=True)
    sale_id = db.Column(db.Integer, db.ForeignKey("sales.id"), index=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey("purchases.id"), index=True)
    payment_id = db.Column(db.Integer, db.ForeignKey("payments.id"), index=True)
    receipt_id = db.Column(db.Integer, db.ForeignKey("receipts.id"), index=True)
    expense_id = db.Column(db.Integer, db.ForeignKey("expenses.id"), index=True)

    gl_journal_entry_id = db.Column(
        db.Integer, db.ForeignKey("gl_journal_entries.id"), index=True
    )
    gl_clearing_entry_id = db.Column(
        db.Integer, db.ForeignKey("gl_journal_entries.id"), index=True
    )
    gl_bounce_entry_id = db.Column(
        db.Integer, db.ForeignKey("gl_journal_entries.id"), index=True
    )

    notes = db.Column(db.Text)
    bounce_reason = db.Column(db.String(500))  # سبب الإرتداد

    days_until_due = db.Column(db.Integer)  # أيام متبقية للاستحقاق
    is_overdue = db.Column(db.Boolean, default=False, index=True)  # متأخر
    alert_sent = db.Column(db.Boolean, default=False)  # تم إرسال تنبيه

    is_active = db.Column(db.Boolean, default=True, index=True)
    archived_at = db.Column(db.DateTime)
    archive_reason = db.Column(db.String(500))

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    customer = db.relationship(
        "Customer", backref="cheques", foreign_keys=[customer_id]
    )
    supplier = db.relationship(
        "Supplier", backref="cheques", foreign_keys=[supplier_id]
    )
    sale = db.relationship("Sale", backref="cheques", foreign_keys=[sale_id])
    receipt = db.relationship("Receipt", backref="cheques", foreign_keys=[receipt_id])
    expense = db.relationship("Expense", backref="cheques", foreign_keys=[expense_id])
    user = db.relationship("User", foreign_keys=[user_id])

    _PARENT_FK_COLUMNS = (
        "sale_id",
        "purchase_id",
        "expense_id",
        "payment_id",
        "receipt_id",
    )

    @validates("amount")
    def _validate_amount_positive(self, key, value):
        if value is not None and Decimal(str(value)) <= 0:
            raise ValueError("مبلغ الشيك يجب أن يكون أكبر من صفر")
        return value

    @validates("sale_id", "purchase_id", "expense_id", "payment_id", "receipt_id")
    def _validate_single_parent_doc(self, key, value):
        """At most one of the parent-document FKs may be set on a
        single cheque.  All others must be NULL when this one is
        set.  The application layer (here) is the primary guard;
        the database has a CHECK constraint (see below) for
        defence-in-depth."""
        if value is None:
            return value
        others = [k for k in self._PARENT_FK_COLUMNS if k != key]
        for other in others:
            other_value = getattr(self, other, None)
            if other_value is not None:
                raise ValueError(
                    f"Cheque.{key} and Cheque.{other} are mutually exclusive "
                    f"parent-document references.  At most one may be set on "
                    f"a single cheque."
                )
        return value

    @validates("cheque_type")
    def _validate_cheque_type(self, key, value):
        """cheque_type must be 'incoming' or 'outgoing'."""
        if value not in ("incoming", "outgoing"):
            raise ValueError(
                f"Cheque.cheque_type must be 'incoming' or 'outgoing', got {value!r}"
            )
        return value

    __table_args__ = (
        db.CheckConstraint(
            "("
            "(CASE WHEN sale_id     IS NULL THEN 0 ELSE 1 END) + "
            "(CASE WHEN purchase_id IS NULL THEN 0 ELSE 1 END) + "
            "(CASE WHEN expense_id   IS NULL THEN 0 ELSE 1 END) + "
            "(CASE WHEN payment_id   IS NULL THEN 0 ELSE 1 END) + "
            "(CASE WHEN receipt_id   IS NULL THEN 0 ELSE 1 END)"
            ") <= 1",
            name="ck_cheque_single_parent_doc",
        ),
    )

    def __repr__(self):
        return f"<Cheque {self.cheque_number} - {self.cheque_type} - {self.status}>"

    def update_status_based_on_date(self):
        """تحديث الحالة والتحذيرات حسب التاريخ"""
        if self.status in ["cleared", "cancelled", "bounced"]:
            return

        today = datetime.now().date()

        self.days_until_due = (self.due_date - today).days

        if today > self.due_date:
            self.is_overdue = True
        else:
            self.is_overdue = False

    def calculate_amount_base(self):
        """حساب المبلغ بالدرهم"""
        amount = Decimal(str(self.amount))
        if self.exchange_rate is not None:
            rate = Decimal(str(self.exchange_rate))
            if rate <= 0:
                raise ValueError("Invalid exchange rate: must be positive")
            self.amount_base = (amount * rate).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        else:
            self.amount_base = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def receive_cheque(self, *, actor_id=None):
        """تسجيل استلام الشيك الوارد"""
        if self.cheque_type == "incoming" and not self.gl_journal_entry_id:
            from services.gl_service import GLService

            try:
                customer = self.customer
                credit_account = (
                    GLService.get_customer_credit_account(customer)
                    if self.customer_id
                    else AccountResolver.resolve(
                        AccountRole.AP_CONTROL
                        if self.supplier_id
                        else AccountRole.AR_CONTROL,
                        tenant_id=self.tenant_id,
                    )
                )
                partner_id = (
                    customer.id
                    if customer and customer.customer_type == "partner"
                    else None
                )
                lines = [
                    {
                        "account": _resolve_account("UNDER_COLLECTION", self.tenant_id),
                        "debit": self.amount_base,
                        "credit": 0,
                        "description": f"استلام شيك رقم {self.cheque_bank_number}",
                    },
                    {
                        "account": credit_account,
                        "debit": 0,
                        "credit": self.amount_base,
                        "description": f"استلام شيك من عميل - رقم {self.cheque_bank_number}",
                        "party_id": partner_id,
                    },
                ]

                entry = GLService.post_entry(
                    lines=lines,
                    description=f"استلام شيك وارد رقم {self.cheque_bank_number}",
                    reference_type="cheque_receive",
                    reference_id=self.id,
                    entry_date=datetime.combine(self.issue_date, datetime.min.time()),
                    tenant_id=self.tenant_id,
                    created_by=actor_id or self.user_id,
                    idempotency_key=f"cheque_receive:{self.id}",
                )
                if entry is not None and not self.gl_journal_entry_id:
                    self.gl_journal_entry_id = entry.id
            except Exception as e:
                current_app.logger.error(
                    f"Failed to create GL entry for cheque receipt {self.id}: {e}"
                )
                raise

    def issue_cheque(self, *, actor_id=None):
        """تسجيل إصدار الشيك الصادر"""
        if self.cheque_type == "outgoing" and not self.gl_journal_entry_id:
            from services.gl_service import GLService

            try:
                customer = self.customer if not self.supplier_id else None
                debit_account = (
                    GLService.get_customer_credit_account(customer)
                    if customer
                    else _resolve_account("AP_CONTROL", self.tenant_id)
                )
                lines = [
                    {
                        "account": debit_account,
                        "debit": self.amount_base,
                        "credit": 0,
                        "description": f"إصدار شيك رقم {self.cheque_bank_number}",
                        "party_id": customer.id
                        if customer and customer.customer_type == "partner"
                        else None,
                    },
                    {
                        "account": _resolve_account(
                            "DEFERRED_CHEQUES_PAYABLE", self.tenant_id
                        ),
                        "debit": 0,
                        "credit": self.amount_base,
                        "description": f"إصدار شيك - رقم {self.cheque_bank_number}",
                    },
                ]

                entry = GLService.post_entry(
                    lines=lines,
                    description=f"إصدار شيك صادر رقم {self.cheque_bank_number}",
                    reference_type="cheque_issue",
                    reference_id=self.id,
                    entry_date=datetime.combine(self.issue_date, datetime.min.time()),
                    tenant_id=self.tenant_id,
                    created_by=actor_id or self.user_id,
                    idempotency_key=f"cheque_issue:{self.id}",
                )
                self.gl_journal_entry_id = entry.id
            except Exception as e:
                current_app.logger.error(
                    f"Failed to create GL entry for cheque issue {self.id}: {e}"
                )
                raise

    def deposit_cheque(self, deposit_date=None):
        """إيداع الشيك في البنك"""
        if self.status not in ["pending", "under_collection"]:
            raise ValueError(f"لا يمكن إيداع شيك بحالة: {self.status_ar}")

        effective_date = deposit_date or datetime.now().date()
        if effective_date < self.issue_date:
            raise ValueError("تاريخ الإيداع يجب ألا يسبق إصدار الشيك.")
        self.status = "deposited"
        self.deposit_date = effective_date

    def clear_cheque(
        self,
        clearance_date=None,
        clearance_exchange_rate=None,
        *,
        actor_id=None,
        bank_charges=0,
    ):
        """تأكيد صرف الشيك من البنك - المحاسبة الحقيقية تبدأ هنا"""
        if self.status not in ["deposited", "pending"]:
            raise ValueError(f"لا يمكن تأكيد صرف شيك بحالة: {self.status_ar}")

        bank_charges = Decimal(str(bank_charges))
        if not bank_charges.is_finite() or bank_charges < 0:
            raise ValueError("Bank charges must be a nonnegative amount.")
        bank_charges = bank_charges.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        effective_date = clearance_date or datetime.now().date()
        if effective_date < (self.deposit_date or self.issue_date):
            raise ValueError("تاريخ الصرف يجب ألا يسبق الإصدار أو الإيداع.")
        from services.currency_service import CurrencyService

        _base = CurrencyService.get_base_currency()

        explicit_rate = None
        if self.currency != _base and clearance_exchange_rate is not None:
            explicit_rate = Decimal(str(clearance_exchange_rate))
            if not explicit_rate.is_finite() or explicit_rate <= 0:
                raise ValueError("Invalid clearance exchange rate: must be positive")

        self.status = "cleared"
        self.clearance_date = effective_date

        if self.currency != _base and explicit_rate is not None:
            self.clearance_exchange_rate = explicit_rate.quantize(
                Decimal("0.000001"), rounding=ROUND_HALF_UP
            )
        elif self.currency != _base:
            try:
                current_rate = CurrencyService.get_exchange_rate(self.currency, _base)
                self.clearance_exchange_rate = current_rate
            except Exception:
                self.clearance_exchange_rate = self.exchange_rate
        else:
            self.clearance_exchange_rate = Decimal("1.0")

        if self.amount_base is None:
            self.calculate_amount_base()

        amount = Decimal(str(self.amount))
        rate = Decimal(str(self.clearance_exchange_rate))
        self.actual_amount_base = (amount * rate).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        self.currency_gain_loss = (
            self.actual_amount_base - Decimal(str(self.amount_base))
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        if self.actual_amount_base <= 0 or (
            self.cheque_type == "incoming" and bank_charges > self.actual_amount_base
        ):
            raise ValueError("The cleared cheque amount cannot cover the bank charges.")
        self.cleared_date = effective_date
        self._create_clearing_journal_entry(
            actor_id=actor_id, bank_charges=bank_charges
        )

        from models.payment import Payment, Receipt

        payment = Payment.query.filter_by(cheque_id=self.id).first()
        if payment:
            payment.confirm_payment()

        receipt = Receipt.query.filter_by(cheque_id=self.id).first()
        if receipt:
            receipt.confirm_receipt()
        elif (
            self.cheque_type == "incoming"
            and self.customer_id
            and not (self.sale_id or self.receipt_id or self.payment_id or payment)
        ):
            from models.customer import recompute_customer_balance

            db.session.flush()
            recompute_customer_balance(self.customer_id)

    def _create_clearing_journal_entry(
        self, *, actor_id=None, bank_charges=Decimal("0")
    ):
        """إنشاء القيد المحاسبي عند صرف الشيك

        اصطلاح الإشارة المُثبَّت (موجب currency_gain_loss = الفعلي أعلى من الدفتري):
        - وارد: موجب = ربح  → دائن أرباح فرق العملة؛ سالب = خسارة → مدين خسائر فرق العملة
        - صادر: موجب = خسارة (دُفع نقدًا أكثر من الالتزام) → مدين خسائر؛ سالب = ربح → دائن أرباح
        """
        from services.gl_service import GLService

        fx_gain_account = _resolve_account("FX_GAIN", self.tenant_id)
        fx_loss_account = _resolve_account("FX_LOSS", self.tenant_id)
        bank_account = _resolve_account("BANK", self.tenant_id)

        try:
            lines = []

            if self.cheque_type == "incoming":
                lines.append(
                    {
                        "account": bank_account,
                        "debit": self.actual_amount_base - bank_charges,
                        "credit": 0,
                        "description": f"صرف شيك وارد رقم {self.cheque_bank_number}",
                    }
                )
                lines.append(
                    {
                        "account": _resolve_account("UNDER_COLLECTION", self.tenant_id),
                        "debit": 0,
                        "credit": self.amount_base,
                        "description": f"صرف شيك رقم {self.cheque_bank_number}",
                    }
                )

                if self.currency_gain_loss and self.currency_gain_loss != 0:
                    if self.currency_gain_loss > 0:
                        lines.append(
                            {
                                "account": fx_gain_account,  # أرباح فرق العملة
                                "debit": 0,
                                "credit": abs(self.currency_gain_loss),
                                "description": f"ربح فرق عملة - شيك {self.cheque_bank_number}",
                            }
                        )
                    else:
                        lines.append(
                            {
                                "account": fx_loss_account,  # خسائر فرق العملة
                                "debit": abs(self.currency_gain_loss),
                                "credit": 0,
                                "description": f"خسارة فرق عملة - شيك {self.cheque_bank_number}",
                            }
                        )

            elif self.cheque_type == "outgoing":
                lines.append(
                    {
                        "account": _resolve_account(
                            "DEFERRED_CHEQUES_PAYABLE", self.tenant_id
                        ),
                        "debit": self.amount_base,
                        "credit": 0,
                        "description": f"صرف شيك صادر رقم {self.cheque_bank_number}",
                    }
                )
                lines.append(
                    {
                        "account": bank_account,
                        "debit": 0,
                        "credit": self.actual_amount_base + bank_charges,
                        "description": f"صرف شيك رقم {self.cheque_bank_number}",
                    }
                )

                if self.currency_gain_loss and self.currency_gain_loss != 0:
                    if self.currency_gain_loss > 0:
                        lines.append(
                            {
                                "account": fx_loss_account,  # خسائر فرق العملة
                                "debit": abs(self.currency_gain_loss),
                                "credit": 0,
                                "description": f"خسارة فرق عملة - شيك {self.cheque_bank_number}",
                            }
                        )
                    else:
                        lines.append(
                            {
                                "account": fx_gain_account,  # أرباح فرق العملة
                                "debit": 0,
                                "credit": abs(self.currency_gain_loss),
                                "description": f"ربح فرق عملة - شيك {self.cheque_bank_number}",
                            }
                        )

            if bank_charges:
                lines.append(
                    {
                        "account": AccountResolver.resolve(
                            AccountRole.BANK_CHARGES, tenant_id=self.tenant_id
                        ),
                        "debit": bank_charges,
                        "description": f"رسوم البنك للشيك {self.cheque_bank_number}",
                    }
                )
            entry = GLService.post_entry(
                lines=lines,
                description=f"صرف شيك {self.type_ar} رقم {self.cheque_bank_number}",
                reference_type="cheque_clear",
                reference_id=self.id,
                tenant_id=getattr(self, "tenant_id", None),
                created_by=actor_id,
                entry_date=datetime.combine(self.clearance_date, datetime.min.time()),
                idempotency_key=f"cheque_clear:{self.id}",
            )
            if entry is not None and not self.gl_clearing_entry_id:
                self.gl_clearing_entry_id = entry.id

        except Exception as e:
            current_app.logger.error(
                f"Failed to create GL entry for cheque {self.id}: {e}"
            )
            raise

    def bounce_cheque(self, reason, *, actor_id=None):
        """رفض الشيك من البنك - إرجاع الدين"""
        if self.status not in ["deposited", "pending"]:
            raise ValueError(f"لا يمكن رفض شيك بحالة: {self.status_ar}")

        reversal = self._reverse_linked_journal("cheque_bounce", actor_id)
        self.gl_bounce_entry_id = reversal.id
        self.status = "bounced"
        self.bounce_reason = reason
        self.clearance_date = datetime.now().date()

        if self.cheque_type == "incoming" and self.customer_id:
            db.session.flush()
            from models.customer import recompute_customer_balance

            recompute_customer_balance(self.customer_id)
        from models.payment import Payment, Receipt

        payment = Payment.query.filter_by(cheque_id=self.id).first()
        if payment:
            payment.reject_payment(reason)

        receipt = Receipt.query.filter_by(cheque_id=self.id).first()
        if receipt:
            receipt.reject_receipt(reason)

    def _reverse_linked_journal(self, reference_type, actor_id=None):
        from services.cheque_accounting_integration import ChequeAccountingIntegration

        original = ChequeAccountingIntegration._original_entry(self)
        return original.reverse_entry(
            created_by=actor_id, reversal_reference=(reference_type, self.id)
        )

    def cancel_cheque(self, reason=None):
        """إلغاء الشيك - عكس القيود المحاسبية"""
        if self.status == "cancelled":
            return

        self.status = "cancelled"
        if reason:
            self.notes = (self.notes or "") + f"\nسبب الإلغاء: {reason}"

        if self.cheque_type == "incoming" and self.customer_id:
            db.session.flush()
            from models.customer import recompute_customer_balance

            recompute_customer_balance(self.customer_id)
        self._create_cancel_journal_entry()

    def _create_cancel_journal_entry(self):
        """إنشاء قيد عكسي عند إلغاء الشيك"""
        if self.gl_journal_entry_id is None:
            return
        return self._reverse_linked_journal("cheque_cancel")

    def archive(self, reason=None):
        """أرشفة الشيك - مع عكس القيد إذا كان نشطاً"""
        was_active = self.is_active and self.status in [
            "pending",
            "deposited",
            "under_collection",
        ]

        self.is_active = False
        self.archived_at = datetime.now(timezone.utc)
        if reason:
            self.archive_reason = reason

        if was_active:
            if self.cheque_type == "incoming" and self.customer_id:
                db.session.flush()
                from models.customer import recompute_customer_balance

                recompute_customer_balance(self.customer_id)
            self._create_cancel_journal_entry()

    def restore(self):
        """استعادة من الأرشيف"""
        self.is_active = True
        self.archived_at = None
        self.archive_reason = None

    @property
    def is_due_soon(self):
        """شيك قريب الاستحقاق (خلال 7 أيام)"""
        return self.days_until_due is not None and 0 <= self.days_until_due <= 7

    @property
    def gl_entry_number(self):
        """رقم القيد المحاسبي المرتبط بهذا الشيك (لعرضه في التقارير).

        يُفضَّل القيد المخزَّن صراحةً (صرف/ارتداد)، وإلا نبحث عن قيد الإصدار
        أو الإلغاء عبر reference_id. كل البحث مقيد بمستأجر الشيك.
        """
        from models.gl import GLJournalEntry

        entry_id = self.gl_clearing_entry_id or self.gl_bounce_entry_id
        if entry_id:
            entry = db.session.get(GLJournalEntry, entry_id)
            if entry and entry.tenant_id == self.tenant_id:
                return entry.entry_number
        entry = (
            GLJournalEntry.query.filter(
                GLJournalEntry.reference_type.in_(
                    ("cheque_issue", "cheque_cancel", "cheque_clear", "cheque_bounce")
                ),
                GLJournalEntry.reference_id == self.id,
            )
            .order_by(GLJournalEntry.id.desc())
            .first()
        )
        return entry.entry_number if entry else None

    @property
    def status_ar(self):
        """الحالة بالعربي"""
        statuses = {
            "pending": "معلق (استُلم)",
            "deposited": "مودع في البنك",
            "cleared": "مصروف",
            "bounced": "مرتد",
            "cancelled": "ملغي",
            "under_collection": "تحت التحصيل",
        }
        return statuses.get(self.status, self.status)

    @property
    def is_confirmed(self):
        """هل الشيك مؤكد الصرف (يُحسب في الإيرادات الفعلية)"""
        return self.status == "cleared"

    @property
    def is_pending(self):
        """هل الشيك معلّق (لا يُحسب في الإيرادات الفعلية)"""
        return self.status in ["pending", "deposited", "under_collection"]

    @property
    def type_ar(self):
        """النوع بالعربي"""
        types = {"incoming": "وارد", "outgoing": "صادر"}
        return types.get(self.cheque_type, self.cheque_type)

    def to_dict(self):
        """تحويل إلى dict"""
        return {
            "id": self.id,
            "cheque_number": self.cheque_number,
            "cheque_bank_number": self.cheque_bank_number,
            "cheque_type": self.cheque_type,
            "type_ar": self.type_ar,
            "bank_name": self.bank_name,
            "amount": float(self.amount),
            "currency": self.currency,
            "exchange_rate": float(self.exchange_rate) if self.exchange_rate else 1.0,
            "clearance_exchange_rate": float(self.clearance_exchange_rate)
            if self.clearance_exchange_rate
            else None,
            "amount_base": float(self.amount_base) if self.amount_base else 0,
            "actual_amount_base": float(self.actual_amount_base)
            if self.actual_amount_base
            else None,
            "currency_gain_loss": float(self.currency_gain_loss)
            if self.currency_gain_loss
            else 0,
            "issue_date": self.issue_date.isoformat() if self.issue_date else None,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "clearance_date": self.clearance_date.isoformat()
            if self.clearance_date
            else None,
            "status": self.status,
            "status_ar": self.status_ar,
            "days_until_due": self.days_until_due,
            "is_overdue": self.is_overdue,
            "is_due_soon": self.is_due_soon,
            "drawer_name": self.drawer_name,
            "payee_name": self.payee_name,
            "customer_id": self.customer_id,
            "supplier_id": self.supplier_id,
        }

    @staticmethod
    def get_incoming_cheques(customer_id=None, status=None):
        """الشيكات الواردة"""
        query = Cheque.query.filter_by(cheque_type="incoming", is_active=True)

        if customer_id:
            query = query.filter_by(customer_id=customer_id)

        if status:
            query = query.filter_by(status=status)

        return query.order_by(Cheque.due_date).all()

    @staticmethod
    def get_outgoing_cheques(supplier_id=None, status=None):
        """الشيكات الصادرة"""
        query = Cheque.query.filter_by(cheque_type="outgoing", is_active=True)

        if supplier_id:
            query = query.filter_by(supplier_id=supplier_id)

        if status:
            query = query.filter_by(status=status)

        return query.order_by(Cheque.due_date).all()

    @staticmethod
    def get_due_soon_cheques():
        """الشيكات القريبة من الاستحقاق (7 أيام)"""
        Cheque.update_all_statuses()

        return (
            Cheque.query.filter(
                Cheque.is_active.is_(True),
                Cheque.status == "pending",
                Cheque.days_until_due <= 7,
                Cheque.days_until_due >= 0,
            )
            .order_by(Cheque.due_date)
            .all()
        )

    @staticmethod
    def get_overdue_cheques():
        """الشيكات المتأخرة"""
        Cheque.update_all_statuses()

        return (
            Cheque.query.filter(
                Cheque.is_active.is_(True),
                Cheque.status == "pending",
                Cheque.is_overdue.is_(True),
            )
            .order_by(Cheque.due_date)
            .all()
        )

    @staticmethod
    def update_all_statuses():
        """تحديث حالة كل الشيكات"""
        pending_cheques = Cheque.query.filter_by(status="pending", is_active=True).all()

        for cheque in pending_cheques:
            cheque.update_status_based_on_date()

        db.session.commit()

    @staticmethod
    def get_statistics():
        """إحصائيات الشيكات"""
        total_incoming = Cheque.query.filter_by(
            cheque_type="incoming", is_active=True
        ).count()
        total_outgoing = Cheque.query.filter_by(
            cheque_type="outgoing", is_active=True
        ).count()

        pending_incoming = Cheque.query.filter_by(
            cheque_type="incoming", status="pending", is_active=True
        ).count()

        pending_outgoing = Cheque.query.filter_by(
            cheque_type="outgoing", status="pending", is_active=True
        ).count()

        incoming_amount = db.session.query(db.func.sum(Cheque.amount_base)).filter_by(
            cheque_type="incoming", status="pending", is_active=True
        ).scalar() or Decimal("0")

        outgoing_amount = db.session.query(db.func.sum(Cheque.amount_base)).filter_by(
            cheque_type="outgoing", status="pending", is_active=True
        ).scalar() or Decimal("0")

        overdue = Cheque.query.filter_by(
            status="pending", is_active=True, is_overdue=True
        ).count()

        due_soon = Cheque.query.filter(
            Cheque.status == "pending",
            Cheque.is_active.is_(True),
            Cheque.days_until_due <= 7,
            Cheque.days_until_due >= 0,
        ).count()

        return {
            "total_incoming": total_incoming,
            "total_outgoing": total_outgoing,
            "pending_incoming": pending_incoming,
            "pending_outgoing": pending_outgoing,
            "incoming_amount": float(incoming_amount),
            "outgoing_amount": float(outgoing_amount),
            "overdue": overdue,
            "due_soon": due_soon,
            "bounced": Cheque.query.filter_by(status="bounced", is_active=True).count(),
        }
