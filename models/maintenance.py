"""
Maintenance Module Models — نماذج وحدة الصيانة
"""
from datetime import date, datetime, time, timezone
from decimal import Decimal
from extensions import db
from models.tenant_scope import TenantScopedMixin
from utils.helpers import generate_number


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

    # المالي
    payment_mode = db.Column(db.String(20), default='cash')  # cash/card/cheque/transfer/account
    deposit = db.Column(db.Numeric(15, 3), default=0)
    tax_inclusive = db.Column(db.Boolean, default=False)
    subtotal = db.Column(db.Numeric(15, 3), default=0)
    discount_line_total = db.Column(db.Numeric(15, 3), default=0)
    discount_total_value = db.Column(db.Numeric(15, 3), default=0)
    discount_total_percent = db.Column(db.Numeric(5, 2), default=0)
    tax_amount = db.Column(db.Numeric(15, 3), default=0)
    total_amount = db.Column(db.Numeric(15, 3), default=0)
    paid_amount = db.Column(db.Numeric(15, 3), default=0)
    balance_due = db.Column(db.Numeric(15, 3), default=0)

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

    def calculate_totals(self):
        self.subtotal = sum((Decimal(str(it.line_total)) for it in self.items), Decimal('0')) + \
                        sum((Decimal(str(sv.line_total)) for sv in self.services), Decimal('0'))
        disc_val = Decimal(str(self.discount_total_value or 0))
        disc_pct = Decimal(str(self.discount_total_percent or 0))
        if disc_pct > 0:
            self.subtotal = self.subtotal * (1 - disc_pct / 100)
        rate = Decimal(str(self.tax_rate or 0)) if hasattr(self, 'tax_rate') else Decimal('0')
        # tax handled at line level; aggregate here
        self.tax_amount = sum((Decimal(str(it.tax_amount or 0)) for it in self.items), Decimal('0')) + \
                          sum((Decimal(str(sv.tax_amount or 0)) for sv in self.services), Decimal('0'))
        self.total_amount = self.subtotal + self.tax_amount - disc_val
        self.balance_due = self.total_amount - Decimal(str(self.paid_amount or 0))


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
    discount_percent = db.Column(db.Numeric(5, 2), default=0)
    discount_value = db.Column(db.Numeric(15, 3), default=0)
    line_discount_mode = db.Column(db.String(10), default='percent')  # percent/value
    tax_rate = db.Column(db.Numeric(5, 2), default=0)
    tax_amount = db.Column(db.Numeric(15, 3), default=0)
    line_total = db.Column(db.Numeric(15, 3), default=0)
    movement_id = db.Column(db.Integer, db.ForeignKey('stock_movements.id'), nullable=True)

    order = db.relationship('MaintenanceOrder', back_populates='items')
    product = db.relationship('Product')
    warehouse = db.relationship('Warehouse')
    movement = db.relationship('StockMovement')

    def calculate_line_total(self):
        qty = Decimal(str(self.quantity or 0))
        price = Decimal(str(self.unit_price or 0))
        disc_pct = Decimal(str(self.discount_percent or 0))
        disc_val = Decimal(str(self.discount_value or 0))
        rate = Decimal(str(self.tax_rate or 0))

        base = qty * price
        if self.line_discount_mode == 'percent':
            base = base * (1 - disc_pct / 100)
        else:
            base = base - disc_val
        if base < 0:
            base = Decimal('0')
        self.tax_amount = (base * rate / 100).quantize(Decimal('0.001'))
        self.line_total = (base + self.tax_amount).quantize(Decimal('0.001'))


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
    discount_percent = db.Column(db.Numeric(5, 2), default=0)
    discount_value = db.Column(db.Numeric(15, 3), default=0)
    tax_rate = db.Column(db.Numeric(5, 2), default=0)
    tax_amount = db.Column(db.Numeric(15, 3), default=0)
    line_total = db.Column(db.Numeric(15, 3), default=0)
    engineer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    order = db.relationship('MaintenanceOrder', back_populates='services')
    engineer = db.relationship('User', foreign_keys=[engineer_id])

    def calculate_line_total(self):
        qty = Decimal('1')
        price = Decimal(str(self.unit_price or 0))
        disc_pct = Decimal(str(self.discount_percent or 0))
        disc_val = Decimal(str(self.discount_value or 0))
        rate = Decimal(str(self.tax_rate or 0))

        base = qty * price
        base = base * (1 - disc_pct / 100) - disc_val
        if base < 0:
            base = Decimal('0')
        self.tax_amount = (base * rate / 100).quantize(Decimal('0.001'))
        self.line_total = (base + self.tax_amount).quantize(Decimal('0.001'))


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
    subtotal = db.Column(db.Numeric(15, 3), default=0)
    discount_total = db.Column(db.Numeric(15, 3), default=0)
    tax_amount = db.Column(db.Numeric(15, 3), default=0)
    total_amount = db.Column(db.Numeric(15, 3), default=0)
    paid_amount = db.Column(db.Numeric(15, 3), default=0)
    balance_due = db.Column(db.Numeric(15, 3), default=0)
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
    returned_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    reason = db.Column(db.Text, nullable=True)
    total_value = db.Column(db.Numeric(15, 3), default=0)
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
# 12. سجل الأجهزة
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
