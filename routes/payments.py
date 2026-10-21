from datetime import datetime
from decimal import Decimal

from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from sqlalchemy import select

from extensions import db
from models import Receipt, Customer, InvoiceSettings, Supplier
from services.payment_service import PaymentService
from services.currency_service import CurrencyService
from utils.decorators import permission_required, get_owned_or_404
from utils.helpers import create_audit_log
from routes.ledger import reverse_or_purge_gl_entries

payments_bp = Blueprint('payments', __name__, url_prefix='/payments')


def _resolve_document_rate(currency, submitted_rate, document_currency, document_rate):
    """F7: حماية من سعر صرف محمّل مسبقاً من مستند بعملة أخرى.

    نموذج سند القبض يعرض سعر صرف الفاتورة/الشراء في حقل readonly — فإن
    غيّر المستخدم عملة السند تبقى القيمة القديمة (سعر عملة المستند) وتُسجَّل
    بها عملية بعملة أخرى. هنا نرفض سعر المستند ونأخذ سعر السوق.

    Returns:
        (rate, corrected) — السعر المستخدم وهل تم استبداله بسعر السوق.
    """
    from services.currency_service import CurrencyService

    if not currency or not document_currency:
        return submitted_rate, False

    if str(currency).upper() == str(document_currency).upper():
        # نفس العملة → سعر المستند هو الصحيح
        if document_rate:
            return Decimal(str(document_rate)), False
        return submitted_rate, False

    # عملة مختلفة → سعر السوق (لا يُقبل سعر المستند)
    try:
        market = CurrencyService.get_exchange_rate(
            currency, CurrencyService.get_base_currency())
    except Exception:
        market = None
    if market:
        return market, True
    return submitted_rate, False


def _archive_payment_record(record_id, reason):
    """أرشف سند صرف أو قبض - تنفيذ واحد يستعمله المساران.

    static/js/payments.js ينادي /payments/archive/<id> بصيغة JSON بينما
    المسارات القائمة /payments/payments/<id>/archive و
    /payments/receipts/<id>/archive تستعمل النموذج. التنفيذ هنا واحد حتى
    لا تختلف النتائج.

    يرفع الاستثناء عند الفشل، ويتولى كل مسار عرض الخطأ بطريقته.
    """
    from models import Payment
    from services.archive_service import ArchiveService

    reason = (reason or '').strip() or 'تم الأرشفة من الواجهة'

    # get_owned_or_404 يُنهي الطلب بـ404/403 بدل أن يعيد None، لذلك
    # يُستدعى هنا داخل try ويُلتقط الاستثناء ليعيد JSON.
    from werkzeug.exceptions import NotFound, Forbidden

    try:
        # سند الصرف أولاً، ثم سند القبض - المعرّفات في جدولين منفصلين.
        payment = get_owned_or_404(Payment, record_id, code=404)
    except (NotFound, Forbidden):
        payment = None
    except Exception:
        raise

    if payment is not None:
        archive_service = ArchiveService()
        archive_service.archive_record(
            'payments', payment, reason=reason, commit=False)
        create_audit_log('archive', 'payments', payment.id)

        # عكس القيد المحاسبي - يجب أن ينجح قبل الاعتماد.
        from models import GLJournalEntry
        gl_entries = GLJournalEntry.query.filter_by(
            reference_type='Payment',
            reference_id=record_id,
            is_reversed=False
        ).all()
        for entry in gl_entries:
            entry.reverse_entry(
                description=f'Reverse Payment {payment.payment_number}')

        db.session.commit()
        return 'payments', payment

    try:
        receipt = get_owned_or_404(Receipt, record_id, code=404)
    except (NotFound, Forbidden):
        receipt = None

    if receipt is not None:
        archive_service = ArchiveService()
        archive_service.archive_record(
            'receipts', receipt, reason=reason, commit=False)
        create_audit_log('archive', 'receipts', receipt.id)
        db.session.commit()
        return 'receipts', receipt

    return None, None


def _recompute_sale_settlement(sale):
    """F5: إعادة احتساب تسوية الفاتورة من المبلغ المسدَّد (عملة الأساس).

    نفس صيغة ``models/sale.py::recalculate_payment_status``: المدفوع
    يُحتسب بعملة الأساس، والمتبقي = قيمة الفاتورة − المدفوع، وحالة الدفع
    تُشتق من المتبقي.
    """
    rate = Decimal(str(sale.exchange_rate or 1))
    paid_base = Decimal(str(sale.paid_amount_base or 0))

    if rate > 0:
        sale.paid_amount = (paid_base / rate).quantize(Decimal('0.001'))

    sale.balance_due = max(
        Decimal('0'), Decimal(str(sale.amount_base or 0)) - paid_base)

    if sale.balance_due <= Decimal('0.01'):
        sale.payment_status = 'paid'
        sale.balance_due = Decimal('0')
    elif paid_base > 0:
        sale.payment_status = 'partial'
    else:
        sale.payment_status = 'unpaid'

    return sale


