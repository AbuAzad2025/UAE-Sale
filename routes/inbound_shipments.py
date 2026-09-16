"""
Inbound Shipments — استقبال شحنات البضائع الواردة
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from extensions import db
from models.inbound_shipment import InboundShipment
from services.inbound_shipment_service import InboundShipmentService
from utils.decorators import permission_required
from utils.helpers import create_audit_log
from models.tenant_scope import get_current_tenant_id

inbound_bp = Blueprint('inbound_shipments', __name__, url_prefix='/inbound-shipments')


def _tenant_id():
    try:
        return get_current_tenant_id()
    except Exception:
        return None


@inbound_bp.route('')
@login_required
@permission_required('manage_warehouse')
def list_inbound():
    status = request.args.get('status', '', type=str)
    q = InboundShipment.query
    if status:
        q = q.filter_by(status=status)
    rows = q.order_by(InboundShipment.created_at.desc()).all()
    return render_template('inbound_shipments/list.html', shipments=rows)


@inbound_bp.route('/<int:id>')
@login_required
@permission_required('manage_warehouse')
def view_inbound(id):
    s = db.get_or_404(InboundShipment, id)
    return render_template('inbound_shipments/view.html', shipment=s)


@inbound_bp.route('/create', methods=['GET', 'POST'])
@login_required
@permission_required('manage_warehouse')
def create_inbound():
    if request.method == 'POST':
        try:
            lines_data = []
            i = 0
            while True:
                pid = request.form.get(f'lines[{i}][product_id]', type=int)
                if not pid:
                    break
                qty = request.form.get(f'lines[{i}][quantity_expected]', type=float)
                cost = request.form.get(f'lines[{i}][unit_cost]', 0, type=float)
                if pid and qty and qty > 0:
                    lines_data.append({'product_id': pid, 'quantity_expected': qty, 'unit_cost': cost})
                i += 1
            if not lines_data:
                flash('⚠️ يجب إضافة منتج واحد على الأقل', 'danger')
                return redirect(url_for('inbound_shipments.create_inbound'))
            exp_str = request.form.get('expected_at')
            from datetime import datetime
            exp = datetime.strptime(exp_str, '%Y-%m-%d').date() if exp_str else None
            s = InboundShipmentService.create_shipment(
                warehouse_id=request.form.get('warehouse_id', type=int),
                supplier_id=request.form.get('supplier_id', type=int),
                purchase_order_id=request.form.get('purchase_order_id', type=int),
                carrier=request.form.get('carrier'),
                tracking_number=request.form.get('tracking_number'),
                expected_at=exp,
                tenant_id=_tenant_id(),
                created_by_id=current_user.id,
                lines_data=lines_data,
                notes=request.form.get('notes'),
            )
            create_audit_log('create', 'inbound_shipments', s.id)
            flash(f'✅ تم إنشاء شحنة واردة {s.shipment_number}', 'success')
            return redirect(url_for('inbound_shipments.view_inbound', id=s.id))
        except Exception as e:
            db.session.rollback()
            flash(f'❌ خطأ: {str(e)}', 'danger')
    from models import Warehouse, Product, Supplier
    from models.erp_modules import PurchaseOrder
    warehouses = Warehouse.query.filter_by(is_active=True).all()
    products = Product.query.filter_by(is_active=True).order_by(Product.name).all()
    suppliers = Supplier.query.filter_by(is_active=True).all()
    pos = PurchaseOrder.query.order_by(PurchaseOrder.created_at.desc()).limit(50).all()
    return render_template('inbound_shipments/create.html', warehouses=warehouses, products=products, suppliers=suppliers, purchase_orders=pos)


@inbound_bp.route('/<int:id>/arrive', methods=['POST'])
@login_required
@permission_required('manage_warehouse')
def arrive_inbound(id):
    try:
        InboundShipmentService.arrive(id, current_user.id)
        flash('✅ تم تأكيد وصول الشحنة', 'success')
    except ValueError as e:
        flash(f'⚠️ {str(e)}', 'danger')
    return redirect(url_for('inbound_shipments.view_inbound', id=id))


@inbound_bp.route('/<int:id>/inspect', methods=['POST'])
@login_required
@permission_required('manage_warehouse')
def inspect_inbound(id):
    try:
        # Accept all by default; detailed quantities can be posted as line_id/quantity_accepted
        InboundShipmentService.inspect_shipment(id)
        flash('✅ تم الفحص', 'success')
    except ValueError as e:
        flash(f'⚠️ {str(e)}', 'danger')
    return redirect(url_for('inbound_shipments.view_inbound', id=id))


@inbound_bp.route('/<int:id>/put-away', methods=['POST'])
@login_required
@permission_required('manage_warehouse')
def put_away_inbound(id):
    try:
        InboundShipmentService.put_away(id, current_user.id)
        flash('✅ تم إدخال البضاعة للمستودعات', 'success')
    except ValueError as e:
        flash(f'⚠️ {str(e)}', 'danger')
    return redirect(url_for('inbound_shipments.view_inbound', id=id))


@inbound_bp.route('/<int:id>/close', methods=['POST'])
@login_required
@permission_required('manage_warehouse')
def close_inbound(id):
    try:
        InboundShipmentService.close(id, current_user.id)
        flash('✅ تم إغلاق الشحنة', 'success')
    except ValueError as e:
        flash(f'⚠️ {str(e)}', 'danger')
    return redirect(url_for('inbound_shipments.view_inbound', id=id))


@inbound_bp.route('/<int:id>/cancel', methods=['POST'])
@login_required
@permission_required('manage_warehouse')
def cancel_inbound(id):
    try:
        InboundShipmentService.cancel(id, current_user.id)
        flash('✅ تم إلغاء الشحنة', 'success')
    except ValueError as e:
        flash(f'⚠️ {str(e)}', 'danger')
    return redirect(url_for('inbound_shipments.view_inbound', id=id))
