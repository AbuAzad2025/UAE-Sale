from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user
from extensions import db
from models import Product, ProductCategory
from utils.decorators import permission_required
from utils.helpers import create_audit_log, generate_sku, generate_barcode, save_uploaded_file
from services.stock_service import StockService

products_bp = Blueprint('products', __name__, url_prefix='/products')


@products_bp.route('/')
@login_required
@permission_required('manage_products')
def index():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    search = request.args.get('search', '', type=str)
    category_id = request.args.get('category', type=int)
    stock_filter = request.args.get('stock', '', type=str)
    
    query = Product.query
    
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
    
    query = query.filter_by(is_active=True)
    
    pagination = query.order_by(Product.name).paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )
    
    categories = ProductCategory.query.filter_by(is_active=True).all()
    
    return render_template('products/index.html',
                         products=pagination.items,
                         pagination=pagination,
                         categories=categories)


@products_bp.route('/create', methods=['GET', 'POST'])
@login_required
@permission_required('manage_products')
def create():
    from forms.product import ProductForm
    form = ProductForm()
    
    # تعيين choices للتصنيفات
    categories = ProductCategory.query.filter_by(is_active=True).all()
    form.category_id.choices = [(0, 'بدون تصنيف')] + [(c.id, c.name) for c in categories]
    
    if request.method == 'POST':
        current_app.logger.info(f"POST request to create product. Form data keys: {list(request.form.keys())}")
        
        if form.validate_on_submit():
            try:
                current_app.logger.info("Form validation passed. Creating product...")
                sku = request.form.get('sku')
                if not sku:
                    sku = generate_sku()
                
                # تحويل الأسعار إلى float مع التعامل مع القيم الفارغة
                def safe_float(value, default=0.0):
                    if not value or value.strip() == '':
                        return default
                    try:
                        return float(value)
                    except (ValueError, TypeError):
                        return default
                
                product = Product(
                    name=request.form.get('name'),
                    name_ar=request.form.get('name_ar'),
                    sku=sku,
                    barcode=request.form.get('barcode') or generate_barcode(),
                    category_id=request.form.get('category_id') or None,
                    regular_price=safe_float(request.form.get('regular_price')),
                    merchant_price=safe_float(request.form.get('merchant_price')),
                    partner_price=safe_float(request.form.get('partner_price')),
                    cost_price=safe_float(request.form.get('cost_price')),
                    current_stock=safe_float(request.form.get('current_stock')),
                    min_stock_alert=safe_float(request.form.get('min_stock_alert')),
                    unit=request.form.get('unit', 'piece'),
                    location=request.form.get('location'),
                    description=request.form.get('description'),
                    notes=request.form.get('notes')
                )
                
                current_app.logger.info(f"Product object created: {product.name}")
                
                if 'image' in request.files:
                    file = request.files['image']
                    if file.filename:
                        image_path = save_uploaded_file(file, 'products')
                        if image_path:
                            product.image_url = image_path
                
                db.session.add(product)
                db.session.commit()
                current_app.logger.info(f"Product saved to database with ID: {product.id}")
                
                create_audit_log('create', 'products', product.id)
                
                flash('تم إضافة المنتج بنجاح', 'success')
                return redirect(url_for('products.index'))
            
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error creating product: {str(e)}")
                flash(f'حدث خطأ: {str(e)}', 'danger')
        else:
            # Form validation failed
            current_app.logger.warning(f"Form validation failed. Errors: {form.errors}")
            for field, errors in form.errors.items():
                for error in errors:
                    flash(f'خطأ في حقل {field}: {error}', 'danger')
    
    categories = ProductCategory.query.filter_by(is_active=True).all()
    return render_template('products/create.html', form=form, categories=categories)


@products_bp.route('/<int:id>')
@login_required
@permission_required('manage_products')
def view(id):
    product = Product.query.get_or_404(id)
    
    movements = product.stock_movements.order_by(
        db.desc('created_at')
    ).limit(20).all()
    
    return render_template('products/view.html',
                         product=product,
                         movements=movements)


@products_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('manage_products')
def edit(id):
    product = Product.query.get_or_404(id)
    from forms.product import ProductForm
    form = ProductForm(obj=product)
    
    # تعيين choices للتصنيفات
    categories = ProductCategory.query.filter_by(is_active=True).all()
    form.category_id.choices = [(0, 'بدون تصنيف')] + [(c.id, c.name) for c in categories]
    
    if request.method == 'POST' and form.validate_on_submit():
        try:
            product.name = request.form.get('name')
            product.name_ar = request.form.get('name_ar')
            product.sku = request.form.get('sku')
            product.barcode = request.form.get('barcode')
            product.category_id = request.form.get('category_id') or None
            product.regular_price = request.form.get('regular_price')
            product.merchant_price = request.form.get('merchant_price')
            product.partner_price = request.form.get('partner_price')
            product.min_stock_alert = request.form.get('min_stock_alert')
            product.unit = request.form.get('unit')
            product.location = request.form.get('location')
            product.description = request.form.get('description')
            product.notes = request.form.get('notes')
            
            if current_user.can_see_costs():
                product.cost_price = request.form.get('cost_price')
            
            if 'image' in request.files:
                file = request.files['image']
                if file.filename:
                    image_path = save_uploaded_file(file, 'products')
                    if image_path:
                        product.image_url = image_path
            
            db.session.commit()
            
            create_audit_log('update', 'products', product.id)
            
            flash('تم تحديث بيانات المنتج بنجاح', 'success')
            return redirect(url_for('products.view', id=product.id))
        
        except Exception as e:
            db.session.rollback()
            flash(f'حدث خطأ: {str(e)}', 'danger')
    
    categories = ProductCategory.query.filter_by(is_active=True).all()
    return render_template('products/edit.html', form=form, product=product, categories=categories)