def _reverse_receipt_allocations(receipt):
    """F5: عكس كل تخصيص على فاتورته — من التخصيصات المحفوظة في السند.

    كان يُعكس المبلغ الكلي على أول فاتورة فقط، فتُخصم الفاتورة الأولى
    مرتين وتبقى البقية مُسدَّدة بلا سند. الآن يُعكس كل تخصيص على فاتورته
    (Receipt.allocations_json / Receipt.get_allocations) وتُعاد تسوية كل
    فاتورة من المبلغ المتبقي فيها.

    ملاحظة (F5): التسوية تُحتسب هنا من المبلغ المسدَّد في الفاتورة نفسها
    ولا نستعمل ``models.sale.recompute_sale_settlement``، لأن اشتقاقها
    (``compute_sale_paid_base``) يجمع سندات القبض بـ ``Receipt.sale_id``
    فقط — أي سند تخصَّص لفاتورة ثانوية لا يظهر في اشتقاق تلك الفاتورة،
    فاستعماله هنا يمحو تسوية الفاتورة الثانية ويسبّب تضارباً في الحساب.
    """
    from models import Sale

    touched = []
    for alloc in (receipt.get_allocations() or []):
        sale_id = alloc.get('sale_id')
        if not sale_id:
            continue
        try:
            sale = Sale.query.filter_by(id=int(sale_id)).first()
        except (TypeError, ValueError):
            continue
        if sale is None:
            continue

        amount_base = Decimal(str(alloc.get('amount_base') or 0))
        if amount_base <= 0:
            continue

        sale.paid_amount_base = max(
            Decimal('0'), Decimal(str(sale.paid_amount_base or 0)) - amount_base)
        _recompute_sale_settlement(sale)
        touched.append(sale)

    return touched


def _reverse_payment_allocation(payment):
    """F5: عكس تخصيص سند الصرف على فاتورته (إن وُجدت فاتورة مرتبطة).

    عكس مساهمة السند في تسوية الفاتورة هو معاكس ما يضيفه الاشتقاق
    (``models/sale.py::compute_sale_paid_base``): الاسترداد (refund) نقص
    المدفوع فيعود، والدفعة العادية زادته فيُنقص.
    """
    from models import Sale

    if not payment.sale_id:
        return None

    sale = Sale.query.filter_by(id=payment.sale_id).first()
    if sale is None:
        return None

    amount_base = Decimal(str(payment.amount_base or 0))
    if amount_base <= 0:
        return sale

    paid_base = Decimal(str(sale.paid_amount_base or 0))
    if (payment.payment_type or '') == 'refund':
        # الاسترداد كان نقص المدفوع → عودته تزيده.
        sale.paid_amount_base = paid_base + amount_base
    else:
        sale.paid_amount_base = max(Decimal('0'), paid_base - amount_base)

    _recompute_sale_settlement(sale)
    return sale


@payments_bp.route('/archive/<int:id>', methods=['POST'])
@login_required
@permission_required('manage_payments')
def archive_payment_json(id):
    """أرشفة سند صرف/قبض بصيغة JSON.

    static/js/payments.js يستدعي هذا المسار_handle لكنه لم يكن موجوداً،
    فكان زر الأرشفة يعيد 404. يقرأ السبب من النموذج أو من JSON.
    """
    from flask import jsonify

    reason = (request.form.get('reason')
              or (request.get_json(silent=True) or {}).get('reason') or '')

    try:
        table, record = _archive_payment_record(id, reason)
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to archive payment {id}: {e}')
        current_app.logger.exception('handler failed')
        return jsonify({
            'status': 'error',
            'ok': False,
            'message': 'فشلت الأرشفة: حدث خطأ غير متوقع',
        }), 500

    if record is None:
        return jsonify({
            'status': 'error',
            'ok': False,
            'message': 'السجل غير موجود',
        }), 404

    return jsonify({
        'status': 'success',
        'ok': True,
        'id': record.id,
        'type': table,
        'message': 'تمت الأرشفة بنجاح',
    })


@payments_bp.route('/search-entities')
@login_required
@permission_required('manage_payments')
def search_entities():
    """اقتراح كيانات للبحث في نموذج الدفع.

    static/js/payment_form.js و static/js/payments.js يستدعيان
    /payments/search-entities?type=<type>&q=<query> ويتوقعان مصفوفة
    عناصر، كل عنصر فيه id و display و phone اختياري.
    """
    from flask import jsonify
    from models import Customer, Supplier

    entity_type = (request.args.get('type') or 'customers').lower()
    query = (request.args.get('q') or '').strip()

    if entity_type in ('suppliers', 'supplier'):
        if not query:
            return jsonify([])
        rows = Supplier.query.filter(
            Supplier.is_active == True,  # noqa: E712
            db.or_(
                Supplier.name.ilike(f'%{query}%'),
                Supplier.company_name.ilike(f'%{query}%'),
                Supplier.phone.ilike(f'%{query}%'),
            )
        ).order_by(Supplier.name).limit(20).all()
        return jsonify([{
            'id': s.id,
            'display': s.name,
            'name': s.name,
            'phone': s.phone,
        } for s in rows])

    # الافتراضي: الزبائن
    if not query:
        return jsonify([])

    rows = Customer.query.filter(
        Customer.is_active == True,  # noqa: E712
        db.or_(
            Customer.name.ilike(f'%{query}%'),
            Customer.phone.ilike(f'%{query}%'),
        )
    ).order_by(Customer.name).limit(20).all()
    return jsonify([{
        'id': c.id,
        'display': c.name,
        'name': c.name,
        'phone': c.phone,
    } for c in rows])


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
            'amount_base': receipt.amount_base,
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
            'amount_base': payment.amount_base,
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
    payment = get_owned_or_404(Payment, id)
    return render_template('payments/view_receipt.html', receipt=payment, is_payment=True)


