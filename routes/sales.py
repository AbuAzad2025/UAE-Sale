from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from extensions import db, csrf
from models import Sale, Customer, Product, InvoiceSettings
from services.sale_service import SaleService
from services.currency_service import CurrencyService
from utils.decorators import permission_required
from utils.helpers import create_audit_log

sales_bp = Blueprint('sales', __name__, url_prefix='/sales')


@sales_bp.route('/')
@login_required
@permission_required('manage_sales')
def index():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    search = request.args.get('search', '', type=str)
    status = request.args.get('status', '', type=str)
    payment_status = request.args.get('payment_status', '', type=str)
    
    query = Sale.query
    
    # إخفاء المبيعات المؤرشفة
    from models import ArchivedRecord
    from sqlalchemy import select
    archived_sales = select(ArchivedRecord.record_id).filter(
        ArchivedRecord.table_name == 'sales'
    ).scalar_subquery()
    query = query.filter(~Sale.id.in_(archived_sales))
    
    if search:
        search_filter = f'%{search}%'
        query = query.join(Customer).filter(
            db.or_(
                Sale.sale_number.ilike(search_filter),
                Customer.name.ilike(search_filter)
            )
        )
    
    if status:
        query = query.filter_by(status=status)
    else:
        query = query.filter_by(status='confirmed')
    
    if payment_status:
        query = query.filter_by(payment_status=payment_status)
    
    if current_user.is_seller():
        query = query.filter_by(seller_id=current_user.id)
    
    pagination = query.order_by(Sale.sale_date.desc()).paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )
    
    return render_template('sales/index.html',
                         sales=pagination.items,
                         pagination=pagination)


@sales_bp.route('/create', methods=['GET', 'POST'])
@login_required
@permission_required('manage_sales')
def create():
    if request.method == 'POST':
        try:
            customer_id = request.form.get('customer_id', type=int)
            customer = Customer.query.get_or_404(customer_id)
            
            lines_data = []
            line_count = int(request.form.get('line_count', 0))
            
            for i in range(line_count):
                try:
                    product_id_str = request.form.get(f'lines[{i}][product_id]')
                    product_id = int(product_id_str) if product_id_str else None
                    
                    quantity_str = request.form.get(f'lines[{i}][quantity]')
                    quantity = float(quantity_str) if quantity_str else None
                    
                    discount_str = request.form.get(f'lines[{i}][discount_percent]')
                    discount_percent = float(discount_str) if discount_str else 0
                    
                    price_str = request.form.get(f'lines[{i}][unit_price]')
                    override_price = float(price_str) if price_str else None
                    
                    if product_id and quantity and quantity > 0:
                        product = Product.query.get(product_id)
                        if product:
                            lines_data.append({
                                'product': product,
                                'quantity': quantity,
                                'discount_percent': discount_percent,
                                'unit_price': override_price
                            })
                except (ValueError, TypeError) as e:
                    # Skip invalid lines
                    continue
            
            if not lines_data:
                flash('يجب إضافة منتج واحد على الأقل', 'danger')
                return redirect(url_for('sales.create'))
            
            currency = request.form.get('currency', 'AED')
            user_exchange_rate = request.form.get('exchange_rate', type=float)
            
            # Track manual exchange rate changes for audit
            exchange_rate_manual = request.form.get('exchange_rate_manual') == 'true'
            exchange_rate_server = request.form.get('exchange_rate_server', type=float)
            exchange_rate_diff = request.form.get('exchange_rate_difference', type=float)
            
            discount_amount = request.form.get('discount_amount', type=float, default=0)
            shipping_cost = request.form.get('shipping_cost', type=float, default=0)
            tax_rate = request.form.get('tax_rate', type=float, default=0)
            notes = request.form.get('notes')
            
            # Add exchange rate audit to notes if manually changed
            if exchange_rate_manual and exchange_rate_server and user_exchange_rate:
                if user_exchange_rate < exchange_rate_server:
                    audit_note = f"\n[تنبيه] سعر صرف يدوي: {user_exchange_rate:.6f} (سعر السيرفر: {exchange_rate_server:.6f}, فرق: {exchange_rate_diff:.2f}%)"
                    notes = (notes or '') + audit_note
            
            payment_amount = request.form.get('payment_amount', type=float, default=0)
            payment_method = request.form.get('payment_method', 'cash')
            
            payment_data = None
            if payment_amount > 0:
                payment_data = {
                    'amount': payment_amount,
                    'payment_method': payment_method,
                    'currency': currency,  # Payment currency
                    'exchange_rate': user_exchange_rate,  # Payment exchange rate
                    'reference_number': request.form.get('reference_number'),
                    'cheque_number': request.form.get('cheque_number'),
                    'cheque_date': request.form.get('cheque_date'),
                    'bank_name': request.form.get('bank_name'),
                }
            
            sale = SaleService.create_sale(
                customer=customer,
                seller=current_user,
                lines_data=lines_data,
                currency='AED',  # Invoice always in AED
                user_exchange_rate=1.0,  # Always 1 for AED
                discount_amount=discount_amount,
                shipping_cost=shipping_cost,
                tax_rate=tax_rate,
                notes=notes,
                payment_data=payment_data
            )
            
            create_audit_log('create', 'sales', sale.id)
            
            flash('تم إنشاء الفاتورة بنجاح', 'success')
            return redirect(url_for('sales.view', id=sale.id))
        
        except ValueError as e:
            flash(str(e), 'danger')
        except Exception as e:
            flash(f'حدث خطأ: {str(e)}', 'danger')
    
    # No need to load customers or exchange rates - loaded via AJAX for speed
    return render_template('sales/create.html')


