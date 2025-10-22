from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from extensions import db
from models import Receipt, Customer, InvoiceSettings
from services.payment_service import PaymentService
from services.currency_service import CurrencyService
from utils.decorators import permission_required
from utils.helpers import create_audit_log
from datetime import datetime

payments_bp = Blueprint('payments', __name__, url_prefix='/payments')


@payments_bp.route('/receipts')
@login_required
@permission_required('manage_payments')
def receipts():
    """عرض جميع المدفوعات (سندات القبض والصرف) في قائمة موحدة"""
    from models import Payment
    
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    search = request.args.get('search', '', type=str)
    direction_filter = request.args.get('direction', '', type=str)  # incoming, outgoing, all
    
    # جمع سندات القبض والصرف
    receipts_query = Receipt.query
    payments_query = Payment.query
    
    if search:
        search_filter = f'%{search}%'
        receipts_query = receipts_query.join(Customer).filter(
            db.or_(
                Receipt.receipt_number.ilike(search_filter),
                Customer.name.ilike(search_filter)
            )
        )
        payments_query = payments_query.filter(
            db.or_(
                Payment.payment_number.ilike(search_filter),
                Payment.supplier_name.ilike(search_filter)
            )
        )
    
    # فلترة الاتجاه
    if direction_filter == 'incoming':
        receipts_query = receipts_query.filter(Receipt.direction == 'incoming')
        payments_query = payments_query.filter(Payment.direction == 'incoming')
    elif direction_filter == 'outgoing':
        receipts_query = receipts_query.filter(Receipt.direction == 'outgoing')
        payments_query = payments_query.filter(Payment.direction == 'outgoing')
    
    # إخفاء السندات المؤرشفة
    from models import ArchivedRecord
    archived_receipts = db.session.query(ArchivedRecord.record_id).filter(
        ArchivedRecord.table_name == 'receipts'
    ).subquery()
    archived_payments = db.session.query(ArchivedRecord.record_id).filter(
        ArchivedRecord.table_name == 'payments'
    ).subquery()
    
    receipts_query = receipts_query.filter(~Receipt.id.in_(archived_receipts))
    payments_query = payments_query.filter(~Payment.id.in_(archived_payments))
    
    if current_user.is_seller():
        receipts_query = receipts_query.filter_by(user_id=current_user.id)
        payments_query = payments_query.filter_by(user_id=current_user.id)
    
    # جمع النتائج
    all_receipts = receipts_query.all()
    all_payments = payments_query.all()
    
    # دمج النتائج مع إضافة نوع السند
    combined_items = []
    
    for receipt in all_receipts:
        combined_items.append({
            'id': receipt.id,
            'number': receipt.receipt_number,
            'date': receipt.receipt_date,
            'amount': receipt.amount,
            'currency': receipt.currency,
            'amount_aed': receipt.amount_aed,
            'direction': receipt.direction,
            'type': 'receipt',
            'customer_name': receipt.customer.name if receipt.customer else '-',
            'supplier_name': None,
            'payment_method': receipt.payment_method,
            'payment_confirmed': receipt.payment_confirmed,
            'source_type': receipt.source_type,
            'notes': receipt.notes
        })
    
    for payment in all_payments:
        combined_items.append({
            'id': payment.id,
            'number': payment.payment_number,
            'date': payment.payment_date,
            'amount': payment.amount,
            'currency': payment.currency,
            'amount_aed': payment.amount_aed,
            'direction': payment.direction,
            'type': 'payment',
            'customer_name': None,
            'supplier_name': payment.supplier_name,
            'payment_method': payment.payment_method,
            'payment_confirmed': payment.payment_confirmed,
            'source_type': payment.payment_type,
            'notes': payment.notes
        })
    
    # ترتيب حسب التاريخ
    combined_items.sort(key=lambda x: x['date'], reverse=True)
    
    # تطبيق pagination يدوياً
    start = (page - 1) * per_page
    end = start + per_page
    paginated_items = combined_items[start:end]
    
    # إنشاء pagination object يدوياً
    class SimplePagination:
        def __init__(self, page, per_page, total, items):
            self.page = page
            self.per_page = per_page
            self.total = total
            self.items = items
            self.pages = (total + per_page - 1) // per_page
            self.has_prev = page > 1
            self.has_next = page < self.pages
            self.prev_num = page - 1 if self.has_prev else None
            self.next_num = page + 1 if self.has_next else None
    
    pagination = SimplePagination(
        page=page,
        per_page=per_page,
        total=len(combined_items),
        items=paginated_items
    )
    
    return render_template('payments/receipts.html',
                         receipts=paginated_items,
                         pagination=pagination,
                         direction_filter=direction_filter)


@payments_bp.route('/payments/<int:id>')
@login_required
@permission_required('manage_payments')
def view_payment(id):
    """عرض سند صرف - يستخدم نفس قالب سندات القبض"""
    from models import Payment
    payment = Payment.query.get_or_404(id)
    return render_template('payments/view_receipt.html', receipt=payment, is_payment=True)


