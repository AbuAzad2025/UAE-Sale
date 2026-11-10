"""
Maintenance Routes — بلوبرينت وحدة الصيانة
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify
from flask_login import login_required, current_user
from extensions import db
from utils.decorators import permission_required, get_owned_or_raise
from utils.feature_guards import install_feature_gate
from services.maintenance_service import (
    create_maintenance_order, change_status, add_order_item, add_order_service,
    apply_order_discount, warranty_action, create_receipt, create_maintenance_invoice,
    create_maintenance_return, post_maintenance_gl, get_orders,
)
from models.maintenance import (
    MaintenanceOrder, MaintenanceOrderItem, MaintenanceOrderService,
    MaintenanceOrderStatusLog, MaintenanceReceipt, MaintenanceInvoice,
    MaintenanceReturn, MaintenanceReturnLine, MaintenanceSetting,
    MaintenanceService, MaintenanceWarrantyAudit, MaintenanceDeviceRegistry,
)
from models import Customer, Product, User, Warehouse
from decimal import Decimal
from sqlalchemy import func
from datetime import date, timedelta

maintenance_bp = Blueprint('maintenance', __name__, url_prefix='/maintenance')
install_feature_gate(maintenance_bp, 'maintenance')


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------
@maintenance_bp.route('/')
@login_required
@permission_required('maintenance_view')
def list_orders():
    from sqlalchemy import inspect as sa_inspect
    page = request.args.get('page', 1, type=int)
    status = request.args.get('status', '', type=str)
    date_from = request.args.get('date_from', '', type=str).strip()
    date_to = request.args.get('date_to', '', type=str).strip()
    warranty = request.args.get('warranty', '', type=str).strip()

    pagination = get_orders(
        tenant_id=current_user.tenant_id or current_user.id,
        status=status or None,
        date_from=date_from or None,
        date_to=date_to or None,
        warranty_status=warranty or None,
        page=page,
        per_page=20,
    )
    return render_template('maintenance/list.html',
                           orders=pagination.items, pagination=pagination,
                           status=status, date_from=date_from, date_to=date_to,
                           warranty=warranty)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------
@maintenance_bp.route('/create', methods=['GET', 'POST'])
@login_required
@permission_required('maintenance_receive')
def create_order():
    from datetime import date as _date
    if request.method == 'POST':
        try:
            order = create_maintenance_order(
                tenant_id=current_user.tenant_id or current_user.id,
                customer_id=request.form.get('customer_id', type=int),
                received_by=current_user.id,
                device_brand=request.form.get('device_brand'),
                device_model=request.form.get('device_model'),
                device_serial=request.form.get('device_serial'),
                device_imei=request.form.get('device_imei'),
                device_plate=request.form.get('device_plate'),
                device_problem=request.form.get('device_problem'),
                priority=request.form.get('priority', 'normal'),
                payment_mode=request.form.get('payment_mode', 'cash'),
                deposit=request.form.get('deposit', 0),
                tax_inclusive=request.form.get('tax_inclusive') == 'on',
                engineer_id=request.form.get('engineer_id', type=int) or None,
                service_advisor_id=request.form.get('service_advisor_id', type=int) or None,
            )
            flash(f'تم إنشاء أمر الصيانة {order.order_no}', 'success')
            return redirect(url_for('maintenance.view_order', id=order.id))
        except ValidationError as e:
            flash(str(e), 'danger')
    customers = Customer.query.filter_by(is_active=True).all()
    engineers = User.query.filter_by(is_active=True).all()
    return render_template('maintenance/create.html',
                           customers=customers, engineers=engineers,
                           today=_date.today().isoformat())


# ---------------------------------------------------------------------------
# View
# ---------------------------------------------------------------------------
@maintenance_bp.route('/<int:id>')
@login_required
@permission_required('maintenance_view')
def view_order(id):
    order = get_owned_or_raise(MaintenanceOrder, id)
    if order is None:
        flash('أمر الصيانة غير موجود', 'danger')
        return redirect(url_for('maintenance.list_orders'))
    products = Product.query.filter_by(is_active=True).all()
    warehouses = Warehouse.query.filter_by(is_active=True).all()
    return render_template('maintenance/view.html', order=order, products=products, warehouses=warehouses)


# ---------------------------------------------------------------------------
# Status change
# ---------------------------------------------------------------------------
@maintenance_bp.route('/<int:id>/status', methods=['POST'])
@login_required
@permission_required('maintenance_work')
def change_order_status(id):
    try:
        new_status = request.form.get('status')
        note = request.form.get('note', '')
        order = change_status(id, new_status, current_user.id, note)
        flash(f'تم تغيير الحالة إلى {order.status}', 'success')
    except ValidationError as e:
        flash(str(e), 'danger')
    return redirect(url_for('maintenance.view_order', id=id))


# ---------------------------------------------------------------------------
# Add item (part)
# ---------------------------------------------------------------------------
@maintenance_bp.route('/<int:id>/item', methods=['POST'])
@login_required
@permission_required('maintenance_work')
def add_item(id):
    try:
        add_order_item(
            order_id=id,
            product_id=request.form.get('product_id', type=int),
            quantity=request.form.get('quantity', type=float),
            unit_price=request.form.get('unit_price', type=float),
            tenant_id=current_user.tenant_id or current_user.id,
            discount_percent=request.form.get('discount_percent', 0),
            discount_value=request.form.get('discount_value', 0),
            line_discount_mode=request.form.get('line_discount_mode', 'percent'),
            tax_rate=request.form.get('tax_rate', 0),
            warehouse_id=request.form.get('warehouse_id', type=int),
        )
        flash('تم إضافة البند', 'success')
    except ValidationError as e:
        flash(str(e), 'danger')
    return redirect(url_for('maintenance.view_order', id=id))


# ---------------------------------------------------------------------------
# Add service
# ---------------------------------------------------------------------------
@maintenance_bp.route('/<int:id>/service', methods=['POST'])
@login_required
@permission_required('maintenance_work')
def add_service(id):
    try:
        add_order_service(
            order_id=id,
            service_code=request.form.get('service_code'),
            service_name=request.form.get('service_name'),
            service_name_ar=request.form.get('service_name_ar'),
            unit_price=request.form.get('unit_price', type=float),
            duration_minutes=request.form.get('duration_minutes', type=int),
            tenant_id=current_user.tenant_id or current_user.id,
            discount_percent=request.form.get('discount_percent', 0),
            discount_value=request.form.get('discount_value', 0),
            tax_rate=request.form.get('tax_rate', 0),
            engineer_id=current_user.id,
        )
        flash('تم إضافة الخدمة', 'success')
    except ValidationError as e:
        flash(str(e), 'danger')
    return redirect(url_for('maintenance.view_order', id=id))


# ---------------------------------------------------------------------------
# Discount
# ---------------------------------------------------------------------------
@maintenance_bp.route('/<int:id>/discount', methods=['POST'])
@login_required
@permission_required('maintenance_discount')
def apply_discount(id):
    try:
        override = request.form.get('override') == 'on'
        apply_order_discount(
            order_id=id,
            discount_percent=request.form.get('discount_percent', type=float) or None,
            discount_value=request.form.get('discount_value', type=float) or None,
            changed_by=current_user.id,
            override=override,
        )
        flash('تم تطبيق الخصم', 'success')
    except ValidationError as e:
        flash(str(e), 'danger')
    return redirect(url_for('maintenance.view_order', id=id))


# ---------------------------------------------------------------------------
# Warranty
# ---------------------------------------------------------------------------
@maintenance_bp.route('/<int:id>/warranty', methods=['POST'])
@login_required
@permission_required('maintenance_work')
def warranty(id):
    try:
        action = request.form.get('action')  # checked/void/restore
        reason = request.form.get('reason', '')
        order = warranty_action(
            tenant_id=current_user.tenant_id or current_user.id,
            order_id=id,
            action=action,
            performed_by=current_user.id,
            reason=reason,
        )
        flash(f'تم إجراء إجراء الكفالة: {action}', 'success')
    except ValidationError as e:
        flash(str(e), 'danger')
    return redirect(url_for('maintenance.view_order', id=id))


# ---------------------------------------------------------------------------
# Receipt
# ---------------------------------------------------------------------------
@maintenance_bp.route('/<int:id>/receive', methods=['POST'])
@login_required
@permission_required('maintenance_receive')
def receive(id):
    try:
        receipt = create_receipt(
            order_id=id,
            amount=request.form.get('amount', type=float),
            payment_method=request.form.get('payment_method', 'cash'),
            cashier_id=current_user.id,
        )
        flash(f'تم إنشاء سند قبض {receipt.receipt_no}', 'success')
    except ValidationError as e:
        flash(str(e), 'danger')
    return redirect(url_for('maintenance.view_order', id=id))


# ---------------------------------------------------------------------------
# Invoice
# ---------------------------------------------------------------------------
@maintenance_bp.route('/<int:id>/invoice', methods=['POST'])
@login_required
@permission_required('maintenance_close')
def create_invoice(id):
    try:
        invoice = create_maintenance_invoice(id, current_user.id)
        flash(f'تم إنشاء فاتورة الصيانة {invoice.invoice_no}', 'success')
    except ValidationError as e:
        flash(str(e), 'danger')
    return redirect(url_for('maintenance.view_order', id=id))


# ---------------------------------------------------------------------------
# Return
# ---------------------------------------------------------------------------
@maintenance_bp.route('/<int:id>/return', methods=['POST'])
@login_required
@permission_required('maintenance_work')
def create_return(id):
    try:
        ret = create_maintenance_return(
            order_id=id,
            returned_by=current_user.id,
            reason=request.form.get('reason', ''),
        )
        flash(f'تم إنشاء مرتجع الصيانة {ret.return_no}', 'success')
    except ValidationError as e:
        flash(str(e), 'danger')
    return redirect(url_for('maintenance.view_order', id=id))


# ---------------------------------------------------------------------------
# GL Posting
# ---------------------------------------------------------------------------
@maintenance_bp.route('/<int:id>/gl-post', methods=['POST'])
@login_required
@permission_required('maintenance_close')
def gl_post(id):
    try:
        entry = post_maintenance_gl(id)
        flash(f'تم ترحيل القيد المحاسبي {entry.entry_number}', 'success')
    except ValidationError as e:
        flash(str(e), 'danger')
    return redirect(url_for('maintenance.view_order', id=id))


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
@maintenance_bp.route('/settings', methods=['GET', 'POST'])
@login_required
@permission_required('maintenance_settings')
def settings():
    settings = MaintenanceSetting.query.filter_by(
        tenant_id=current_user.tenant_id or current_user.id
    ).first()
    if not settings:
        settings = MaintenanceSetting(tenant_id=current_user.tenant_id or current_user.id)
        db.session.add(settings)
        db.session.commit()

    if request.method == 'POST':
        settings.default_warehouse_id = request.form.get('default_warehouse_id', type=int)
        settings.max_discount_percent = Decimal(str(request.form.get('max_discount_percent', 15)))
        settings.max_discount_value = Decimal(str(request.form.get('max_discount_value', 500)))
        settings.require_warranty_check = request.form.get('require_warranty_check') == 'on'
        settings.color_warranty = request.form.get('color_warranty', '#10b981')
        settings.color_non_warranty = request.form.get('color_non_warranty', '#ef4444')
        settings.color_unknown = request.form.get('color_unknown', '#f59e0b')
        settings.allow_engineer_cancel_warranty = request.form.get('allow_engineer_cancel_warranty') == 'on'
        settings.allow_engineer_restore_warranty = request.form.get('allow_engineer_restore_warranty') == 'on'
        db.session.commit()
        flash('تم حفظ إعدادات الصيانة', 'success')
        return redirect(url_for('maintenance.settings'))

    warehouses = Warehouse.query.filter_by(is_active=True).all()
    return render_template('maintenance/settings.html', settings=settings, warehouses=warehouses)


# ---------------------------------------------------------------------------
# Services (fixed price)
# ---------------------------------------------------------------------------
@maintenance_bp.route('/services', methods=['GET', 'POST'])
@login_required
@permission_required('maintenance_settings')
def services_list():
    if request.method == 'POST':
        svc = MaintenanceService(
            tenant_id=current_user.tenant_id or current_user.id,
            service_code=request.form.get('service_code'),
            name=request.form.get('name'),
            name_ar=request.form.get('name_ar'),
            category=request.form.get('category', 'other'),
            fixed_price=Decimal(str(request.form.get('fixed_price', 0))),
            duration_minutes=int(request.form.get('duration_minutes', 0)),
            tax_rate=Decimal(str(request.form.get('tax_rate', 0))),
            is_active=request.form.get('is_active') == 'on',
            requires_parts=request.form.get('requires_parts') == 'on',
            sort_order=int(request.form.get('sort_order', 0)),
        )
        db.session.add(svc)
        db.session.commit()
        flash('تم إضافة الخدمة', 'success')
        return redirect(url_for('maintenance.services_list'))

    services = MaintenanceService.query.filter_by(
        tenant_id=current_user.tenant_id or current_user.id
    ).order_by(MaintenanceService.sort_order).all()
    return render_template('maintenance/services.html', services=services)


# ---------------------------------------------------------------------------
# Device Registry
# ---------------------------------------------------------------------------
@maintenance_bp.route('/devices', methods=['GET', 'POST'])
@login_required
@permission_required('maintenance_view')
def devices_list():
    if request.method == 'POST':
        dev = MaintenanceDeviceRegistry(
            tenant_id=current_user.tenant_id or current_user.id,
            customer_id=request.form.get('customer_id', type=int),
            product_id=request.form.get('product_id', type=int) or None,
            serial_number=request.form.get('serial_number'),
            imei=request.form.get('imei'),
            plate=request.form.get('plate'),
            brand=request.form.get('brand'),
            model=request.form.get('model'),
            purchase_date=request.form.get('purchase_date') or None,
            warranty_end_date=request.form.get('warranty_end_date') or None,
            warranty_type=request.form.get('warranty_type'),
            is_under_warranty=request.form.get('is_under_warranty') == 'on',
            warranty_notes=request.form.get('warranty_notes'),
        )
        db.session.add(dev)
        db.session.commit()
        flash('تم إضافة الجهاز للسجل', 'success')
        return redirect(url_for('maintenance.devices_list'))

    devices = MaintenanceDeviceRegistry.query.filter_by(
        tenant_id=current_user.tenant_id or current_user.id
    ).all()
    customers = Customer.query.filter_by(is_active=True).all()
    products = Product.query.filter_by(is_active=True).all()
    return render_template('maintenance/devices.html',
                           devices=devices, customers=customers, products=products)


# ===========================================================================
# Print Receipt & Invoice
# ===========================================================================
@maintenance_bp.route('/<int:id>/print-receipt')
@login_required
@permission_required('maintenance_view')
def print_receipt(id):
    order = get_owned_or_raise(MaintenanceOrder, id)
    if order is None:
        flash('أمر الصيانة غير موجود', 'danger')
        return redirect(url_for('maintenance.list_orders'))
    receipts = order.receipts
    return render_template('maintenance/print_receipt.html', order=order, receipts=receipts)


@maintenance_bp.route('/<int:id>/print-invoice')
@login_required
@permission_required('maintenance_view')
def print_invoice(id):
    order = get_owned_or_raise(MaintenanceOrder, id)
    if order is None:
        flash('أمر الصيانة غير موجود', 'danger')
        return redirect(url_for('maintenance.list_orders'))
    return render_template('maintenance/print_invoice.html', order=order)


# ===========================================================================
# Cost Report / Maintenance Profitability
# ===========================================================================
@maintenance_bp.route('/cost-report')
@login_required
@permission_required('maintenance_view')
def maintenance_cost_report():
    tenant_id = current_user.tenant_id or current_user.id
    date_from = request.args.get('date_from', '', type=str).strip()
    date_to = request.args.get('date_to', '', type=str).strip()

    q = MaintenanceOrder.query.filter_by(tenant_id=tenant_id, is_archived=False)
    if date_from:
        q = q.filter(MaintenanceOrder.received_at >= date_from)
    if date_to:
        q = q.filter(MaintenanceOrder.received_at <= date_to)

    orders = q.all()

    # حساب التكاليف والأرباح لكل أمر
    order_details = []
    total_revenue = Decimal('0')
    total_cost = Decimal('0')
    total_discount = Decimal('0')
    total_tax = Decimal('0')
    total_paid = Decimal('0')

    for o in orders:
        parts_cost = sum((Decimal(str(it.unit_price)) * Decimal(str(it.quantity)) for it in o.items), Decimal('0'))
        total_cost += parts_cost
        total_revenue += Decimal(str(o.total_amount))
        total_discount += Decimal(str(o.discount_total_value or 0))
        total_tax += Decimal(str(o.tax_amount or 0))
        total_paid += Decimal(str(o.paid_amount or 0))
        
        order_profit = Decimal(str(o.total_amount)) - parts_cost
        order_profit_pct = (order_profit / Decimal(str(o.total_amount)) * 100) if o.total_amount > 0 else Decimal('0')
        
        order_details.append({
            'order': o,
            'parts_cost': parts_cost,
            'profit': order_profit,
            'profit_pct': order_profit_pct,
        })

    gross_profit = total_revenue - total_cost
    profit_margin = (gross_profit / total_revenue * 100) if total_revenue > 0 else Decimal('0')

    # Per engineer performance
    engineer_stats = {}
    for o in orders:
        eng = o.engineer_id
        if eng not in engineer_stats:
            engineer_stats[eng] = {'orders': 0, 'revenue': Decimal('0'), 'cost': Decimal('0')}
        engineer_stats[eng]['orders'] += 1
        engineer_stats[eng]['revenue'] += Decimal(str(o.total_amount))

    # Monthly trend (last 6 months)
    from datetime import date as _date
    today = _date.today()
    monthly = []
    for m in range(5, -1, -1):
        y = today.year
        mo = today.month - m
        while mo <= 0:
            mo += 12
            y -= 1
        month_start = _date(y, mo, 1)
        if mo == 12:
            month_end = _date(y + 1, 1, 1)
        else:
            month_end = _date(y, mo + 1, 1)
        month_orders = [o for o in orders if o.received_at and month_start <= o.received_at.date() < month_end]
        m_rev = sum((Decimal(str(o.total_amount)) for o in month_orders), Decimal('0'))
        m_cost = sum((Decimal(str(sum((Decimal(str(it.unit_price)) * Decimal(str(it.quantity)) for it in o.items), Decimal('0')))) for o in month_orders), Decimal('0'))
        monthly.append({
            'label': month_start.strftime('%Y-%m'),
            'orders': len(month_orders),
            'revenue': float(m_rev),
            'cost': float(m_cost),
            'profit': float(m_rev - m_cost),
        })

    return render_template('maintenance/cost_report.html',
                           order_details=order_details,
                           total_revenue=total_revenue,
                           total_cost=total_cost,
                           total_discount=total_discount,
                           total_tax=total_tax,
                           total_paid=total_paid,
                           gross_profit=gross_profit,
                           profit_margin=profit_margin,
                           engineer_stats=engineer_stats,
                           monthly=monthly,
                           date_from=date_from,
                           date_to=date_to)


# ===========================================================================
# Customer Rating
# ===========================================================================
@maintenance_bp.route('/<int:id>/rate', methods=['POST'])
@login_required
@permission_required('maintenance_view')
def rate_order(id):
    order = get_owned_or_raise(MaintenanceOrder, id)
    if order is None:
        flash('أمر الصيانة غير موجود', 'danger')
        return redirect(url_for('maintenance.list_orders'))

    rating = request.form.get('rating', type=int)
    comment = request.form.get('comment', '')

    if not rating or rating < 1 or rating > 5:
        flash('التقييم يجب أن يكون بين 1 و 5', 'danger')
        return redirect(url_for('maintenance.view_order', id=id))

    order.customer_rating = rating
    order.customer_comment = comment
    order.rated_at = datetime.now(timezone.utc)
    db.session.commit()
    flash('تم تسجيل تقييم العميل بنجاح', 'success')
    return redirect(url_for('maintenance.view_order', id=id))


# ===========================================================================
# Warranty Period / Post-Service Warranty
# ===========================================================================
@maintenance_bp.route('/<int:id>/warranty-period', methods=['POST'])
@login_required
@permission_required('maintenance_work')
def set_warranty_period(id):
    order = get_owned_or_raise(MaintenanceOrder, id)
    if order is None:
        flash('أمر الصيانة غير موجود', 'danger')
        return redirect(url_for('maintenance.list_orders'))

    warranty_days = request.form.get('warranty_days', type=int)
    warranty_notes = request.form.get('warranty_notes', '')

    if not warranty_days or warranty_days < 0:
        flash('أيام الضمان يجب أن تكون رقماً موجبا', 'danger')
        return redirect(url_for('maintenance.view_order', id=id))

    order.warranty_period_days = warranty_days
    order.warranty_period_notes = warranty_notes
    order.warranty_period_start = date.today()
    order.warranty_period_end = date.today() + timedelta(days=warranty_days)
    db.session.commit()
    flash(f'تم تعيين فترة ضمان {warranty_days} يوم', 'success')
    return redirect(url_for('maintenance.view_order', id=id))


# ===========================================================================
# Notify Customer (WhatsApp / Email placeholder)
# ===========================================================================
@maintenance_bp.route('/<int:id>/notify', methods=['POST'])
@login_required
@permission_required('maintenance_work')
def notify_customer(id):
    order = get_owned_or_raise(MaintenanceOrder, id)
    if order is None:
        flash('أمر الصيانة غير موجود', 'danger')
        return redirect(url_for('maintenance.list_orders'))

    channel = request.form.get('channel', 'whatsapp')
    message = request.form.get('message', '')

    if not message:
        message = f"عزيزي العميل، أصبح أمر الصيانة رقم {order.order_no} جاهزاً للاستلام. يرجى مراجعتنا."

    # Placeholder for WhatsApp/Email integration
    flash(f'تم إرسال الإشعار عبر {channel} للعميل (تنبيه: بحاجة تفعيل مزود الخدمة)', 'info')
    return redirect(url_for('maintenance.view_order', id=id))


# ===========================================================================
# Archive Order (Soft Delete)
# ===========================================================================
@maintenance_bp.route('/<int:id>/archive', methods=['POST'])
@login_required
@permission_required('maintenance_close')
def archive_order(id):
    order = get_owned_or_raise(MaintenanceOrder, id)
    if order is None:
        flash('أمر الصيانة غير موجود', 'danger')
        return redirect(url_for('maintenance.list_orders'))

    order.is_archived = True
    order.archived_at = datetime.now(timezone.utc)
    order.archived_by = current_user.id
    db.session.commit()
    flash('تم أرشفة أمر الصيانة', 'success')
    return redirect(url_for('maintenance.list_orders'))
