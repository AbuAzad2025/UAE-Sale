from datetime import datetime

from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from sqlalchemy import select

from extensions import db
from models import Receipt, Customer, InvoiceSettings, Supplier
from services.payment_service import PaymentService
from services.currency_service import CurrencyService
from utils.decorators import permission_required
from utils.helpers import create_audit_log

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
    archived_receipts_select = select(ArchivedRecord.record_id).where(
        ArchivedRecord.table_name == 'receipts'
    )
    archived_payments_select = select(ArchivedRecord.record_id).where(
        ArchivedRecord.table_name == 'payments'
    )
    
    receipts_query = receipts_query.filter(Receipt.id.notin_(archived_receipts_select))
    payments_query = payments_query.filter(Payment.id.notin_(archived_payments_select))
    
    if current_user.is_seller():
        receipts_query = receipts_query.filter(Receipt.user_id == current_user.id)
        payments_query = payments_query.filter(Payment.user_id == current_user.id)
    
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
    from flask import current_app
    company = {
        'name_ar': current_app.config.get('COMPANY_NAME_AR'),
        'address': current_app.config.get('COMPANY_ADDRESS'),
        'phone': current_app.config.get('COMPANY_PHONE'),
    }
    return render_template('payments/print_receipt.html', receipt=payment, is_payment=True, company=company, printed_at=datetime.now())


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
        
        # 1. Archive the record (No commit yet)
        archive_service.archive_record('payments', payment, reason='تم أرشفة سند الصرف', commit=False)
        create_audit_log('archive', 'payments', payment.id)
        
        # 2. Reverse GL Entry (Must succeed)
        from services.gl_service import GLService
        GLService.reverse_entry(
            reference_type='Payment',
            reference_id=id,
            description=f'Reverse Payment {payment.payment_number}'
        )
        
        # 3. Commit all
        db.session.commit()
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to archive payment {id}: {e}')
        flash(f'فشلت الأرشفة: {str(e)}', 'danger')
        return redirect(url_for('payments.receipts'))
    
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
            payment_method_value = (request.form.get('payment_method') or '').strip()
            if not payment_method_value:
                flash('يرجى اختيار طريقة الدفع.', 'warning')
                exchange_rates = CurrencyService.get_all_rates('AED')
                suggested_amount = sale.balance_due
                return render_template('payments/create_receipt.html',
                                     customers=[sale.customer],
                                     preselected_customer=sale.customer,
                                     suggested_amount=suggested_amount,
                                     exchange_rates=exchange_rates,
                                     sale=sale,
                                     form_data=request.form)
            
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
                'payment_method': payment_method_value,
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
            flash(f'حدث خطأ: {str(e)}\nتحقق من البيانات المدخلة وحاول مرة أخرى.', 'danger')
    
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


@payments_bp.route('/voucher/create', methods=['GET'])
@login_required
@permission_required('manage_payments')
def create_voucher():
    """عرض صفحة إنشاء سند مالي موحد (قبض/صرف)"""
    import json
    from models import Supplier
    
    # تحضير البيانات لـ JS
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()
    suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all()
    
    customers_data = [{
        'id': c.id,
        'name': c.name,
        'type': c.customer_type
    } for c in customers]
    
    suppliers_data = [{
        'id': s.id,
        'name': s.name
    } for s in suppliers]
    
    return render_template('payments/voucher.html',
                         customers_json=json.dumps(customers_data),
                         suppliers_json=json.dumps(suppliers_data),
                         today_date=datetime.now().date().isoformat())