@products_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('manage_products')
def delete(id):
    """حذف (إلغاء تفعيل) المنتج - soft delete"""
    product = Product.query.get_or_404(id)
    
    try:
        # التحقق من وجود عمليات مرتبطة
        from models import SaleLine, PurchaseLine
        sales_count = SaleLine.query.filter_by(product_id=id).count()
        purchases_count = PurchaseLine.query.filter_by(product_id=id).count()
        
        if sales_count > 0 or purchases_count > 0:
            # soft delete
            product.is_active = False
            db.session.commit()
            flash(f'تم إلغاء تفعيل المنتج "{product.name}" (لديه عمليات مسجلة)', 'warning')
            create_audit_log('deactivate', 'products', id)
        else:
            # hard delete
            db.session.delete(product)
            db.session.commit()
            flash(f'تم حذف المنتج "{product.name}" نهائياً', 'success')
            create_audit_log('delete', 'products', id)
        
        return redirect(url_for('products.index'))
    
    except Exception as e:
        db.session.rollback()
        flash(f'خطأ في الحذف: {str(e)}', 'danger')
        return redirect(url_for('products.view', id=id))


@products_bp.route('/api/search')
@login_required
def api_search():
    """API endpoint للبحث عن المنتجات"""
    query = request.args.get('q', '')
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    # السماح بالبحث حتى بدون query (لعرض كل المنتجات)
    if query and len(query) >= 1:
        products = Product.query.filter(
            Product.is_active == True,
            db.or_(
                Product.name.ilike(f'%{query}%'),
                Product.sku.ilike(f'%{query}%'),
                Product.barcode.ilike(f'%{query}%')
            )
        ).order_by(Product.name).limit(per_page).all()
    else:
        # عرض كل المنتجات (مرتبين أبجدياً)
        products = Product.query.filter_by(
            is_active=True
        ).order_by(Product.name).limit(per_page).all()
    
    results = [{
        'id': p.id,
        'name': p.name,
        'code': p.sku or '',
        'text': f"{p.name} ({p.sku})" if p.sku else p.name,
        'sku': p.sku,
        'price': float(p.regular_price),
        'stock': float(p.current_stock),
        'unit': p.unit,
        'is_low_stock': p.is_low_stock(),
    } for p in products]
    
    return jsonify(results)


@products_bp.route('/categories')
@login_required
@permission_required('manage_products')
def categories():
    categories = ProductCategory.query.filter_by(is_active=True).order_by(ProductCategory.name).all()
    return render_template('products/categories.html', categories=categories)


@products_bp.route('/categories/create', methods=['POST'])
@login_required
@permission_required('manage_products')
def create_category():
    try:
        # دعم JSON و Form Data
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form
        
        category = ProductCategory(
            name=data.get('name'),
            name_ar=data.get('name_ar'),
            description=data.get('description')
        )
        
        db.session.add(category)
        db.session.commit()
        
        # إرجاع JSON إذا كان الطلب JSON
        if request.is_json:
            return jsonify({
                'success': True,
                'message': 'تم إضافة الفئة بنجاح',
                'category': {
                    'id': category.id,
                    'name': category.name,
                    'name_ar': category.name_ar,
                    'description': category.description
                }
            })
        
        flash('تم إضافة التصنيف بنجاح', 'success')
        return redirect(url_for('products.categories'))
    
    except Exception as e:
        db.session.rollback()
        
        if request.is_json:
            return jsonify({
                'success': False,
                'error': str(e)
            }), 400
        
        flash(f'حدث خطأ: {str(e)}', 'danger')
        return redirect(url_for('products.categories'))


@products_bp.route('/<int:id>/adjust-stock', methods=['POST'])
@login_required
@permission_required('manage_products')
def adjust_stock(id):
    product = Product.query.get_or_404(id)
    
    try:
        adjustment_type = request.form.get('adjustment_type')
        quantity = float(request.form.get('quantity', 0))
        reason = request.form.get('reason', 'adjustment')
        notes = request.form.get('notes', '')
        
        if quantity <= 0:
            return jsonify({'success': False, 'message': 'الكمية يجب أن تكون أكبر من صفر'})
        
        old_stock = product.current_stock
        
        if adjustment_type == 'add':
            new_stock = old_stock + quantity
        elif adjustment_type == 'subtract':
            new_stock = old_stock - quantity
            if new_stock < 0:
                return jsonify({'success': False, 'message': 'لا يمكن أن يكون المخزون سالباً'})
        elif adjustment_type == 'set':
            new_stock = quantity
        else:
            return jsonify({'success': False, 'message': 'نوع التعديل غير صحيح'})
        
        product.current_stock = new_stock
        
        from models import StockMovement
        movement = StockMovement(
            product_id=product.id,
            movement_type='adjustment',
            quantity=quantity if adjustment_type != 'set' else (new_stock - old_stock),
            previous_stock=old_stock,
            new_stock=new_stock,
            reference=f'تعديل يدوي - {reason}',
            notes=notes,
            user_id=current_user.id
        )
        
        db.session.add(movement)
        db.session.commit()
        
        create_audit_log('update', 'products', product.id, f'تعديل مخزون: {old_stock} → {new_stock}')
        
        return jsonify({
            'success': True, 
            'message': f'تم تعديل المخزون من {old_stock} إلى {new_stock}',
            'new_stock': new_stock
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'حدث خطأ: {str(e)}'})

