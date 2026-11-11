"""
Maintenance Module Models — نماذج وحدة الصيانة
"""
from datetime import date, datetime, time, timezone
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy import DDL, event
from extensions import db
from models.tenant_scope import TenantScopedMixin
from utils.helpers import generate_number


def _effective_quantity(quantity, returned_quantity):
    """The quantity still on the order after the returned parts/services."""
    effective = Decimal(str(quantity or 0)) - Decimal(str(returned_quantity or 0))
    return effective if effective > 0 else Decimal('0')


# ---------------------------------------------------------------------------
# 1. رأس أمر الصيانة
# ---------------------------------------------------------------------------
class MaintenanceOrder(TenantScopedMixin, db.Model):
    """أمر صيانة — رأس الأمر"""
    __tablename__ = 'maintenance_orders'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=True, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=True, index=True)

    order_no = db.Column(db.String(50), unique=True, nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False, index=True)

    # بيانات الجهاز
    device_brand = db.Column(db.String(100), nullable=True)
    device_model = db.Column(db.String(100), nullable=True)
    device_serial = db.Column(db.String(100), nullable=True, index=True)
    device_imei = db.Column(db.String(100), nullable=True)
    device_plate = db.Column(db.String(50), nullable=True)
    device_problem = db.Column(db.Text, nullable=True)

    # التواريخ والحالة
    received_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    valid_until = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), default='received', index=True)  # received/diagnosis/waiting_approval/in_progress/waiting_parts/ready/closed/cancelled/on_hold
    priority = db.Column(db.String(20), default='normal')  # low/normal/urgent

    # الكفالة
    warranty_status = db.Column(db.String(20), nullable=True)  # under_warranty/expired/void/unknown
    warranty_checked = db.Column(db.Boolean, default=False)
    warranty_verified_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    warranty_checked_at = db.Column(db.DateTime, nullable=True)
    warranty_notes = db.Column(db.Text, nullable=True)
    color_tag = db.Column(db.String(20), nullable=True)  # green/red/yellow

    # الكفالة المرتبطة ببيع سابق
    warranty_sale_id = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=True)

    # المستخدمون
    received_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    engineer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    service_advisor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    # تقييم العميل
    customer_rating = db.Column(db.Integer, nullable=True)  # 1-5
    customer_comment = db.Column(db.Text, nullable=True)
    rated_at = db.Column(db.DateTime, nullable=True)

    # فترة ضمان ما بعد الصيانة
    warranty_period_days = db.Column(db.Integer, nullable=True)
    warranty_period_notes = db.Column(db.Text, nullable=True)
    warranty_period_start = db.Column(db.Date, nullable=True)
    warranty_period_end = db.Column(db.Date, nullable=True)

    # المالي - العملة
    currency = db.Column(db.String(3), default='AED', nullable=False, index=True)  # عملة المعاملة
    exchange_rate = db.Column(db.Numeric(15, 6), default=1, nullable=False)  # سعر الصرف مقابل عملة التينانت الأساسية
    amount_base = db.Column(db.Numeric(15, 3), default=0, nullable=False)  # المبلغ المحول لعملة التينانت الأساسية

    payment_mode = db.Column(db.String(20), default='cash')  # cash/card/cheque/transfer/account
    deposit = db.Column(db.Numeric(15, 3), default=0)
    deposit_payment_method = db.Column(db.String(20), nullable=True)
    tax_inclusive = db.Column(db.Boolean, default=False)
    subtotal = db.Column(db.Numeric(15, 3), default=0)
    discount_line_total = db.Column(db.Numeric(15, 3), default=0)
    discount_total_value = db.Column(db.Numeric(15, 3), default=0)
    discount_total_percent = db.Column(db.Numeric(5, 2), default=0)
    tax_amount = db.Column(db.Numeric(15, 3), default=0)
    total_amount = db.Column(db.Numeric(15, 3), default=0)
    paid_amount = db.Column(db.Numeric(15, 3), default=0)
    balance_due = db.Column(db.Numeric(15, 3), default=0)
    subtotal_base = db.Column(db.Numeric(15, 3), default=0)  # المبلغ الفرعي بعملة الأساس
    tax_amount_base = db.Column(db.Numeric(15, 3), default=0)  # الضريبة بعملة الأساس
    total_amount_base = db.Column(db.Numeric(15, 3), default=0)  # الإجمالي بعملة الأساس
    paid_amount_base = db.Column(db.Numeric(15, 3), default=0)  # المبلغ المسدد بعملة الأساس
    balance_due_base = db.Column(db.Numeric(15, 3), default=0)  # الرصيد المستحق بعملة الأساس

    # تفاصيل التكلفة والسعر
    cost_price_total = db.Column(db.Numeric(15, 3), default=0)  # تكلفة القطع والخدمات الفعلية
    selling_price_total = db.Column(db.Numeric(15, 3), default=0)  # سعر البيع للعميل
    technician_notes = db.Column(db.Text, nullable=True)  # ملاحظات المهندس الداخلية
    quality_check_passed = db.Column(db.Boolean, default=False)  # فحص جودة مكتمل
    quality_check_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    quality_check_at = db.Column(db.DateTime, nullable=True)
    completion_time_hours = db.Column(db.Numeric(10, 2), nullable=True)  # وقت الإكمال بالساعات

    # الموافقات والتدقيق
    is_archived = db.Column(db.Boolean, default=False)
    archived_at = db.Column(db.DateTime, nullable=True)
    archived_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    # العلاقات
    customer = db.relationship('Customer')
    received_by_user = db.relationship('User', foreign_keys=[received_by])
    engineer = db.relationship('User', foreign_keys=[engineer_id])
    service_advisor = db.relationship('User', foreign_keys=[service_advisor_id])
    warranty_verifier = db.relationship('User', foreign_keys=[warranty_verified_by])
    items = db.relationship('MaintenanceOrderItem', back_populates='order', cascade='all, delete-orphan')
    services = db.relationship('MaintenanceOrderService', back_populates='order', cascade='all, delete-orphan')
    status_logs = db.relationship('MaintenanceOrderStatusLog', back_populates='order', cascade='all, delete-orphan')
    receipts = db.relationship('MaintenanceReceipt', back_populates='order', cascade='all, delete-orphan')
    invoice = db.relationship('MaintenanceInvoice', back_populates='order', uselist=False, cascade='all, delete-orphan')
    returns = db.relationship('MaintenanceReturn', back_populates='order', cascade='all, delete-orphan')
    credit_notes = db.relationship('MaintenanceCreditNote', back_populates='order', cascade='all, delete-orphan')

    def calculate_totals(self):
        """Recompute every amount of the document from the pricing engine.

        Field meaning (kept consistent with services/maintenance_pricing.py):

        * ``subtotal``             price basis of the lines after their own
                                   discounts, before the order-level discount
        * ``discount_line_total``  sum of the line discounts
        * ``discount_total_value`` the applied order-level discount (money)
        * ``tax_amount``           total VAT
        * ``total_amount``         net of VAT plus VAT, after all discounts

        The net revenue of the document is ``total_amount - tax_amount``.
        """
        from services.maintenance_pricing import PriceLine, calculate_maintenance_pricing

        price_lines = []
        for item in self.items:
            price_lines.append(PriceLine(
                quantity=_effective_quantity(item.quantity, item.returned_quantity),
                unit_price=item.unit_price,
                tax_rate=item.tax_rate, tax_treatment='standard',
                discount_mode=item.line_discount_mode or 'percent',
                discount_percent=item.discount_percent, discount_value=item.discount_value,
            ))
        for service in self.services:
            price_lines.append(PriceLine(
                quantity=_effective_quantity(service.quantity, service.returned_quantity),
                unit_price=service.unit_price,
                tax_rate=service.tax_rate, tax_treatment='standard',
                discount_mode='percent',
                discount_percent=service.discount_percent,
                discount_value=service.discount_value,
            ))

        percent = Decimal(str(self.discount_total_percent or 0))
        # When a percentage is applied, the stored money amount is the derived
        # one, so it must not be sent to the engine as a second discount.
        value = Decimal(str(self.discount_total_value or 0)) if percent <= 0 else Decimal('0')
        totals = calculate_maintenance_pricing(
            price_lines,
            tax_inclusive=bool(self.tax_inclusive),
            discount_percent=percent,
            discount_value=value,
        )

        for line, calculated in zip(list(self.items) + list(self.services), totals.lines):
            line.tax_amount = calculated.tax_amount
            line.line_total = calculated.total_amount

        self.subtotal = totals.price_basis_subtotal
        self.discount_line_total = totals.line_discount
        self.discount_total_value = totals.order_discount
        self.tax_amount = totals.tax_amount
        self.total_amount = totals.total_amount
        self.balance_due = self.total_amount - Decimal(str(self.paid_amount or 0))

        # تحويل المبالغ إلى عملة التينانت الأساسية
        rate = Decimal(str(self.exchange_rate or 1))
        self.subtotal_base = (self.subtotal * rate).quantize(Decimal('0.001'))
        self.tax_amount_base = (self.tax_amount * rate).quantize(Decimal('0.001'))
        self.total_amount_base = (self.total_amount * rate).quantize(Decimal('0.001'))
        self.paid_amount_base = (self.paid_amount * rate).quantize(Decimal('0.001'))
        self.balance_due_base = (self.balance_due * rate).quantize(Decimal('0.001'))

        # Actual cost of the work (analytic: the GL carries the inventory-backed
        # part; labour is tracked here because the payroll flow expenses wages
        # at payment time and has no accrual clearing path).
        parts_cost = sum((Decimal(str(it.cost_price or 0))
                          * _effective_quantity(it.quantity, it.returned_quantity)
                          for it in self.items), Decimal('0'))
        labor_cost = sum((Decimal(str(sv.cost_price or 0))
                          * _effective_quantity(sv.quantity, sv.returned_quantity)
                          for sv in self.services), Decimal('0'))
        self.cost_price_total = parts_cost + labor_cost
        self.selling_price_total = self.total_amount