@payments_bp.route('/voucher/submit', methods=['POST'])
@login_required
@permission_required('manage_payments')
def create_voucher_submit():
    """معالجة حفظ السند المالي الموحد"""
    try:
        direction = request.form.get('direction') # incoming, outgoing
        party_type = request.form.get('party_type') # customer, supplier
        party_id = request.form.get('party_id', type=int)
        amount = request.form.get('amount', type=float)
        payment_method = request.form.get('payment_method')
        date_str = request.form.get('date')
        notes = request.form.get('notes')
        
        # العملة وسعر الصرف (افتراضي: AED بمعدل 1)
        currency = request.form.get('currency', 'AED')
        user_exchange_rate = request.form.get('exchange_rate', type=float, default=1.0)
        
        # بيانات الشيك
        cheque_number = request.form.get('cheque_number')
        cheque_date = request.form.get('cheque_date')
        bank_name = request.form.get('bank_name')

        if not party_id or not amount:
            flash('يرجى تعبئة جميع الحقول الإلزامية', 'warning')
            return redirect(url_for('payments.create_voucher'))

        # 1. معالجة سند القبض (Receipt) - وارد
        if direction == 'incoming':
            if party_type == 'customer':
                # سند قبض من عميل (المنطق الحالي)
                receipt_data = {
                    'customer_id': party_id,
                    'amount': amount,
                    'currency': currency,
                    'user_exchange_rate': user_exchange_rate,
                    'payment_method': payment_method,
                    'notes': notes,
                    'cheque_number': cheque_number if payment_method == 'cheque' else None,
                    'cheque_date': cheque_date if payment_method == 'cheque' else None,
                    'bank_name': bank_name if payment_method == 'cheque' else None,
                }
                receipt = PaymentService.create_receipt(receipt_data)
                flash(f'تم إنشاء سند القبض رقم {receipt.receipt_number} بنجاح', 'success')
                return redirect(url_for('payments.receipts'))
            
            elif party_type == 'supplier':
                # سند قبض من مورد (مرتجع مشتريات أو تسوية)
                # نحتاج منطق جديد أو استخدام Payment بـ direction='incoming'
                # حالياً Payment يدعم direction='incoming' حسب الموديل
                
                from models import Payment
                from utils.helpers import generate_number
                from decimal import Decimal
                
                exchange_rate = CurrencyService.get_exchange_rate(currency, 'AED', user_rate=user_exchange_rate)
                amount_decimal = Decimal(str(amount))
                amount_aed = amount_decimal * exchange_rate
                
                supplier = Supplier.query.get(party_id)
                payment = Payment(
                    payment_number=generate_number('PAY', Payment, 'payment_number'), # ربما نحتاج تسلسل منفصل؟
                    payment_type='refund', # استرداد
                    direction='incoming',
                    supplier_id=supplier.id,
                    supplier_name=supplier.name,
                    amount=amount_decimal,
                    currency=currency,
                    exchange_rate=exchange_rate,
                    amount_aed=amount_aed,
                    payment_method=payment_method,
                    notes=notes,
                    cheque_number=cheque_number if payment_method == 'cheque' else None,
                    cheque_date=cheque_date if payment_method == 'cheque' else None,
                    bank_name=bank_name if payment_method == 'cheque' else None,
                    user_id=current_user.id
                )
                db.session.add(payment)
                db.session.commit()
                flash('تم إنشاء سند قبض من مورد بنجاح', 'success')
                return redirect(url_for('payments.receipts'))

        # 2. معالجة سند الصرف (Payment) - صادر
        elif direction == 'outgoing':
            from models import Payment
            from utils.helpers import generate_number
            from decimal import Decimal
            
            exchange_rate = CurrencyService.get_exchange_rate(currency, 'AED', user_rate=user_exchange_rate)
            amount_decimal = Decimal(str(amount))
            amount_aed = amount_decimal * exchange_rate
            
            if party_type == 'supplier':
                # دفع لمورد (المنطق المعتاد)
                supplier = Supplier.query.get(party_id)
                payment = Payment(
                    payment_number=generate_number('PAY', Payment, 'payment_number'),
                    payment_type='bill_payment',
                    direction='outgoing',
                    supplier_id=supplier.id,
                    supplier_name=supplier.name,
                    amount=amount_decimal,
                    currency=currency,
                    exchange_rate=exchange_rate,
                    amount_aed=amount_aed,
                    payment_method=payment_method,
                    notes=notes,
                    cheque_number=cheque_number if payment_method == 'cheque' else None,
                    cheque_date=cheque_date if payment_method == 'cheque' else None,
                    bank_name=bank_name if payment_method == 'cheque' else None,
                    user_id=current_user.id
                )
                db.session.add(payment)
                db.session.flush() # Flush to get ID

                # معالجة خاصة للشيكات (إنشاء سجل شيك + قيد محاسبي خاص)
                if payment_method == 'cheque' and cheque_number:
                    from models import Cheque
                    cheque = Cheque(
                        cheque_number=cheque_number,
                        cheque_bank_number=cheque_number,
                        cheque_type='outgoing',
                        supplier_id=supplier.id,
                        payment_id=payment.id,
                        amount=payment.amount,
                        currency=payment.currency,
                        exchange_rate=payment.exchange_rate,
                        amount_aed=payment.amount_aed,
                        issue_date=datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else datetime.now().date(),
                        due_date=datetime.strptime(cheque_date, '%Y-%m-%d').date() if cheque_date else datetime.now().date(),
                        bank_name=bank_name,
                        payee_name=supplier.name,
                        status='pending',
                        notes=notes,
                        user_id=current_user.id
                    )
                    db.session.add(cheque)
                    db.session.flush()
                    
                    # استخدام منطق الشيك المحاسبي (ذمم دائنة -> شيكات مؤجلة)
                    cheque.issue_cheque()
                    
                else:
                    # GL Entry for Standard Payment (Cash/Bank)
                    try:
                        from services.gl_service import GLService
                        GLService.ensure_core_accounts()
                        
                        # Credit: Cash/Bank
                        credit_account = '1110' # Cash
                        if payment_method == 'bank_transfer' or payment_method == 'card':
                            credit_account = '1120' # Bank

                        lines = [
                            {'account': '2110', 'debit': payment.amount, 'description': f'سداد للمورد {payment.supplier_name}'},
                            {'account': credit_account, 'credit': payment.amount, 'description': f'سند صرف {payment.payment_number}'}
                        ]
                        GLService.post_entry(
                            lines,
                            description=f'Payment {payment.payment_number}',
                            reference_type='Payment',
                            reference_id=payment.id,
                            currency=currency,
                            exchange_rate=exchange_rate
                        )
                    except Exception as e:
                        current_app.logger.error(f"GL Posting failed for supplier payment: {e}")

                db.session.commit()
                flash('تم إنشاء سند صرف لمورد بنجاح', 'success')
                return redirect(url_for('payments.receipts'))
            
            elif party_type == 'customer':
                # دفع لعميل (استرداد أو تسوية أو سحب شريك)
                # Payment model has customer_id field
                customer = Customer.query.get(party_id)
                payment = Payment(
                    payment_number=generate_number('PAY', Payment, 'payment_number'),
                    payment_type='refund',
                    direction='outgoing',
                    customer_id=customer.id,
                    amount=amount_decimal,
                    currency=currency,
                    exchange_rate=exchange_rate,
                    amount_aed=amount_aed,
                    payment_method=payment_method,
                    notes=notes,
                    cheque_number=cheque_number if payment_method == 'cheque' else None,
                    cheque_date=cheque_date if payment_method == 'cheque' else None,
                    bank_name=bank_name if payment_method == 'cheque' else None,
                    user_id=current_user.id
                )
                db.session.add(payment)
                db.session.flush() # Flush to get ID

                # معالجة خاصة للشيكات (إنشاء سجل شيك + قيد محاسبي خاص)
                if payment_method == 'cheque' and cheque_number:
                    from models import Cheque
                    cheque = Cheque(
                        cheque_number=cheque_number,
                        cheque_bank_number=cheque_number,
                        cheque_type='outgoing',
                        customer_id=customer.id,
                        payment_id=payment.id,
                        amount=payment.amount,
                        currency=payment.currency,
                        exchange_rate=payment.exchange_rate,
                        amount_aed=payment.amount_aed,
                        issue_date=datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else datetime.now().date(),
                        due_date=datetime.strptime(cheque_date, '%Y-%m-%d').date() if cheque_date else datetime.now().date(),
                        bank_name=bank_name,
                        payee_name=customer.name,
                        status='pending',
                        notes=notes,
                        user_id=current_user.id
                    )
                    db.session.add(cheque)
                    db.session.flush()
                    
                    # استخدام منطق الشيك المحاسبي المركزي
                    try:
                        cheque.issue_cheque()
                    except Exception as e:
                        current_app.logger.error(f"Cheque issue accounting failed: {e}")

                else:
                    # GL Entry for Customer/Partner/Merchant Payment (Non-Cheque)
                    try:
                        from services.gl_service import GLService
                        GLService.ensure_core_accounts()
                        
                        credit_account = GLService.get_payment_debit_account(payment_method)
                        
                        # Debit Account based on Customer Type
                        debit_account = GLService.get_customer_credit_account(customer)
                        
                        lines = [
                            {'account': debit_account, 'debit': payment.amount, 'description': f'سداد/سحب {customer.name}'},
                            {'account': credit_account, 'credit': payment.amount, 'description': f'سند صرف {payment.payment_number}'}
                        ]
                        GLService.post_entry(
                            lines,
                            description=f'Payment {payment.payment_number}',
                            reference_type='Payment',
                            reference_id=payment.id,
                            currency=currency,
                            exchange_rate=exchange_rate
                        )
                    except Exception as e:
                        current_app.logger.error(f"GL Posting failed for customer payment: {e}")

                db.session.commit()
                flash('تم إنشاء سند صرف لعميل/شريك بنجاح', 'success')
                return redirect(url_for('payments.receipts'))

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Voucher creation error: {e}")
        flash(f'حدث خطأ أثناء حفظ السند: {str(e)}', 'danger')
        return redirect(url_for('payments.create_voucher'))

    return redirect(url_for('payments.receipts'))


