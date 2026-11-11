"""
Maintenance Service — منطق الأعمال لوحدة الصيانة

سياسة محاسبية معتمدة (انظر docs/maintenance_status.md):
  * القطع تُصرَف من المخزون بتكلفتها الفعلية (المتوسط المتحرك) عند الصرف،
    فيبقى حساب المخزون مطابقاً لمذكرة المخزون دائماً.
  * تكلفة العمل تُتابَع تحليلياً على الأمر ولا تُرحَّل، لأن الرواتب في هذا
    النظام تُحمَّل عند الصرف ولا يوجد مسار تسوية مستحقات.
  * الإيراد والضريبة يُعترف بهما عند ترحيل فاتورة الصيانة.
  * الأعمال المغطاة بالضمان لا تُحمَّل على العميل: تُعاد تبويب تكلفة قطعها
    من تكلفة الصيانة إلى مصروف الضمان.
  * التسليم الآجل مسموح: يغلق الأمر على الحساب بعد ترحيل الفاتورة والبقاء
    ضمن حد ائتمان العميل، أما النقدي فيشترط سداده كاملاً.
"""
import logging
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps
from uuid import uuid4

from extensions import db
from models.maintenance import (
    MaintenanceOrder, MaintenanceOrderItem, MaintenanceOrderService,
    MaintenanceOrderStatusLog, MaintenanceReceipt, MaintenanceInvoice,
    MaintenanceReturn, MaintenanceReturnLine, MaintenanceSetting,
    MaintenanceService, MaintenanceWarrantyAudit, MaintenanceDeviceRegistry,
    MaintenanceSupplierPayment,
)
from models.warehouse import Warehouse
from models.gl import GLJournalEntry, GLJournalLine
from models import Customer, Product, User
from services import maintenance_accounting as accounting
from services.costing_service import CostingService
from services.stock_service import StockService
from utils.decorators import tx
from utils.errors import ValidationError
from utils.feature_guards import is_feature_enabled
from services.maintenance_security import (
    current_maintenance_tenant, get_maintenance_order, require_maintenance_actor,
)

logger = logging.getLogger(__name__)

D = Decimal
ZERO = Decimal('0')

# الحالات التي يُسمح فيها بأن تُصدر فاتورة أو تُصرف قطع.
BILLABLE_STATUSES = ('in_progress', 'ready')
# الحالات التي يُسمح فيها بال르기/إلغاء الأمر.
EDITABLE_STATUSES = ('received', 'diagnosis', 'waiting_approval', 'in_progress',
                     'waiting_parts', 'on_hold')


def _unavailable(operation):
    """Fail closed until the operation has a verified workflow."""
    @wraps(operation)
    def blocked(*args, **kwargs):
        raise ValidationError('هذه العملية موقوفة مؤقتاً لحين استكمال تدقيق الصيانة')
    return blocked


def _intake_text(value, label, max_length):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError(f'{label} غير صالح')
    value = value.strip()
    if len(value) > max_length:
        raise ValidationError(f'{label} يتجاوز الحد المسموح ({max_length} حرفاً)')
    return value or None