# ---------------------------------------------------------------------------
# 2. بنود القطع (أمر الصيانة)
# ---------------------------------------------------------------------------
class MaintenanceOrderItem(db.Model):
    """بند قطعة غيار في أمر الصيانة"""
    __tablename__ = 'maintenance_order_items'

    id = db.Column(db.Integer, primary_key=True)
    maintenance_order_id = db.Column(db.Integer, db.ForeignKey('maintenance_orders.id'), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False, index=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouses.id'), nullable=True)
    quantity = db.Column(db.Numeric(15, 3), default=1)
    unit_price = db.Column(db.Numeric(15, 3), default=0)
    # عملة البند (تيرث من الأمر إذا لم تُحدد)
    currency = db.Column(db.String(3), nullable=True)
    exchange_rate = db.Column(db.Numeric(15, 6), nullable=True)
    amount_base = db.Column(db.Numeric(15, 3), nullable=True)  # السعر totale بعملة الأساس
    discount_percent = db.Column(db.Numeric(5, 2), default=0)
    discount_value = db.Column(db.Numeric(15, 3), default=0)
    line_discount_mode = db.Column(db.String(10), default='percent')  # percent/value
    tax_rate = db.Column(db.Numeric(5, 2), default=0)
    tax_amount = db.Column(db.Numeric(15, 3), default=0)
    line_total = db.Column(db.Numeric(15, 3), default=0)
    movement_id = db.Column(db.Integer, db.ForeignKey('stock_movements.id'), nullable=True)
    cost_price = db.Column(db.Numeric(15, 3), default=0)  # التكلفة الفعلية للقطعة من المخزون
    cost_source = db.Column(db.String(50), default='inventory')  # inventory/supplier/manual
    returned_quantity = db.Column(db.Numeric(15, 3), default=0)  # الكمية المرتجعة إلى المخزون

    order = db.relationship('MaintenanceOrder', back_populates='items')
    product = db.relationship('Product')
    warehouse = db.relationship('Warehouse')
    movement = db.relationship('StockMovement')

    def calculate_line_total(self):
        """Line amounts: net after the line discount, VAT, and the gross total.

        The stored ``line_total`` is GROSS (net + VAT) and ``tax_amount`` is
        the VAT part of it, so the net revenue of a line is
        ``line_total - tax_amount``. Exclusive prices add VAT on top; an
        inclusive price is de-composed into net and VAT.
        """
        qty = Decimal(str(self.quantity or 0))
        price = Decimal(str(self.unit_price or 0))
        disc_pct = Decimal(str(self.discount_percent or 0))
        disc_val = Decimal(str(self.discount_value or 0))
        rate = Decimal(str(self.tax_rate or 0))
        inclusive = bool(getattr(self.order, 'tax_inclusive', False))

        base = qty * price
        if self.line_discount_mode == 'percent':
            base = base * (1 - disc_pct / 100)
        else:
            base = base - disc_val
        if base < 0:
            base = Decimal('0')
        base = base.quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)

        if inclusive and rate > 0:
            divisor = Decimal('1') + rate / Decimal('100')
            net = (base / divisor).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)
            tax = base - net
        else:
            net = base
            tax = (base * rate / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        self.tax_amount = tax
        self.line_total = (net + tax).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# 3. الخدمات (ميكانيك/كهرباء/جهد/أخرى)
# ---------------------------------------------------------------------------
class MaintenanceOrderService(db.Model):
    """بند خدمة في أمر الصيانة"""
    __tablename__ = 'maintenance_order_services'

    id = db.Column(db.Integer, primary_key=True)
    maintenance_order_id = db.Column(db.Integer, db.ForeignKey('maintenance_orders.id'), nullable=False, index=True)
    service_code = db.Column(db.String(50), nullable=True)
    service_name = db.Column(db.String(200), nullable=False)
    service_name_ar = db.Column(db.String(200), nullable=True)
    unit_price = db.Column(db.Numeric(15, 3), default=0)
    duration_minutes = db.Column(db.Integer, default=0)
    # عملة البند (تيرث من الأمر إذا لم تُحدد)
    currency = db.Column(db.String(3), nullable=True)
    exchange_rate = db.Column(db.Numeric(15, 6), nullable=True)
    amount_base = db.Column(db.Numeric(15, 3), nullable=True)  # السعر totale بعملة الأساس
    discount_percent = db.Column(db.Numeric(5, 2), default=0)
    discount_value = db.Column(db.Numeric(15, 3), default=0)
    tax_rate = db.Column(db.Numeric(5, 2), default=0)
    tax_amount = db.Column(db.Numeric(15, 3), default=0)
    line_total = db.Column(db.Numeric(15, 3), default=0)
    engineer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    cost_price = db.Column(db.Numeric(15, 3), default=0)  # تكلفة الخدمة الفعلية (راتب المهندس/المورد)
    cost_source = db.Column(db.String(50), default='labor')  # labor/supplier/manual
    quantity = db.Column(db.Numeric(15, 3), default=1)
    returned_quantity = db.Column(db.Numeric(15, 3), default=0)

    order = db.relationship('MaintenanceOrder', back_populates='services')
    engineer = db.relationship('User', foreign_keys=[engineer_id])

    def calculate_line_total(self):
        """Service line amounts: net after the line discount, VAT, gross total."""
        qty = Decimal(str(self.quantity or 1))
        price = Decimal(str(self.unit_price or 0))
        disc_pct = Decimal(str(self.discount_percent or 0))
        disc_val = Decimal(str(self.discount_value or 0))
        rate = Decimal(str(self.tax_rate or 0))
        inclusive = bool(getattr(self.order, 'tax_inclusive', False))

        base = qty * price * (1 - disc_pct / 100) - disc_val
        if base < 0:
            base = Decimal('0')
        base = base.quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)

        if inclusive and rate > 0:
            divisor = Decimal('1') + rate / Decimal('100')
            net = (base / divisor).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)
            tax = base - net
        else:
            net = base
            tax = (base * rate / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        self.tax_amount = tax
        self.line_total = (net + tax).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# 4. سجل انتقال الحالات
# ---------------------------------------------------------------------------
class MaintenanceOrderStatusLog(db.Model):
    """سجل تغيير حالات أمر الصيانة"""
    __tablename__ = 'maintenance_order_status_log'

    id = db.Column(db.Integer, primary_key=True)
    maintenance_order_id = db.Column(db.Integer, db.ForeignKey('maintenance_orders.id'), nullable=False, index=True)
    from_status = db.Column(db.String(20), nullable=True)
    to_status = db.Column(db.String(20), nullable=False)
    changed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    changed_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    note = db.Column(db.Text, nullable=True)

    order = db.relationship('MaintenanceOrder', back_populates='status_logs')
    user = db.relationship('User')


# ---------------------------------------------------------------------------
# 5. سندات القبض (استقبال فقط)
# ---------------------------------------------------------------------------
class MaintenanceReceipt(db.Model):
    """سند قبض لأمر الصيانة"""
    __tablename__ = 'maintenance_receipts'

    id = db.Column(db.Integer, primary_key=True)
    maintenance_order_id = db.Column(db.Integer, db.ForeignKey('maintenance_orders.id'), nullable=False, index=True)
    receipt_no = db.Column(db.String(50), unique=True, nullable=False, index=True)
    # عملة القبض
    currency = db.Column(db.String(3), nullable=True)
    exchange_rate = db.Column(db.Numeric(15, 6), nullable=True)
    amount_base = db.Column(db.Numeric(15, 3), nullable=True)  # المبلغ المحول بعملة الأساس
    amount = db.Column(db.Numeric(15, 3), default=0)
    payment_method = db.Column(db.String(20), nullable=False)  # cash/card/cheque/transfer
    cashier_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    reference_type = db.Column(db.String(50), nullable=True)
    reference_id = db.Column(db.Integer, nullable=True)
    posted = db.Column(db.Boolean, default=False)
    posted_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    order = db.relationship('MaintenanceOrder', back_populates='receipts')
    cashier = db.relationship('User')


# ---------------------------------------------------------------------------
# 6. فواتير الصيانة (مستقلة عن مبيعات المبيعات)
# ---------------------------------------------------------------------------
class MaintenanceInvoice(db.Model):
    """فاتورة صيانة — مستقلة عن فواتير المبيعات العادية"""
    __tablename__ = 'maintenance_invoices'

    id = db.Column(db.Integer, primary_key=True)
    maintenance_order_id = db.Column(db.Integer, db.ForeignKey('maintenance_orders.id'), nullable=False, index=True, unique=True)
    invoice_no = db.Column(db.String(50), unique=True, nullable=False, index=True)
    # عملة الفاتورة
    currency = db.Column(db.String(3), nullable=True)
    exchange_rate = db.Column(db.Numeric(15, 6), nullable=True)
    amount_base = db.Column(db.Numeric(15, 3), nullable=True)  # المبلغ الإجمالي بعملة الأساس
    subtotal = db.Column(db.Numeric(15, 3), default=0)
    discount_total = db.Column(db.Numeric(15, 3), default=0)
    tax_amount = db.Column(db.Numeric(15, 3), default=0)
    total_amount = db.Column(db.Numeric(15, 3), default=0)
    paid_amount = db.Column(db.Numeric(15, 3), default=0)
    balance_due = db.Column(db.Numeric(15, 3), default=0)
    subtotal_base = db.Column(db.Numeric(15, 3), default=0)
    tax_amount_base = db.Column(db.Numeric(15, 3), default=0)
    total_amount_base = db.Column(db.Numeric(15, 3), default=0)
    paid_amount_base = db.Column(db.Numeric(15, 3), default=0)
    balance_due_base = db.Column(db.Numeric(15, 3), default=0)
    posted = db.Column(db.Boolean, default=False)
    posted_at = db.Column(db.DateTime, nullable=True)
    gl_posted = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    order = db.relationship('MaintenanceOrder', back_populates='invoice')


# ---------------------------------------------------------------------------
# 7. مرتجعات الصيانة
# ---------------------------------------------------------------------------
class MaintenanceReturn(db.Model):
    """مرتجع صيانة"""
    __tablename__ = 'maintenance_returns'

    id = db.Column(db.Integer, primary_key=True)
    maintenance_order_id = db.Column(db.Integer, db.ForeignKey('maintenance_orders.id'), nullable=False, index=True)
    return_no = db.Column(db.String(50), unique=True, nullable=False, index=True)
    # عملة المرتجع
    currency = db.Column(db.String(3), nullable=True)
    exchange_rate = db.Column(db.Numeric(15, 6), nullable=True)
    amount_base = db.Column(db.Numeric(15, 3), nullable=True)  # المبلغ المحول بعملة الأساس
    returned_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    reason = db.Column(db.Text, nullable=True)
    total_value = db.Column(db.Numeric(15, 3), default=0)
    total_value_base = db.Column(db.Numeric(15, 3), default=0)
    posted = db.Column(db.Boolean, default=False)
    posted_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    order = db.relationship('MaintenanceOrder', back_populates='returns')
    user = db.relationship('User')


# ---------------------------------------------------------------------------
# 8. بنود المرتجعات
# ---------------------------------------------------------------------------
class MaintenanceReturnLine(db.Model):
    """بند مرتجع صيانة"""
    __tablename__ = 'maintenance_return_lines'

    id = db.Column(db.Integer, primary_key=True)
    return_id = db.Column(db.Integer, db.ForeignKey('maintenance_returns.id'), nullable=False, index=True)
    order_item_id = db.Column(db.Integer, db.ForeignKey('maintenance_order_items.id'), nullable=True)
    order_service_id = db.Column(db.Integer, db.ForeignKey('maintenance_order_services.id'), nullable=True)
    quantity = db.Column(db.Numeric(15, 3), default=1)
    unit_price = db.Column(db.Numeric(15, 3), default=0)
    line_total = db.Column(db.Numeric(15, 3), default=0)

    ret = db.relationship('MaintenanceReturn')
    item = db.relationship('MaintenanceOrderItem')
    service = db.relationship('MaintenanceOrderService')


# ---------------------------------------------------------------------------
# 9. إعدادات الصيانة لكل تينانت
# ---------------------------------------------------------------------------
class MaintenanceSetting(db.Model):
    """إعدادات وحدة الصيانة لكل تينانت"""
    __tablename__ = 'maintenance_settings'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True, unique=True)
    default_warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouses.id'), nullable=True)
    maintenance_ar_account_id = db.Column(db.Integer, nullable=True)  # ذمم الصيانة مدينة
    maintenance_revenue_account_id = db.Column(db.Integer, nullable=True)  # إيراد الصيانة
    max_discount_percent = db.Column(db.Numeric(5, 2), default=15)
    max_discount_value = db.Column(db.Numeric(15, 3), default=500)
    require_warranty_check = db.Column(db.Boolean, default=True)
    color_warranty = db.Column(db.String(20), default='#10b981')  # green
    color_non_warranty = db.Column(db.String(20), default='#ef4444')  # red
    color_unknown = db.Column(db.String(20), default='#f59e0b')  # yellow
    allow_engineer_cancel_warranty = db.Column(db.Boolean, default=False)
    allow_engineer_restore_warranty = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# 10. الخدمات الثابتة السعر (لوحة المشرف)
