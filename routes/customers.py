from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from extensions import db
from models import Customer, Sale
from utils.decorators import permission_required
from utils.helpers import create_audit_log
from services.payment_service import PaymentService

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
            
            flash('تم إضافة الزبون بنجاح', 'success')
            return redirect(url_for('customers.index'))
        
        except Exception as e:
            db.session.rollback()
            flash(f'حدث خطأ: {str(e)}', 'danger')
    
    return render_template('customers/create.html', form=form)


@customers_bp.route('/<int:id>')
@login_required
@permission_required('manage_customers')
def view(id):
    customer = Customer.query.get_or_404(id)
    
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
    customer = Customer.query.get_or_404(id)
    
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
            
            flash('تم تحديث بيانات الزبون بنجاح', 'success')
            return redirect(url_for('customers.view', id=customer.id))
        
        except Exception as e:
            db.session.rollback()
            flash(f'حدث خطأ: {str(e)}', 'danger')
    
    return render_template('customers/edit.html', customer=customer)


@customers_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('manage_customers')
def delete(id):
    customer = Customer.query.get_or_404(id)
    
    sales_count = Sale.query.filter_by(customer_id=id).count()
    
    if sales_count > 0:
        customer.is_active = False
        db.session.commit()
        flash('تم تعطيل الزبون (لديه عمليات مسجلة)', 'warning')
    else:
        db.session.delete(customer)
        db.session.commit()
        flash('تم حذف الزبون بنجاح', 'success')
    
    create_audit_log('delete', 'customers', id)
    
    return redirect(url_for('customers.index'))


@customers_bp.route('/<int:id>/statement')
@login_required
@permission_required('manage_customers')
def statement(id):
    customer = Customer.query.get_or_404(id)
    
    date_from = request.args.get('date_from', type=str)
    date_to = request.args.get('date_to', type=str)
    
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
        transactions.append({
            'date': sale.sale_date,
            'type': 'sale',
            'reference': sale.sale_number,
            'debit': float(sale.amount_aed),
            'credit': 0,
            'balance': 0,
            'description': f'فاتورة بيع'
        })
    
    for payment in payments:
        transactions.append({
            'date': payment.payment_date,
            'type': 'payment',
            'reference': payment.reference_number or f'دفع #{payment.id}',
            'debit': 0,
            'credit': float(payment.amount_aed),
            'balance': 0,
            'description': f'دفع - {payment.payment_method}'
        })
    
    transactions.sort(key=lambda x: x['date'])
    
    running_balance = 0
    for trans in transactions:
        running_balance += trans['debit'] - trans['credit']
        trans['balance'] = running_balance
    
    return render_template('customers/statement.html',
                         customer=customer,
                         transactions=transactions,
                         final_balance=running_balance)


@customers_bp.route('/api/search')
@login_required
def api_search():
    query = request.args.get('q', '')
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    # السماح بالبحث حتى بدون query (لعرض كل العملاء)
    if query and len(query) >= 1:
        customers = Customer.query.filter(
            Customer.is_active == True,
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
    customer = Customer.query.get_or_404(id)
    
    # Get unpaid sales
    unpaid_sales = Sale.query.filter(
        Sale.customer_id == id,
        Sale.balance_due > 0,
        Sale.is_active == True
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
    customer = Customer.query.get_or_404(id)
    
    sales = Sale.query.filter_by(
        customer_id=id, 
        status='confirmed'
    ).order_by(Sale.sale_date.desc()).all()
    
    sales_data = []
    for sale in sales:
        balance = sale.amount_aed - sale.paid_amount_aed
        if balance > 0:
            sales_data.append({
                'id': sale.id,
                'invoice_number': sale.sale_number or f'#{sale.id}',
                'sale_date': sale.sale_date.strftime('%Y-%m-%d'),
                'amount_aed': float(sale.amount_aed),
                'paid_amount_aed': float(sale.paid_amount_aed),
                'balance': float(balance)
            })
    
    return jsonify({'sales': sales_data})

