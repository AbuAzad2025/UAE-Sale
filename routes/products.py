from decimal import Decimal

from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user
from extensions import db, limiter
from models import Product, ProductCategory, Customer, ProductPartner
from utils.decorators import permission_required, get_owned_or_404

from utils.helpers import create_audit_log, generate_sku, generate_barcode, save_uploaded_file
from services.stock_service import StockService

products_bp = Blueprint('products', __name__, url_prefix='/products')


def _parse_product_partners(form):  # noqa: C901
    raw_partner_ids = form.getlist('partner_customer_id')
    raw_percentages = form.getlist('partner_percentage')
    count = max(len(raw_partner_ids), len(raw_percentages))

    seen_partner_ids = set()
    partners = []
    total = 0.0

    for i in range(count):
        partner_id_raw = (raw_partner_ids[i] if i < len(raw_partner_ids) else '') or ''
        percentage_raw = (raw_percentages[i] if i < len(raw_percentages) else '') or ''

        partner_id_raw = partner_id_raw.strip()
        percentage_raw = percentage_raw.strip()

        if not partner_id_raw and not percentage_raw:
            continue

        if not partner_id_raw or not percentage_raw:
            return None, '⚠️ يرجى اختيار الشريك وإدخال نسبته في كل سطر.'

        try:
            partner_id = int(partner_id_raw)
        except Exception:
            return None, '⚠️ الشريك المحدد غير صالح.'

        try:
            percentage = float(percentage_raw)
        except Exception:
            return None, '⚠️ نسبة الشريك غير صحيحة.'

        if percentage <= 0 or percentage > 100:
            return None, '⚠️ نسبة الشريك يجب أن تكون بين 0 و 100.'

        if partner_id in seen_partner_ids:
            return None, '⚠️ لا يمكن تكرار نفس الشريك أكثر من مرة لنفس المنتج.'

        partner_customer = Customer.query.filter_by(id=partner_id, is_active=True, customer_type='partner').first()
        if not partner_customer:
            return None, '⚠️ الشريك المحدد غير موجود أو غير مُعرّف كـ شريك.'

        seen_partner_ids.add(partner_id)
        total += percentage
        partners.append({'partner_customer_id': partner_id, 'percentage': percentage})

    if total > 100.000001:
        return None, '⚠️ مجموع نسب الشركاء لا يمكن أن يتجاوز 100%.'

    return partners, None


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
@limiter.limit("10 per minute", methods=['POST'])
def create():  # noqa: C901
    from forms.product import ProductForm
    from models import Warehouse

    form = ProductForm()

    # تعيين choices للتصنيفات
    categories = ProductCategory.query.filter_by(is_active=True).all()
    form.category_id.choices = [(0, 'بلا')] + [(c.id, c.name) for c in categories]
    preselected_warehouse_id = request.args.get('warehouse_id', type=int)
    merchants = Customer.query.filter_by(is_active=True, customer_type='merchant').order_by(Customer.name).all()
    partners = Customer.query.filter_by(is_active=True, customer_type='partner').order_by(Customer.name).all()

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

                warehouse_id = request.form.get('warehouse_id', type=int)
                current_stock = safe_float(request.form.get('current_stock'))
                initial_stock = current_stock

                # التحقق من المستودع
                if not warehouse_id:
                    flash('⚠️ يجب اختيار المستودع', 'warning')
                    warehouses = Warehouse.query.filter_by(is_active=True).all()
                    return render_template('products/create.html', form=form, categories=categories, warehouses=warehouses, merchants=merchants, partners=partners)  # noqa: E501

                warehouse = db.session.get(Warehouse, warehouse_id)
                if not warehouse or not warehouse.is_active:
                    flash('⚠️ المستودع المحدد غير صالح', 'warning')
                    warehouses = Warehouse.query.filter_by(is_active=True).all()
                    return render_template('products/create.html', form=form, categories=categories, warehouses=warehouses, merchants=merchants, partners=partners)  # noqa: E501

                merchant_customer_id = request.form.get('merchant_customer_id', type=int)
                if merchant_customer_id:
                    merchant_customer = Customer.query.filter_by(id=merchant_customer_id, is_active=True, customer_type='merchant').first()
                    if not merchant_customer:
                        flash('⚠️ التاجر المحدد غير موجود أو غير مُعرّف كتاجر.', 'warning')
                        warehouses = Warehouse.query.filter_by(is_active=True).all()
                        return render_template('products/create.html', form=form, categories=categories, warehouses=warehouses, merchants=merchants, partners=partners)  # noqa: E501

                partner_rows, partner_error = _parse_product_partners(request.form)
                if partner_error:
                    flash(partner_error, 'warning')
                    warehouses = Warehouse.query.filter_by(is_active=True).all()
                    return render_template('products/create.html', form=form, categories=categories, warehouses=warehouses, merchants=merchants, partners=partners)  # noqa: E501

                unit_value = request.form.get('unit') or None

                product = Product(
                    name=request.form.get('name'),
                    name_ar=request.form.get('name_ar'),
                    sku=sku,
                    part_number=request.form.get('part_number'),
                    barcode=request.form.get('barcode') or generate_barcode(),
                    category_id=(form.category_id.data or None),
                    regular_price=safe_float(request.form.get('regular_price')),
                    merchant_price=safe_float(request.form.get('merchant_price')),
                    merchant_share=safe_float(request.form.get('merchant_share'), default=100.0),
                    partner_price=safe_float(request.form.get('partner_price')),
                    cost_price=safe_float(request.form.get('cost_price')),
                    current_stock=0,
                    min_stock_alert=safe_float(request.form.get('min_stock_alert')),
                    unit=unit_value,
                    location=request.form.get('location'),
                    description=request.form.get('description'),
                    notes=request.form.get('notes'),
                    merchant_customer_id=merchant_customer_id or None,
                )

                current_app.logger.info(f"Product object created: {product.name}")

                if 'image' in request.files:
                    file = request.files['image']
                    if file.filename:
                        image_path = save_uploaded_file(file, 'products')
                        if image_path:
                            product.image_url = image_path

                db.session.add(product)
                db.session.flush()  # للحصول على product.id

                if partner_rows:
                    for row in partner_rows:
                        product.partner_shares.append(ProductPartner(
                            product_id=product.id,
                            partner_customer_id=row['partner_customer_id'],
                            percentage=row['percentage'],
                        ))

                # إضافة حركة مخزون إذا كانت الكمية أكبر من صفر
                if initial_stock > 0:
                    StockService.create_movement(
                        product_id=product.id,
                        quantity=initial_stock,
                        movement_type='adjustment',
                        reference_type='Product Creation',
                        reference_id=product.id,
                        notes=f'مخزون أولي عند إضافة المنتج إلى المستودع: {warehouse.name_ar or warehouse.name}',
                        warehouse_id=warehouse_id
                    )

                db.session.commit()
                current_app.logger.info(f"Product saved to database with ID: {product.id}")

                create_audit_log('create', 'products', product.id)

                flash(f'✓ تم إضافة المنتج "{product.name}" بنجاح إلى المستودع "{warehouse.name_ar or warehouse.name}"', 'success')
                return redirect(url_for('products.index'))

            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error creating product: {str(e)}")
                flash(f'❌ فشل إضافة المنتج: {str(e)}\n💡 تأكد من:\n   • اسم المنتج فريد\n   • الأسعار صحيحة\n   • SKU غير مكرر', 'danger')
        else:
            # Form validation failed
            current_app.logger.warning(f"Form validation failed. Errors: {form.errors}")
            for field, errors in form.errors.items():
                for error in errors:
                    flash(f'⚠️ خطأ في حقل {field}: {error}', 'danger')

    # GET request - إرسال البيانات للقالب
    categories = ProductCategory.query.filter_by(is_active=True).all()
    warehouses = Warehouse.query.filter_by(is_active=True).order_by(Warehouse.is_main.desc(), Warehouse.created_at.desc(), Warehouse.name).all()

    return render_template('products/create.html',
                           form=form,
                           categories=categories,
                           warehouses=warehouses,
                           merchants=merchants,
                           partners=partners,
                           preselected_warehouse_id=preselected_warehouse_id)