@sales_bp.route('/<int:id>')
@login_required
@permission_required('manage_sales')
def view(id):
    sale = Sale.query.get_or_404(id)
    
    if current_user.is_seller() and sale.seller_id != current_user.id:
        flash('ليس لديك صلاحية لعرض هذه الفاتورة', 'danger')
        return redirect(url_for('sales.index'))
    
    return render_template('sales/view.html', sale=sale)


@sales_bp.route('/<int:id>/print')
@login_required
@permission_required('manage_sales')
def print_invoice(id):
    sale = Sale.query.get_or_404(id)
    
    if current_user.is_seller() and sale.seller_id != current_user.id:
        flash('ليس لديك صلاحية لطباعة هذه الفاتورة', 'danger')
        return redirect(url_for('sales.index'))
    
    # Get invoice settings
    from config import Config
    settings = InvoiceSettings.get_active()
    
    # استخدام القالب النشط من الإعدادات
    template = settings.active_template if settings and settings.active_template else 'modern'
    template_path = f'invoices/{template}.html'
    
    # التحقق من وجود القالب، وإلا استخدام القالب الافتراضي
    try:
        return render_template(template_path, sale=sale, settings=settings, config=Config)
    except:
        # إذا لم يوجد القالب، استخدام modern كافتراضي
        return render_template('invoices/modern.html', sale=sale, settings=settings, config=Config)


@sales_bp.route('/<int:id>/cancel', methods=['POST'])
@login_required
@permission_required('manage_sales')
def cancel(id):
    if current_user.is_seller():
        flash('ليس لديك صلاحية لإلغاء الفواتير', 'danger')
        return redirect(url_for('sales.index'))
    
    sale = Sale.query.get_or_404(id)
    
    try:
        SaleService.cancel_sale(sale)
        
        create_audit_log('cancel', 'sales', sale.id)
        
        flash('تم إلغاء الفاتورة بنجاح', 'success')
    
    except Exception as e:
        flash(f'حدث خطأ: {str(e)}', 'danger')
    
    return redirect(url_for('sales.view', id=id))


@sales_bp.route('/api/get-price')
@login_required
def api_get_price():
    product_id = request.args.get('product_id', type=int)
    customer_id = request.args.get('customer_id', type=int)
    
    if not product_id or not customer_id:
        return jsonify({'error': 'Missing parameters'}), 400
    
    product = Product.query.get(product_id)
    customer = Customer.query.get(customer_id)
    
    if not product or not customer:
        return jsonify({'error': 'Not found'}), 404
    
    price = product.get_price_for_customer(customer.customer_type)
    
    return jsonify({
        'price': float(price),
        'cost_price': float(product.cost_price) if current_user.can_see_costs() else None,
        'current_stock': float(product.current_stock),
        'unit': product.unit
    })


