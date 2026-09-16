"""
Shipments — الإرساليات الميدانية

Dedicated flow distinct from stock_transfers (warehouse↔warehouse):
Shipment is a field sales expedition: take goods from any warehouse to a site,
then sell/charge/invoice until closed.
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from extensions import db
from models.shipment import Shipment
from services.shipment_service import ShipmentService
from utils.decorators import permission_required
from utils.helpers import create_audit_log
from models.tenant_scope import get_current_tenant_id

shipment_bp = Blueprint('shipments', __name__, url_prefix='/shipments')


def _tenant_id():
    try:
        return get_current_tenant_id()
    except Exception:
        return None


@shipment_bp.route('')
@login_required
@permission_required('manage_warehouse')
def list_shipments():
    status = request.args.get('status', '', type=str)
    q = Shipment.query
    if status:
        q = q.filter_by(status=status)
    shipments = q.order_by(Shipment.created_at.desc()).all()
    return render_template('shipments/list.html', shipments=shipments)


@shipment_bp.route('/<int:id>')
@login_required
@permission_required('manage_warehouse')
def view_shipment(id):
    s = db.get_or_404(Shipment, id)
    # Sales linked to this shipment (if any)
    from models.sale import Sale
    sales = Sale.query.filter_by(shipment_id=s.id).order_by(Sale.created_at.desc()).all() if hasattr(Sale, 'shipment_id') else []
    return render_template('shipments/view.html', shipment=s, sales=sales)


@shipment_bp.route('/create', methods=['GET', 'POST'])
@login_required
@permission_required('manage_warehouse')
def create_shipment():
    if request.method == 'POST':
        try:
            lines_data = []
            i = 0
            while True:
                pid = request.form.get(f'lines[{i}][product_id]', type=int)
                if not pid:
                    break
                qty = request.form.get(f'lines[{i}][quantity]', type=float)
                cost = request.form.get(f'lines[{i}][unit_cost]', 0, type=float)
                price = request.form.get(f'lines[{i}][unit_price]', 0, type=float)
                if pid and qty and qty > 0:
                    lines_data.append({'product_id': pid, 'quantity': qty, 'unit_cost': cost, 'unit_price': price})
                i += 1
            if not lines_data:
                flash('⚠️ يجب إضافة منتج واحد على الأقل', 'danger')
                return redirect(url_for('shipments.create_shipment'))
            s = ShipmentService.create_shipment(
                from_warehouse_id=request.form.get('from_warehouse_id', type=int),
                destination_name=request.form.get('destination_name'),
                destination_warehouse_id=request.form.get('destination_warehouse_id', type=int),
                destination_type=request.form.get('destination_type', 'site'),
                tenant_id=_tenant_id(),
                created_by_id=current_user.id,
                assigned_to_id=request.form.get('assigned_to_id', type=int),
                lines_data=lines_data,
                notes=request.form.get('notes'),
            )
            create_audit_log('create', 'shipments', s.id)
            flash(f'✅ تم إنشاء الإرسالية {s.shipment_number}', 'success')
            return redirect(url_for('shipments.view_shipment', id=s.id))
        except Exception as e:
            db.session.rollback()
            flash(f'❌ خطأ: {str(e)}', 'danger')
    from models import Warehouse, Product
    from models.user import User
    warehouses = Warehouse.query.filter_by(is_active=True).all()
    products = Product.query.filter_by(is_active=True).order_by(Product.name).all()
    users = User.query.filter_by(is_active=True).all()
    return render_template('shipments/create.html', warehouses=warehouses, products=products, users=users)


@shipment_bp.route('/<int:id>/send', methods=['POST'])
@login_required
@permission_required('manage_warehouse')
def send_shipment(id):
    try:
        ShipmentService.send_shipment(id, current_user.id)
        flash('✅ تم إرسال الإرسالية', 'success')
    except ValueError as e:
        flash(f'⚠️ {str(e)}', 'danger')
    return redirect(url_for('shipments.view_shipment', id=id))


@shipment_bp.route('/<int:id>/arrive', methods=['POST'])
@login_required
@permission_required('manage_warehouse')
def arrive_shipment(id):
    try:
        ShipmentService.arrive_shipment(id, current_user.id)
        flash('✅ تم تأكيد وصول الإرسالية', 'success')
    except ValueError as e:
        flash(f'⚠️ {str(e)}', 'danger')
    return redirect(url_for('shipments.view_shipment', id=id))


@shipment_bp.route('/<int:id>/start-selling', methods=['POST'])
@login_required
@permission_required('manage_warehouse')
def start_selling(id):
    try:
        ShipmentService.start_selling(id, current_user.id)
        flash('✅ بدأ البيع الميداني', 'success')
    except ValueError as e:
        flash(f'⚠️ {str(e)}', 'danger')
    return redirect(url_for('shipments.view_shipment', id=id))


@shipment_bp.route('/<int:id>/close', methods=['POST'])
@login_required
@permission_required('manage_warehouse')
def close_shipment(id):
    try:
        ShipmentService.close_shipment(id, current_user.id)
        flash('✅ تم إغلاق الإرسالية', 'success')
    except ValueError as e:
        flash(f'⚠️ {str(e)}', 'danger')
    return redirect(url_for('shipments.view_shipment', id=id))


@shipment_bp.route('/<int:id>/cancel', methods=['POST'])
@login_required
@permission_required('manage_warehouse')
def cancel_shipment(id):
    try:
        ShipmentService.cancel_shipment(id, current_user.id)
        flash('✅ تم إلغاء الإرسالية', 'success')
    except ValueError as e:
        flash(f'⚠️ {str(e)}', 'danger')
    return redirect(url_for('shipments.view_shipment', id=id))


# JSON helpers for Select2 (reuse shipments.js expectations)
@shipment_bp.route('/api/warehouses')
@login_required
def api_warehouses():
    q = request.args.get('q', '', type=str).strip()
    from models import Warehouse
    query = Warehouse.query.filter_by(is_active=True)
    if q:
        query = query.filter(Warehouse.name.ilike(f'%{q}%'))
    rows = query.limit(20).all()
    return jsonify([{'id': w.id, 'text': w.name, 'name': w.name} for w in rows])


@shipment_bp.route('/api/products')
@login_required
def api_products():
    q = request.args.get('q', '', type=str).strip()
    from models import Product
    query = Product.query.filter_by(is_active=True)
    if q:
        query = query.filter(Product.name.ilike(f'%{q}%'))
    rows = query.limit(20).all()
    return jsonify([{'id': p.id, 'text': p.name, 'name': p.name, 'unit_price': str(p.regular_price or 0)} for p in rows])