@products_bp.route('/<int:id>')
@login_required
@permission_required('manage_products')
def view(id):
    product = get_owned_or_404(Product, id)

    movements = product.stock_movements.order_by(
        db.desc('created_at')
    ).limit(20).all()

    return render_template('products/view.html',
                           product=product,
                           movements=movements)


@products_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('manage_products')
def edit(id):  # noqa: C901
    product = get_owned_or_404(Product, id)
    from forms.product import ProductForm
    from models import Warehouse
    form = ProductForm(obj=product)

    # تعيين choices للتصنيفات
    categories = ProductCategory.query.filter_by(is_active=True).all()
    form.category_id.choices = [(0, 'بلا')] + [(c.id, c.name) for c in categories]
    warehouses = Warehouse.query.filter_by(is_active=True).order_by(Warehouse.is_main.desc(), Warehouse.name).all()
    merchants = Customer.query.filter_by(is_active=True, customer_type='merchant').order_by(Customer.name).all()
    partners = Customer.query.filter_by(is_active=True, customer_type='partner').order_by(Customer.name).all()

    if request.method == 'POST' and form.validate_on_submit():
        try:
            def safe_float(value, default=None):
                if value is None or value == '':
                    return default
                try:
                    return float(value)
                except (ValueError, TypeError):
                    return default

            old_stock = float(product.current_stock or 0)
            new_stock = safe_float(request.form.get('current_stock'), default=old_stock)

            if new_stock is not None and new_stock < 0:
                flash('⚠️ لا يمكن أن تكون الكمية أقل من صفر.', 'warning')
                return render_template('products/edit.html', form=form, product=product, categories=categories, warehouses=warehouses, merchants=merchants, partners=partners)  # noqa: E501

            warehouse_id = request.form.get('warehouse_id', type=int)
            merchant_customer_id = request.form.get('merchant_customer_id', type=int)
            if merchant_customer_id:
                merchant_customer = Customer.query.filter_by(id=merchant_customer_id, is_active=True, customer_type='merchant').first()
                if not merchant_customer:
                    flash('⚠️ التاجر المحدد غير موجود أو غير مُعرّف كتاجر.', 'warning')
                    return render_template('products/edit.html', form=form, product=product, categories=categories, warehouses=warehouses, merchants=merchants, partners=partners)  # noqa: E501

            partner_rows, partner_error = _parse_product_partners(request.form)
            if partner_error:
                flash(partner_error, 'warning')
                return render_template('products/edit.html', form=form, product=product, categories=categories, warehouses=warehouses, merchants=merchants, partners=partners)  # noqa: E501

            product.name = request.form.get('name')
            product.name_ar = request.form.get('name_ar')
            product.sku = request.form.get('sku')
            product.part_number = request.form.get('part_number')
            product.barcode = request.form.get('barcode')
            product.category_id = (form.category_id.data or None)
            product.regular_price = safe_float(request.form.get('regular_price'), default=0)
            product.merchant_price = safe_float(request.form.get('merchant_price'))
            product.merchant_share = safe_float(request.form.get('merchant_share'), default=100.0)
            product.partner_price = safe_float(request.form.get('partner_price'))
            product.min_stock_alert = safe_float(request.form.get('min_stock_alert'), default=0)
            unit_value = request.form.get('unit')
            if 'unit' in request.form:
                product.unit = unit_value or None
            product.location = request.form.get('location')
            product.description = request.form.get('description')
            product.notes = request.form.get('notes')
            product.merchant_customer_id = merchant_customer_id or None

            if current_user.can_see_costs():
                product.cost_price = safe_float(request.form.get('cost_price'), default=0)

            product.partner_shares.clear()
            if partner_rows:
                for row in partner_rows:
                    product.partner_shares.append(ProductPartner(
                        product_id=product.id,
                        partner_customer_id=row['partner_customer_id'],
                        percentage=row['percentage'],
                    ))

            if new_stock is not None and abs(new_stock - old_stock) > 1e-6:
                if not warehouse_id:
                    warehouse_id = None
                StockService.create_movement(
                    product_id=product.id,
                    quantity=new_stock - old_stock,
                    movement_type='adjustment',
                    reference_type='Product Update',
                    reference_id=product.id,
                    notes=f'تعديل مخزون من {old_stock} إلى {new_stock}',
                    warehouse_id=warehouse_id
                )

            if 'image' in request.files:
                file = request.files['image']
                if file.filename:
                    image_path = save_uploaded_file(file, 'products')
                    if image_path:
                        product.image_url = image_path

            db.session.commit()

            create_audit_log('update', 'products', product.id)

            flash('✅ تم تحديث بيانات المنتج بنجاح!', 'success')
            return redirect(url_for('products.view', id=product.id))

        except Exception as e:
            db.session.rollback()
            flash(f'❌ فشل تحديث المنتج: {str(e)}', 'danger')

    categories = ProductCategory.query.filter_by(is_active=True).all()
    return render_template('products/edit.html', form=form, product=product, categories=categories, warehouses=warehouses, merchants=merchants, partners=partners)  # noqa: E501