@payments_bp.route('/payments/<int:id>/print')
@login_required
@permission_required('manage_payments')
def print_payment(id):
    """طباعة سند صرف - يستخدم نفس قالب طباعة سندات القبض"""
    from models import Payment
    payment = get_owned_or_404(Payment, id)
    from flask import current_app
    company = {
        'name_ar': current_app.config.get('COMPANY_NAME_AR'),
        'address': current_app.config.get('COMPANY_ADDRESS'),
        'phone': current_app.config.get('COMPANY_PHONE'),
    }
    
    settings = InvoiceSettings.get_active()
    
    # Template selection (payments use receipt templates)
    template = request.args.get('template', 'modern')
    _ALLOWED_TEMPLATES = ('modern', 'classic', 'gulf', 'minimal', 'simple')
    template = request.args.get('template') or 'modern'
    if template not in _ALLOWED_TEMPLATES:
        template = 'modern'
    
    template_labels = {
        'modern': 'مودرن',
        'classic': 'كلاسيك',
        'gulf': 'خليجي',
        'minimal': 'بسيط',
        'simple': 'مبسط'
    }
    available_templates = [(k, v) for k, v in template_labels.items() if k in _ALLOWED_TEMPLATES]
    
    return render_template(
        f'receipts/{template}.html',
        receipt=payment,
        is_payment=True,
        settings=settings,
        company=company,
        printed_at=datetime.now(),
        available_templates=available_templates,
        current_template=template,
        document_type='payment',
        document_id=payment.id
    )


@payments_bp.route('/payments/<int:id>/archive', methods=['POST'])
@login_required
@permission_required('manage_payments')
def archive_payment(id):
    """أرشفة سند صرف"""
    from models import Payment
    from services.archive_service import ArchiveService

    payment = get_owned_or_404(Payment, id)

    try:
        archive_service = ArchiveService()

        # 1. Archive the record (No commit yet)
        archive_service.archive_record('payments', payment, reason='تم أرشفة سند الصرف', commit=False)
        create_audit_log('archive', 'payments', payment.id)

        # 2. Reverse GL Entry (Must succeed)
        from models import GLJournalEntry
        gl_entries = GLJournalEntry.query.filter_by(
            reference_type='Payment',
            reference_id=id,
            is_reversed=False
        ).all()
        for entry in gl_entries:
            entry.reverse_entry(
                description=f'Reverse Payment {payment.payment_number}'
            )

        # 3. Commit all
        db.session.commit()

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to archive payment {id}: {e}')
        current_app.logger.exception('handler failed')
        flash(f'فشلت الأرشفة: حدث خطأ غير متوقع', 'danger')
        return redirect(url_for('payments.receipts'))

    return redirect(url_for('payments.receipts'))


@payments_bp.route('/payments/<int:id>/restore', methods=['POST'])
@login_required
@permission_required('manage_payments')
def restore_payment(id):
    """استعادة سند صرف من الأرشيف"""
    from models import ArchivedRecord
    from models import Payment

    # SECURITY: verify underlying payment belongs to actor's tenant
    get_owned_or_404(Payment, id, code=404)

    archived = ArchivedRecord.query.filter_by(
        table_name='payments',
        record_id=id
    ).first_or_404()

    try:
        db.session.delete(archived)
        db.session.commit()
        create_audit_log('restore', 'payments', id)
    except Exception:
        db.session.rollback()

    return redirect(url_for('payments.archived_receipts'))