@payments_bp.route('/receipts/create', methods=['GET', 'POST'])
@login_required
@permission_required('manage_payments')
def create_receipt():
    # Redirect legacy route to new unified voucher
    return redirect(url_for('payments.create_voucher'))


@payments_bp.route('/receipts/<int:id>')
@login_required
@permission_required('manage_payments')
def view_receipt(id):
    receipt = Receipt.query.get_or_404(id)
    
    if current_user.is_seller() and not current_user.is_owner and receipt.user_id != current_user.id:
        flash('ليس لديك صلاحية لعرض هذا السند', 'danger')
        return redirect(url_for('payments.receipts'))
    
    return render_template('payments/view_receipt.html', receipt=receipt)


@payments_bp.route('/receipts/<int:id>/print')
@login_required
@permission_required('manage_payments')
def print_receipt(id):
    receipt = Receipt.query.get_or_404(id)
    
    if current_user.is_seller() and not current_user.is_owner and receipt.user_id != current_user.id:
        flash('ليس لديك صلاحية لطباعة هذا السند', 'danger')
        return redirect(url_for('payments.receipts'))
    
    # Get invoice settings
    settings = InvoiceSettings.get_active()
    
    # استخدام القالب النشط من الإعدادات
    template = settings.active_template if settings and settings.active_template else 'modern'
    template_path = f'receipts/{template}.html'
    
    # التحقق من وجود القالب، وإلا استخدام القالب الافتراضي
    try:
        from flask import current_app
        company = {
            'name_ar': current_app.config.get('COMPANY_NAME_AR'),
            'address': current_app.config.get('COMPANY_ADDRESS'),
            'phone': current_app.config.get('COMPANY_PHONE'),
        }
        return render_template(template_path, receipt=receipt, settings=settings, company=company, printed_at=datetime.now())
    except:
        # إذا لم يوجد القالب، استخدام modern كافتراضي
        from flask import current_app
        company = {
            'name_ar': current_app.config.get('COMPANY_NAME_AR'),
            'address': current_app.config.get('COMPANY_ADDRESS'),
            'phone': current_app.config.get('COMPANY_PHONE'),
        }
        return render_template('receipts/modern.html', receipt=receipt, settings=settings, company=company, printed_at=datetime.now())


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
    """حذف أو أرشفة سند قبض"""
    from models import Receipt, Cheque
    from services.archive_service import ArchiveService
    
    receipt = Receipt.query.get_or_404(id)
    
    # التحقق من الارتباطات
    has_links = False
    if receipt.allocations:
        has_links = True
    if receipt.cheque_id:
        has_links = True
    if receipt.cheques:  # التحقق من الشيكات المرتبطة
        has_links = True
    
    try:
        # 1. عكس التخصيصات (إعادة الرصيد للفاتورة)
        if receipt.allocations:
            from models import Sale
            for allocation in receipt.allocations:
                sale = Sale.query.get(allocation.sale_id)
                if sale:
                    sale.paid_amount -= allocation.allocated_amount
                    sale.balance_due = sale.total_amount - sale.paid_amount
                    sale.update_payment_status()

        # 2. القرار: أرشفة أو حذف
        if has_links:
            # عكس القيد المحاسبي (للحفاظ على السجل)
            try:
                from services.gl_service import GLService
                GLService.reverse_entry(
                    reference_type='Receipt',
                    reference_id=receipt.id,
                    description=f'Reverse Receipt {receipt.receipt_number}'
                )
            except Exception as e:
                current_app.logger.warning(f'GL reversal warning: {e}')

            # أرشفة (Soft Delete)
            archive_service = ArchiveService()
            archive_service.archive_record('receipts', receipt, reason='تم أرشفة السند لوجود ارتباطات', commit=False)
            
            # أرشفة الشيكات المرتبطة
            for cheque in receipt.cheques:
                archive_service.archive_record('cheques', cheque, reason='تم أرشفة الشيك لارتباطه بسند مؤرشف', commit=False)
            
            create_audit_log('archive', 'receipts', id)
            db.session.commit()
            flash(f'تم أرشفة سند القبض "{receipt.receipt_number}" (لوجود حركات مرتبطة)', 'warning')
        else:
            # حذف القيود المحاسبية المرتبطة (تنظيف شامل)
            from models import GLJournalEntry
            GLJournalEntry.query.filter_by(reference_type='Receipt', reference_id=receipt.id).delete()

            # حذف نهائي (Hard Delete)
            # حذف الشيكات المرتبطة أولاً لتجنب خطأ المفتاح الأجنبي
            for cheque in receipt.cheques:
                db.session.delete(cheque)
                
            db.session.delete(receipt)
            create_audit_log('delete', 'receipts', id)
            db.session.commit()
            flash(f'تم حذف سند القبض "{receipt.receipt_number}" نهائياً', 'success')
            
        return redirect(url_for('payments.receipts'))
    
    except Exception as e:
        db.session.rollback()
        flash(f'فشل الحذف: {str(e)}', 'danger')
        return redirect(url_for('payments.view_receipt', id=id))


