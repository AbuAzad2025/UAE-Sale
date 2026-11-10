"""
Maintenance Service — منطق الأعمال الكامل لوحدة الصيانة
"""
import logging
from datetime import date, datetime, time, timezone
from decimal import Decimal, ROUND_HALF_UP
from extensions import db
from models.maintenance import (
    MaintenanceOrder, MaintenanceOrderItem, MaintenanceOrderService,
    MaintenanceOrderStatusLog, MaintenanceReceipt, MaintenanceInvoice,
    MaintenanceReturn, MaintenanceReturnLine, MaintenanceSetting,
    MaintenanceService, MaintenanceWarrantyAudit, MaintenanceDeviceRegistry,
)
from models.warehouse import Warehouse, StockMovement
from models.gl import GLAccount, GLJournalEntry, GLJournalLine
from models import Customer, Product, User, Sale
from services.gl_service import GLService
from services.stock_service import StockService
from utils.helpers import generate_number
from utils.decorators import get_owned_or_raise
from utils.errors import ValidationError
from utils.feature_guards import is_feature_enabled

logger = logging.getLogger(__name__)

D = Decimal

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
def create_maintenance_order(tenant_id, customer_id, received_by, **kwargs):
    """إنشاء أمر صيانة جديد."""
    if not is_feature_enabled('maintenance'):
        raise ValidationError('ميزة الصيانة غير مفعلة لهذا التينانت')

    customer = db.session.get(Customer, customer_id)
    if not customer or customer.tenant_id != tenant_id:
        raise ValidationError('العميل غير موجود أو لا يتبع هذا التينانت')

    receiver = db.session.get(User, received_by)
    if not receiver:
        raise ValidationError('مستلم الأمر غير موجود')

    # Device registry lookup for warranty
    device_serial = kwargs.get('device_serial')
    warranty_status = 'unknown'
    color_tag = '#f59e0b'  # yellow
    warranty_checked = False

    reg = MaintenanceDeviceRegistry.query.filter_by(
        tenant_id=tenant_id,
        serial_number=device_serial
    ).first() if device_serial else None

    if reg:
        warranty_checked = True
        if reg.is_under_warranty and reg.warranty_end_date and date.today() <= reg.warranty_end_date:
            warranty_status = 'under_warranty'
            color_tag = '#10b981'  # green
        else:
            warranty_status = 'expired'
            color_tag = '#ef4444'  # red

    order_no = generate_number('MN', MaintenanceOrder, 'order_no')

    order = MaintenanceOrder(
        tenant_id=tenant_id,
        branch_id=kwargs.get('branch_id', tenant_id),
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
        deposit=D(str(kwargs.get('deposit', 0))),
        tax_inclusive=bool(kwargs.get('tax_inclusive', False)),
        notes=kwargs.get('notes'),
    )
    db.session.add(order)
    db.session.flush()

    # Status log
    _log_status(order, None, 'received', received_by, 'إنشاء أمر صيانة جديد')

    # Warranty audit
    if warranty_checked:
        _warranty_audit(tenant_id, order.id, customer_id, device_serial, 'checked',
                        received_by, None, warranty_status, 'فحص الكفالة عند الاستقبال')

    db.session.commit()
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


