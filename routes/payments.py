from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from extensions import db
from models import Receipt, Customer, InvoiceSettings
from services.payment_service import PaymentService
from services.currency_service import CurrencyService
from utils.decorators import permission_required
from utils.helpers import create_audit_log

payments_bp = Blueprint('payments', __name__, url_prefix='/payments')


@payments_bp.route('/receipts')
@login_required
@permission_required('manage_payments')
def receipts():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    search = request.args.get('search', '', type=str)
    
    query = Receipt.query
    
    if search:
        search_filter = f'%{search}%'
        query = query.join(Customer).filter(
            db.or_(
                Receipt.receipt_number.ilike(search_filter),
                Customer.name.ilike(search_filter)
            )
        )
    
    if current_user.is_seller():
        query = query.filter_by(user_id=current_user.id)
    
    pagination = query.order_by(Receipt.receipt_date.desc()).paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )
    
    return render_template('payments/receipts.html',
                         receipts=pagination.items,
                         pagination=pagination)


@payments_bp.route('/receipts/create', methods=['GET', 'POST'])
@login_required
@permission_required('manage_payments')
def create_receipt():
    preselected_customer = None
    suggested_amount = None
    customer_id_param = request.args.get('customer_id', type=int)
    
    if customer_id_param:
        preselected_customer = Customer.query.get(customer_id_param)
        # حساب المبلغ المقترح (إجمالي الديون)
        if preselected_customer and preselected_customer.balance < 0:
            suggested_amount = abs(preselected_customer.balance)
    
    if request.method == 'POST':
        try:
            customer_id = request.form.get('customer_id', type=int)
            customer = Customer.query.get_or_404(customer_id)
            
            amount = request.form.get('amount', type=float)
            currency = request.form.get('currency', 'AED')
            user_exchange_rate = request.form.get('exchange_rate', type=float)
            payment_method = request.form.get('payment_method', 'cash')
            
            reference_number = request.form.get('reference_number')
            cheque_number = request.form.get('cheque_number')
            cheque_date = request.form.get('cheque_date') or None
            bank_name = request.form.get('bank_name')
            notes = request.form.get('notes')
            
            allocate_to_sales = {}
            unpaid_sales = PaymentService.get_unpaid_sales(customer)
            
            for sale in unpaid_sales:
                allocated = request.form.get(f'allocate[{sale.id}]', type=float, default=0)
                if allocated > 0:
                    allocate_to_sales[sale.id] = allocated
            
            receipt_data = {
                'customer_id': customer.id,
                'amount': amount,
                'currency': currency,
                'user_exchange_rate': user_exchange_rate,
                'payment_method': payment_method,
                'reference_number': reference_number,
                'cheque_number': cheque_number,
                'cheque_date': cheque_date,
                'bank_name': bank_name,
                'notes': notes,
                'allocate_to_sales': allocate_to_sales if allocate_to_sales else None
            }
            
            receipt = PaymentService.create_receipt(receipt_data)
            
            create_audit_log('create', 'receipts', receipt.id)
            
            flash('تم إنشاء سند القبض بنجاح', 'success')
            return redirect(url_for('payments.view_receipt', id=receipt.id))
        
        except Exception as e:
            flash(f'حدث خطأ: {str(e)}', 'danger')
    
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()
    exchange_rates = CurrencyService.get_all_rates('AED')
    
    return render_template('payments/create_receipt.html',
                         customers=customers,
                         preselected_customer=preselected_customer,
                         suggested_amount=suggested_amount,
                         exchange_rates=exchange_rates)


@payments_bp.route('/receipts/<int:id>')
@login_required
@permission_required('manage_payments')
def view_receipt(id):
    receipt = Receipt.query.get_or_404(id)
    
    if current_user.is_seller() and receipt.user_id != current_user.id:
        flash('ليس لديك صلاحية لعرض هذا السند', 'danger')
        return redirect(url_for('payments.receipts'))
    
    return render_template('payments/view_receipt.html', receipt=receipt)


@payments_bp.route('/receipts/<int:id>/print')
@login_required
@permission_required('manage_payments')
def print_receipt(id):
    receipt = Receipt.query.get_or_404(id)
    
    if current_user.is_seller() and receipt.user_id != current_user.id:
        flash('ليس لديك صلاحية لطباعة هذا السند', 'danger')
        return redirect(url_for('payments.receipts'))
    
    # Get invoice settings
    settings = InvoiceSettings.get_active()
    
    # استخدام القالب النشط من الإعدادات
    template = settings.active_template if settings and settings.active_template else 'modern'
    template_path = f'receipts/{template}.html'
    
    # التحقق من وجود القالب، وإلا استخدام القالب الافتراضي
    try:
        return render_template(template_path, receipt=receipt, settings=settings)
    except:
        # إذا لم يوجد القالب، استخدام modern كافتراضي
        return render_template('receipts/modern.html', receipt=receipt, settings=settings)


@payments_bp.route('/receipts/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('manage_payments')
def delete_receipt(id):
    """حذف (إلغاء) سند قبض"""
    receipt = Receipt.query.get_or_404(id)
    
    try:
        # إلغاء السند (تغيير الحالة)
        receipt.status = 'cancelled'
        
        # إعادة المبالغ المخصصة للفواتير
        if receipt.allocations:
            from models import Sale
            for allocation in receipt.allocations:
                sale = Sale.query.get(allocation.sale_id)
                if sale:
                    sale.paid_amount -= allocation.allocated_amount
                    sale.balance_due = sale.total_amount - sale.paid_amount
                    sale.update_payment_status()
        
        db.session.commit()
        
        # عكس القيد المحاسبي
        try:
            from models import GLEntry
            gl_entry = GLEntry.query.filter_by(
                reference_type='Receipt',
                reference_id=receipt.id
            ).first()
            
            if gl_entry:
                from services.gl_service import GLService
                GLService.reverse_entry(gl_entry.id, f'عكس سند قبض محذوف {receipt.receipt_number}')
        except Exception as e:
            current_app.logger.warning(f'GL reversal failed: {e}')
        
        create_audit_log('delete', 'receipts', id)
        
        flash(f'تم إلغاء سند القبض "{receipt.receipt_number}" بنجاح', 'success')
        return redirect(url_for('payments.receipts'))
    
    except Exception as e:
        db.session.rollback()
        flash(f'خطأ في الحذف: {str(e)}', 'danger')
        return redirect(url_for('payments.view_receipt', id=id))


@payments_bp.route('/api/customer-balance/<int:customer_id>')
@login_required
def api_customer_balance(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    
    balance_aed = PaymentService.get_customer_balance_aed(customer)
    unpaid_sales = PaymentService.get_unpaid_sales(customer)
    
    return {
        'balance_aed': float(balance_aed),
        'unpaid_sales': [{
            'id': sale.id,
            'sale_number': sale.sale_number,
            'sale_date': sale.sale_date.isoformat(),
            'total_amount': float(sale.total_amount),
            'balance_due': float(sale.balance_due),
            'currency': sale.currency
        } for sale in unpaid_sales]
    }

