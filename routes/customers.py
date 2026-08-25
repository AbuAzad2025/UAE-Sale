from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required
from extensions import db, limiter
from models import Customer, Sale
from utils.decorators import permission_required
from utils.helpers import create_audit_log
from services.payment_service import PaymentService
from decimal import Decimal
from datetime import datetime

customers_bp = Blueprint('customers', __name__, url_prefix='/customers')


@customers_bp.route('/')
@login_required
@permission_required('manage_customers')
def index():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    search = request.args.get('search', '', type=str)
    customer_type = request.args.get('type', '', type=str)

    query = Customer.query

    if search:
        search_filter = f'%{search}%'
        query = query.filter(
            db.or_(
                Customer.name.ilike(search_filter),
                Customer.phone.ilike(search_filter),
                Customer.email.ilike(search_filter)
            )
        )

    if customer_type:
        query = query.filter_by(customer_type=customer_type)

    query = query.filter_by(is_active=True)

    pagination = query.order_by(Customer.name).paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )

    return render_template('customers/index.html',
                           customers=pagination.items,
                           pagination=pagination)


@customers_bp.route('/create', methods=['GET', 'POST'])
@login_required
@permission_required('manage_customers')
@limiter.limit("10 per minute", methods=['POST'])
def create():
    from forms.customer import CustomerForm
    form = CustomerForm()

    if form.validate_on_submit():
        try:
            customer = Customer(
                name=form.name.data,
                name_ar=form.name_ar.data,
                customer_type=form.customer_type.data,
                phone=form.phone.data,
                email=form.email.data,
                address=form.address.data,
                tax_number=form.tax_number.data,
                preferred_currency=form.preferred_currency.data,
                notes=form.notes.data
            )

            db.session.add(customer)
            db.session.commit()

            create_audit_log('create', 'customers', customer.id)

            flash('✅ تم إضافة الزبون بنجاح!', 'success')
            return redirect(url_for('customers.index'))

        except Exception as e:
            db.session.rollback()
            from utils.error_messages import ErrorMessages
            flash(ErrorMessages.database_error(str(e)), 'danger')

    return render_template('customers/create.html', form=form)


@customers_bp.route('/<int:id>')
@login_required
@permission_required('manage_customers')
def view(id):
    customer = db.get_or_404(Customer, id)

    sales = Sale.query.filter_by(customer_id=id).order_by(Sale.sale_date.desc()).limit(20).all()

    balance = PaymentService.get_customer_balance_aed(customer)

    unpaid_sales = PaymentService.get_unpaid_sales(customer)

    return render_template('customers/view.html',
                           customer=customer,
                           sales=sales,
                           balance=balance,
                           unpaid_sales=unpaid_sales)


@customers_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('manage_customers')
def edit(id):
    customer = db.get_or_404(Customer, id)

    if request.method == 'POST':
        try:
            customer.name = request.form.get('name')
            customer.name_ar = request.form.get('name_ar')
            customer.customer_type = request.form.get('customer_type')
            customer.phone = request.form.get('phone')
            customer.email = request.form.get('email')
            customer.address = request.form.get('address')
            customer.tax_number = request.form.get('tax_number')
            customer.preferred_currency = request.form.get('preferred_currency')
            customer.notes = request.form.get('notes')

            db.session.commit()

            create_audit_log('update', 'customers', customer.id)

            flash('✅ تم تحديث بيانات الزبون بنجاح!', 'success')
            return redirect(url_for('customers.view', id=customer.id))

        except Exception as e:
            db.session.rollback()
            from utils.error_messages import ErrorMessages
            flash(ErrorMessages.database_error(str(e)), 'danger')

    return render_template('customers/edit.html', customer=customer)