@sales_bp.route('/archived')
@login_required
@permission_required('manage_sales')
def archived():
    """عرض المبيعات المؤرشفة"""
    from models import ArchivedRecord
    from datetime import datetime
    
    archived_sales_query = db.session.query(ArchivedRecord).filter(
        ArchivedRecord.table_name == 'sales'
    )
    
    archived_items = []
    
    for archived in archived_sales_query.all():
        data = archived.data
        # Get the actual sale to retrieve customer name
        sale = Sale.query.get(archived.record_id)
        archived_items.append({
            'id': archived.record_id,
            'sale_number': data.get('sale_number'),
            'sale_date': datetime.fromisoformat(data.get('sale_date').replace('Z', '+00:00')) if isinstance(data.get('sale_date'), str) else data.get('sale_date'),
            'customer': sale.customer if sale else None,
            'total_amount': float(data.get('total_amount', 0)),
            'currency': data.get('currency'),
            'payment_status': data.get('payment_status'),
            'archived_at': archived.archived_at
        })
    
    archived_items.sort(key=lambda x: x['archived_at'], reverse=True)
    
    return render_template('sales/archived.html', sales=archived_items)


@sales_bp.route('/<int:id>/archive', methods=['POST'])
@login_required
@permission_required('manage_sales')
def archive(id):
    """أرشفة فاتورة"""
    from services.archive_service import ArchiveService
    
    sale = Sale.query.get_or_404(id)
    
    try:
        archive_service = ArchiveService()
        archive_service.archive_record('sales', sale, reason='تم أرشفة فاتورة المبيعات')
        create_audit_log('archive', 'sales', sale.id)
    except Exception as e:
        db.session.rollback()
    
    return redirect(url_for('sales.index'))


@sales_bp.route('/<int:id>/restore', methods=['POST'])
@login_required
@permission_required('manage_sales')
def restore(id):
    """استعادة فاتورة من الأرشيف"""
    from models import ArchivedRecord
    
    archived = ArchivedRecord.query.filter_by(
        table_name='sales',
        record_id=id
    ).first_or_404()
    
    try:
        db.session.delete(archived)
        db.session.commit()
        create_audit_log('restore', 'sales', id)
    except Exception as e:
        db.session.rollback()
    
    return redirect(url_for('sales.archived'))


# =====================================
# API Endpoints - Backend Calculations
# =====================================

@sales_bp.route('/api/calculate-totals', methods=['POST'])
def api_calculate_sale_totals():
    """API لحساب إجماليات فاتورة المبيعات - Backend Calculation"""
    try:
        from decimal import Decimal
        
        data = request.get_json(force=True)
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        lines = data.get('lines', [])
        discount_amount = Decimal(str(data.get('discount_amount', 0)))
        shipping_cost = Decimal(str(data.get('shipping_cost', 0)))
        tax_rate = Decimal(str(data.get('tax_rate', 0)))
        
        # حساب المجموع الفرعي
        subtotal = Decimal('0')
        for line in lines:
            try:
                qty = Decimal(str(line.get('quantity', 0)))
                price = Decimal(str(line.get('unit_price', 0)))
                discount_percent = Decimal(str(line.get('discount_percent', 0)))
                
                if qty > 0 and price > 0:
                    line_subtotal = qty * price
                    line_discount = line_subtotal * (discount_percent / Decimal('100'))
                    line_total = line_subtotal - line_discount
                    subtotal += line_total
            except (ValueError, TypeError, KeyError):
                continue
        
        # حساب الإجماليات
        after_discount = subtotal - discount_amount + shipping_cost
        tax_amount = after_discount * (tax_rate / Decimal('100'))
        total = after_discount + tax_amount
        
        return jsonify({
            'success': True,
            'subtotal': float(subtotal),
            'discount': float(discount_amount),
            'shipping': float(shipping_cost),
            'tax_rate': float(tax_rate),
            'tax_amount': float(tax_amount),
            'total': float(total),
            'line_count': len([l for l in lines if Decimal(str(l.get('quantity', 0))) > 0])
        }), 200
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
