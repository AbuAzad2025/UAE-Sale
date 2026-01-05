from datetime import datetime, timedelta, timezone
from decimal import Decimal
from flask import Blueprint, render_template, current_app, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from extensions import db
from models import Sale, Customer, Product, Payment, Receipt, GLAccount, GLJournalLine
from services.stock_service import StockService

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    return redirect(url_for('main.dashboard'))



@main_bp.route('/dashboard')
@login_required
def dashboard():
    today = datetime.now(timezone.utc).date()
    month_start = today.replace(day=1)
    
    stats = {}
    
    total_customers = Customer.query.filter_by(is_active=True).count()
    stats['customers_count'] = total_customers
    
    total_products = Product.query.filter_by(is_active=True).count()
    stats['products_count'] = total_products
    
    low_stock = []
    try:
        low_stock = StockService.get_low_stock_products(limit=10)
    except Exception as e:
        current_app.logger.error(f"Failed to fetch low stock products: {e}")

    stats['low_stock_count'] = len(low_stock)
    stats['low_stock_products'] = low_stock
    
    out_of_stock = []
    try:
        out_of_stock = StockService.get_out_of_stock_products()
    except Exception as e:
        current_app.logger.error(f"Failed to fetch out of stock products: {e}")
        
    stats['out_of_stock_count'] = len(out_of_stock)
    
    today_sales = db.session.query(
        func.count(Sale.id),
        func.sum(Sale.amount_aed)
    ).filter(
        func.date(Sale.sale_date) == today,
        Sale.status == 'confirmed'
    ).first()
    
    stats['today_sales_count'] = today_sales[0] or 0
    stats['today_sales_amount'] = float(today_sales[1] or 0)
    
    month_sales = db.session.query(
        func.count(Sale.id),
        func.sum(Sale.amount_aed)
    ).filter(
        func.date(Sale.sale_date) >= month_start,
        Sale.status == 'confirmed'
    ).first()
    
    stats['month_sales_count'] = month_sales[0] or 0
    stats['month_sales_amount'] = float(month_sales[1] or 0)
    
    if current_user.can_see_costs():
        month_profit = db.session.query(
            func.sum(Sale.amount_aed)
        ).filter(
            func.date(Sale.sale_date) >= month_start,
            Sale.status == 'confirmed'
        ).scalar() or Decimal('0')
        
        stats['month_profit'] = float(month_profit)
    
    total_receivables = db.session.query(
        func.sum(Sale.amount_aed - Sale.paid_amount_aed)
    ).filter(
        Sale.status == 'confirmed',
        Sale.balance_due > 0
    ).scalar() or Decimal('0')
    
    stats['total_receivables'] = float(total_receivables)
    
    if current_user.can_see_costs():
        try:
            cash_acc = GLAccount.query.filter_by(code='1000').first()
            if cash_acc:
                cash_debit = db.session.query(func.sum(GLJournalLine.debit)).filter_by(account_id=cash_acc.id).scalar() or Decimal('0')
                cash_credit = db.session.query(func.sum(GLJournalLine.credit)).filter_by(account_id=cash_acc.id).scalar() or Decimal('0')
                stats['cash_balance'] = float(cash_debit - cash_credit)
            
            bank_acc = GLAccount.query.filter_by(code='1010').first()
            if bank_acc:
                bank_debit = db.session.query(func.sum(GLJournalLine.debit)).filter_by(account_id=bank_acc.id).scalar() or Decimal('0')
                bank_credit = db.session.query(func.sum(GLJournalLine.credit)).filter_by(account_id=bank_acc.id).scalar() or Decimal('0')
                stats['bank_balance'] = float(bank_debit - bank_credit)
            
            inventory_acc = GLAccount.query.filter_by(code='1200').first()
            if inventory_acc:
                inv_debit = db.session.query(func.sum(GLJournalLine.debit)).filter_by(account_id=inventory_acc.id).scalar() or Decimal('0')
                inv_credit = db.session.query(func.sum(GLJournalLine.credit)).filter_by(account_id=inventory_acc.id).scalar() or Decimal('0')
                stats['inventory_value_gl'] = float(inv_debit - inv_credit)
        except Exception:
            pass
    
    # Optimized query with eager loading (N+1 problem fix)
    recent_sales = Sale.query.options(
        joinedload(Sale.customer),
        joinedload(Sale.seller)
    ).filter_by(
        status='confirmed'
    ).order_by(Sale.sale_date.desc()).limit(10).all()
    
    stats['recent_sales'] = recent_sales
    
    if current_user.is_seller():
        my_today_sales = db.session.query(
            func.count(Sale.id),
            func.sum(Sale.amount_aed)
        ).filter(
            func.date(Sale.sale_date) == today,
            Sale.seller_id == current_user.id,
            Sale.status == 'confirmed'
        ).first()
        
        stats['my_today_sales_count'] = my_today_sales[0] or 0
        stats['my_today_sales_amount'] = float(my_today_sales[1] or 0)
    
    return render_template('dashboard.html', stats=stats)