@products_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('manage_products')
def delete(id):
    """حذف (إلغاء تفعيل) المنتج - soft delete"""
    product = get_owned_or_404(Product, id)

    try:
        # التحقق من وجود عمليات مرتبطة
        from models import SaleLine, PurchaseLine
        sales_count = SaleLine.query.filter_by(product_id=id).count()
        purchases_count = PurchaseLine.query.filter_by(product_id=id).count()

        if sales_count > 0 or purchases_count > 0:
            # soft delete
            product.is_active = False
            db.session.commit()
            flash(f'⚠️ تم إلغاء تفعيل المنتج "{product.name}" (لديه عمليات مسجلة).\n💡 لا يمكن حذفه نهائياً للحفاظ على السجلات.', 'warning')
            create_audit_log('deactivate', 'products', id)
        else:
            # hard delete
            db.session.delete(product)
            db.session.commit()
            flash(f'✅ تم حذف المنتج "{product.name}" نهائياً!', 'success')
            create_audit_log('delete', 'products', id)

        return redirect(url_for('products.index'))

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting product {id}: {e}")
        flash('❌ فشل حذف المنتج. حدث خطأ غير متوقع.', 'danger')
        return redirect(url_for('products.view', id=id))


@products_bp.route('/api/search')
@login_required
@permission_required('manage_products')
def api_search():
    """API endpoint للبحث عن المنتجات"""
    query = request.args.get('q', '')
    _ = request.args.get('page', 1, type=int)
    per_page = 20

    # السماح بالبحث حتى بدون query (لعرض كل المنتجات)
    if query and len(query) >= 1:
        products = Product.query.filter(
            Product.is_active.is_(True),
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
        data = request.get_json() if request.is_json else request.form

        name = (data.get('name') or '').strip()
        name_ar = (data.get('name_ar') or '').strip() or None
        description = (data.get('description') or '').strip() or None

        if not name:
            message = '⚠️ يجب إدخال اسم الفئة.'
            if request.is_json:
                return jsonify({'success': False, 'error': message}), 400
            flash(message, 'warning')
            return redirect(url_for('products.categories'))

        # منع التكرار (نفس الاسم بغض النظر عن حالة الأحرف)
        existing = ProductCategory.query.filter(
            db.func.lower(ProductCategory.name) == name.lower()
        ).first()
        if existing:
            message = '⚠️ هذه الفئة موجودة مسبقاً.'
            if request.is_json:
                return jsonify({'success': False, 'error': message}), 400
            flash(message, 'warning')
            return redirect(url_for('products.categories'))

        category = ProductCategory(
            name=name,
            name_ar=name_ar,
            description=description,
            is_active=True
        )

        db.session.add(category)
        db.session.commit()

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

        flash('✅ تم إضافة التصنيف بنجاح!', 'success')
        return redirect(url_for('products.categories'))

    except Exception as e:
        db.session.rollback()

        if request.is_json:
            return jsonify({
                'success': False,
                'error': str(e)
            }), 400

        flash(f'❌ حدث خطأ: {str(e)}', 'danger')
        return redirect(url_for('products.categories'))


@products_bp.route('/<int:id>/adjust-stock', methods=['POST'])
@login_required
@permission_required('manage_products')
def adjust_stock(id):
    product = get_owned_or_404(Product, id)

    try:
        adjustment_type = request.form.get('adjustment_type')
        quantity = float(request.form.get('quantity', 0))
        reason = request.form.get('reason', 'adjustment')
        notes = request.form.get('notes', '')

        if quantity <= 0:
            return jsonify({'success': False, 'message': 'الكمية يجب أن تكون أكبر من صفر'})

        old_stock = Decimal(str(product.current_stock or 0))

        if adjustment_type == 'add':
            new_stock = old_stock + Decimal(str(quantity))
        elif adjustment_type == 'subtract':
            new_stock = old_stock - Decimal(str(quantity))
            if new_stock < 0:
                return jsonify({'success': False, 'message': 'لا يمكن أن يكون المخزون سالباً'})
        elif adjustment_type == 'set':
            new_stock = Decimal(str(quantity))
        else:
            return jsonify({'success': False, 'message': 'نوع التعديل غير صحيح'})

        product.current_stock = new_stock

        from models import StockMovement, Warehouse
        warehouse = Warehouse.query.filter_by(is_active=True, is_main=True).first()
        if not warehouse:
            warehouse = Warehouse.query.filter_by(is_active=True).first()
        if not warehouse:
            warehouse = Warehouse(name='Main Warehouse', name_ar='المستودع الرئيسي',
                                  is_active=True, is_main=True)
            db.session.add(warehouse)
            db.session.flush()

        movement = StockMovement(
            product_id=product.id,
            warehouse_id=warehouse.id,
            movement_type='adjustment',
            quantity=(Decimal(str(quantity)) if adjustment_type != 'set'
                      else Decimal(str(new_stock)) - Decimal(str(old_stock))),
            reference_type='Manual Adjustment',
            notes=notes or f'تعديل يدوي - {reason}',
            user_id=current_user.id
        )

        db.session.add(movement)
        db.session.commit()

        create_audit_log('update', 'products', product.id, f'تعديل مخزون: {old_stock} → {new_stock}')

        return jsonify({
            'success': True,
            'message': f'تم تعديل المخزون من {old_stock} إلى {new_stock}',
            'new_stock': float(new_stock)
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'حدث خطأ: {str(e)}'})