@customers_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('manage_customers')
def delete(id):
    customer = db.get_or_404(Customer, id)

    try:
        # Check for related records preventing deletion
        sales_count = Sale.query.filter_by(customer_id=id).count()
        from models import Payment, Receipt
        payments_count = Payment.query.filter_by(customer_id=id).count()
        receipts_count = Receipt.query.filter_by(customer_id=id).count()

        if sales_count > 0 or payments_count > 0 or receipts_count > 0:
            customer.is_active = False
            db.session.commit()
            flash(f'⚠️ تم إلغاء تفعيل العميل "{customer.name}" بدلاً من حذفه لوجود ({sales_count} فاتورة، {payments_count} دفعة، {receipts_count} سند قبض) مرتبطة به.', 'warning')  # noqa: E501
        else:
            db.session.delete(customer)
            db.session.commit()
            flash(f'✅ تم حذف العميل "{customer.name}" نهائياً!', 'success')

        create_audit_log('delete', 'customers', id)

    except Exception as e:
        db.session.rollback()
        # Fallback to soft delete if hard delete fails (e.g. other constraints)
        try:
            # Re-fetch customer to ensure it's attached to the new session transaction
            customer = db.session.get(Customer, id)
            if customer:
                customer.is_active = False
                db.session.add(customer)
                db.session.commit()
                flash(f'⚠️ تعذر الحذف النهائي للعميل "{customer.name}" بسبب ارتباطات في قاعدة البيانات. تم إلغاء تفعيله بدلاً من ذلك.', 'warning')
        except Exception:
            flash(f'❌ حدث خطأ أثناء حذف العميل: {str(e)}', 'danger')
            current_app.logger.error(f"Error deleting customer {id}: {e}")

    return redirect(url_for('customers.index'))