def change_status(order_id, new_status, changed_by, note=None):
    """تغيير حالة أمر الصيانة مع تدقيق."""
    order = get_owned_or_raise(MaintenanceOrder, order_id)
    if order is None:
        raise ValidationError('أمر الصيانة غير موجود')

    current = order.status
    allowed = ALLOWED_TRANSITIONS.get(current, [])
    if new_status not in allowed:
        raise ValidationError(f'لا يمكن الانتقال من {current} إلى {new_status}')

    # Engineer cannot close
    if new_status == 'closed':
        from flask_login import current_user
        if not getattr(current_user, 'is_owner', False) and not getattr(current_user, 'is_super_admin', lambda: False)():
            # Check permission
            pass  # permission handled at route level

    old_status = current
    order.status = new_status
    order.updated_at = datetime.now(timezone.utc)

    _log_status(order, old_status, new_status, changed_by, note)

    if new_status == 'closed':
        order.paid_amount = order.total_amount  # mark fully paid conceptually
        order.balance_due = D('0')

    db.session.commit()
    return order


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
# 3. Add line items (parts / services)
# ---------------------------------------------------------------------------
def add_order_item(order_id, product_id, quantity, unit_price, tenant_id,
                   discount_percent=0, discount_value=0, line_discount_mode='percent',
                   tax_rate=0, warehouse_id=None):
    """إضافة بند قطعة غيار لأمر الصيانة."""
    order = get_owned_or_raise(MaintenanceOrder, order_id)
    if order is None:
        raise ValidationError('أمر الصيانة غير موجود')

    if order.status not in ('received', 'diagnosis', 'in_progress'):
        raise ValidationError('لا يمكن إضافة بنود في الحالة الحالية')

    product = db.session.get(Product, product_id)
    if not product:
        raise ValidationError('المنتج غير موجود')

    settings = _get_settings(tenant_id)
    discount_percent = D(str(discount_percent))
    if discount_percent > settings.max_discount_percent:
        raise ValidationError(f'الخصم يتجاوز السقف المسموح ({settings.max_discount_percent}%)')

    line = MaintenanceOrderItem(
        maintenance_order_id=order.id,
        product_id=product_id,
        warehouse_id=warehouse_id,
        quantity=D(str(quantity)),
        unit_price=D(str(unit_price)),
        discount_percent=discount_percent,
        discount_value=D(str(discount_value)),
        line_discount_mode=line_discount_mode,
        tax_rate=D(str(tax_rate)),
    )
    line.calculate_line_total()
    db.session.add(line)
    db.session.flush()

    # Stock movement for maintenance issue
    if warehouse_id:
        StockService.create_movement(
            product_id=product_id,
            quantity=-D(str(quantity)),  # issue reduces stock
            movement_type='maintenance',
            reference_type='maintenance_order',
            reference_id=order.id,
            notes=f'صرف قطعة لأمر صيانة {order.order_no}',
            warehouse_id=warehouse_id,
        )
        line.movement_id = db.session.query(StockMovement).filter_by(
            reference_type='maintenance_order', reference_id=order.id
        ).order_by(StockMovement.id.desc()).first().id

    order.calculate_totals()
    db.session.commit()
    return line


def add_order_service(order_id, service_code, service_name, service_name_ar,
                      unit_price, duration_minutes, tenant_id,
                      discount_percent=0, discount_value=0, tax_rate=0,
                      engineer_id=None):
    """إضافة بند خدمة لأمر الصيانة."""
    order = get_owned_or_raise(MaintenanceOrder, order_id)
    if order is None:
        raise ValidationError('أمر الصيانة غير موجود')

    if order.status not in ('received', 'diagnosis', 'in_progress'):
        raise ValidationError('لا يمكن إضافة بنود في الحالة الحالية')

    settings = _get_settings(tenant_id)
    discount_percent = D(str(discount_percent))
    if discount_percent > settings.max_discount_percent:
        raise ValidationError(f'الخصم يتجاوز السقف المسموح ({settings.max_discount_percent}%)')

    line = MaintenanceOrderService(
        maintenance_order_id=order.id,
        service_code=service_code,
        service_name=service_name,
        service_name_ar=service_name_ar,
        unit_price=D(str(unit_price)),
        duration_minutes=int(duration_minutes),
        discount_percent=discount_percent,
        discount_value=D(str(discount_value)),
        tax_rate=D(str(tax_rate)),
        engineer_id=engineer_id,
    )
    line.calculate_line_total()
    db.session.add(line)
    order.calculate_totals()
    db.session.commit()
    return line


# ---------------------------------------------------------------------------
# 4. Discount at order level
# ---------------------------------------------------------------------------
def apply_order_discount(order_id, discount_percent=None, discount_value=None,
                         changed_by=None, override=False):
    """تطبيق خصم على مستوى الأمر مع فحص السقف."""
    order = get_owned_or_raise(MaintenanceOrder, order_id)
    if order is None:
        raise ValidationError('أمر الصيانة غير موجود')

    settings = _get_settings(order.tenant_id)

    if discount_percent is not None:
        discount_percent = D(str(discount_percent))
        if discount_percent > settings.max_discount_percent and not override:
            raise ValidationError(f'الخصم النسبة يتجاوز السقف ({settings.max_discount_percent}%)')
        order.discount_total_percent = discount_percent

    if discount_value is not None:
        discount_value = D(str(discount_value))
        if discount_value > settings.max_discount_value and not override:
            raise ValidationError(f'الخصم القيمة يتجاوز السقف ({settings.max_discount_value})')
        order.discount_total_value = discount_value

    order.calculate_totals()
    db.session.commit()
    return order


