from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from extensions import db
from models import Purchase, PurchaseLine, Product, Supplier
from services.stock_service import StockService
from services.currency_service import CurrencyService
from services.gl_service import GLService
from utils.decorators import admin_required
from utils.helpers import create_audit_log, generate_number
from decimal import Decimal

purchases_bp = Blueprint('purchases', __name__, url_prefix='/purchases')


@purchases_bp.route('/')
@login_required
@admin_required
def index():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    search = request.args.get('search', '', type=str)
    
    query = Purchase.query
    
    if search:
        search_filter = f'%{search}%'
        query = query.filter(
            db.or_(
                Purchase.purchase_number.ilike(search_filter),
                Purchase.supplier_name.ilike(search_filter)
            )
        )
    
    query = query.filter_by(status='confirmed')
    
    pagination = query.order_by(Purchase.purchase_date.desc()).paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )
    
    return render_template('purchases/index.html',
                         purchases=pagination.items,
                         pagination=pagination)


@purchases_bp.route('/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create():
    if request.method == 'POST':
        try:
            current_app.logger.info("POST request received for purchase creation")
            current_app.logger.info(f"Form data keys: {list(request.form.keys())}")
            current_app.logger.info(f"Line count from form: {request.form.get('line_count')}")
            
            purchase_number = generate_number('P', Purchase, 'purchase_number')
            
            # الحصول على معلومات المورد
            supplier_id = request.form.get('supplier_id', type=int)
            supplier = None
            supplier_name = request.form.get('supplier_name', '')
            supplier_phone = request.form.get('supplier_phone', '')
            supplier_email = request.form.get('supplier_email', '')
            
            # إذا تم اختيار مورد من القائمة
            if supplier_id:
                supplier = Supplier.query.get(supplier_id)
                if supplier:
                    supplier_name = supplier.name
                    supplier_phone = supplier.phone or ''
                    supplier_email = supplier.email or ''
            
            # التحقق من وجود اسم المورد
            if not supplier_name:
                flash('❌ يجب إدخال اسم المورد', 'danger')
                return redirect(url_for('purchases.create'))
            
            currency = request.form.get('currency', 'AED')
            user_exchange_rate = request.form.get('exchange_rate', type=float)
            
            exchange_rate = CurrencyService.get_exchange_rate(
                currency,
                'AED',
                user_rate=user_exchange_rate
            )
            
            purchase = Purchase(
                purchase_number=purchase_number,
                supplier_id=supplier_id,  # ربط المورد
                supplier_name=supplier_name,
                supplier_phone=supplier_phone,
                supplier_email=supplier_email,
                currency=currency,
                exchange_rate=exchange_rate,
                discount_amount=request.form.get('discount_amount', type=float, default=0),
                tax_rate=request.form.get('tax_rate', type=float, default=0),
                notes=request.form.get('notes'),
                user_id=current_user.id,
                # تعيين قيم افتراضية لتجنب NOT NULL constraint
                subtotal=0,
                tax_amount=0,
                total_amount=0,
                amount_aed=0
            )
            
            db.session.add(purchase)
            db.session.flush()
            
            line_count = int(request.form.get('line_count', 0))
            current_app.logger.info(f"Processing {line_count} lines")
            
            # طباعة جميع البيانات المرسلة
            for key, value in request.form.items():
                if key.startswith('lines['):
                    current_app.logger.info(f"Line data: {key} = {value}")
            
            current_app.logger.info("Starting to process lines...")
            lines_added = 0
            for i in range(line_count):
                product_id = request.form.get(f'lines[{i}][product_id]', type=int)
                quantity = request.form.get(f'lines[{i}][quantity]', type=float)
                unit_cost = request.form.get(f'lines[{i}][unit_cost]', type=float)
                discount_percent = request.form.get(f'lines[{i}][discount_percent]', type=float, default=0)
                
                current_app.logger.info(f"Processing line {i}: product_id={product_id}, qty={quantity}, cost={unit_cost}")
                
                if product_id and quantity and quantity > 0 and unit_cost:
                    product = Product.query.get(product_id)
                    
                    if product:
                        line = PurchaseLine(
                            purchase_id=purchase.id,
                            product_id=product_id,
                            quantity=quantity,
                            unit_cost=unit_cost,
                            discount_percent=discount_percent
                        )
                        
                        line.calculate_line_total()
                        db.session.add(line)
                        lines_added += 1
                        current_app.logger.info(f"Line added: {product.name} x {quantity} @ {unit_cost}")
            
            current_app.logger.info(f"Lines added: {lines_added}")
            
            if lines_added == 0:
                current_app.logger.warning("No lines added - rolling back")
                db.session.rollback()
                flash('❌ يجب إضافة منتج واحد على الأقل', 'danger')
                return redirect(url_for('purchases.create'))
            
            # حساب الإجماليات يدوياً من البيانات المحفوظة
            subtotal = 0
            current_app.logger.info(f"Starting calculation for {line_count} lines")
            
            for i in range(line_count):
                product_id = request.form.get(f'lines[{i}][product_id]', type=int)
                quantity = request.form.get(f'lines[{i}][quantity]', type=float)
                unit_cost = request.form.get(f'lines[{i}][unit_cost]', type=float)
                discount_percent = request.form.get(f'lines[{i}][discount_percent]', type=float, default=0)
                
                current_app.logger.info(f"Line {i}: product_id={product_id}, qty={quantity}, cost={unit_cost}, discount={discount_percent}")
                
                if product_id and quantity and quantity > 0 and unit_cost:
                    line_subtotal = quantity * unit_cost
                    line_discount = line_subtotal * (discount_percent / 100)
                    line_total = line_subtotal - line_discount
                    subtotal += line_total
                    current_app.logger.info(f"Line {i} calculated: {line_subtotal} - {line_discount} = {line_total}")
                else:
                    current_app.logger.warning(f"Line {i} skipped: invalid data")
            
            current_app.logger.info(f"Final subtotal: {subtotal}")
            
            purchase.subtotal = subtotal
            purchase.tax_amount = subtotal * (purchase.tax_rate / 100)
            purchase.total_amount = subtotal + purchase.tax_amount
            from decimal import Decimal
            purchase.amount_aed = Decimal(str(purchase.total_amount)) * purchase.exchange_rate
            
            current_app.logger.info(f"Final totals: subtotal={purchase.subtotal}, tax={purchase.tax_amount}, total={purchase.total_amount}, aed={purchase.amount_aed}")
            
            db.session.flush()
            
            StockService.process_purchase_lines(purchase)
            
            # القيود المحاسبية
            try:
                GLService.ensure_core_accounts()
                lines = [
                    {'account': '1200', 'debit': purchase.amount_aed, 'description': f'شراء بضاعة {purchase.purchase_number}'},
                    {'account': '2000', 'credit': purchase.amount_aed, 'description': f'مورد: {purchase.supplier_name}'}
                ]
                GLService.post_entry(
                    lines, 
                    description=f'Purchase {purchase.purchase_number}', 
                    reference_type='Purchase', 
                    reference_id=purchase.id, 
                    currency=purchase.currency, 
                    exchange_rate=purchase.exchange_rate
                )
            except Exception as e:
                current_app.logger.warning(f'GL posting failed: {e}')
            
            # تحديث إحصائيات المورد
            if supplier:
                try:
                    supplier.update_statistics()
                except Exception as e:
                    current_app.logger.warning(f'Supplier stats update failed: {e}')
            
            current_app.logger.info("About to commit to database...")
            current_app.logger.info(f"Final values: subtotal={purchase.subtotal}, tax_amount={purchase.tax_amount}, total_amount={purchase.total_amount}, amount_aed={purchase.amount_aed}")
            db.session.commit()
            current_app.logger.info("Database commit successful!")
            
            create_audit_log('create', 'purchases', purchase.id)
            
            flash('✅ تم إنشاء فاتورة الشراء بنجاح', 'success')
            return redirect(url_for('purchases.view', id=purchase.id))
        
        except Exception as e:
            current_app.logger.error(f"Error in purchase creation: {str(e)}")
            current_app.logger.error(f"Error type: {type(e)}")
            import traceback
            current_app.logger.error(f"Traceback: {traceback.format_exc()}")
            db.session.rollback()
            flash(f'حدث خطأ: {str(e)}', 'danger')
    
    exchange_rates = CurrencyService.get_all_rates('AED')
    
    return render_template('purchases/create.html', exchange_rates=exchange_rates)


@purchases_bp.route('/<int:id>')
@login_required
@admin_required
def view(id):
    purchase = Purchase.query.get_or_404(id)
    return render_template('purchases/view.html', purchase=purchase)


@purchases_bp.route('/<int:id>/print')
@login_required
@admin_required
def print_purchase(id):
    purchase = Purchase.query.get_or_404(id)
    return render_template('purchases/print.html', purchase=purchase)

