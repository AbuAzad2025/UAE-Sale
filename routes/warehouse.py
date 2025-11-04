from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from extensions import db
from models import Product, StockMovement, Warehouse
from services.stock_service import StockService
from utils.decorators import permission_required
from decimal import Decimal

warehouse_bp = Blueprint('warehouse', __name__, url_prefix='/warehouse')


@warehouse_bp.route('/')
@login_required
@permission_required('manage_warehouse')
def index():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    search = request.args.get('search', '', type=str)
    category_id = request.args.get('category', type=int)
    stock_filter = request.args.get('stock', '', type=str)
    
    query = Product.query.filter_by(is_active=True)
    
    if search:
        search_filter = f'%{search}%'
        query = query.filter(
            db.or_(
                Product.name.ilike(search_filter),
                Product.sku.ilike(search_filter),
                Product.barcode.ilike(search_filter)
            )
        )
    
    if category_id:
        query = query.filter_by(category_id=category_id)
    
    if stock_filter == 'low':
        query = query.filter(Product.current_stock <= Product.min_stock_alert)
    elif stock_filter == 'out':
        query = query.filter(Product.current_stock <= 0)
    
    pagination = query.order_by(Product.name).paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )
    
    return render_template('warehouse/index.html',
                         products=pagination.items,
                         pagination=pagination)


@warehouse_bp.route('/movements')
@login_required
@permission_required('manage_warehouse')
def movements():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    product_id = request.args.get('product', type=int)
    movement_type = request.args.get('type', '', type=str)
    
    query = StockMovement.query
    
    if product_id:
        query = query.filter_by(product_id=product_id)
    
    if movement_type:
        query = query.filter_by(movement_type=movement_type)
    
    pagination = query.order_by(StockMovement.created_at.desc()).paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )
    
    return render_template('warehouse/movements.html',
                         movements=pagination.items,
                         pagination=pagination)


@warehouse_bp.route('/low-stock')
@login_required
@permission_required('manage_warehouse')
def low_stock():
    products = StockService.get_low_stock_products()
    return render_template('warehouse/low_stock.html', products=products)


@warehouse_bp.route('/out-of-stock')
@login_required
@permission_required('manage_warehouse')
def out_of_stock():
    products = StockService.get_out_of_stock_products()
    return render_template('warehouse/out_of_stock.html', products=products)


@warehouse_bp.route('/create-warehouse', methods=['GET', 'POST'])
@login_required
@permission_required('admin')
def create_warehouse():
    if request.method == 'POST':
        try:
            name = request.form.get('name', '').strip()
            name_ar = request.form.get('name_ar', '').strip()
            code = request.form.get('code', '').strip()
            location = request.form.get('location', '').strip()
            parent_id = request.form.get('parent_id', type=int) or None
            manager_id = request.form.get('manager_id', type=int) or None
            is_main = request.form.get('is_main') == 'on'
            
            if not name:
                flash('اسم المستودع مطلوب', 'error')
                return redirect(url_for('warehouse.create_warehouse'))
            
            if not location:
                flash('الموقع مطلوب', 'error')
                return redirect(url_for('warehouse.create_warehouse'))
            
            # Check if code exists
            if code:
                existing = Warehouse.query.filter_by(code=code).first()
                if existing:
                    flash('رمز المستودع موجود مسبقاً', 'error')
                    return redirect(url_for('warehouse.create_warehouse'))
            
            # Check if parent warehouse exists
            if parent_id:
                parent_warehouse = Warehouse.query.get(parent_id)
                if not parent_warehouse:
                    flash('المستودع الأب غير موجود', 'error')
                    return redirect(url_for('warehouse.create_warehouse'))
                if not parent_warehouse.is_active:
                    flash('المستودع الأب غير نشط', 'error')
                    return redirect(url_for('warehouse.create_warehouse'))
            
            warehouse = Warehouse(
                name=name,
                name_ar=name_ar,
                code=code,
                location=location,
                parent_id=parent_id,
                is_main=is_main,
                manager_id=manager_id or current_user.id,
                is_active=True
            )
            
            db.session.add(warehouse)
            db.session.commit()
            
            warehouse_type = "فرعي" if parent_id else "مستقل"
            flash(f'✓ تم إنشاء المستودع {warehouse_type} "{name}" بنجاح', 'success')
            return redirect(url_for('warehouse.list_warehouses'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'خطأ في إنشاء المستودع: {str(e)}', 'error')
            return redirect(url_for('warehouse.create_warehouse'))
    
    # GET request - show form with data
    from models import User
    
    # Get all active warehouses for parent selection (except sub-warehouses)
    parent_warehouses = Warehouse.query.filter_by(is_active=True, parent_id=None).all()
    
    # Get all users for manager selection
    users = User.query.filter_by(is_active=True).all()
    
    return render_template('warehouse/create_warehouse.html', 
                         parent_warehouses=parent_warehouses,
                         users=users)


@warehouse_bp.route('/list')
@login_required
@permission_required('manage_warehouse')
def list_warehouses():
    warehouses = Warehouse.query.filter_by(is_active=True).all()
    return render_template('warehouse/list_warehouses.html', warehouses=warehouses)


@warehouse_bp.route('/add-stock/<int:product_id>', methods=['POST'])
@login_required
@permission_required('manage_warehouse')
def add_stock(product_id):
    try:
        product = Product.query.get_or_404(product_id)
        quantity = Decimal(request.form.get('quantity', 0))
        notes = request.form.get('notes', '').strip()
        warehouse_id = request.form.get('warehouse_id', type=int)
        
        if quantity <= 0:
            return jsonify({'success': False, 'message': 'الكمية يجب أن تكون أكبر من صفر'}), 400
        
        # Update product stock
        product.current_stock = (product.current_stock or Decimal('0')) + quantity
        
        if not warehouse_id:
            warehouse = Warehouse.query.filter_by(is_active=True, is_main=True).first()
            if not warehouse:
                warehouse = Warehouse.query.filter_by(is_active=True).first()
            if not warehouse:
                return jsonify({'success': False, 'message': 'لا يوجد مستودع نشط'}), 400
            warehouse_id = warehouse.id
        
        movement = StockMovement(
            product_id=product_id,
            warehouse_id=warehouse_id,
            movement_type='adjustment',
            quantity=quantity,
            user_id=current_user.id,
            notes=notes or 'إضافة كمية يدوية'
        )
        
        db.session.add(movement)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'تم إضافة {quantity} وحدة للمنتج {product.name}',
            'new_stock': float(product.current_stock)
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