@payments_bp.route('/create_from_sale/<int:sale_id>', methods=['GET', 'POST'])
@login_required
@permission_required('manage_payments')
def create_from_sale(sale_id):
    """إنشاء سند دفع من فاتورة بيع معينة"""
    from models import Sale

    sale = get_owned_or_404(Sale, sale_id)

    if request.method == 'POST':
        try:
            try:
                _base_curr = CurrencyService.get_base_currency()
            except Exception:
                _base_curr = 'ILS'
            amount = request.form.get('amount', type=float)
            currency = request.form.get('currency') or _base_curr
            user_exchange_rate = request.form.get('exchange_rate', type=float)
            payment_method_value = (request.form.get('payment_method') or '').strip()

            # F7: سعر الصرف — لا يُقبل سعر الفاتورة إذا اختلفت عملة السند
            # (الحقل readonly في النموذج يحمل سعر الفاتورة دائماً).
            user_exchange_rate, rate_corrected = _resolve_document_rate(
                currency, user_exchange_rate, sale.currency, sale.exchange_rate)
            if rate_corrected:
                flash('تم اعتماد سعر صرف السوق لأن عملة السند تختلف عن عملة الفاتورة.', 'warning')

            if not payment_method_value:
                flash('يرجى اختيار طريقة الدفع.', 'warning')
                exchange_rates = CurrencyService.get_all_rates(_base_curr)
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
            current_app.logger.exception('handler failed')
            flash(f'حدث خطأ: حدث خطأ غير متوقع\nتحقق من البيانات المدخلة وحاول مرة أخرى.', 'danger')

    # استخدام القالب الموحد مع بيانات إضافية
    customers = [sale.customer]  # العميل من الفاتورة
    suggested_amount = sale.balance_due
    try:
        _base_curr_get = CurrencyService.get_base_currency()
    except Exception:
        _base_curr_get = 'ILS'
    exchange_rates = CurrencyService.get_all_rates(_base_curr_get)

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
                           customers=customers_data,
                           suppliers=suppliers_data,
                           today_date=datetime.now().date().isoformat())


@payments_bp.route('/voucher/submit', methods=['POST'])
@login_required
@permission_required('manage_payments')
def create_voucher_submit():  # noqa: C901
    """معالجة حفظ السند المالي الموحد"""
    try:
        try:
            _base_curr_v = CurrencyService.get_base_currency()
        except Exception:
            _base_curr_v = 'ILS'
        direction = request.form.get('direction')  # incoming, outgoing
        party_type = request.form.get('party_type')  # customer, supplier
        party_id = request.form.get('party_id', type=int)
        amount = request.form.get('amount', type=float)
        payment_method = request.form.get('payment_method')
        date_str = request.form.get('date')
        notes = request.form.get('notes')

        # العملة وسعر الصرف (افتراضي: عملة الأساس بمعدل 1)
        currency = request.form.get('currency') or _base_curr_v
        user_exchange_rate = request.form.get('exchange_rate', type=float, default=1.0)

        # بيانات الشيك
        cheque_number = request.form.get('cheque_number')
        cheque_date = request.form.get('cheque_date')
        bank_name = request.form.get('bank_name')

        cheque_due = None
        if cheque_date:
            try:
                cheque_due = datetime.strptime(cheque_date, '%Y-%m-%d').date()
            except (ValueError, TypeError):
                cheque_due = None

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

                exchange_rate = CurrencyService.get_exchange_rate(currency, _base_curr_v, user_rate=user_exchange_rate)
                amount_decimal = Decimal(str(amount))
                amount_base = amount_decimal * exchange_rate

                supplier = get_owned_or_404(Supplier, party_id)
                payment = Payment(
                    payment_number=generate_number('PAY', Payment, 'payment_number'),  # ربما نحتاج تسلسل منفصل؟
                    payment_type='refund',  # استرداد
                    direction='incoming',
                    supplier_id=supplier.id,
                    supplier_name=supplier.name,
                    amount=amount_decimal,
                    currency=currency,
                    exchange_rate=exchange_rate,
                    amount_base=amount_base,
                    payment_method=payment_method,
                    notes=notes,
                    cheque_number=cheque_number if payment_method == 'cheque' else None,
                    cheque_date=cheque_due if payment_method == 'cheque' else None,
                    bank_name=bank_name if payment_method == 'cheque' else None,
                    user_id=current_user.id
                )
                db.session.add(payment)
                db.session.flush()

                try:
                    from services.gl_service import GLService
                    GLService.ensure_core_accounts()
                    if payment_method == 'cash':
                        debit_account = '1110'
                    elif payment_method in ('bank_transfer', 'card'):
                        debit_account = '1120'
                    else:
                        debit_account = '1110'
                    lines = [
                        {'account': debit_account, 'debit': amount_decimal, 'description': f'استرداد من المورد {supplier.name}'},
                        {'account': '2110', 'credit': amount_decimal, 'description': f'سند قبض من مورد {payment.payment_number}'}
                    ]
                    GLService.post_entry(
                        lines,
                        description=f'Supplier Refund {payment.payment_number}',
                        reference_type='Payment',
                        reference_id=payment.id,
                        currency=currency,
                        exchange_rate=exchange_rate
                    )
                except Exception as e:
                    current_app.logger.warning(f'GL posting failed for supplier refund: {e}')

                db.session.commit()
                flash('تم إنشاء سند قبض من مورد بنجاح', 'success')
                return redirect(url_for('payments.receipts'))

        # 2. معالجة سند الصرف (Payment) - صادر
        elif direction == 'outgoing':
            from models import Payment
            from utils.helpers import generate_number

            exchange_rate = CurrencyService.get_exchange_rate(currency, _base_curr_v, user_rate=user_exchange_rate)
            amount_decimal = Decimal(str(amount))
            amount_base = amount_decimal * exchange_rate

            if party_type == 'supplier':
                # دفع لمورد (المنطق المعتاد)
                supplier = get_owned_or_404(Supplier, party_id)
                payment = Payment(
                    payment_number=generate_number('PAY', Payment, 'payment_number'),
                    payment_type='bill_payment',
                    direction='outgoing',
                    supplier_id=supplier.id,
                    supplier_name=supplier.name,
                    amount=amount_decimal,
                    currency=currency,
                    exchange_rate=exchange_rate,
                    amount_base=amount_base,
                    payment_method=payment_method,
                    notes=notes,
                    cheque_number=cheque_number if payment_method == 'cheque' else None,
                    cheque_date=cheque_due if payment_method == 'cheque' else None,
                    bank_name=bank_name if payment_method == 'cheque' else None,
                    user_id=current_user.id
                )
                db.session.add(payment)
                db.session.flush()  # Flush to get ID

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
                        amount_base=payment.amount_base,
                        issue_date=datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else datetime.now().date(),
                        due_date=cheque_due or datetime.now().date(),
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
                        credit_account = '1110'  # Cash
                        if payment_method == 'bank_transfer' or payment_method == 'card':
                            credit_account = '1120'  # Bank

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
                customer = get_owned_or_404(Customer, party_id)
                payment = Payment(
                    payment_number=generate_number('PAY', Payment, 'payment_number'),
                    payment_type='refund',
                    direction='outgoing',
                    customer_id=customer.id,
                    amount=amount_decimal,
                    currency=currency,
                    exchange_rate=exchange_rate,
                    amount_base=amount_base,
                    payment_method=payment_method,
                    notes=notes,
                    cheque_number=cheque_number if payment_method == 'cheque' else None,
                    cheque_date=cheque_due if payment_method == 'cheque' else None,
                    bank_name=bank_name if payment_method == 'cheque' else None,
                    user_id=current_user.id
                )
                db.session.add(payment)
                db.session.flush()  # Flush to get ID

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
                        amount_base=payment.amount_base,
                        issue_date=datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else datetime.now().date(),
                        due_date=cheque_due or datetime.now().date(),
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
        current_app.logger.exception('handler failed')
        flash(f'حدث خطأ أثناء حفظ السند: حدث خطأ غير متوقع', 'danger')
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
    receipt = get_owned_or_404(Receipt, id)

    if current_user.is_seller() and not current_user.is_owner and receipt.user_id != current_user.id:
        flash('ليس لديك صلاحية لعرض هذا السند', 'danger')
        return redirect(url_for('payments.receipts'))

    return render_template('payments/view_receipt.html', receipt=receipt)