@customers_bp.route('/<int:id>/statement')
@login_required
@permission_required('manage_customers')
def statement(id):
    customer = db.get_or_404(Customer, id)

    date_from = request.args.get('date_from', type=str)
    date_to = request.args.get('date_to', type=str)
    transaction_type = request.args.get('transaction_type', 'all')

    from sqlalchemy import func
    from models import Payment

    sales_query = Sale.query.filter_by(customer_id=id, status='confirmed')
    payments_query = Payment.query.filter_by(customer_id=id)

    if date_from:
        sales_query = sales_query.filter(func.date(Sale.sale_date) >= date_from)
        payments_query = payments_query.filter(func.date(Payment.payment_date) >= date_from)

    if date_to:
        sales_query = sales_query.filter(func.date(Sale.sale_date) <= date_to)
        payments_query = payments_query.filter(func.date(Payment.payment_date) <= date_to)

    sales = sales_query.order_by(Sale.sale_date).all()
    payments = payments_query.order_by(Payment.payment_date).all()

    transactions = []

    for sale in sales:
        sale_lines_data = []
        for idx, line in enumerate(sale.lines, start=1):
            quantity = Decimal(str(line.quantity or 0))
            unit_price = Decimal(str(line.unit_price or 0))
            discount_percent = Decimal(str(line.discount_percent or 0))
            gross_amount = (quantity * unit_price)
            discount_value = (gross_amount * discount_percent / Decimal('100')) if discount_percent else Decimal('0')
            sale_lines_data.append({
                'index': idx,
                'product_name': line.product.get_display_name('ar') if line.product else 'بند غير معرف',
                'product_sku': line.product.sku if line.product and line.product.sku else None,
                'unit': line.product.unit if line.product and hasattr(line.product, 'unit') else None,
                'quantity': float(quantity),
                'unit_price': float(unit_price),
                'discount_percent': float(discount_percent),
                'discount_value': float(discount_value),
                'gross_amount': float(gross_amount),
                'line_total': float(line.line_total or 0),
                'notes': line.notes or ''
            })

        sale_payments = sale.payments.order_by(Payment.payment_date.asc()).all()
        sale_payments_data = []
        last_payment_date = None

        for payment in sale_payments:
            if last_payment_date is None or payment.payment_date > last_payment_date:
                last_payment_date = payment.payment_date

            cheque = payment.cheque if hasattr(payment, 'cheque') else None
            sale_payments_data.append({
                'id': payment.id,
                'payment_number': payment.payment_number,
                'payment_date': payment.payment_date,
                'amount_base': float(payment.amount_base or 0),
                'amount_original': float(payment.amount or 0),
                'currency': payment.currency or 'AED',
                'exchange_rate': float(payment.exchange_rate or 1),
                'reference_number': payment.reference_number or '-',
                'payment_method': payment.payment_method,
                'payment_method_display': payment.get_method_display('ar') if hasattr(payment, 'get_method_display') else payment.payment_method,
                'status_ar': payment.status_ar if hasattr(payment, 'status_ar') else ('مؤكدة ✅' if payment.payment_confirmed else 'معلقة ⏳'),
                'payment_confirmed': payment.payment_confirmed,
                'user': payment.user.get_display_name('ar') if payment.user and hasattr(payment.user, 'get_display_name') else (payment.user.full_name if payment.user else None),  # noqa: E501
                'notes': payment.notes or '',
                'direction': payment.direction,
                'cheque_number': cheque.cheque_number if cheque else payment.cheque_number,
                'cheque_bank': cheque.bank_name if cheque else payment.bank_name,
                'cheque_due_date': cheque.due_date if cheque else None
            })

        sale_data = {
            'id': sale.id,
            'number': sale.sale_number,
            'date': sale.sale_date,
            'status': sale.payment_status,
            'subtotal': float(sale.subtotal or 0),
            'discount_amount': float(sale.discount_amount or 0),
            'shipping_cost': float(sale.shipping_cost or 0),
            'tax_rate': float(sale.tax_rate or 0),
            'tax_amount': float(sale.tax_amount or 0),
            'total_amount': float(sale.total_amount or sale.amount_base or 0),
            'amount_base': float(sale.amount_base or 0),
            'paid_amount': float(sale.paid_amount_base or 0),
            'balance_due': float(sale.balance_due or 0),
            'currency': sale.currency or 'AED',
            'exchange_rate': float(sale.exchange_rate or 1),
            'seller': sale.seller.get_display_name('ar') if sale.seller and hasattr(sale.seller, 'get_display_name') else (sale.seller.full_name if sale.seller else None),  # noqa: E501
            'notes': sale.notes or '',
            'lines': sale_lines_data,
            'payments': sale_payments_data,
            'last_payment_date': last_payment_date
        }

        transactions.append({
            'date': sale.sale_date,
            'type': 'sale',
            'reference': sale.sale_number,
            'debit': float(sale.amount_base or 0),
            'credit': 0,
            'balance': 0,
            'description': 'فاتورة بيع',
            'currency': sale.currency or 'AED',
            'exchange_rate': float(sale.exchange_rate or 1),
            'paid_amount': float(sale.paid_amount_base or 0),
            'balance_due': float(sale.balance_due or 0),
            'status': sale.payment_status,
            'sale': sale_data
        })

    for payment in payments:
        credit_amount = float(payment.amount_base or 0) if payment.direction == 'incoming' else 0.0
        debit_amount = float(payment.amount_base or 0) if payment.direction != 'incoming' else 0.0

        cheque = payment.cheque if hasattr(payment, 'cheque') else None

        transactions.append({
            'date': payment.payment_date,
            'type': 'payment',
            'reference': payment.reference_number or payment.payment_number or f'دفع #{payment.id}',
            'debit': debit_amount,
            'credit': credit_amount,
            'balance': 0,
            'description': f'دفعة - {payment.get_method_display("ar") if hasattr(payment, "get_method_display") else payment.payment_method}',
            'currency': payment.currency or 'AED',
            'exchange_rate': float(payment.exchange_rate or 1),
            'paid_amount': credit_amount,
            'balance_due': 0,
            'status': payment.status_ar if hasattr(payment, 'status_ar') else ('مؤكدة ✅' if payment.payment_confirmed else 'معلقة ⏳'),
            'payment': {
                'id': payment.id,
                'payment_number': payment.payment_number,
                'payment_date': payment.payment_date,
                'amount_base': float(payment.amount_base or 0),
                'amount_original': float(payment.amount or 0),
                'currency': payment.currency or 'AED',
                'exchange_rate': float(payment.exchange_rate or 1),
                'payment_method': payment.payment_method,
                'payment_method_display': payment.get_method_display('ar') if hasattr(payment, 'get_method_display') else payment.payment_method,
                'reference_number': payment.reference_number or '-',
                'direction': payment.direction,
                'payment_confirmed': payment.payment_confirmed,
                'status_ar': payment.status_ar if hasattr(payment, 'status_ar') else ('مؤكدة ✅' if payment.payment_confirmed else 'معلقة ⏳'),
                'user': payment.user.get_display_name('ar') if payment.user and hasattr(payment.user, 'get_display_name') else (payment.user.full_name if payment.user else None),  # noqa: E501
                'notes': payment.notes or '',
                'cheque_number': cheque.cheque_number if cheque else payment.cheque_number,
                'cheque_bank': cheque.bank_name if cheque else payment.bank_name,
                'cheque_due_date': cheque.due_date if cheque else payment.cheque_date,
                'cheque_clearance_date': cheque.clearance_date if cheque else None
            }
        })

    transactions.sort(key=lambda x: (x['date'] or datetime.min))

    if transaction_type in {'sale', 'payment'}:
        transactions = [trans for trans in transactions if trans['type'] == transaction_type]

    running_balance = 0
    for trans in transactions:
        running_balance += trans['debit'] - trans['credit']
        trans['balance'] = running_balance

    return render_template(
        'customers/statement.html',
        customer=customer,
        transactions=transactions,
        final_balance=running_balance,
        filters={
            'date_from': date_from or '',
            'date_to': date_to or '',
            'transaction_type': transaction_type
        }
    )


