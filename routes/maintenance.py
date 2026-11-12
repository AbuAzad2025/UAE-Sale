"""
Maintenance Routes — بلوبرينت وحدة الصيانة
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from extensions import db
from utils.decorators import permission_required
from utils.errors import ValidationError
from utils.feature_guards import install_feature_gate
from services.maintenance_security import (
    current_maintenance_tenant,
    get_maintenance_order,
)
from services.maintenance_service import (
    create_maintenance_order,
    change_status,
    add_order_item,
    add_order_service,
    apply_order_discount,
    warranty_action,
    create_receipt,
    create_maintenance_invoice,
    create_maintenance_return,
    create_maintenance_credit_note,
    get_orders,
    get_maintenance_cost_analysis,
    get_overdue_orders,
    quality_check,
    set_completion_time,
    send_customer_notification,
    create_maintenance_purchase,
    receive_maintenance_purchase,
    pay_maintenance_supplier,
    ALLOWED_TRANSITIONS,
    BILLABLE_STATUSES,
)
from models.maintenance import (
    MaintenanceOrder,
    MaintenanceOrderStatusLog,
    MaintenanceSetting,
    MaintenanceService,
    MaintenanceDeviceRegistry,
)
from models import Customer, Product, Tenant, User, Warehouse
from decimal import Decimal
from datetime import date, datetime, timedelta, timezone

maintenance_bp = Blueprint("maintenance", __name__, url_prefix="/maintenance")
install_feature_gate(maintenance_bp, "maintenance")

# Write endpoints that are verified. Anything else (notifications, purchase
# orders, settings of a not-yet-verified kind) is refused by the server, not
# merely hidden in the interface.
ALLOWED_WRITE_ENDPOINTS = {
    "maintenance.create_order",
    "maintenance.change_order_status",
    "maintenance.add_item",
    "maintenance.add_service",
    "maintenance.apply_discount",
    "maintenance.warranty",
    "maintenance.receive",
    "maintenance.create_invoice",
    "maintenance.create_credit_note",
    "maintenance.create_return",
    "maintenance.quality_check",
    "maintenance.set_completion_time",
    "maintenance.rate_order",
    "maintenance.set_warranty_period",
    "maintenance.archive_order",
    "maintenance.notify_customer",
    "maintenance.settings",
    "maintenance.services_list",
    "maintenance.devices_list",
    "maintenance.purchases_list",
    "maintenance.receive_purchase",
    "maintenance.pay_supplier",
}


@maintenance_bp.before_request
def _maintenance_safety_gate():
    # Let login_required redirect anonymous visitors; never infer a tenant from
    # the platform owner's user id or operate with an unscoped tenant.
    if not current_user.is_authenticated:
        return
    try:
        current_maintenance_tenant()
    except ValidationError:
        abort(403)
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        if request.endpoint not in ALLOWED_WRITE_ENDPOINTS:
            abort(
                503, description="هذه العملية موقوفة مؤقتاً لحين استكمال تدقيق الصيانة"
            )


def _tenant_id():
    return current_maintenance_tenant()


def _order_or_404(order_id):
    order = get_maintenance_order(order_id)
    if (
        order is None
        or order.customer is None
        or order.customer.tenant_id != _tenant_id()
    ):
        abort(404)
    return order


def _flash_error(exc):
    flash(str(exc), "danger")


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------
@maintenance_bp.route("/")
@login_required
@permission_required("maintenance_view")
def list_orders():
    page = request.args.get("page", 1, type=int)
    status = request.args.get("status", "", type=str)
    date_from = request.args.get("date_from", "", type=str).strip()
    date_to = request.args.get("date_to", "", type=str).strip()
    warranty = request.args.get("warranty", "", type=str).strip()

    try:
        pagination = get_orders(
            tenant_id=_tenant_id(),
            status=status or None,
            date_from=date_from or None,
            date_to=date_to or None,
            warranty_status=warranty or None,
            page=page,
            per_page=20,
        )
    except ValidationError as exc:
        _flash_error(exc)
        return redirect(url_for("maintenance.list_orders"))
    overdue = get_overdue_orders(_tenant_id())
    return render_template(
        "maintenance/list.html",
        orders=pagination.items,
        pagination=pagination,
        status=status,
        date_from=date_from,
        date_to=date_to,
        warranty=warranty,
        overdue=overdue,
    )


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------
@maintenance_bp.route("/create", methods=["GET", "POST"])
@login_required
@permission_required("maintenance_receive")
def create_order():
    if request.method == "POST":
        try:
            order = create_maintenance_order(
                tenant_id=_tenant_id(),
                customer_id=request.form.get("customer_id", type=int),
                received_by=current_user.id,
                device_brand=request.form.get("device_brand"),
                device_model=request.form.get("device_model"),
                device_serial=request.form.get("device_serial"),
                device_imei=request.form.get("device_imei"),
                device_plate=request.form.get("device_plate"),
                device_problem=request.form.get("device_problem"),
                notes=request.form.get("notes"),
                priority=request.form.get("priority", "normal"),
                payment_mode=request.form.get("payment_mode", "cash"),
                deposit=request.form.get("deposit", 0),
                tax_inclusive=request.form.get("tax_inclusive") == "on",
                currency=request.form.get("currency", "AED"),
                exchange_rate=request.form.get("exchange_rate", 1),
                engineer_id=request.form.get("engineer_id", type=int) or None,
                service_advisor_id=request.form.get("service_advisor_id", type=int)
                or None,
            )
            # If a deposit was specified, create a linked receipt immediately.
            deposit = request.form.get("deposit", type=float) or 0
            if deposit and deposit > 0:
                try:
                    create_receipt(
                        order_id=order.id,
                        amount=deposit,
                        payment_method=request.form.get(
                            "deposit_payment_method", "cash"
                        ),
                        cashier_id=current_user.id,
                        currency=request.form.get("currency", "AED"),
                        exchange_rate=request.form.get("exchange_rate", 1),
                        is_deposit=True,
                    )
                    flash(
                        f"تم تسجيل دفعة مقدمة {deposit:,.3f} {request.form.get('currency', 'AED')}",
                        "info",
                    )
                except ValidationError as exc:
                    _flash_error(exc)
            flash(f"تم إنشاء أمر الصيانة {order.order_no}", "success")
            return redirect(url_for("maintenance.view_order", id=order.id))
        except ValidationError as exc:
            _flash_error(exc)
    customers = Customer.query.filter_by(tenant_id=_tenant_id(), is_active=True).all()
    engineers = User.query.filter_by(tenant_id=_tenant_id(), is_active=True).all()
    return render_template(
        "maintenance/create.html",
        customers=customers,
        engineers=engineers,
        today=date.today().isoformat(),
    )


# ---------------------------------------------------------------------------
# View
# ---------------------------------------------------------------------------
@maintenance_bp.route("/<int:id>")
@login_required
@permission_required("maintenance_view")
def view_order(id):
    order = _order_or_404(id)
    products = Product.query.filter_by(tenant_id=_tenant_id(), is_active=True).all()
    warehouses = Warehouse.query.filter_by(tenant_id=_tenant_id(), is_active=True).all()
    transitions = [
        status
        for status in ALLOWED_TRANSITIONS.get(order.status, ())
        if status != "closed"
        and (status != "cancelled" or current_user.has_permission("maintenance_close"))
    ]
    status_history = (
        MaintenanceOrderStatusLog.query.filter_by(maintenance_order_id=order.id)
        .order_by(MaintenanceOrderStatusLog.changed_at, MaintenanceOrderStatusLog.id)
        .all()
    )
    return render_template(
        "maintenance/view.html",
        order=order,
        products=products,
        warehouses=warehouses,
        transitions=transitions,
        status_history=status_history,
        billable_statuses=BILLABLE_STATUSES,
    )


# ---------------------------------------------------------------------------
# Status change
# ---------------------------------------------------------------------------
@maintenance_bp.route("/<int:id>/status", methods=["POST"])
@login_required
@permission_required("maintenance_work")
def change_order_status(id):
    try:
        new_status = request.form.get("status")
        note = request.form.get("note", "")
        order = change_status(id, new_status, current_user.id, note)
        flash(f"تم تغيير الحالة إلى {order.status}", "success")
    except ValidationError as exc:
        _flash_error(exc)
    return redirect(url_for("maintenance.view_order", id=id))


# ---------------------------------------------------------------------------
# Add item (part)
# ---------------------------------------------------------------------------
@maintenance_bp.route("/<int:id>/item", methods=["POST"])
@login_required
@permission_required("maintenance_work")
def add_item(id):
    try:
        add_order_item(
            order_id=id,
            product_id=request.form.get("product_id", type=int),
            quantity=request.form.get("quantity", type=float),
            unit_price=request.form.get("unit_price", type=float),
            tenant_id=_tenant_id(),
            discount_percent=request.form.get("discount_percent", 0),
            discount_value=request.form.get("discount_value", 0),
            line_discount_mode=request.form.get("line_discount_mode", "percent"),
            tax_rate=request.form.get("tax_rate", 0),
            warehouse_id=request.form.get("warehouse_id", type=int),
            actor_id=current_user.id,
        )
        flash("تم إضافة البند وصرف القطعة من المخزون", "success")
    except ValidationError as exc:
        _flash_error(exc)
    return redirect(url_for("maintenance.view_order", id=id))


# ---------------------------------------------------------------------------
# Add service
# ---------------------------------------------------------------------------
@maintenance_bp.route("/<int:id>/service", methods=["POST"])
@login_required
@permission_required("maintenance_work")
def add_service(id):
    try:
        add_order_service(
            order_id=id,
            service_code=request.form.get("service_code"),
            service_name=request.form.get("service_name"),
            service_name_ar=request.form.get("service_name_ar"),
            unit_price=request.form.get("unit_price", type=float),
            duration_minutes=request.form.get("duration_minutes", type=int),
            tenant_id=_tenant_id(),
            discount_percent=request.form.get("discount_percent", 0),
            tax_rate=request.form.get("tax_rate", 0),
            engineer_id=current_user.id,
            cost_price=request.form.get("cost_price", 0) or 0,
            actor_id=current_user.id,
        )
        flash("تم إضافة الخدمة", "success")
    except ValidationError as exc:
        _flash_error(exc)
    return redirect(url_for("maintenance.view_order", id=id))


# ---------------------------------------------------------------------------
# Discount
# ---------------------------------------------------------------------------
@maintenance_bp.route("/<int:id>/discount", methods=["POST"])
@login_required
@permission_required("maintenance_discount")
def apply_discount(id):
    try:
        override = request.form.get("override") == "on"
        if not override and not current_user.has_permission("maintenance_settings"):
            override = False
        apply_order_discount(
            order_id=id,
            # Exactly one of the two may be sent: the percentage wins when it
            # is set, otherwise the fixed amount is used.
            discount_percent=(request.form.get("discount_percent", type=float) or None),
            discount_value=(request.form.get("discount_value", type=float) or None),
            changed_by=current_user.id,
            override=override,
        )
        flash("تم تطبيق الخصم", "success")
    except ValidationError as exc:
        _flash_error(exc)
    return redirect(url_for("maintenance.view_order", id=id))


# ---------------------------------------------------------------------------
# Warranty
# ---------------------------------------------------------------------------
@maintenance_bp.route("/<int:id>/warranty", methods=["POST"])
@login_required
@permission_required("maintenance_work")
def warranty(id):
    try:
        action = request.form.get("action")
        reason = request.form.get("reason", "")
        warranty_action(
            tenant_id=_tenant_id(),
            order_id=id,
            action=action,
            performed_by=current_user.id,
            reason=reason,
        )
        flash(f"تم تنفيذ إجراء الكفالة: {action}", "success")
    except ValidationError as exc:
        _flash_error(exc)
    return redirect(url_for("maintenance.view_order", id=id))


# ---------------------------------------------------------------------------
# Receipt
# ---------------------------------------------------------------------------
@maintenance_bp.route("/<int:id>/receive", methods=["POST"])
@login_required
@permission_required("maintenance_cashier")
def receive(id):
    try:
        receipt = create_receipt(
            order_id=id,
            amount=request.form.get("amount", type=float),
            payment_method=request.form.get("payment_method", "cash"),
            cashier_id=current_user.id,
            currency=request.form.get("currency"),
            exchange_rate=request.form.get("exchange_rate", type=float),
        )
        flash(f"تم إنشاء سند قبض {receipt.receipt_no}", "success")
    except ValidationError as exc:
        _flash_error(exc)
    return redirect(url_for("maintenance.view_order", id=id))


# ---------------------------------------------------------------------------
# Invoice
# ---------------------------------------------------------------------------
@maintenance_bp.route("/<int:id>/invoice", methods=["POST"])
@login_required
@permission_required("maintenance_close")
def create_invoice(id):
    try:
        invoice = create_maintenance_invoice(
            id,
            current_user.id,
            currency=request.form.get("currency"),
            exchange_rate=request.form.get("exchange_rate", type=float),
        )
        flash(f"تم إنشاء فاتورة الصيانة {invoice.invoice_no} وترحيل قيدها", "success")
    except ValidationError as exc:
        _flash_error(exc)
    return redirect(url_for("maintenance.view_order", id=id))


# ---------------------------------------------------------------------------
# Credit Note
# ---------------------------------------------------------------------------
@maintenance_bp.route("/<int:id>/credit-note", methods=["POST"])
@login_required
@permission_required("maintenance_close")
def create_credit_note(id):
    try:
        cn = create_maintenance_credit_note(
            order_id=id,
            created_by=current_user.id,
            reason=request.form.get("reason", ""),
            currency=request.form.get("currency"),
            exchange_rate=request.form.get("exchange_rate", type=float),
        )
        flash(f"تم إنشاء إشعار دائن {cn.credit_note_no} وترحيل قيده", "success")
    except ValidationError as exc:
        _flash_error(exc)
    return redirect(url_for("maintenance.view_order", id=id))


# ---------------------------------------------------------------------------
# Return
# ---------------------------------------------------------------------------
@maintenance_bp.route("/<int:id>/return", methods=["POST"])
@login_required
@permission_required("maintenance_work")
def create_return(id):
    try:
        lines = []
        item_id = request.form.get("order_item_id", type=int)
        quantity = request.form.get("quantity", type=float)
        if item_id and quantity:
            lines.append({"order_item_id": item_id, "quantity": quantity})
        service_id = request.form.get("order_service_id", type=int)
        service_quantity = request.form.get("service_quantity", type=float)
        if service_id and service_quantity:
            lines.append({"order_service_id": service_id, "quantity": service_quantity})
        if not lines:
            raise ValidationError("حدد البند المرتجع والكمية")
        ret = create_maintenance_return(
            order_id=id,
            returned_by=current_user.id,
            reason=request.form.get("reason", ""),
            lines=lines,
            currency=request.form.get("currency"),
            exchange_rate=request.form.get("exchange_rate", type=float),
        )
        flash(f"تم إنشاء مرتجع الصيانة {ret.return_no}", "success")
    except ValidationError as exc:
        _flash_error(exc)
    return redirect(url_for("maintenance.view_order", id=id))


# ---------------------------------------------------------------------------
# Quality control and completion time
# ---------------------------------------------------------------------------
@maintenance_bp.route("/<int:id>/quality-check", methods=["POST"])
@login_required
@permission_required("maintenance_work")
def quality_check_order(id):
    try:
        passed = request.form.get("passed") == "on"
        quality_check(id, passed, current_user.id, request.form.get("notes", ""))
        flash("تم تسجيل فحص الجودة", "success")
    except ValidationError as exc:
        _flash_error(exc)
    return redirect(url_for("maintenance.view_order", id=id))


@maintenance_bp.route("/<int:id>/completion-time", methods=["POST"])
@login_required
@permission_required("maintenance_work")
def set_completion_time_order(id):
    try:
        set_completion_time(id, request.form.get("hours", 0), current_user.id)
        flash("تم تسجيل وقت الإكمال", "success")
    except ValidationError as exc:
        _flash_error(exc)
    return redirect(url_for("maintenance.view_order", id=id))


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
@maintenance_bp.route("/settings", methods=["GET", "POST"])
@login_required
@permission_required("maintenance_settings")
def settings():
    tenant_id = _tenant_id()
    settings_row = MaintenanceSetting.query.filter_by(tenant_id=tenant_id).first()
    if not settings_row:
        settings_row = MaintenanceSetting(
            tenant_id=tenant_id,
            max_discount_percent=15,
            max_discount_value=500,
            require_warranty_check=True,
            color_warranty="#10b981",
            color_non_warranty="#ef4444",
            color_unknown="#f59e0b",
        )

    if request.method == "POST":
        percent = request.form.get("max_discount_percent", type=float)
        value = request.form.get("max_discount_value", type=float)
        if percent is None or not 0 <= percent <= 100:
            flash("سقف الخصم النسبة يجب أن يكون بين 0 و 100", "danger")
            return redirect(url_for("maintenance.settings"))
        if value is None or value < 0:
            flash("سقف الخصم القيمة غير صالح", "danger")
            return redirect(url_for("maintenance.settings"))
        settings_row.max_discount_percent = Decimal(str(percent))
        settings_row.max_discount_value = Decimal(str(value))
        settings_row.require_warranty_check = (
            request.form.get("require_warranty_check") == "on"
        )
        settings_row.allow_engineer_cancel_warranty = (
            request.form.get("allow_engineer_cancel_warranty") == "on"
        )
        settings_row.allow_engineer_restore_warranty = (
            request.form.get("allow_engineer_restore_warranty") == "on"
        )
        warehouse_id = request.form.get("default_warehouse_id", type=int)
        if warehouse_id:
            warehouse = Warehouse.query.filter_by(
                id=warehouse_id, tenant_id=tenant_id
            ).first()
            if not warehouse:
                flash("المستودع المحدد غير متاح", "danger")
                return redirect(url_for("maintenance.settings"))
            settings_row.default_warehouse_id = warehouse.id
        else:
            settings_row.default_warehouse_id = None
        db.session.commit()
        flash("تم حفظ إعدادات الصيانة", "success")
        return redirect(url_for("maintenance.settings"))

    warehouses = Warehouse.query.filter_by(tenant_id=tenant_id, is_active=True).all()
    return render_template(
        "maintenance/settings.html", settings=settings_row, warehouses=warehouses
    )


# ---------------------------------------------------------------------------
# Services (fixed price)
# ---------------------------------------------------------------------------
@maintenance_bp.route("/services", methods=["GET", "POST"])
@login_required
@permission_required("maintenance_settings")
def services_list():
    tenant_id = _tenant_id()
    if request.method == "POST":
        code = (request.form.get("service_code") or "").strip()
        name = (request.form.get("name") or "").strip()
        if not code or not name:
            flash("كود الخدمة واسمها مطلوبان", "danger")
            return redirect(url_for("maintenance.services_list"))
        if MaintenanceService.query.filter_by(
            tenant_id=tenant_id, service_code=code
        ).first():
            flash("هذا الكود مستخدم بالفعل", "danger")
            return redirect(url_for("maintenance.services_list"))
        price = request.form.get("fixed_price", type=float)
        if price is None or price < 0:
            flash("السعر الثابت غير صالح", "danger")
            return redirect(url_for("maintenance.services_list"))
        svc = MaintenanceService(
            tenant_id=tenant_id,
            service_code=code,
            name=name,
            name_ar=request.form.get("name_ar"),
            category=request.form.get("category", "other"),
            fixed_price=Decimal(str(price)),
            duration_minutes=int(request.form.get("duration_minutes", 0) or 0),
            tax_rate=Decimal(str(request.form.get("tax_rate", 0) or 0)),
            is_active=request.form.get("is_active") == "on",
            requires_parts=request.form.get("requires_parts") == "on",
            sort_order=int(request.form.get("sort_order", 0) or 0),
        )
        db.session.add(svc)
        db.session.commit()
        flash("تم إضافة الخدمة", "success")
        return redirect(url_for("maintenance.services_list"))

    services = (
        MaintenanceService.query.filter_by(tenant_id=tenant_id)
        .order_by(MaintenanceService.sort_order)
        .all()
    )
    return render_template("maintenance/services.html", services=services)


# ---------------------------------------------------------------------------
# Device registry
# ---------------------------------------------------------------------------
@maintenance_bp.route("/devices", methods=["GET", "POST"])
@login_required
@permission_required("maintenance_view")
def devices_list():
    tenant_id = _tenant_id()
    if request.method == "POST":
        # Writing the registry can grant free warranty work, so it needs the
        # administrative permission, not the view permission.
        if not current_user.has_permission("maintenance_settings"):
            abort(403)
        customer_id = request.form.get("customer_id", type=int)
        customer = Customer.query.filter_by(id=customer_id, tenant_id=tenant_id).first()
        if not customer:
            flash("العميل غير موجود ضمن هذا التينانت", "danger")
            return redirect(url_for("maintenance.devices_list"))
        serial = (request.form.get("serial_number") or "").strip() or None
        if (
            serial
            and MaintenanceDeviceRegistry.query.filter_by(
                tenant_id=tenant_id, serial_number=serial
            ).first()
        ):
            flash("الرقم التسلسلي مسجل بالفعل لهذا التينانت", "danger")
            return redirect(url_for("maintenance.devices_list"))
        dev = MaintenanceDeviceRegistry(
            tenant_id=tenant_id,
            customer_id=customer.id,
            product_id=request.form.get("product_id", type=int) or None,
            serial_number=serial,
            imei=(request.form.get("imei") or "").strip() or None,
            plate=(request.form.get("plate") or "").strip() or None,
            brand=request.form.get("brand"),
            model=request.form.get("model"),
            purchase_date=request.form.get("purchase_date") or None,
            warranty_end_date=request.form.get("warranty_end_date") or None,
            warranty_type=request.form.get("warranty_type"),
            is_under_warranty=request.form.get("is_under_warranty") == "on",
            warranty_notes=request.form.get("warranty_notes"),
        )
        db.session.add(dev)
        db.session.commit()
        flash("تم إضافة الجهاز للسجل", "success")
        return redirect(url_for("maintenance.devices_list"))

    devices = MaintenanceDeviceRegistry.query.filter_by(tenant_id=tenant_id).all()
    customers = Customer.query.filter_by(tenant_id=tenant_id, is_active=True).all()
    products = Product.query.filter_by(tenant_id=tenant_id, is_active=True).all()
    return render_template(
        "maintenance/devices.html",
        devices=devices,
        customers=customers,
        products=products,
    )


# ===========================================================================
# Print
# ===========================================================================
@maintenance_bp.route("/<int:id>/print-intake")
@login_required
@permission_required("maintenance_view")
def print_intake(id):
    order = _order_or_404(id)
    tenant = db.session.get(Tenant, _tenant_id())
    if tenant is None:
        abort(404)
    return render_template("maintenance/print_intake.html", order=order, tenant=tenant)


@maintenance_bp.route("/<int:id>/print-receipt")
@login_required
@permission_required("maintenance_view")
def print_receipt(id):
    order = _order_or_404(id)
    receipt_id = request.args.get("receipt_id", type=int)
    receipt = (
        next((r for r in order.receipts if r.id == receipt_id), None)
        if receipt_id
        else None
    )
    if receipt_id is None and len(order.receipts) == 1:
        receipt = order.receipts[0]
    if receipt is None:
        abort(404, description="حدد سند القبض المطلوب طباعته")
    return render_template(
        "maintenance/print_receipt.html",
        order=order,
        receipt=receipt,
        tenant=db.session.get(Tenant, _tenant_id()),
    )


@maintenance_bp.route("/<int:id>/print-invoice")
@login_required
@permission_required("maintenance_view")
def print_invoice(id):
    order = _order_or_404(id)
    if not order.invoice:
        abort(404)
    return render_template(
        "maintenance/print_invoice.html",
        order=order,
        tenant=db.session.get(Tenant, _tenant_id()),
    )


# ===========================================================================
# Cost report
# ===========================================================================
@maintenance_bp.route("/cost-report")
@login_required
@permission_required("maintenance_view")
def maintenance_cost_report():
    tenant_id = _tenant_id()
    date_from = request.args.get("date_from", "", type=str).strip()
    date_to = request.args.get("date_to", "", type=str).strip()

    try:
        analysis = get_maintenance_cost_analysis(
            tenant_id, date_from or None, date_to or None
        )
    except ValidationError as exc:
        _flash_error(exc)
        return redirect(url_for("maintenance.maintenance_cost_report"))

    orders = (
        MaintenanceOrder.query.join(
            Customer, Customer.id == MaintenanceOrder.customer_id
        )
        .filter(
            MaintenanceOrder.tenant_id == tenant_id,
            Customer.tenant_id == tenant_id,
            MaintenanceOrder.is_archived.is_(False),
        )
        .order_by(MaintenanceOrder.received_at.desc())
        .all()
    )

    order_details = []
    for order in orders:
        parts_cost = sum(
            (
                Decimal(str(it.cost_price or 0)) * Decimal(str(it.quantity or 0))
                for it in order.items
            ),
            Decimal("0"),
        )
        labor_cost = sum(
            (Decimal(str(sv.cost_price or 0)) for sv in order.services), Decimal("0")
        )
        revenue = Decimal(str(order.total_amount or 0)) - Decimal(
            str(order.tax_amount or 0)
        )
        cost = parts_cost + labor_cost
        profit = revenue - cost
        order_details.append(
            {
                "order": order,
                "parts_cost": parts_cost,
                "labor_cost": labor_cost,
                "cost": cost,
                "revenue": revenue,
                "profit": profit,
                "profit_pct": (profit / revenue * 100) if revenue > 0 else Decimal("0"),
            }
        )

    engineer_stats = {}
    for order in orders:
        key = order.engineer_id or 0
        entry = engineer_stats.setdefault(
            key, {"orders": 0, "revenue": Decimal("0"), "cost": Decimal("0")}
        )
        entry["orders"] += 1
        entry["revenue"] += Decimal(str(order.total_amount or 0)) - Decimal(
            str(order.tax_amount or 0)
        )
        entry["cost"] += sum(
            (
                Decimal(str(it.cost_price or 0)) * Decimal(str(it.quantity or 0))
                for it in order.items
            ),
            Decimal("0"),
        )

    today = date.today()
    monthly = []
    for offset in range(5, -1, -1):
        year, month = today.year, today.month - offset
        while month <= 0:
            month += 12
            year -= 1
        month_start = date(year, month, 1)
        month_end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        month_orders = [
            o
            for o in orders
            if o.received_at and month_start <= o.received_at.date() < month_end
        ]
        revenue = sum(
            (
                Decimal(str(o.total_amount or 0)) - Decimal(str(o.tax_amount or 0))
                for o in month_orders
            ),
            Decimal("0"),
        )
        cost = sum(
            (
                sum(
                    (
                        Decimal(str(it.cost_price or 0))
                        * Decimal(str(it.quantity or 0))
                        for it in o.items
                    ),
                    Decimal("0"),
                )
                for o in month_orders
            ),
            Decimal("0"),
        )
        monthly.append(
            {
                "label": month_start.strftime("%Y-%m"),
                "orders": len(month_orders),
                "revenue": float(revenue),
                "cost": float(cost),
                "profit": float(revenue - cost),
            }
        )

    return render_template(
        "maintenance/cost_report.html",
        order_details=order_details,
        total_orders=analysis["total_orders"],
        total_revenue=analysis["total_revenue"],
        total_cost=analysis["total_parts_cost"] + analysis["total_labor_cost"],
        total_parts_cost=analysis["total_parts_cost"],
        total_labor_cost=analysis["total_labor_cost"],
        total_discount=analysis["total_discount"],
        total_tax=analysis["total_tax"],
        total_paid=analysis["total_paid"],
        gross_profit=analysis["gross_profit"],
        profit_margin=analysis["profit_margin_pct"],
        engineer_stats=engineer_stats,
        monthly=monthly,
        date_from=date_from,
        date_to=date_to,
    )


# ===========================================================================
# Notify the customer (real provider, real outcome)
# ===========================================================================
@maintenance_bp.route("/<int:id>/notify", methods=["POST"])
@login_required
@permission_required("maintenance_work")
def notify_customer(id):
    try:
        result = send_customer_notification(
            id,
            channel=request.form.get("channel", "whatsapp"),
            custom_message=request.form.get("message", "").strip() or None,
            actor_id=current_user.id,
        )
        if result["sent"]:
            flash(
                f"تم إرسال الإشعار إلى {result['contact']} عبر {result['channel']}",
                "success",
            )
        else:
            flash(f"لم يُرسل الإشعار: {result['error']}", "danger")
    except ValidationError as exc:
        _flash_error(exc)
    return redirect(url_for("maintenance.view_order", id=id))


# ===========================================================================
# Purchasing maintenance parts (supplier side)
# ===========================================================================
@maintenance_bp.route("/purchases", methods=["GET", "POST"])
@login_required
@permission_required("maintenance_purchase")
def purchases_list():
    tenant_id = _tenant_id()
    from models import Supplier
    from models.erp_modules import PurchaseOrder

    if request.method == "POST":
        try:
            lines = []
            product_id = request.form.get("product_id", type=int)
            quantity = request.form.get("quantity", type=float)
            unit_cost = request.form.get("unit_cost", type=float)
            if product_id and quantity and unit_cost:
                lines.append(
                    {
                        "product_id": product_id,
                        "quantity": quantity,
                        "unit_cost": unit_cost,
                    }
                )
            purchase = create_maintenance_purchase(
                tenant_id=tenant_id,
                supplier_id=request.form.get("supplier_id", type=int),
                warehouse_id=request.form.get("warehouse_id", type=int),
                lines_data=lines,
                user_id=current_user.id,
                expected_delivery=request.form.get("expected_delivery") or None,
                notes=request.form.get("notes"),
                tax_rate=request.form.get("tax_rate", 0) or 0,
            )
            flash(f"تم إنشاء أمر شراء قطع الصيانة {purchase.po_number}", "success")
            return redirect(url_for("maintenance.purchases_list"))
        except ValidationError as exc:
            _flash_error(exc)
            return redirect(url_for("maintenance.purchases_list"))

    purchases = (
        PurchaseOrder.query.filter_by(tenant_id=tenant_id)
        .order_by(PurchaseOrder.po_date.desc())
        .limit(50)
        .all()
    )
    suppliers = Supplier.query.filter_by(tenant_id=tenant_id, is_active=True).all()
    products = Product.query.filter_by(tenant_id=tenant_id, is_active=True).all()
    warehouses = Warehouse.query.filter_by(tenant_id=tenant_id, is_active=True).all()
    return render_template(
        "maintenance/purchases.html",
        purchases=purchases,
        suppliers=suppliers,
        products=products,
        warehouses=warehouses,
    )


@maintenance_bp.route("/purchases/<int:id>/receive", methods=["POST"])
@login_required
@permission_required("maintenance_purchase")
def receive_purchase(id):
    try:
        purchase = receive_maintenance_purchase(id, current_user.id)
        flash(
            f"تم استلام قطع أمر الشراء {purchase.po_number} وترحيل ذمم الصيانة",
            "success",
        )
    except ValidationError as exc:
        _flash_error(exc)
    return redirect(url_for("maintenance.purchases_list"))


@maintenance_bp.route("/purchases/pay", methods=["POST"])
@login_required
@permission_required("maintenance_cashier")
def pay_supplier():
    try:
        result = pay_maintenance_supplier(
            supplier_id=request.form.get("supplier_id", type=int),
            amount=request.form.get("amount", type=float),
            payment_method=request.form.get("payment_method", "cash"),
            user_id=current_user.id,
        )
        flash(
            f"تم سداد {result['amount']:,.3f} د.إ للمورد — المتبقي {result['outstanding_after']:,.3f} د.إ",
            "success",
        )
    except ValidationError as exc:
        _flash_error(exc)
    return redirect(url_for("maintenance.purchases_list"))


# ===========================================================================
# Customer rating
# ===========================================================================
@maintenance_bp.route("/<int:id>/rate", methods=["POST"])
@login_required
@permission_required("maintenance_view")
def rate_order(id):
    order = _order_or_404(id)
    rating = request.form.get("rating", type=int)
    comment = request.form.get("comment", "")
    if not rating or rating < 1 or rating > 5:
        flash("التقييم يجب أن يكون بين 1 و 5", "danger")
        return redirect(url_for("maintenance.view_order", id=id))
    order.customer_rating = rating
    order.customer_comment = comment
    order.rated_at = datetime.now(timezone.utc)
    db.session.commit()
    flash("تم تسجيل تقييم العميل بنجاح", "success")
    return redirect(url_for("maintenance.view_order", id=id))


# ===========================================================================
# Warranty period after the service
# ===========================================================================
@maintenance_bp.route("/<int:id>/warranty-period", methods=["POST"])
@login_required
@permission_required("maintenance_work")
def set_warranty_period(id):
    order = _order_or_404(id)
    warranty_days = request.form.get("warranty_days", type=int)
    if warranty_days is None or warranty_days < 0:
        flash("أيام الضمان يجب أن تكون رقماً غير سالب", "danger")
        return redirect(url_for("maintenance.view_order", id=id))
    order.warranty_period_days = warranty_days
    order.warranty_period_notes = request.form.get("warranty_notes", "")
    order.warranty_period_start = date.today()
    order.warranty_period_end = date.today() + timedelta(days=warranty_days)
    db.session.commit()
    flash(f"تم تعيين فترة ضمان {warranty_days} يوم", "success")
    return redirect(url_for("maintenance.view_order", id=id))


# ===========================================================================
# Archive order (soft delete)
# ===========================================================================
@maintenance_bp.route("/<int:id>/archive", methods=["POST"])
@login_required
@permission_required("maintenance_close")
def archive_order(id):
    order = _order_or_404(id)
    if order.status not in ("closed", "cancelled"):
        flash("لا يمكن أرشفة أمر لم يُغلق بعد", "danger")
        return redirect(url_for("maintenance.view_order", id=id))
    if order.is_archived:
        flash("الأمر مؤرشف بالفعل", "info")
        return redirect(url_for("maintenance.list_orders"))
    order.is_archived = True
    order.archived_at = datetime.now(timezone.utc)
    order.archived_by = current_user.id
    db.session.commit()
    flash("تم أرشفة أمر الصيانة", "success")
    return redirect(url_for("maintenance.list_orders"))