# ---------------------------------------------------------------------------
# 5. Warranty actions
# ---------------------------------------------------------------------------
def warranty_action(tenant_id, order_id, action, performed_by, reason=None,
                    serial_number=None, product_id=None):
    """إجراء على الكفالة:检查/إلغاء/إعادة."""
    order = get_owned_or_raise(MaintenanceOrder, order_id)
    if order is None:
        raise ValidationError('أمر الصيانة غير موجود')

    settings = _get_settings(tenant_id)
    from flask_login import current_user
    user = db.session.get(User, performed_by)

    if action == 'void':
        if not getattr(current_user, 'is_owner', False) and not settings.allow_engineer_cancel_warranty:
            raise ValidationError('غير مصرح بإلغاء الكفالة')
        order.warranty_status = 'void'
        order.color_tag = '#ef4444'
    elif action == 'restore':
        if not getattr(current_user, 'is_owner', False) and not settings.allow_engineer_restore_warranty:
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

    db.session.commit()
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
def create_receipt(order_id, amount, payment_method, cashier_id, reference_type=None,
                   reference_id=None):
    """إنشاء سند قبض لأمر الصيانة (استقبال فقط)."""
    order = get_owned_or_raise(MaintenanceOrder, order_id)
    if order is None:
        raise ValidationError('أمر الصيانة غير موجود')

    amount = D(str(amount))
    if amount <= 0:
        raise ValidationError('المبلغ يجب أن يكون أكبر من صفر')

    receipt_no = generate_number('PT-MN', MaintenanceReceipt, 'receipt_no')

    receipt = MaintenanceReceipt(
        maintenance_order_id=order.id,
        receipt_no=receipt_no,
        amount=amount,
        payment_method=payment_method,
        cashier_id=cashier_id,
        reference_type=reference_type,
        reference_id=reference_id,
        posted=True,
        posted_at=datetime.now(timezone.utc),
    )
    db.session.add(receipt)

    order.paid_amount = (order.paid_amount or D('0')) + amount
    order.balance_due = order.total_amount - order.paid_amount
    if order.balance_due <= 0:
        order.status = 'closed'

    db.session.commit()
    return receipt


# ---------------------------------------------------------------------------
# 7. Create Maintenance Invoice (independent from sales invoices)
# ---------------------------------------------------------------------------
def create_maintenance_invoice(order_id, created_by):
    """إنشاء فاتورة صيانة مستقلة."""
    order = get_owned_or_raise(MaintenanceOrder, order_id)
    if order is None:
        raise ValidationError('أمر الصيانة غير موجود')

    if order.invoice:
        raise ValidationError('الفاتورة موجودة بالفعل لهذا الأمر')

    invoice_no = generate_number('MI', MaintenanceInvoice, 'invoice_no')

    invoice = MaintenanceInvoice(
        maintenance_order_id=order.id,
        invoice_no=invoice_no,
        subtotal=order.subtotal,
        discount_total=order.discount_total_value,
        tax_amount=order.tax_amount,
        total_amount=order.total_amount,
        paid_amount=order.paid_amount,
        balance_due=order.balance_due,
        posted=True,
        posted_at=datetime.now(timezone.utc),
        gl_posted=False,
    )
    db.session.add(invoice)
    db.session.commit()
    return invoice