@customers_bp.route('/api/search')
@login_required
def api_search():
    query = request.args.get('q', '')
    _ = request.args.get('page', 1, type=int)
    per_page = 20

    # السماح بالبحث حتى بدون query (لعرض كل العملاء)
    if query and len(query) >= 1:
        customers = Customer.query.filter(
            Customer.is_active.is_(True),
            db.or_(
                Customer.name.ilike(f'%{query}%'),
                Customer.phone.ilike(f'%{query}%'),
                Customer.email.ilike(f'%{query}%')
            )
        ).order_by(Customer.name).limit(per_page).all()
    else:
        # عرض كل العملاء (مرتبين أبجدياً)
        customers = Customer.query.filter_by(
            is_active=True
        ).order_by(Customer.name).limit(per_page).all()

    results = [{
        'id': c.id,
        'name': c.name,
        'phone': c.phone or '',
        'text': f"{c.name} - {c.phone}" if c.phone else c.name,
        'customer_type': c.customer_type,
        'customer_classification': c.customer_classification,
        'balance': float(c.get_balance())
    } for c in customers]

    return jsonify(results)


@customers_bp.route('/<int:id>/balance')
@login_required
def customer_balance(id):
    """Get customer balance and unpaid sales - API for payment receipts"""
    customer = db.get_or_404(Customer, id)

    # Get unpaid sales
    unpaid_sales = Sale.query.filter(
        Sale.customer_id == id,
        Sale.balance_due > 0,
        Sale.is_active.is_(True)
    ).order_by(Sale.sale_date.desc()).all()

    return jsonify({
        'balance': float(customer.get_balance()),
        'unpaid_sales': [{
            'id': s.id,
            'sale_number': s.sale_number,
            'total_amount': float(s.total_amount),
            'paid_amount': float(s.paid_amount),
            'balance_due': float(s.balance_due),
            'payment_status': s.payment_status,
            'sale_date': s.sale_date.strftime('%Y-%m-%d')
        } for s in unpaid_sales]
    })


@customers_bp.route('/<int:id>/sales')
@login_required
@permission_required('manage_customers')
def customer_sales(id):
    _ = db.get_or_404(Customer, id)

    sales = Sale.query.filter_by(
        customer_id=id,
        status='confirmed'
    ).order_by(Sale.sale_date.desc()).all()

    sales_data = []
    for sale in sales:
        balance = sale.amount_base - sale.paid_amount_base
        if balance > 0:
            sales_data.append({
                'id': sale.id,
                'invoice_number': sale.sale_number or f'#{sale.id}',
                'sale_date': sale.sale_date.strftime('%Y-%m-%d'),
                'amount_base': float(sale.amount_base),
                'paid_amount_base': float(sale.paid_amount_base),
                'balance': float(balance)
            })

    return jsonify({'sales': sales_data})