@payments_bp.route('/receipts/<int:id>/print')
@login_required
@permission_required('manage_payments')
def print_receipt(id):
    receipt = get_owned_or_404(Receipt, id)

    if current_user.is_seller() and not current_user.is_owner and receipt.user_id != current_user.id:
        flash('ليس لديك صلاحية لطباعة هذا السند', 'danger')
        return redirect(url_for('payments.receipts'))

    # Get invoice settings
    settings = InvoiceSettings.get_active()

    # Template selection via URL param (?template=modern) or settings
    import re
    _ALLOWED_TEMPLATES = ('modern', 'classic', 'gulf', 'minimal', 'simple')
    template = request.args.get('template') or (settings.active_template if settings and settings.active_template else 'modern')
    if template not in _ALLOWED_TEMPLATES and not re.fullmatch(r'[A-Za-z0-9_-]+', template or ''):
        template = 'modern'
    if template not in _ALLOWED_TEMPLATES:
        template = 'modern'

    template_labels = {
        'modern': 'مودرن',
        'classic': 'كلاسيك',
        'gulf': 'خليجي',
        'minimal': 'بسيط',
        'simple': 'مبسط'
    }
    available_templates = [(k, v) for k, v in template_labels.items() if k in _ALLOWED_TEMPLATES]

    from flask import current_app
    company = {
        'name_ar': current_app.config.get('COMPANY_NAME_AR'),
        'address': current_app.config.get('COMPANY_ADDRESS'),
        'phone': current_app.config.get('COMPANY_PHONE'),
    }

    try:
        return render_template(
            f'receipts/{template}.html',
            receipt=receipt,
            settings=settings,
            company=company,
            printed_at=datetime.now(),
            available_templates=available_templates,
            current_template=template,
            document_type='receipt',
            document_id=receipt.id
        )
    except Exception:
        return render_template(
            'receipts/modern.html',
            receipt=receipt,
            settings=settings,
            company=company,
            printed_at=datetime.now(),
            available_templates=available_templates,
            current_template='modern',
            document_type='receipt',
            document_id=receipt.id
        )


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
            'date': datetime.fromisoformat(data.get('receipt_date').replace('Z', '+00:00')) if isinstance(data.get('receipt_date'), str) else data.get('receipt_date'),  # noqa: E501
            'amount': float(data.get('amount', 0)),
            'currency': data.get('currency'),
            'amount_base': float(data.get('amount_base', 0)),
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
            'date': datetime.fromisoformat(data.get('payment_date').replace('Z', '+00:00')) if isinstance(data.get('payment_date'), str) else data.get('payment_date'),  # noqa: E501
            'amount': float(data.get('amount', 0)),
            'currency': data.get('currency'),
            'amount_base': float(data.get('amount_base', 0)),
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

    receipt = get_owned_or_404(Receipt, id)

    try:
        archive_service = ArchiveService()
        archive_service.archive_record('receipts', receipt, reason='تم أرشفة سند القبض')
        create_audit_log('archive', 'receipts', receipt.id)
    except Exception:
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
    except Exception:
        db.session.rollback()

    return redirect(url_for('payments.archived_receipts'))


