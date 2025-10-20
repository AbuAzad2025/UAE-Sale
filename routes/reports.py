from datetime import datetime, timedelta, timezone
from decimal import Decimal
from flask import Blueprint, render_template, request
from flask_login import login_required, current_user
from sqlalchemy import func
from extensions import db
from models import Sale, SaleLine, Purchase, Product, Customer
from utils.decorators import permission_required

reports_bp = Blueprint('reports', __name__, url_prefix='/reports')


@reports_bp.route('/')
@login_required
@permission_required('view_reports')
def index():
    return render_template('reports/index.html')


@reports_bp.route('/sales')
@login_required
@permission_required('view_reports')
def sales():
    date_from = request.args.get('date_from', '', type=str)
    date_to = request.args.get('date_to', '', type=str)
    customer_id = request.args.get('customer', type=int)
    seller_id = request.args.get('seller', type=int)
    
    query = Sale.query.filter_by(status='confirmed')
    
    if date_from:
        query = query.filter(func.date(Sale.sale_date) >= date_from)
    
    if date_to:
        query = query.filter(func.date(Sale.sale_date) <= date_to)
    
    if customer_id:
        query = query.filter_by(customer_id=customer_id)
    
    if seller_id:
        query = query.filter_by(seller_id=seller_id)
    elif current_user.is_seller():
        query = query.filter_by(seller_id=current_user.id)
    
    sales_list = query.order_by(Sale.sale_date.desc()).all()
    
    total_sales = Decimal('0')
    total_paid = Decimal('0')
    total_due = Decimal('0')
    
    for sale in sales_list:
        total_sales += (sale.amount_aed or Decimal('0'))
        total_paid += (sale.paid_amount_aed or Decimal('0'))
        total_due += ((sale.amount_aed or Decimal('0')) - (sale.paid_amount_aed or Decimal('0')))
    
    total_profit = Decimal('0')
    if current_user.can_see_costs():
        for sale in sales_list:
            total_profit += (sale.get_profit() or Decimal('0'))
    
    summary = {
        'count': len(sales_list),
        'total_sales': float(total_sales),
        'total_paid': float(total_paid),
        'total_due': float(total_due),
        'total_profit': float(total_profit) if current_user.can_see_costs() else None
    }
    
    return render_template('reports/sales.html',
                         sales=sales_list,
                         summary=summary)


@reports_bp.route('/purchases')
@login_required
@permission_required('view_reports')
def purchases():
    if current_user.is_seller():
        return render_template('errors/403.html'), 403
    
    date_from = request.args.get('date_from', '', type=str)
    date_to = request.args.get('date_to', '', type=str)
    
    query = Purchase.query.filter_by(status='confirmed')
    
    if date_from:
        query = query.filter(func.date(Purchase.purchase_date) >= date_from)
    
    if date_to:
        query = query.filter(func.date(Purchase.purchase_date) <= date_to)
    
    purchases_list = query.order_by(Purchase.purchase_date.desc()).all()
    
    total_purchases = Decimal('0')
    for p in purchases_list:
        total_purchases += (p.amount_aed or Decimal('0'))
    
    summary = {
        'count': len(purchases_list),
        'total_purchases': float(total_purchases)
    }
    
    return render_template('reports/purchases.html',
                         purchases=purchases_list,
                         summary=summary)


@reports_bp.route('/receivables')
@login_required
@permission_required('view_reports')
def receivables():
    now = datetime.now(timezone.utc)
    
    all_sales = Sale.query.filter(
        Sale.status == 'confirmed'
    ).all()
    
    all_sales = [sale for sale in all_sales if (sale.amount_aed or Decimal('0')) > (sale.paid_amount_aed or Decimal('0'))]
    
    aging_data = {
        'current': {'sales': [], 'total': Decimal('0')},
        'days_30': {'sales': [], 'total': Decimal('0')},
        'days_60': {'sales': [], 'total': Decimal('0')},
        'days_90': {'sales': [], 'total': Decimal('0')},
        'over_90': {'sales': [], 'total': Decimal('0')},
    }
    
    for sale in all_sales:
        sale_date = sale.sale_date
        if sale_date.tzinfo is None:
            sale_date = sale_date.replace(tzinfo=timezone.utc)
        days_old = (now - sale_date).days
        balance = (sale.amount_aed or Decimal('0')) - (sale.paid_amount_aed or Decimal('0'))
        
        sale.days_old = days_old
        sale.calculated_balance = balance
        
        if days_old <= 30:
            aging_data['current']['sales'].append(sale)
            aging_data['current']['total'] += balance
        elif days_old <= 60:
            aging_data['days_30']['sales'].append(sale)
            aging_data['days_30']['total'] += balance
        elif days_old <= 90:
            aging_data['days_60']['sales'].append(sale)
            aging_data['days_60']['total'] += balance
        elif days_old <= 120:
            aging_data['days_90']['sales'].append(sale)
            aging_data['days_90']['total'] += balance
        else:
            aging_data['over_90']['sales'].append(sale)
            aging_data['over_90']['total'] += balance
    
    total_receivables = sum(data['total'] for data in aging_data.values())
    
    summary = {
        'total_receivables': float(total_receivables),
        'current': float(aging_data['current']['total']),
        'days_30': float(aging_data['days_30']['total']),
        'days_60': float(aging_data['days_60']['total']),
        'days_90': float(aging_data['days_90']['total']),
        'over_90': float(aging_data['over_90']['total']),
    }
    
    return render_template('reports/receivables.html',
                         aging_data=aging_data,
                         summary=summary)


@reports_bp.route('/inventory')
@login_required
@permission_required('view_reports')
def inventory():
    category_id = request.args.get('category', type=int)
    
    query = Product.query.filter_by(is_active=True)
    
    if category_id:
        query = query.filter_by(category_id=category_id)
    
    products = query.order_by(Product.name).all()
    
    total_value = Decimal('0')
    total_items = Decimal('0')
    
    for p in products:
        total_items += (p.current_stock or Decimal('0'))
        if current_user.can_see_costs():
            total_value += (p.current_stock or Decimal('0')) * (p.cost_price or Decimal('0'))
    
    summary = {
        'products_count': len(products),
        'total_items': float(total_items),
        'total_value': float(total_value) if current_user.can_see_costs() else None
    }
    
    return render_template('reports/inventory.html',
                         products=products,
                         summary=summary)


@reports_bp.route('/top-selling')
@login_required
@permission_required('view_reports')
def top_selling():
    date_from = request.args.get('date_from', '', type=str)
    date_to = request.args.get('date_to', '', type=str)
    limit = request.args.get('limit', 20, type=int)
    
    query = db.session.query(
        Product.id,
        Product.name,
        func.sum(SaleLine.quantity).label('total_quantity'),
        func.sum(SaleLine.line_total).label('total_sales')
    ).join(
        SaleLine, Product.id == SaleLine.product_id
    ).join(
        Sale, SaleLine.sale_id == Sale.id
    ).filter(
        Sale.status == 'confirmed'
    )
    
    if date_from:
        query = query.filter(func.date(Sale.sale_date) >= date_from)
    
    if date_to:
        query = query.filter(func.date(Sale.sale_date) <= date_to)
    
    products = query.group_by(
        Product.id, Product.name
    ).order_by(
        func.sum(SaleLine.quantity).desc()
    ).limit(limit).all()
    
    return render_template('reports/top_selling.html', products=products)