@payments_bp.route('/payments/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('manage_payments')
def delete_payment(id):
    """حذف أو أرشفة سند صرف"""
    from models import Payment, Cheque
    from services.archive_service import ArchiveService

    payment = Payment.query.get_or_404(id)
    
    # التحقق من الارتباطات
    has_links = False
    if payment.cheque_id:
        has_links = True
    if payment.cheques:  # التحقق من الشيكات المرتبطة
        has_links = True
    # يمكن إضافة شروط أخرى للارتباط هنا
    
    try:
        # 1. القرار: أرشفة أو حذف
        if has_links:
            # عكس القيد المحاسبي
            try:
                from services.gl_service import GLService
                GLService.reverse_entry(
                    reference_type='Payment',
                    reference_id=payment.id,
                    description=f'Reverse Payment {payment.payment_number}'
                )
            except Exception as e:
                current_app.logger.warning(f"GL Reversal warning: {e}")

            # أرشفة
            archive_service = ArchiveService()
            archive_service.archive_record('payments', payment, reason='تم أرشفة السند لوجود ارتباطات', commit=False)
            
            # أرشفة الشيكات المرتبطة
            for cheque in payment.cheques:
                archive_service.archive_record('cheques', cheque, reason='تم أرشفة الشيك لارتباطه بسند مؤرشف', commit=False)

            create_audit_log('archive', 'payments', id)
            db.session.commit()
            flash(f'تم أرشفة سند الصرف "{payment.payment_number}" (لوجود حركات مرتبطة)', 'warning')
        else:
            # حذف القيود المحاسبية المرتبطة
            from models import GLJournalEntry
            GLJournalEntry.query.filter_by(reference_type='Payment', reference_id=payment.id).delete()

            # حذف نهائي
            # حذف الشيكات المرتبطة أولاً
            for cheque in payment.cheques:
                db.session.delete(cheque)

            db.session.delete(payment)
            create_audit_log('delete', 'payments', id)
            db.session.commit()
            flash(f'تم حذف سند الصرف "{payment.payment_number}" نهائياً', 'success')
            
        return redirect(url_for('payments.receipts'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'فشل الحذف: {str(e)}', 'danger')
        return redirect(url_for('payments.view_payment', id=id))


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
            payment_method_value = (request.form.get('payment_method') or '').strip()
            if not payment_method_value:
                flash('يرجى اختيار طريقة الدفع.', 'warning')
                return render_template('payments/create_receipt.html',
                                     purchase=purchase,
                                     supplier=supplier,
                                     suggested_amount=suggested_amount,
                                     is_payment=True,
                                     form_data=request.form)
            notes = request.form.get('notes', '')
            exchange_rate = request.form.get('exchange_rate', type=float, default=1.0)
            currency = request.form.get('currency', default='AED')
            
            reference_number = request.form.get('reference_number')
            cheque_number = request.form.get('cheque_number')
            cheque_date = request.form.get('cheque_date') or None
            bank_name = request.form.get('bank_name')
            # حقول خاصة بطرق دفع معينة
            bank_name_transfer = request.form.get('bank_name_transfer')
            reference_number_transfer = request.form.get('reference_number_transfer')
            card_last4 = request.form.get('card_last4')
            reference_number_card = request.form.get('reference_number_card')
            
            if amount <= 0 or amount > balance:
                flash('المبلغ غير صحيح.\nتحقق من الصيغة الصحيحة وحاول مرة أخرى.', 'danger')
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
                payment_method=payment_method_value,
                notes=notes,
                user_id=current_user.id,
                direction='outgoing',
                payment_type='supplier_payment'
            )
            
            # تعيين حقول المرجع/البنك حسب الطريقة
            if payment_method_value == 'bank_transfer':
                payment.bank_name = bank_name_transfer or bank_name
                payment.reference_number = reference_number_transfer or reference_number
            elif payment_method_value == 'card':
                payment.reference_number = reference_number_card or reference_number
                if card_last4:
                    payment.notes = f'{payment.notes or ""} بطاقة آخر 4: {card_last4}'.strip()
            elif payment_method_value == 'e_wallet':
                from flask import request as _req
                ref_ew = _req.form.get('reference_number_ewallet')
                payment.reference_number = ref_ew or reference_number
            else:
                payment.reference_number = reference_number
                payment.bank_name = bank_name
            
            db.session.add(payment)
            db.session.flush()
            
            # إنشاء سجل الشيك وربطه إذا كانت طريقة الدفع شيك
            if payment_method_value == 'cheque' and cheque_number:
                from models import Cheque
                cheque = Cheque(
                    cheque_number=cheque_number,
                    cheque_bank_number=cheque_number,
                    cheque_type='outgoing',
                    supplier_id=purchase.supplier_id,
                    amount=amount_decimal,
                    currency=currency,
                    exchange_rate=exchange_rate_decimal,
                    amount_aed=amount_aed,
                    issue_date=datetime.utcnow().date(),
                    due_date=cheque_date if cheque_date else None,
                    bank_name=bank_name,
                    status='pending',
                    notes=notes
                )
                db.session.add(cheque)
                db.session.flush()
                payment.cheque_id = cheque.id
                payment.payment_confirmed = False
            
            # قيد محاسبي لسند الصرف
            try:
                from services.gl_service import GLService
                GLService.ensure_core_accounts()
                cash_or_bank = '1110' if payment_method_value == 'cash' else '1120'
                lines = [
                    {'account': '2110', 'debit': payment.amount_aed, 'description': f'سداد للمورد {payment.supplier_name}'},
                    {'account': cash_or_bank, 'credit': payment.amount_aed, 'description': f'سند صرف {payment.payment_number}'}
                ]
                GLService.post_entry(
                    lines,
                    description=f'Payment {payment.payment_number}',
                    reference_type='Payment',
                    reference_id=payment.id,
                    currency=payment.currency,
                    exchange_rate=payment.exchange_rate
                )
            except Exception as e:
                pass
            
            db.session.commit()
            
            flash('تم إنشاء سند الصرف بنجاح', 'success')
            return redirect(url_for('purchases.view', id=purchase_id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'حدث خطأ: {str(e)}', 'danger')
    
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