@payments_bp.route('/receipts/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('manage_payments')
def delete_receipt(id):  # noqa: C901
    """حذف أو أرشفة سند قبض"""
    from models import Receipt
    from services.archive_service import ArchiveService

    receipt = get_owned_or_404(Receipt, id)
    from models import Cheque
    linked_cheques = Cheque.query.filter_by(receipt_id=receipt.id).all()

    # التحقق من الارتباطات
    has_links = False
    if receipt.source_type == 'sale' and receipt.source_id:
        has_links = True
    if receipt.sale_id or receipt.purchase_id or receipt.get_allocations():
        has_links = True
    if receipt.cheque_id:
        has_links = True
    if linked_cheques:  # التحقق من الشيكات المرتبطة
        has_links = True

    try:
        # 1. عكس التخصيصات — كل تخصيص على فاتورته (F5)
        # كان يُعكس المبلغ الكلي على أول فاتورة فقط (source_id) —
        # فتُخصم الفاتورة الأولى مرتين وتبقى البقية مُسدَّدة بلا سند.
        # الآن يُعكس كل تخصيص على فاتورته (Receipt.allocations_json).
        _reverse_receipt_allocations(receipt)

        # 2. القرار: أرشفة أو حذف
        if has_links:
            # عكس القيد المحاسبي إجباري (F2): فشله يُعلن ولا تُؤرشف السند.
            try:
                reverse_or_purge_gl_entries(
                    'Receipt',
                    receipt.id,
                    description=f'عكس سند قبض {receipt.receipt_number}',
                )
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(
                    f'Failed to reverse GL entries for receipt {receipt.id}: {e}')
                flash(
                    f'❌ تعذّر عكس القيود المحاسبية لسند القبض '
                    f'"{receipt.receipt_number}" — لم تُؤرشف السند.\n💡 {e}',
                    'danger')
                return redirect(url_for('payments.view_receipt', id=id))

            # أرشفة (Soft Delete)
            archive_service = ArchiveService()
            archive_service.archive_record('receipts', receipt, reason='تم أرشفة السند لوجود ارتباطات', commit=False)

            # أرشفة الشيكات المرتبطة
            for cheque in linked_cheques:
                archive_service.archive_record('cheques', cheque, reason='تم أرشفة الشيك لارتباطه بسند مؤرشف', commit=False)

            # F1: رصيد العميل من مصدره الواحد (لا زيادة يدوية بالمبلغ الكلي)
            if receipt.customer_id:
                from models.customer import recompute_customer_balance
                recompute_customer_balance(receipt.customer_id)

            create_audit_log('archive', 'receipts', id)
            db.session.commit()
            flash(f'تم أرشفة سند القبض "{receipt.receipt_number}" (لوجود حركات مرتبطة)', 'warning')
        else:
            # حذف نهائي: القيود المرحَّلة تُعكس (لا تُحذف أبداً) والمسودات
            # فقط تُحذف — لكل من السند وشيكاته المرتبطة.
            try:
                gl_result = reverse_or_purge_gl_entries(
                    'Receipt',
                    receipt.id,
                    description=f'عكس سند قبض {receipt.receipt_number} (حذف نهائي)',
                )
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(
                    f'Failed to reverse GL entries for receipt {receipt.id}: {e}')
                flash(
                    f'❌ تعذّر عكس القيود المحاسبية لسند القبض '
                    f'"{receipt.receipt_number}" — لم يُحذف السند.\n💡 {e}',
                    'danger')
                return redirect(url_for('payments.view_receipt', id=id))
            for ch in linked_cheques:
                ch.gl_journal_entry_id = None
                ch.gl_clearing_entry_id = None
                ch.gl_bounce_entry_id = None
                db.session.flush()
                for ref in ('cheque_receive', 'cheque_issue', 'cheque_cancel',
                            'cheque_clear', 'cheque_bounce', 'Cheque'):
                    reverse_or_purge_gl_entries(
                        ref,
                        ch.id,
                        description=f'عكس قيد شيك {ch.cheque_bank_number} (حذف سند)',
                    )

            # حذف الشيكات المرتبطة ثم السند
            for cheque in linked_cheques:
                db.session.delete(cheque)

            db.session.delete(receipt)

            # F1: رصيد العميل من مصدره الواحد (لا زيادة يدوية بالمبلغ الكلي)
            if receipt.customer_id:
                from models.customer import recompute_customer_balance
                recompute_customer_balance(receipt.customer_id)

            create_audit_log('delete', 'receipts', id)
            db.session.commit()
            if gl_result['reversed']:
                flash(
                    f'تم حذف سند القبض "{receipt.receipt_number}" نهائياً — '
                    f'وعُكست قيوده المحاسبية ({gl_result["reversed"]} قيد) '
                    f'بدل حذفها حفاظاً على الأثر المحاسبي.',
                    'success')
            else:
                flash(f'تم حذف سند القبض "{receipt.receipt_number}" نهائياً', 'success')

        return redirect(url_for('payments.receipts'))

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('handler failed')
        flash(f'فشل الحذف: حدث خطأ غير متوقع', 'danger')
        return redirect(url_for('payments.view_receipt', id=id))


@payments_bp.route('/payments/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('manage_payments')
def delete_payment(id):
    """حذف أو أرشفة سند صرف"""
    from models import Payment
    from services.archive_service import ArchiveService

    payment = get_owned_or_404(Payment, id)
    from models import Cheque as _Cheque
    linked_cheques = _Cheque.query.filter_by(payment_id=payment.id).all()

    # التحقق من الارتباطات
    has_links = False
    if payment.cheque_id:
        has_links = True
    if linked_cheques:  # التحقق من الشيكات المرتبطة
        has_links = True
    # يمكن إضافة شروط أخرى للارتباط هنا

    try:
        # 1. F5: عكس تخصيص السند على فاتورته (قبل أي حذف/أرشفة)
        _reverse_payment_allocation(payment)

        # 2. القرار: أرشفة أو حذف
        if has_links:
            # عكس القيد المحاسبي إجباري (F2): فشله يُعلن ولا تُؤرشف السند.
            try:
                reverse_or_purge_gl_entries(
                    'Payment',
                    payment.id,
                    description=f'عكس سند صرف {payment.payment_number}',
                )
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(
                    f'Failed to reverse GL entries for payment {payment.id}: {e}')
                flash(
                    f'❌ تعذّر عكس القيود المحاسبية لسند الصرف '
                    f'"{payment.payment_number}" — لم تُؤرشف السند.\n💡 {e}',
                    'danger')
                return redirect(url_for('payments.view_payment', id=id))

            # أرشفة
            archive_service = ArchiveService()
            archive_service.archive_record('payments', payment, reason='تم أرشفة السند لوجود ارتباطات', commit=False)

            # أرشفة الشيكات المرتبطة
            for cheque in linked_cheques:
                archive_service.archive_record('cheques', cheque, reason='تم أرشفة الشيك لارتباطه بسند مؤرشف', commit=False)

            # F1: رصيد العميل من مصدره الواحد بعد عكس تخصيص الفاتورة
            if payment.customer_id:
                from models.customer import recompute_customer_balance
                recompute_customer_balance(payment.customer_id)

            create_audit_log('archive', 'payments', id)
            db.session.commit()
            flash(f'تم أرشفة سند الصرف "{payment.payment_number}" (لوجود حركات مرتبطة)', 'warning')
        else:
            # حذف القيود المرتبطة: القيود المرحَّلة تُعكس (لا تُحذف أبداً)
            # والمسودات فقط تُحذف.
            try:
                gl_result = reverse_or_purge_gl_entries(
                    'Payment',
                    payment.id,
                    description=f'عكس سند صرف {payment.payment_number} (حذف نهائي)',
                )
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(
                    f'Failed to reverse GL entries for payment {payment.id}: {e}')
                flash(
                    f'❌ تعذّر عكس القيود المحاسبية لسند الصرف '
                    f'"{payment.payment_number}" — لم يُحذف السند.\n💡 {e}',
                    'danger')
                return redirect(url_for('payments.view_payment', id=id))
            for ch in linked_cheques:
                ch.gl_journal_entry_id = None
                ch.gl_clearing_entry_id = None
                ch.gl_bounce_entry_id = None
                db.session.flush()
                for ref in ('cheque_receive', 'cheque_issue', 'cheque_cancel',
                            'cheque_clear', 'cheque_bounce'):
                    reverse_or_purge_gl_entries(
                        ref,
                        ch.id,
                        description=f'عكس قيد شيك {ch.cheque_bank_number} (حذف سند)',
                    )

            # حذف الشيكات المرتبطة ثم السند
            for cheque in linked_cheques:
                db.session.delete(cheque)

            db.session.delete(payment)

            # F1: رصيد العميل من مصدره الواحد بعد عكس تخصيص الفاتورة
            if payment.customer_id:
                from models.customer import recompute_customer_balance
                recompute_customer_balance(payment.customer_id)

            create_audit_log('delete', 'payments', id)
            db.session.commit()
            if gl_result['reversed']:
                flash(
                    f'تم حذف سند الصرف "{payment.payment_number}" نهائياً — '
                    f'وعُكست قيوده المحاسبية ({gl_result["reversed"]} قيد) '
                    f'بدل حذفها حفاظاً على الأثر المحاسبي.',
                    'success')
            else:
                flash(f'تم حذف سند الصرف "{payment.payment_number}" نهائياً', 'success')

        return redirect(url_for('payments.receipts'))

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('handler failed')
        flash(f'فشل الحذف: حدث خطأ غير متوقع', 'danger')
        return redirect(url_for('payments.view_payment', id=id))


@payments_bp.route('/create_payment/<int:purchase_id>', methods=['GET', 'POST'])
@login_required
@permission_required('manage_payments')
def create_payment(purchase_id):  # noqa: C901
    """إنشاء سند صرف لفاتورة مشتريات"""
    from models import Purchase, Payment, Supplier
    from utils.helpers import generate_number
    from sqlalchemy import func

    purchase = get_owned_or_404(Purchase, purchase_id)
    supplier = get_owned_or_404(Supplier, purchase.supplier_id) if purchase.supplier_id else None

    # F13: per-invoice balance from this purchase's own tracked paid
    # amount — paid_amount is tracked in BASE currency, so the comparison
    # must be base-vs-base (amount_base − paid_amount).
    paid_amount = purchase.get_paid_amount()

    # حساب المبلغ المتبقي (بالعملة الأساسية)
    balance = float(purchase.amount_base or 0) - float(paid_amount)
    suggested_amount = balance if balance > 0 else 0

    if request.method == 'POST':
        try:
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
            try:
                _base_curr_pay = CurrencyService.get_base_currency()
            except Exception:
                _base_curr_pay = 'ILS'
            currency = request.form.get('currency') or _base_curr_pay

            # F7: لا يُقبل سعر صرف فاتورة الشراء إذا اختلفت عملة السند
            exchange_rate, rate_corrected = _resolve_document_rate(
                currency, exchange_rate, purchase.currency, purchase.exchange_rate)
            if rate_corrected:
                flash('تم اعتماد سعر صرف السوق لأن عملة السند تختلف عن عملة فاتورة الشراء.', 'warning')

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
            amount_base = amount_decimal * exchange_rate_decimal

            # إنشاء سند الصرف
            payment_number = generate_number('PAY', Payment, 'payment_number')
            payment = Payment(
                payment_number=payment_number,
                supplier_id=purchase.supplier_id,
                supplier_name=purchase.supplier_name,
                # F3: ربط السند بفاتورة الشراء — بدونه لا تُكتب
                # Purchase.paid_amount / payment_status أبداً فتبقى كل
                # فاتورة "غير مسددة" في أعمار الذمم الدائنة للأبد.
                purchase_id=purchase.id,
                amount=amount_decimal,
                currency=currency,
                exchange_rate=exchange_rate_decimal,
                amount_base=amount_base,
                payment_method=payment_method_value,
                notes=notes,
                user_id=current_user.id,
                direction='outgoing',
                payment_type='supplier_payment',
                # شيك تحت التحصيل لا يُسوّي الفاتورة قبل صرفه (F8)
                payment_confirmed=(payment_method_value != 'cheque'),
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
                    amount_base=amount_base,
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
                    {'account': '2110', 'debit': payment.amount, 'description': f'سداد للمورد {payment.supplier_name}'},
                    {'account': cash_or_bank, 'credit': payment.amount, 'description': f'سند صرف {payment.payment_number}'}
                ]
                GLService.post_entry(
                    lines,
                    description=f'Payment {payment.payment_number}',
                    reference_type='Payment',
                    reference_id=payment.id,
                    currency=payment.currency,
                    exchange_rate=payment.exchange_rate
                )
            except Exception:
                pass

            db.session.commit()

            flash('تم إنشاء سند الصرف بنجاح', 'success')
            return redirect(url_for('purchases.view', id=purchase_id))

        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('handler failed')
            flash(f'حدث خطأ: حدث خطأ غير متوقع', 'danger')

    # استخدام نفس القالب الموحد لسندات القبض/الصرف
    return render_template('payments/create_receipt.html',
                           purchase=purchase,
                           supplier=supplier,
                           suggested_amount=suggested_amount,
                           is_payment=True)  # علامة لتمييز سند الصرف


@payments_bp.route('/api/customer-balance/<int:customer_id>')
@login_required
@permission_required('manage_payments')
def api_customer_balance(customer_id):
    # SECURITY: cross-tenant check on the customer before exposing
    # financial state.  get_owned_or_404 403s on cross-tenant, 404s
    # on missing — both leak no information.
    customer = get_owned_or_404(Customer, customer_id, code=404)

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