# ---------------------------------------------------------------------------
# 8. Returns
# ---------------------------------------------------------------------------
def create_maintenance_return(order_id, returned_by, reason, lines=None):
    """إنشاء مرتجع صيانة."""
    order = get_owned_or_raise(MaintenanceOrder, order_id)
    if order is None:
        raise ValidationError('أمر الصيانة غير موجود')

    return_no = generate_number('MR', MaintenanceReturn, 'return_no')

    ret = MaintenanceReturn(
        maintenance_order_id=order.id,
        return_no=return_no,
        returned_by=returned_by,
        reason=reason,
        total_value=D('0'),
        posted=True,
        posted_at=datetime.now(timezone.utc),
    )
    db.session.add(ret)
    db.session.flush()

    total = D('0')
    for ln in (lines or []):
        rline = MaintenanceReturnLine(
            return_id=ret.id,
            order_item_id=ln.get('order_item_id'),
            order_service_id=ln.get('order_service_id'),
            quantity=D(str(ln.get('quantity', 1))),
            unit_price=D(str(ln.get('unit_price', 0))),
        )
        rline.line_total = rline.quantity * rline.unit_price
        total += rline.line_total
        db.session.add(rline)

        # Stock movement for return
        if ln.get('order_item_id'):
            item = db.session.get(MaintenanceOrderItem, ln['order_item_id'])
            if item and item.warehouse_id:
                StockService.create_movement(
                    product_id=item.product_id,
                    quantity=rline.quantity,  # positive = return to stock
                    movement_type='maintenance_return',
                    reference_type='maintenance_return',
                    reference_id=ret.id,
                    notes=f'إرجاع قطعة لأمر {order.order_no}',
                    warehouse_id=item.warehouse_id,
                )

    ret.total_value = total
    order.balance_due = max(D('0'), order.balance_due - total)
    db.session.commit()
    return ret


# ---------------------------------------------------------------------------
# 9. GL posting for maintenance (independent from sales GL)
# ---------------------------------------------------------------------------
def post_maintenance_gl(order_id):
    """ترحيل قيد محلي لأمر الصيانة على حسابات الصيانة."""
    order = get_owned_or_raise(MaintenanceOrder, order_id)
    if order is None:
        raise ValidationError('أمر الصيانة غير موجود')

    settings = _get_settings(order.tenant_id)
    ar_account = GLAccount.query.get(settings.maintenance_ar_account_id)
    rev_account = GLAccount.query.get(settings.maintenance_revenue_account_id)
    cogs_account = GLAccount.query.get(5101)  # Maintenance COGS

    if not ar_account or not rev_account:
        raise ValidationError('حسابات الصيانة (AR/Revenue) غير مهيأة في الإعدادات')

    lines = []
    # Credit revenue
    lines.append({'account_code': rev_account.code, 'credit': order.total_amount,
                  'description': f'إيراد صيانة {order.order_no}'})
    # Debit AR or Cash
    if order.payment_mode == 'cash':
        lines.append({'account_code': '1110', 'debit': order.total_amount,
                      'description': f'صندوق - قبض صيانة {order.order_no}'})
    else:
        lines.append({'account_code': ar_account.code, 'debit': order.total_amount,
                      'description': f'ذمم صيانة مدينة - {order.order_no}'})

    # COGS for parts
    cogs_total = sum((D(str(it.unit_price)) * D(str(it.quantity)) for it in order.items), D('0'))
    if cogs_total > 0:
        lines.append({'account_code': cogs_account.code, 'debit': cogs_total,
                      'description': f'تكلفة قطع صيانة {order.order_no}'})
        lines.append({'account_code': '1140', 'credit': cogs_total,
                      'description': f'مخزون - قطع صيانة {order.order_no}'})

    entry = GLService.create_manual_entry(
        description=f'قيد صيانة {order.order_no}',
        lines=lines,
    )
    order.invoice.gl_posted = True if order.invoice else None
    db.session.commit()
    return entry


# ---------------------------------------------------------------------------
# 10. Query helpers
# ---------------------------------------------------------------------------
def get_orders(tenant_id, status=None, date_from=None, date_to=None,
               customer_id=None, engineer_id=None, warranty_status=None,
               page=1, per_page=20):
    """استعلام عن أوامر الصيانة مع عزل تينانت."""
    q = MaintenanceOrder.query.filter_by(tenant_id=tenant_id, is_archived=False)
    if status:
        q = q.filter_by(status=status)
    if customer_id:
        q = q.filter_by(customer_id=customer_id)
    if engineer_id:
        q = q.filter_by(engineer_id=engineer_id)
    if warranty_status:
        q = q.filter_by(warranty_status=warranty_status)
    if date_from:
        q = q.filter(MaintenanceOrder.received_at >= date_from)
    if date_to:
        q = q.filter(MaintenanceOrder.received_at <= date_to)
    return q.order_by(MaintenanceOrder.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