# ---------------------------------------------------------------------------
class MaintenanceService(db.Model):
    """خدمة صيانة بسعر ثابت"""
    __tablename__ = 'maintenance_services'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    service_code = db.Column(db.String(20), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    name_ar = db.Column(db.String(200), nullable=True)
    category = db.Column(db.String(20), default='other')  # mechanical/electrical/labor/diagnostic/other
    fixed_price = db.Column(db.Numeric(15, 3), default=0)
    duration_minutes = db.Column(db.Integer, default=0)
    tax_rate = db.Column(db.Numeric(5, 2), default=0)
    is_active = db.Column(db.Boolean, default=True)
    requires_parts = db.Column(db.Boolean, default=False)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# 11. تدقيق الكفالات
# ---------------------------------------------------------------------------
class MaintenanceWarrantyAudit(db.Model):
    """تدقيق عمليات الكفالة"""
    __tablename__ = 'maintenance_warranty_audit'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    maintenance_order_id = db.Column(db.Integer, db.ForeignKey('maintenance_orders.id'), nullable=True, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)
    serial_number = db.Column(db.String(100), nullable=True, index=True)
    action = db.Column(db.String(20), nullable=False)  # checked/voided/restored
    performed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    performed_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    reason = db.Column(db.Text, nullable=True)
    before_status = db.Column(db.String(20), nullable=True)
    after_status = db.Column(db.String(20), nullable=True)

    order = db.relationship('MaintenanceOrder')
    product = db.relationship('Product')
    user = db.relationship('User')


# ---------------------------------------------------------------------------
# 13. سجل مدفوعات ذمم الصيانة للموردين
# ---------------------------------------------------------------------------
class MaintenanceSupplierPayment(db.Model):
    """سداد ذمم الصيانة دائنة لمورد قطع"""
    __tablename__ = 'maintenance_supplier_payments'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), nullable=False, index=True)
    # عملة السداد
    currency = db.Column(db.String(3), nullable=True)
    exchange_rate = db.Column(db.Numeric(15, 6), nullable=True)
    amount_base = db.Column(db.Numeric(15, 3), nullable=True)  # المبلغ المحول بعملة الأساس
    amount = db.Column(db.Numeric(15, 3), default=0)
    payment_method = db.Column(db.String(20), default='cash')
    reference_number = db.Column(db.String(50), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    posted = db.Column(db.Boolean, default=False)
    posted_at = db.Column(db.DateTime, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    supplier = db.relationship('Supplier')
    user = db.relationship('User')


# ---------------------------------------------------------------------------
# 13. إشعارات الدائن للصيانة (لإلغاء الفاتورة والسماح بالمرتجع بعدها)
# ---------------------------------------------------------------------------
class MaintenanceCreditNote(db.Model):
    """إشعار دائن لصيانة — لعكس الفاتورة والسماح بالمرتجع بعدها."""
    __tablename__ = 'maintenance_credit_notes'

    id = db.Column(db.Integer, primary_key=True)
    maintenance_order_id = db.Column(db.Integer, db.ForeignKey('maintenance_orders.id'), nullable=False, index=True)
    credit_note_no = db.Column(db.String(50), unique=True, nullable=False, index=True)
    # عملة إشعار الدائن
    currency = db.Column(db.String(3), nullable=True)
    exchange_rate = db.Column(db.Numeric(15, 6), nullable=True)
    amount_base = db.Column(db.Numeric(15, 3), nullable=True)  # المبلغ المحول بعملة الأساس
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    reason = db.Column(db.Text, nullable=True)
    total_value = db.Column(db.Numeric(15, 3), default=0)
    total_value_base = db.Column(db.Numeric(15, 3), default=0)
    posted = db.Column(db.Boolean, default=False)
    posted_at = db.Column(db.DateTime, nullable=True)
    gl_posted = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    order = db.relationship('MaintenanceOrder', back_populates='credit_notes')
    user = db.relationship('User')


# ---------------------------------------------------------------------------
# 14. سجل الأجهزة
# ---------------------------------------------------------------------------
class MaintenanceDeviceRegistry(db.Model):
    """سجل أجهزة العملاء"""
    __tablename__ = 'maintenance_device_registry'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)
    serial_number = db.Column(db.String(100), nullable=True, index=True)
    imei = db.Column(db.String(100), nullable=True, index=True)
    plate = db.Column(db.String(50), nullable=True, index=True)
    brand = db.Column(db.String(100), nullable=True)
    model = db.Column(db.String(100), nullable=True)
    purchase_date = db.Column(db.Date, nullable=True)
    warranty_end_date = db.Column(db.Date, nullable=True)
    warranty_type = db.Column(db.String(50), nullable=True)  # manufacturer/extended/dealer/insurance
    is_under_warranty = db.Column(db.Boolean, default=False)
    warranty_notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    customer = db.relationship('Customer')


def _reject_audit_mutation(mapper, connection, target):
    """An audit record must be corrected by appending, never edited or deleted."""
    raise ValueError('Maintenance audit records are append-only')


for _audit_model in (MaintenanceOrderStatusLog, MaintenanceWarrantyAudit):
    event.listen(_audit_model, 'before_update', _reject_audit_mutation)
    event.listen(_audit_model, 'before_delete', _reject_audit_mutation)

    # Local SQLite testing uses create_all instead of Alembic. Install matching
    # database guards there too; PostgreSQL gets its triggers via migration b33.
    for _action in ('UPDATE', 'DELETE'):
        _trigger = f'trg_{_audit_model.__tablename__}_{_action.lower()}_b33'
        _ddl = DDL(
            f'CREATE TRIGGER IF NOT EXISTS {_trigger} BEFORE {_action} '
            f'ON {_audit_model.__tablename__} BEGIN '
            "SELECT RAISE(ABORT, 'Maintenance audit records are append-only'); END"
        )
        event.listen(_audit_model.__table__, 'after_create', _ddl.execute_if(dialect='sqlite'))