def _decimal(value, label, *, maximum=None, allow_zero=True):
    try:
        number = D(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError(f'{label} غير صالح') from None
    if not number.is_finite():
        raise ValidationError(f'{label} غير صالح')
    if number < 0 or (number == 0 and not allow_zero):
        raise ValidationError(f'{label} يجب أن يكون أكبر من صفر')
    if maximum is not None and number > maximum:
        raise ValidationError(f'{label} يتجاوز الحد المسموح')
    return number


# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------
def _get_settings(tenant_id):
    s = MaintenanceSetting.query.filter_by(tenant_id=tenant_id).first()
    if not s:
        s = MaintenanceSetting(tenant_id=tenant_id)
        db.session.add(s)
        db.session.flush()
    return s


# ---------------------------------------------------------------------------
# 1. Create Maintenance Order
# ---------------------------------------------------------------------------
@tx
def create_maintenance_order(tenant_id, customer_id, received_by, **kwargs):
    """إنشاء أمر صيانة جديد."""
    if require_maintenance_actor(received_by, 'maintenance_receive') != tenant_id:
        raise ValidationError('نطاق التينانت غير صالح')
    if not is_feature_enabled('maintenance'):
        raise ValidationError('ميزة الصيانة غير مفعلة لهذا التينانت')

    customer = db.session.get(Customer, customer_id)
    if not customer or customer.tenant_id != tenant_id or not customer.is_active:
        raise ValidationError('العميل غير موجود أو لا يتبع هذا التينانت')

    receiver = db.session.get(User, received_by)
    if not receiver or not receiver.is_active:
        raise ValidationError('مستلم الأمر غير موجود')

    for field in ('engineer_id', 'service_advisor_id'):
        user_id = kwargs.get(field)
        if user_id is not None:
            user = db.session.get(User, user_id)
            if not user or user.tenant_id != tenant_id or not user.is_active:
                raise ValidationError('المستخدم المحدد غير موجود ضمن هذا التينانت')
    if kwargs.get('branch_id') not in (None, tenant_id):
        raise ValidationError('الفرع المحدد غير متاح')
    if kwargs.get('warranty_sale_id') is not None:
        raise ValidationError('ربط الضمان بالمبيعات غير متاح حالياً')
    if kwargs.get('priority', 'normal') not in ('low', 'normal', 'urgent'):
        raise ValidationError('الأولوية غير صالحة')
    if kwargs.get('payment_mode', 'cash') not in ('cash', 'card', 'cheque', 'transfer', 'account'):
        raise ValidationError('طريقة الدفع غير صالحة')
    deposit = _decimal(kwargs.get('deposit', 0), 'مبلغ الدفعة المقدمة')
    if deposit != 0:
        raise ValidationError('الدفعات المقدمة موقوفة مؤقتاً لحين اكتمال دورة القبض')

    for field, label, limit in (
        ('device_brand', 'العلامة التجارية', 100),
        ('device_model', 'الموديل', 100),
        ('device_serial', 'الرقم التسلسلي', 100),
        ('device_imei', 'IMEI', 100),
        ('device_plate', 'رقم اللوحة', 50),
        ('device_problem', 'وصف المشكلة', 10000),
        ('notes', 'الملاحظات', 10000),
        ('warranty_notes', 'ملاحظات الضمان', 10000),
    ):
        kwargs[field] = _intake_text(kwargs.get(field), label, limit)

    # --- warranty lookup: only the customer's own registered device -------
    device_serial = kwargs.get('device_serial')
    warranty_status = 'unknown'
    color_tag = '#f59e0b'  # yellow
    warranty_checked = False

    identifiers = {key: value for key, value in {
        'serial_number': device_serial,
        'imei': kwargs.get('device_imei'),
        'plate': kwargs.get('device_plate'),
    }.items() if value}
    matches = (MaintenanceDeviceRegistry.query.filter_by(
        tenant_id=tenant_id, customer_id=customer_id, **identifiers
    ).limit(2).all() if identifiers else [])
    # Duplicate identifiers are ambiguous: do not silently grant a warranty.
    reg = matches[0] if len(matches) == 1 else None

    if reg:
        warranty_checked = True
        if (reg.is_under_warranty and reg.warranty_end_date
                and date.today() <= reg.warranty_end_date
                and (not reg.purchase_date or reg.purchase_date <= date.today())):
            warranty_status = 'under_warranty'
            color_tag = '#10b981'  # green
        elif reg.warranty_end_date and date.today() > reg.warranty_end_date:
            warranty_status = 'expired'
            color_tag = '#ef4444'  # red

    # The shared number helper releases its lock before the order commits,
    # allowing concurrent requests to choose the same globally unique number.
    order_no = f'MN-{date.today().year}-{uuid4().hex.upper()}'

    order = MaintenanceOrder(
        tenant_id=tenant_id,
        branch_id=kwargs.get('branch_id') or tenant_id,
        order_no=order_no,
        customer_id=customer_id,
        device_brand=kwargs.get('device_brand'),
        device_model=kwargs.get('device_model'),
        device_serial=device_serial,
        device_imei=kwargs.get('device_imei'),
        device_plate=kwargs.get('device_plate'),
        device_problem=kwargs.get('device_problem'),
        valid_until=kwargs.get('valid_until'),
        status='received',
        priority=kwargs.get('priority', 'normal'),
        warranty_status=warranty_status,
        warranty_checked=warranty_checked,
        warranty_verified_by=receiver.id if warranty_checked else None,
        warranty_checked_at=datetime.now(timezone.utc) if warranty_checked else None,
        warranty_notes=kwargs.get('warranty_notes'),
        color_tag=color_tag,
        warranty_sale_id=kwargs.get('warranty_sale_id'),
        received_by=received_by,
        engineer_id=kwargs.get('engineer_id'),
        service_advisor_id=kwargs.get('service_advisor_id'),
        payment_mode=kwargs.get('payment_mode', 'cash'),
        deposit=deposit,
        tax_inclusive=bool(kwargs.get('tax_inclusive', False)),
        notes=kwargs.get('notes'),
    )
    db.session.add(order)
    db.session.flush()

    _log_status(order, None, 'received', received_by, 'إنشاء أمر صيانة جديد')

    if warranty_checked:
        _warranty_audit(tenant_id, order.id, customer_id, None, device_serial,
                        'checked', received_by, None, warranty_status,
                        'فحص الكفالة عند الاستقبال')

    order.calculate_totals()
    return order


# ---------------------------------------------------------------------------
# 2. Status transitions
# ---------------------------------------------------------------------------
ALLOWED_TRANSITIONS = {
    'received': ['diagnosis', 'cancelled'],
    'diagnosis': ['waiting_approval', 'in_progress', 'on_hold'],
    'waiting_approval': ['in_progress', 'received', 'cancelled'],
    'in_progress': ['waiting_parts', 'ready', 'on_hold'],
    'waiting_parts': ['in_progress', 'ready'],
    'ready': ['closed', 'on_hold'],
    'on_hold': ['in_progress', 'ready'],
    'closed': [],
    'cancelled': [],
}


@tx
def change_status(order_id, new_status, changed_by, note=None):
    """تغيير حالة أمر الصيانة مع تدقيق."""
    require_maintenance_actor(changed_by, 'maintenance_work')
    order = get_maintenance_order(order_id, for_update=True)
    if order is None:
        raise ValidationError('أمر الصيانة غير موجود')

    current = order.status
    allowed = ALLOWED_TRANSITIONS.get(current, [])
    if new_status not in allowed:
        raise ValidationError(f'لا يمكن الانتقال من {current} إلى {new_status}')

    if new_status == 'closed':
        require_maintenance_actor(changed_by, 'maintenance_close')
        _close_order(order, changed_by)
    elif new_status == 'cancelled':
        require_maintenance_actor(changed_by, 'maintenance_close')
        _cancel_order(order, changed_by)

    old_status = current
    order.status = new_status
    order.updated_at = datetime.now(timezone.utc)

    _log_status(order, old_status, new_status, changed_by, note)
    return order


def _close_order(order, changed_by):
    """Delivery policy: warranty work is free, cash must be paid, credit may
    be delivered once the invoice is posted and the credit limit holds."""
    if order.status != 'ready':
        raise ValidationError('لا يمكن إغلاق الأمر قبل أن يكون جاهزاً للتسليم')

    if accounting.is_warranty_order(order):
        # Warranty work is not charged: move its parts cost to warranty expense.
        if order.invoice:
            raise ValidationError('أمر الضمان لا يجب أن يكون له فاتورة للعميل')
        accounting.post_warranty_reclassification(order, created_by=changed_by)
        return

    invoice = order.invoice
    if not invoice or not invoice.gl_posted:
        raise ValidationError('لا يمكن التسليم قبل ترحيل فاتورة الصيانة')

    if order.payment_mode == 'account':
        _assert_within_credit_limit(order)
        return

    balance = D(str(order.balance_due or 0))
    if balance > 0:
        raise ValidationError(
            f'لا يمكن التسليم قبل سداد المبلغ المتبقي ({balance:,.3f} د.إ). '
            'التسليم الآجل متاح فقط للأوامر على الحساب.'
        )


def _assert_within_credit_limit(order):
    """Credit delivery: the customer must stay within the credit limit."""
    customer = order.customer
    limit = D(str(customer.credit_limit or 0))
    if limit <= 0:
        return
    outstanding = _maintenance_receivable(customer.id, order.tenant_id)
    exposure = D(str(customer.balance or 0)) + outstanding + D(str(order.balance_due or 0))
    if exposure > limit:
        raise ValidationError(
            f'تجاوز حد ائتمان العميل "{customer.name}"\n'
            f'💡 الحد: {limit:,.3f} د.إ | الرصيد الحالي: {customer.balance or 0:,.3f} د.إ | '
            f'ذمم الصيانة: {outstanding:,.3f} د.إ | المستحق بعد التسليم: {exposure:,.3f} د.إ'
        )


def _maintenance_receivable(customer_id, tenant_id) -> Decimal:
    """Outstanding maintenance receivable of a customer (invoices - receipts)."""
    invoiced = D('0')
    for invoice in MaintenanceInvoice.query.join(
            MaintenanceOrder, MaintenanceOrder.id == MaintenanceInvoice.maintenance_order_id
    ).filter(MaintenanceOrder.tenant_id == tenant_id,
              MaintenanceOrder.customer_id == customer_id).all():
        invoiced += D(str(invoice.total_amount or 0))
    collected = D('0')
    for receipt in MaintenanceReceipt.query.join(
            MaintenanceOrder, MaintenanceOrder.id == MaintenanceReceipt.maintenance_order_id
    ).filter(MaintenanceOrder.tenant_id == tenant_id,
              MaintenanceOrder.customer_id == customer_id).all():
        collected += D(str(receipt.amount or 0))
    return (invoiced - collected).quantize(D('0.001'))


def _cancel_order(order, changed_by):
    """An order may only be cancelled before any financial effect exists."""
    financial_amounts = (order.deposit, order.paid_amount, order.total_amount,
                          order.balance_due)
    if (order.items or order.services or order.receipts or order.invoice
            or any(D(str(amount or 0)) != 0 for amount in financial_amounts)):
        raise ValidationError('لا يمكن إلغاء أمر له بنود أو عمليات مالية قبل تنفيذ دورة العكس')
    for item in order.items:
        if D(str(item.returned_quantity or 0)) != D(str(item.quantity or 0)):
            raise ValidationError('يجب إرجاع القطع المصروفة إلى المخزون قبل إلغاء الأمر')


def _log_status(order, from_status, to_status, changed_by, note):
    log = MaintenanceOrderStatusLog(
        maintenance_order_id=order.id,
        from_status=from_status,
        to_status=to_status,
        changed_by=changed_by,
        note=note or '',
    )
    db.session.add(log)


# ---------------------------------------------------------------------------
# 3. Line items (parts / services)
# ---------------------------------------------------------------------------
@tx
def add_order_item(order_id, product_id, quantity, unit_price, tenant_id,
                   discount_percent=0, discount_value=0, line_discount_mode='percent',
                   tax_rate=0, warehouse_id=None, actor_id=None):
    """إضافة بند قطعة غيار: صرف من المخزون بتكلفة فعلية مع قيد محاسبي."""
    tenant = current_maintenance_tenant()
    if tenant != tenant_id:
        raise ValidationError('نطاق التينانت غير صالح')
    if actor_id is not None:
        require_maintenance_actor(actor_id, 'maintenance_work')

    order = get_maintenance_order(order_id, for_update=True)
    if order is None:
        raise ValidationError('أمر الصيانة غير موجود')
    if order.status not in EDITABLE_STATUSES:
        raise ValidationError('لا يمكن إضافة بنود في الحالة الحالية')
    if order.invoice:
        raise ValidationError('لا يمكن تعديل بنود أمر أُصدرت له فاتورة')

    product = Product.query.filter_by(id=product_id, tenant_id=tenant_id).first()
    if not product:
        raise ValidationError('المنتج غير موجود أو لا يتبع هذا التينانت')

    quantity = _decimal(quantity, 'الكمية', allow_zero=False)
    unit_price = _decimal(unit_price, 'سعر الوحدة', allow_zero=False)
    tax_rate = _decimal(tax_rate, 'معدل الضريبة', maximum=D('100'))
    discount_percent = _decimal(discount_percent, 'نسبة الخصم', maximum=D('100'))
    discount_value = _decimal(discount_value, 'قيمة الخصم')
    if line_discount_mode not in ('percent', 'value'):
        raise ValidationError('طريقة خصم البند غير صالحة')
    if (line_discount_mode == 'percent' and discount_value) or (line_discount_mode == 'value' and discount_percent):
        raise ValidationError('اختر طريقة واحدة لخصم البند')

    settings = _get_settings(tenant_id)
    if discount_percent > D(str(settings.max_discount_percent or 0)):
        raise ValidationError(f'الخصم يتجاوز السقف المسموح ({settings.max_discount_percent}%)')

    warehouse = None
    if warehouse_id is not None:
        warehouse = Warehouse.query.filter_by(id=warehouse_id, tenant_id=tenant_id,
                                              is_active=True).first()
        if not warehouse:
            raise ValidationError('المستودع غير موجود أو لا يتبع هذا التينانت')

    # Actual cost: the moving average, and a product without any cost basis is
    # refused (a part sold without cost would make the profit fictional).
    unit_cost = CostingService.cost_for_sale(product, quantity)

    available, message = StockService.check_availability(product.id, quantity,
                                                          warehouse_id=warehouse.id if warehouse else None)
    if not available:
        raise ValidationError(f'{product.name}: {message}')

    line = MaintenanceOrderItem(
        order=order,
        product_id=product.id,
        warehouse_id=warehouse.id if warehouse else None,
        quantity=quantity,
        unit_price=unit_price,
        discount_percent=discount_percent,
        discount_value=discount_value,
        line_discount_mode=line_discount_mode,
        tax_rate=tax_rate,
        cost_price=unit_cost,
        cost_source='inventory',
    )
    line.calculate_line_total()
    db.session.add(line)
    db.session.flush()

    movement = None
    if warehouse:
        movement = StockService.create_movement(
            product_id=product.id,
            quantity=-quantity,  # issue reduces stock
            movement_type='maintenance',
            reference_type='maintenance_order',
            reference_id=order.id,
            notes=f'صرف قطعة لأمر صيانة {order.order_no}',
            warehouse_id=warehouse.id,
        )
        line.movement_id = movement.id
        db.session.flush()

    # Cost leaves the inventory ledger at the actual cost of the part.
    accounting.post_parts_issue(order, line, unit_cost=unit_cost, quantity=quantity,
                                created_by=actor_id)

    order.calculate_totals()
    return line


@tx
def add_order_service(order_id, service_code, service_name, service_name_ar,
                      unit_price, duration_minutes, tenant_id,
                      discount_percent=0, discount_value=0, tax_rate=0,
                      engineer_id=None, cost_price=0, actor_id=None):
    """إضافة بند خدمة: سعر مع الضريبة، وتكلفة عمل تحليلية."""
    tenant = current_maintenance_tenant()
    if tenant != tenant_id:
        raise ValidationError('نطاق التينانت غير صالح')
    if actor_id is not None:
        require_maintenance_actor(actor_id, 'maintenance_work')

    order = get_maintenance_order(order_id, for_update=True)
    if order is None:
        raise ValidationError('أمر الصيانة غير موجود')
    if order.status not in EDITABLE_STATUSES:
        raise ValidationError('لا يمكن إضافة بنود في الحالة الحالية')
    if order.invoice:
        raise ValidationError('لا يمكن تعديل بنود أمر أُصدرت له فاتورة')

    if engineer_id is not None:
        engineer = db.session.get(User, engineer_id)
        if not engineer or engineer.tenant_id != tenant_id or not engineer.is_active:
            raise ValidationError('المهندس المحدد غير موجود ضمن هذا التينانت')

    settings = _get_settings(tenant_id)
    discount_percent = _decimal(discount_percent, 'نسبة الخصم', maximum=D('100'))
    if discount_percent > D(str(settings.max_discount_percent or 0)):
        raise ValidationError(f'الخصم يتجاوز السقف المسموح ({settings.max_discount_percent}%)')
    tax_rate = _decimal(tax_rate, 'معدل الضريبة', maximum=D('100'))
    unit_price = _decimal(unit_price, 'سعر الخدمة', allow_zero=False)
    cost_price = _decimal(cost_price, 'تكلفة الخدمة')

    line = MaintenanceOrderService(
        order=order,
        service_code=service_code,
        service_name=service_name,
        service_name_ar=service_name_ar,
        quantity=1,
        unit_price=unit_price,
        duration_minutes=int(duration_minutes or 0),
        discount_percent=discount_percent,
        discount_value=0,
        tax_rate=tax_rate,
        engineer_id=engineer_id,
        cost_price=cost_price,
        cost_source='labor',
    )
    line.calculate_line_total()
    db.session.add(line)
    order.calculate_totals()
    return line


# ---------------------------------------------------------------------------
# 4. Discount at order level
# ---------------------------------------------------------------------------
@tx
def apply_order_discount(order_id, discount_percent=None, discount_value=None,
                         changed_by=None, override=False):
    """تطبيق خصم على مستوى الأمر مع فحص السقف."""
    tenant = current_maintenance_tenant()
    if changed_by is not None:
        require_maintenance_actor(changed_by, 'maintenance_discount')

    order = get_maintenance_order(order_id, for_update=True)
    if order is None:
        raise ValidationError('أمر الصيانة غير موجود')
    if order.status not in EDITABLE_STATUSES:
        raise ValidationError('لا يمكن تطبيق خصم في الحالة الحالية')
    if order.invoice:
        raise ValidationError('لا يمكن تعديل خصم أمر أُصدرت له فاتورة')

    settings = _get_settings(order.tenant_id)

    if discount_percent is not None:
        percent = _decimal(discount_percent, 'نسبة الخصم', maximum=D('100'))
        if percent > D(str(settings.max_discount_percent or 0)) and not override:
            raise ValidationError(f'الخصم النسبة يتجاوز السقف ({settings.max_discount_percent}%)')
        order.discount_total_percent = percent
        order.discount_total_value = ZERO  # derived from the percentage
    elif discount_value is not None:
        value = _decimal(discount_value, 'قيمة الخصم')
        if value > D(str(settings.max_discount_value or 0)) and not override:
            raise ValidationError(f'الخصم القيمة يتجاوز السقف ({settings.max_discount_value})')
        order.discount_total_percent = ZERO
        order.discount_total_value = value
    else:
        # Neither given: the discount is cleared.
        order.discount_total_percent = ZERO
        order.discount_total_value = ZERO

    order.calculate_totals()
    return order


# ---------------------------------------------------------------------------
# 5. Warranty actions
# ---------------------------------------------------------------------------
@tx
def warranty_action(tenant_id, order_id, action, performed_by, reason=None,
                    serial_number=None, product_id=None):
    """إجراء على الكفالة: فحص / إلغاء / إعادة."""
    tenant = current_maintenance_tenant()
    if tenant != tenant_id:
        raise ValidationError('نطاق التينانت غير صالح')
    require_maintenance_actor(performed_by, 'maintenance_work')

    order = get_maintenance_order(order_id, for_update=True)
    if order is None:
        raise ValidationError('أمر الصيانة غير موجود')
    if order.invoice:
        raise ValidationError('لا يمكن تغيير حالة الضمان بعد إصدار الفاتورة')

    settings = _get_settings(tenant_id)
    user = db.session.get(User, performed_by)
    is_owner = bool(getattr(user, 'is_owner', False))

    if action == 'void':
        if not is_owner and not settings.allow_engineer_cancel_warranty:
            raise ValidationError('غير مصرح بإلغاء الكفالة')
        order.warranty_status = 'void'
        order.color_tag = '#ef4444'
    elif action == 'restore':
        if not is_owner and not settings.allow_engineer_restore_warranty:
            raise ValidationError('غير مصرح بإعادة الكفالة')
        order.warranty_status = 'under_warranty'
        order.color_tag = '#10b981'
    elif action == 'checked':
        order.warranty_checked = True
        order.warranty_verified_by = performed_by
        order.warranty_checked_at = datetime.now(timezone.utc)
    else:
        raise ValidationError('إجراء كفالة غير معروف')

    before = order.warranty_status
    _warranty_audit(tenant_id, order.id, order.customer_id, product_id or None,
                    serial_number or order.device_serial, action, performed_by,
                    before, order.warranty_status, reason or '')

    return order


def _warranty_audit(tenant_id, order_id, customer_id, product_id, serial_number,
                     action, performed_by, before, after, reason):
    audit = MaintenanceWarrantyAudit(
        tenant_id=tenant_id,
        maintenance_order_id=order_id,
        product_id=product_id,
        serial_number=serial_number,
        action=action,
        performed_by=performed_by,
        before_status=before,
        after_status=after,
        reason=reason,
    )
    db.session.add(audit)


# ---------------------------------------------------------------------------
# 6. Receipts (cashier only)
# ---------------------------------------------------------------------------
@tx
def create_receipt(order_id, amount, payment_method, cashier_id, reference_type=None,
                   reference_id=None):
    """إنشاء سند قبض لأمر الصيانة مع قيد التحصيل."""
    require_maintenance_actor(cashier_id, 'maintenance_cashier')
    order = get_maintenance_order(order_id, for_update=True)
    if order is None:
        raise ValidationError('أمر الصيانة غير موجود')
    if order.status in ('closed', 'cancelled'):
        raise ValidationError('لا يمكن القبض على أمر مغلق أو ملغي')
    if accounting.is_warranty_order(order):
        raise ValidationError('أمر الضمان لا يُقبض عليه من العميل')

    amount = _decimal(amount, 'المبلغ', allow_zero=False)
    balance = D(str(order.balance_due or 0))
    if balance <= 0:
        raise ValidationError('لا يوجد مبلغ مستحق على هذا الأمر')
    if amount > balance:
        raise ValidationError(f'المبلغ أكبر من المتبقي على الأمر ({balance:,.3f} د.إ)')

    receipt_no = _next_receipt_number()
    receipt = MaintenanceReceipt(
        maintenance_order_id=order.id,
        receipt_no=receipt_no,
        amount=amount,
        payment_method=payment_method,
        cashier_id=cashier_id,
        reference_type=reference_type,
        reference_id=reference_id,
        posted=False,
    )
    db.session.add(receipt)
    db.session.flush()

    accounting.post_maintenance_receipt(receipt, created_by=cashier_id)

    order.paid_amount = D(str(order.paid_amount or 0)) + amount
    order.balance_due = order.total_amount - order.paid_amount
    return receipt


def _next_receipt_number():
    from utils.helpers import generate_number
    return generate_number('PT-MN', MaintenanceReceipt, 'receipt_no')


# ---------------------------------------------------------------------------
# 7. Maintenance invoice
# ---------------------------------------------------------------------------
@tx
def create_maintenance_invoice(order_id, created_by):
    """إنشاء فاتورة صيانة مستقلة وترحيل إيرادها وضريبتها."""
    require_maintenance_actor(created_by, 'maintenance_close')
    order = get_maintenance_order(order_id, for_update=True)
    if order is None:
        raise ValidationError('أمر الصيانة غير موجود')
    if order.invoice:
        raise ValidationError('الفاتورة موجودة بالفعل لهذا الأمر')
    if order.status not in BILLABLE_STATUSES:
        raise ValidationError('لا يمكن إصدار فاتورة قبل بدء التنفيذ')
    if not (order.items or order.services):
        raise ValidationError('لا يمكن إصدار فاتورة لأمر بلا بنود')
    if accounting.is_warranty_order(order):
        raise ValidationError('أمر الضمان لا يُصدر له فاتورة للعميل')

    order.calculate_totals()
    net = accounting.order_net_revenue(order)
    vat = D(str(order.tax_amount or 0))
    if net + vat <= 0:
        raise ValidationError('لا يمكن إصدار فاتورة بقيمة صفر')

    from utils.helpers import generate_number
    invoice = MaintenanceInvoice(
        order=order,
        invoice_no=generate_number('MI', MaintenanceInvoice, 'invoice_no'),
        subtotal=order.subtotal,
        discount_total=order.discount_total_value,
        tax_amount=vat,
        total_amount=order.total_amount,
        paid_amount=order.paid_amount,
        balance_due=order.balance_due,
        posted=True,
        posted_at=datetime.now(timezone.utc),
        gl_posted=False,
    )
    db.session.add(invoice)
    db.session.flush()

    accounting.post_maintenance_invoice(order, invoice, created_by=created_by)
    return invoice


# ---------------------------------------------------------------------------
# 8. Returns
# ---------------------------------------------------------------------------
@tx
def create_maintenance_return(order_id, returned_by, reason, lines=None):
    """إنشاء مرتجع صيانة: إرجاع القطع إلى المخزون وعكس تكلفتها."""
    require_maintenance_actor(returned_by, 'maintenance_work')
    order = get_maintenance_order(order_id, for_update=True)
    if order is None:
        raise ValidationError('أمر الصيانة غير موجود')
    if order.status in ('closed', 'cancelled'):
        raise ValidationError('لا يمكن إنشاء مرتجع على أمر مغلق أو ملغي')
    if order.invoice:
        raise ValidationError('لا يمكن إنشاء مرتجع بعد إصدار الفاتورة — يلزم إشعار دائن')

    from utils.helpers import generate_number
    ret = MaintenanceReturn(
        order=order,
        return_no=generate_number('MR', MaintenanceReturn, 'return_no'),
        returned_by=returned_by,
        reason=reason,
        total_value=ZERO,
        posted=False,
    )
    db.session.add(ret)
    db.session.flush()

    total = ZERO
    cost_total = ZERO
    for ln in (lines or []):
        item = None
        if ln.get('order_item_id'):
            item = MaintenanceOrderItem.query.filter_by(
                id=ln['order_item_id'], maintenance_order_id=order.id).first()
            if not item:
                raise ValidationError('بند المرتجع غير موجود ضمن هذا الأمر')
        service = None
        if ln.get('order_service_id'):
            service = MaintenanceOrderService.query.filter_by(
                id=ln['order_service_id'], maintenance_order_id=order.id).first()
            if not service:
                raise ValidationError('بند الخدمة المرتجع غير موجود ضمن هذا الأمر')
        if not item and not service:
            raise ValidationError('سطر المرتجع لا يشير إلى بند')

        quantity = _decimal(ln.get('quantity', 1), 'كمية المرتجع', allow_zero=False)
        unit_price = D(str(ln.get('unit_price', 0) or 0))
        if unit_price <= 0:
            unit_price = D(str((item or service).unit_price or 0))

        if item is not None:
            already = D(str(item.returned_quantity or 0))
            if already + quantity > D(str(item.quantity or 0)):
                raise ValidationError('كمية المرتجع تتجاوز الكمية المصروفة')
            item.returned_quantity = already + quantity
            cost_total += D(str(item.cost_price or 0)) * quantity

        rline = MaintenanceReturnLine(
            return_id=ret.id,
            order_item_id=item.id if item else None,
            order_service_id=service.id if service else None,
            quantity=quantity,
            unit_price=unit_price,
        )
        rline.line_total = rline.quantity * rline.unit_price
        total += rline.line_total
        db.session.add(rline)

        if item is not None and item.warehouse_id:
            StockService.create_movement(
                product_id=item.product_id,
                quantity=quantity,  # positive = return to stock
                movement_type='maintenance_return',
                reference_type='maintenance_return',
                reference_id=ret.id,
                notes=f'إرجاع قطعة لأمر {order.order_no}',
                warehouse_id=item.warehouse_id,
            )

    ret.total_value = total
    if cost_total > 0:
        accounting.post_return_cost(order, ret, cost_total, created_by=returned_by)
        ret.posted = True
        ret.posted_at = datetime.now(timezone.utc)

    order.calculate_totals()
    return ret


# ---------------------------------------------------------------------------
# 9. Query helpers
# ---------------------------------------------------------------------------
def get_orders(tenant_id, status=None, date_from=None, date_to=None,
               customer_id=None, engineer_id=None, warranty_status=None,
               page=1, per_page=20):
    """استعلام عن أوامر الصيانة مع عزل تينانت."""
    if tenant_id != current_maintenance_tenant():
        raise ValidationError('نطاق التينانت غير صالح')

    def parse_date(value):
        if not value:
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        try:
            return date.fromisoformat(value)
        except (ValueError, TypeError):
            raise ValidationError('صيغة التاريخ غير صالحة') from None

    start, end = parse_date(date_from), parse_date(date_to)
    if start and end and start > end:
        raise ValidationError('تاريخ البداية يجب ألا يتجاوز تاريخ النهاية')

    q = (MaintenanceOrder.query
         .join(Customer, Customer.id == MaintenanceOrder.customer_id)
         .filter(MaintenanceOrder.tenant_id == tenant_id, Customer.tenant_id == tenant_id,
                 MaintenanceOrder.is_archived.is_(False)))
    if status:
        q = q.filter_by(status=status)
    if customer_id:
        q = q.filter_by(customer_id=customer_id)
    if engineer_id:
        q = q.filter_by(engineer_id=engineer_id)
    if warranty_status:
        q = q.filter_by(warranty_status=warranty_status)
    if start:
        q = q.filter(MaintenanceOrder.received_at >= datetime.combine(start, time.min))
    if end and end < date.max:
        q = q.filter(MaintenanceOrder.received_at < datetime.combine(end + timedelta(days=1), time.min))
    return q.order_by(MaintenanceOrder.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )


# ---------------------------------------------------------------------------
# 10. Warranty auto-check
# ---------------------------------------------------------------------------
def auto_check_warranty_from_sales(tenant_id, serial_number=None, imei=None,
                                   plate=None, customer_id=None):
    """Check the tenant's device registry, without inferring a sales warranty."""
    if tenant_id != current_maintenance_tenant():
        raise ValidationError('نطاق التينانت غير صالح')
    warranty_info = {
        'warranty_status': 'unknown',
        'warranty_type': None,
        'warranty_start_date': None,
        'warranty_end_date': None,
        'sale_id': None,
        'is_under_warranty': False,
        'days_remaining': None,
        'message': 'لا يوجد سجل ضمان'
    }

    query = MaintenanceDeviceRegistry.query.filter_by(tenant_id=tenant_id)
    if customer_id is not None:
        query = query.filter_by(customer_id=customer_id)
    identifiers = {
        'serial_number': _intake_text(serial_number, 'الرقم التسلسلي', 100),
        'imei': _intake_text(imei, 'IMEI', 100),
        'plate': _intake_text(plate, 'رقم اللوحة', 50),
    }
    identifiers = {key: value for key, value in identifiers.items() if value}
    matches = query.filter_by(**identifiers).limit(2).all() if identifiers else []
    reg = matches[0] if len(matches) == 1 else None

    if reg and reg.warranty_end_date:
        warranty_info['warranty_type'] = reg.warranty_type
        warranty_info['warranty_start_date'] = reg.purchase_date
        warranty_info['warranty_end_date'] = reg.warranty_end_date
        warranty_info['is_under_warranty'] = bool(
            reg.is_under_warranty and reg.warranty_end_date >= date.today()
            and (not reg.purchase_date or reg.purchase_date <= date.today())
        )
        if warranty_info['is_under_warranty']:
            warranty_info['warranty_status'] = 'under_warranty'
            warranty_info['days_remaining'] = (reg.warranty_end_date - date.today()).days
            warranty_info['message'] = 'الجهاز تحت الضمان'
        elif reg.warranty_end_date < date.today():
            warranty_info['warranty_status'] = 'expired'
            warranty_info['message'] = 'الضمان منتهي'

    return warranty_info


# ---------------------------------------------------------------------------
# 11. Stock availability
# ---------------------------------------------------------------------------
def check_stock_availability(tenant_id, product_id, warehouse_id, quantity):
    """التحقق من توفر المخزون قبل الصرف."""
    if tenant_id != current_maintenance_tenant():
        raise ValidationError('نطاق التينانت غير صالح')
    product = Product.query.filter_by(id=product_id, tenant_id=tenant_id).first()
    if not product:
        return {'available': False, 'message': 'المنتج غير موجود', 'current_stock': ZERO}

    available, message = StockService.check_availability(product_id, quantity,
                                                          warehouse_id=warehouse_id)
    current = D(str(product.current_stock or 0))
    result = {'available': available, 'message': message, 'current_stock': current,
              'requested': D(str(quantity or 0))}
    if available:
        result['remaining_after'] = current - D(str(quantity or 0))
    else:
        result['shortage'] = D(str(quantity or 0)) - current
    return result


# ---------------------------------------------------------------------------
# 12. Maintenance cost analysis
# ---------------------------------------------------------------------------
def get_maintenance_cost_analysis(tenant_id, date_from=None, date_to=None):
    """تحليل تكلفة الصيانة وهوامش الربح (تقديري للأجور، فعلي للقطع)."""
    if tenant_id != current_maintenance_tenant():
        raise ValidationError('نطاق التينانت غير صالح')
    q = (MaintenanceOrder.query
         .join(Customer, Customer.id == MaintenanceOrder.customer_id)
         .filter(MaintenanceOrder.tenant_id == tenant_id, Customer.tenant_id == tenant_id,
                 MaintenanceOrder.is_archived.is_(False)))
    if date_from:
        q = q.filter(MaintenanceOrder.received_at >= date_from)
    if date_to:
        q = q.filter(MaintenanceOrder.received_at <= date_to)

    orders = q.all()
    analysis = {
        'total_orders': len(orders),
        'total_revenue': ZERO,
        'total_parts_cost': ZERO,
        'total_labor_cost': ZERO,
        'total_tax': ZERO,
        'total_discount': ZERO,
        'total_paid': ZERO,
        'gross_profit': ZERO,
        'profit_margin_pct': ZERO,
        'orders_by_status': {},
        'orders_by_warranty': {},
        'top_profit_orders': [],
        'loss_orders': [],
    }

    for order in orders:
        parts_cost = sum((D(str(it.cost_price or 0)) * D(str(it.quantity or 0))
                          for it in order.items), ZERO)
        labor_cost = sum((D(str(sv.cost_price or 0)) for sv in order.services), ZERO)
        total_cost = parts_cost + labor_cost
        # Revenue is recognised net of VAT; VAT is a liability, not revenue.
        revenue = D(str(order.total_amount or 0)) - D(str(order.tax_amount or 0))

        analysis['total_revenue'] += revenue
        analysis['total_parts_cost'] += parts_cost
        analysis['total_labor_cost'] += labor_cost
        analysis['total_tax'] += D(str(order.tax_amount or 0))
        analysis['total_discount'] += D(str(order.discount_total_value or 0))
        analysis['total_paid'] += D(str(order.paid_amount or 0))

        analysis['orders_by_status'][order.status] = analysis['orders_by_status'].get(order.status, 0) + 1
        ws = order.warranty_status or 'unknown'
        analysis['orders_by_warranty'][ws] = analysis['orders_by_warranty'].get(ws, 0) + 1

        profit = revenue - total_cost
        analysis['gross_profit'] += profit

        info = {
            'order_no': order.order_no,
            'revenue': revenue,
            'cost': total_cost,
            'profit': profit,
            'margin_pct': (profit / revenue * 100) if revenue > 0 else ZERO,
            'customer': order.customer.name if order.customer else '-',
        }
        if profit < 0:
            analysis['loss_orders'].append(info)
        else:
            analysis['top_profit_orders'].append(info)

    analysis['top_profit_orders'].sort(key=lambda row: row['profit'], reverse=True)
    analysis['top_profit_orders'] = analysis['top_profit_orders'][:10]
    analysis['gross_profit'] = analysis['total_revenue'] - analysis['total_parts_cost'] - analysis['total_labor_cost']
    if analysis['total_revenue'] > 0:
        analysis['profit_margin_pct'] = analysis['gross_profit'] / analysis['total_revenue'] * 100
    return analysis


# ---------------------------------------------------------------------------
# 13. Notifications
# ---------------------------------------------------------------------------
@tx
def send_customer_notification(order_id, channel='whatsapp', custom_message=None,
                               actor_id=None):
    """Send a real notification to the customer and report the actual outcome.

    The provider (WhatsApp/UltraMsg) decides whether the message goes out;
    the caller is told exactly what happened, never a fabricated "sent".
    """
    if actor_id is not None:
        require_maintenance_actor(actor_id, 'maintenance_work')
    order = get_maintenance_order(order_id)
    if order is None:
        raise ValidationError('أمر الصيانة غير موجود')
    customer = order.customer
    if not customer:
        raise ValidationError('العميل غير موجود')

    message = custom_message or (
        f'عزيزي {customer.name}، تم استلام جهازكم بأمر صيانة رقم {order.order_no}. '
        'سنوافكمكم بالجديد عند انتهاء الإصلاح.'
    )

    channel = (channel or 'whatsapp').strip().lower()
    result = {'channel': channel, 'sent': False, 'error': None, 'contact': None,
              'message': message, 'order_no': order.order_no}

    if channel == 'whatsapp':
        from services.whatsapp_service import WhatsAppService
        contact = customer.phone
        result['contact'] = contact
        if not contact:
            result['error'] = 'لا يوجد رقم هاتف للعميل'
        else:
            response = WhatsAppService.send_custom_message(contact, message)
            result['sent'] = bool(response.get('success'))
            result['error'] = response.get('error')
    elif channel == 'email':
        result['contact'] = customer.email
        result['error'] = 'قناة البريد غير مفعّلة: لا يوجد مزود بريد مرتبط'
    elif channel == 'sms':
        result['error'] = 'قناة الرسائل النصية غير مفعّلة'
    else:
        raise ValidationError('قناة إشعار غير معروفة')

    try:
        from utils.helpers import create_audit_log
        create_audit_log('maintenance_notify', 'maintenance_orders', order.id, {
            'channel': channel, 'sent': result['sent'], 'error': result['error'],
        })
    except Exception:  # pragma: no cover - auditing must not break delivery
        logger.exception('Could not write the notification audit for order %s', order.id)

    return result


# ---------------------------------------------------------------------------
# 14. Supplier purchase of parts — maintenance payables
# ---------------------------------------------------------------------------
@tx
def create_maintenance_purchase(tenant_id, supplier_id, warehouse_id, lines_data,
                                user_id, expected_delivery=None, notes=None,
                                tax_rate=0):
    """Create a purchase order for maintenance parts.

    A purchase order is not a financial event: nothing is posted to the ledger
    until the goods are received (see receive_maintenance_purchase).
    """
    tenant = current_maintenance_tenant()
    if tenant != tenant_id:
        raise ValidationError('نطاق التينانت غير صالح')
    require_maintenance_actor(user_id, 'maintenance_purchase')

    from models import Supplier
    from models.erp_modules import PurchaseOrder, PurchaseOrderLine

    supplier = Supplier.query.filter_by(id=supplier_id, tenant_id=tenant_id).first()
    if not supplier:
        raise ValidationError('المورد غير موجود أو لا يتبع هذا التينانت')
    warehouse = Warehouse.query.filter_by(id=warehouse_id, tenant_id=tenant_id,
                                          is_active=True).first()
    if not warehouse:
        raise ValidationError('المستودع غير موجود أو لا يتبع هذا التينانت')
    if not lines_data:
        raise ValidationError('أضف بنداً واحداً على الأقل')

    tax_rate = _decimal(tax_rate, 'معدل الضريبة', maximum=D('100'))

    from utils.helpers import generate_number
    purchase = PurchaseOrder(
        tenant_id=tenant_id,
        po_number=generate_number('MN-PO', PurchaseOrder, 'po_number'),
        supplier_id=supplier.id,
        warehouse_id=warehouse.id,
        requested_by_id=user_id,
        po_date=date.today(),
        expected_delivery=expected_delivery,
        tax_rate=tax_rate,
        status='approved',
        approved_by_id=user_id,
        approved_at=datetime.now(timezone.utc),
        notes=notes,
    )
    db.session.add(purchase)
    db.session.flush()

    for entry in lines_data:
        product = Product.query.filter_by(id=entry.get('product_id'),
                                          tenant_id=tenant_id).first()
        if not product:
            raise ValidationError('أحد منتجات أمر الشراء غير موجود ضمن هذا التينانت')
        quantity = _decimal(entry.get('quantity'), 'الكمية', allow_zero=False)
        unit_cost = _decimal(entry.get('unit_cost'), 'تكلفة الوحدة', allow_zero=False)
        line = PurchaseOrderLine(
            order=purchase,
            product_id=product.id,
            quantity=quantity,
            unit_cost=unit_cost,
            discount_percent=D('0'),
        )
        line.calculate_line_total()
        db.session.add(line)

    db.session.flush()
    purchase.calculate_totals()
    return purchase


@tx
def receive_maintenance_purchase(purchase_id, user_id):
    """Receive the purchased parts: stock in at cost and a maintenance payable."""
    require_maintenance_actor(user_id, 'maintenance_purchase')
    tenant_id = current_maintenance_tenant()

    from models.erp_modules import PurchaseOrder
    purchase = PurchaseOrder.query.filter_by(id=purchase_id, tenant_id=tenant_id).first()
    if not purchase:
        raise ValidationError('أمر الشراء غير موجود')
    if purchase.status in ('received', 'cancelled'):
        raise ValidationError('هذا أمر الشراء مستلم أو ملغي بالفعل')

    for line in purchase.lines:
        remaining = D(str(line.quantity or 0)) - D(str(line.received_quantity or 0))
        if remaining <= 0:
            continue
        StockService.create_movement(
            product_id=line.product_id,
            quantity=remaining,
            movement_type='purchase',
            reference_type='maintenance_purchase',
            reference_id=purchase.id,
            notes=f'استلام قطع صيانة - {purchase.po_number}',
            warehouse_id=purchase.warehouse_id,
            unit_cost_base=D(str(line.unit_cost or 0)),
        )
        line.received_quantity = D(str(line.quantity or 0))

    purchase.status = 'received'
    db.session.flush()
    accounting.post_goods_receipt(purchase, created_by=user_id)
    return purchase


@tx
def pay_maintenance_supplier(supplier_id, amount, payment_method, user_id,
                              reference_number=None, notes=None):
    """Settle what the tenant owes a supplier for maintenance parts."""
    require_maintenance_actor(user_id, 'maintenance_cashier')
    tenant_id = current_maintenance_tenant()

    from models import Supplier
    from models.erp_modules import PurchaseOrder
    supplier = Supplier.query.filter_by(id=supplier_id, tenant_id=tenant_id).first()
    if not supplier:
        raise ValidationError('المورد غير موجود أو لا يتبع هذا التينانت')

    outstanding = _maintenance_payable(supplier.id, tenant_id)
    amount = _decimal(amount, 'المبلغ', allow_zero=False)
    if amount > outstanding:
        raise ValidationError(f'المبلغ أكبر من الذمم الدائنة ({outstanding:,.3f} د.إ)')

    from utils.helpers import generate_number
    payment = MaintenanceSupplierPayment(
        tenant_id=tenant_id,
        supplier_id=supplier.id,
        amount=amount,
        payment_method=payment_method,
        reference_number=reference_number,
        notes=notes,
        posted=False,
        created_by=user_id,
    )
    db.session.add(payment)
    db.session.flush()

    accounting.post_supplier_payment(payment, created_by=user_id)
    payment.posted = True
    payment.posted_at = datetime.now(timezone.utc)
    return {'supplier': supplier, 'payment': payment, 'amount': amount,
            'outstanding_after': outstanding - amount}


def _maintenance_payable(supplier_id, tenant_id) -> Decimal:
    """Outstanding maintenance payable of a supplier (received - paid)."""
    from models.erp_modules import PurchaseOrder
    received = ZERO
    for purchase in PurchaseOrder.query.filter_by(
            tenant_id=tenant_id, supplier_id=supplier_id, status='received').all():
        received += D(str(purchase.total_amount or 0))
    paid = ZERO
    for payment in MaintenanceSupplierPayment.query.filter_by(
            tenant_id=tenant_id, supplier_id=supplier_id).all():
        paid += D(str(payment.amount or 0))
    return (received - paid).quantize(D('0.001'))


# ---------------------------------------------------------------------------
# 15. Overdue orders
# ---------------------------------------------------------------------------
def get_overdue_orders(tenant_id):
    """الحصول على أوامر الصيانة المتأخرة (أكثر من 7 أيام بدون إغلاق)."""
    if tenant_id != current_maintenance_tenant():
        raise ValidationError('نطاق التينانت غير صالح')
    cutoff = date.today() - timedelta(days=7)
    q = MaintenanceOrder.query.filter(
        MaintenanceOrder.tenant_id == tenant_id,
        MaintenanceOrder.is_archived == False,
        MaintenanceOrder.status.in_(['received', 'diagnosis', 'waiting_approval',
                                     'in_progress', 'waiting_parts']),
        MaintenanceOrder.received_at < cutoff,
    )
    return q.order_by(MaintenanceOrder.received_at.asc()).all()


# ---------------------------------------------------------------------------
# 16. Quality control and completion time
# ---------------------------------------------------------------------------
@tx
def quality_check(order_id, passed, checked_by, notes=None):
    """فحص جودة الأمر بعد الإكمال."""
    require_maintenance_actor(checked_by, 'maintenance_work')
    order = get_maintenance_order(order_id, for_update=True)
    if order is None:
        raise ValidationError('أمر الصيانة غير موجود')

    order.quality_check_passed = passed
    order.quality_check_by = checked_by
    order.quality_check_at = datetime.now(timezone.utc)
    if notes:
        order.technician_notes = (order.technician_notes or '') + f'\n[fq] {notes}'
    return order


@tx
def set_completion_time(order_id, hours, changed_by):
    """تسجيل وقت الإكمال الفعلي بالساعات."""
    require_maintenance_actor(changed_by, 'maintenance_work')
    order = get_maintenance_order(order_id, for_update=True)
    if order is None:
        raise ValidationError('أمر الصيانة غير موجود')
    hours = _decimal(hours, 'وقت الإكمال')
    order.completion_time_hours = hours
    return order


# ---------------------------------------------------------------------------
# 17. Quality audit trail
# ---------------------------------------------------------------------------
def get_audit_trail(tenant_id, order_id=None, date_from=None, date_to=None):
    """الحصول على مسار التدقيق الكامل لأوامر الصيانة."""
    if tenant_id != current_maintenance_tenant():
        raise ValidationError('نطاق التينانت غير صالح')
    q = MaintenanceWarrantyAudit.query.filter_by(tenant_id=tenant_id)
    if order_id:
        q = q.filter_by(maintenance_order_id=order_id)
    if date_from:
        q = q.filter(MaintenanceWarrantyAudit.performed_at >= date_from)
    if date_to:
        q = q.filter(MaintenanceWarrantyAudit.performed_at <= date_to)

    return q.order_by(MaintenanceWarrantyAudit.performed_at.desc()).all()