@payments_bp.route('/payments/<int:id>/print')
@login_required
@permission_required('manage_payments')
def print_payment(id):
    """طباعة سند صرف - يستخدم نفس قالب طباعة سندات القبض"""
    from models import Payment
    payment = Payment.query.get_or_404(id)
    return render_template('payments/print_receipt.html', receipt=payment, is_payment=True)


@payments_bp.route('/payments/<int:id>/archive', methods=['POST'])
@login_required
@permission_required('manage_payments')
def archive_payment(id):
    """أرشفة سند صرف"""
    from models import Payment
    from services.archive_service import ArchiveService
    
    payment = Payment.query.get_or_404(id)
    
    try:
        archive_service = ArchiveService()
        archive_service.archive_record('payments', payment, reason='تم أرشفة سند الصرف')
        create_audit_log('archive', 'payments', payment.id)
    except Exception as e:
        db.session.rollback()
    
    return redirect(url_for('payments.receipts'))


@payments_bp.route('/payments/<int:id>/restore', methods=['POST'])
@login_required
@permission_required('manage_payments')
def restore_payment(id):
    """استعادة سند صرف من الأرشيف"""
    from models import ArchivedRecord, Payment
    
    archived = ArchivedRecord.query.filter_by(
        table_name='payments',
        record_id=id
    ).first_or_404()
    
    try:
        db.session.delete(archived)
        db.session.commit()
        create_audit_log('restore', 'payments', id)
    except Exception as e:
        db.session.rollback()
    
    return redirect(url_for('payments.archived_receipts'))




@payments_bp.route('/create_from_sale/<int:sale_id>', methods=['GET', 'POST'])
@login_required
@permission_required('manage_payments')
def create_from_sale(sale_id):
    """إنشاء سند دفع من فاتورة بيع معينة"""
    from models import Sale
    
    sale = Sale.query.get_or_404(sale_id)
    
    if request.method == 'POST':
        try:
            amount = request.form.get('amount', type=float)
            currency = request.form.get('currency', 'AED')
            user_exchange_rate = request.form.get('exchange_rate', type=float)
            payment_method = request.form.get('payment_method', 'cash')
            
            reference_number = request.form.get('reference_number')
            cheque_number = request.form.get('cheque_number')
            cheque_date = request.form.get('cheque_date') or None
            bank_name = request.form.get('bank_name')
            notes = request.form.get('notes')
            
            # تخصيص المبلغ للفاتورة المحددة
            allocate_to_sales = {sale.id: amount}
            
            receipt_data = {
                'customer_id': sale.customer_id,
                'amount': amount,
                'currency': currency,
                'user_exchange_rate': user_exchange_rate,
                'payment_method': payment_method,
                'reference_number': reference_number,
                'cheque_number': cheque_number,
                'cheque_date': cheque_date,
                'bank_name': bank_name,
                'notes': notes,
                'allocate_to_sales': allocate_to_sales
            }
            
            receipt = PaymentService.create_receipt(receipt_data)
            
            create_audit_log('create', 'receipts', receipt.id)
            
            flash('تم إنشاء سند القبض بنجاح', 'success')
            return redirect(url_for('payments.view_receipt', id=receipt.id))
        
        except Exception as e:
            flash(f'حدث خطأ: {str(e)}', 'danger')
    
    # استخدام القالب الموحد مع بيانات إضافية
    customers = [sale.customer]  # العميل من الفاتورة
    suggested_amount = sale.balance_due
    exchange_rates = CurrencyService.get_all_rates('AED')
    
    return render_template('payments/create_receipt.html',
                         customers=customers,
                         preselected_customer=sale.customer,
                         suggested_amount=suggested_amount,
                         exchange_rates=exchange_rates,
                         sale=sale)  # تمرير بيانات الفاتورة


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


@payments_bp.route('/archived')
@login_required
@permission_required('manage_payments')
def archived_receipts():
    """عرض السندات المؤرشفة"""
    from models import ArchivedRecord
    
    # جلب السندات المؤرشفة
    archived_receipts_query = db.session.query(ArchivedRecord).filter(
        ArchivedRecord.table_name == 'receipts'
    )
    archived_payments_query = db.session.query(ArchivedRecord).filter(
        ArchivedRecord.table_name == 'payments'
    )
    
    # دمج النتائج
    archived_items = []
    
    for archived in archived_receipts_query.all():
        data = archived.data
        archived_items.append({
            'id': archived.record_id,
            'number': data.get('receipt_number'),
            'date': datetime.fromisoformat(data.get('receipt_date').replace('Z', '+00:00')) if isinstance(data.get('receipt_date'), str) else data.get('receipt_date'),
            'amount': float(data.get('amount', 0)),
            'currency': data.get('currency'),
            'amount_aed': float(data.get('amount_aed', 0)),
            'type': 'receipt',
            'customer_name': data.get('customer_name'),
            'supplier_name': None,
            'source_type': data.get('source_type'),
            'archived_at': archived.archived_at
        })
    
    for archived in archived_payments_query.all():
        data = archived.data
        archived_items.append({
            'id': archived.record_id,
            'number': data.get('payment_number'),
            'date': datetime.fromisoformat(data.get('payment_date').replace('Z', '+00:00')) if isinstance(data.get('payment_date'), str) else data.get('payment_date'),
            'amount': float(data.get('amount', 0)),
            'currency': data.get('currency'),
            'amount_aed': float(data.get('amount_aed', 0)),
            'type': 'payment',
            'customer_name': None,
            'supplier_name': data.get('supplier_name'),
            'source_type': data.get('payment_type'),
            'archived_at': archived.archived_at
        })
    
    # ترتيب حسب تاريخ الأرشفة
    archived_items.sort(key=lambda x: x['archived_at'], reverse=True)
    
    return render_template('payments/archived.html', archived_items=archived_items)


@payments_bp.route('/receipts/<int:id>/archive', methods=['POST'])
@login_required
@permission_required('manage_payments')
def archive_receipt(id):
    """أرشفة سند قبض"""
    from services.archive_service import ArchiveService
    
    receipt = Receipt.query.get_or_404(id)
    
    try:
        archive_service = ArchiveService()
        archive_service.archive_record('receipts', receipt, reason='تم أرشفة سند القبض')
        create_audit_log('archive', 'receipts', receipt.id)
    except Exception as e:
        db.session.rollback()
    
    return redirect(url_for('payments.receipts'))


@payments_bp.route('/receipts/<int:id>/restore', methods=['POST'])
@login_required
@permission_required('manage_payments')
def restore_receipt(id):
    """استعادة سند قبض من الأرشيف"""
    from models import ArchivedRecord
    
    archived = ArchivedRecord.query.filter_by(
        table_name='receipts',
        record_id=id
    ).first_or_404()
    
    try:
        db.session.delete(archived)
        db.session.commit()
        create_audit_log('restore', 'receipts', id)
    except Exception as e:
        db.session.rollback()
    
    return redirect(url_for('payments.archived_receipts'))


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


@payments_bp.route('/create_payment/<int:purchase_id>', methods=['GET', 'POST'])
@login_required
@permission_required('manage_payments')
def create_payment(purchase_id):
    """إنشاء سند صرف لفاتورة مشتريات"""
    from models import Purchase, Payment, Supplier
    from utils.helpers import generate_number
    from sqlalchemy import func
    
    purchase = Purchase.query.get_or_404(purchase_id)
    supplier = Supplier.query.get(purchase.supplier_id) if purchase.supplier_id else None
    
    # حساب المبلغ المدفوع من جدول payments
    paid_amount = db.session.query(func.sum(Payment.amount_aed)).filter(
        Payment.supplier_id == purchase.supplier_id
    ).scalar() or 0
    
    # حساب المبلغ المتبقي
    balance = float(purchase.total_amount) - float(paid_amount)
    suggested_amount = balance if balance > 0 else 0
    
    if request.method == 'POST':
        try:
            from decimal import Decimal
            
            amount = request.form.get('amount', type=float)
            payment_method = request.form.get('payment_method', 'cash')
            notes = request.form.get('notes', '')
            exchange_rate = request.form.get('exchange_rate', type=float, default=1.0)
            currency = request.form.get('currency', default='AED')
            
            if amount <= 0 or amount > balance:
                flash('المبلغ غير صحيح', 'danger')
                return redirect(url_for('payments.create_payment', purchase_id=purchase_id))
            
            # تحويل إلى Decimal للحسابات الدقيقة
            amount_decimal = Decimal(str(amount))
            exchange_rate_decimal = Decimal(str(exchange_rate))
            amount_aed = amount_decimal * exchange_rate_decimal
            
            # إنشاء سند الصرف
            payment_number = generate_number('PAY', Payment, 'payment_number')
            payment = Payment(
                payment_number=payment_number,
                supplier_id=purchase.supplier_id,
                supplier_name=purchase.supplier_name,
                amount=amount_decimal,
                currency=currency,
                exchange_rate=exchange_rate_decimal,
                amount_aed=amount_aed,
                payment_method=payment_method,
                notes=notes,
                user_id=current_user.id,
                direction='outgoing',
                payment_type='supplier_payment'
            )
            
            db.session.add(payment)
            db.session.commit()
            
            flash('تم إنشاء سند الصرف بنجاح', 'success')
            return redirect(url_for('purchases.view', id=purchase_id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'خطأ: {str(e)}', 'danger')
    
    # استخدام نفس القالب الموحد لسندات القبض/الصرف
    return render_template('payments/create_receipt.html',
                         purchase=purchase,
                         supplier=supplier,
                         suggested_amount=suggested_amount,
                         is_payment=True)  # علامة لتمييز سند الصرف


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

