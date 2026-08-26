from datetime import datetime, timedelta, timezone
from decimal import Decimal
from flask import Blueprint, render_template, current_app, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from extensions import db, cache
from models import Sale, Customer, Product, GLAccount, GLJournalLine
from services.stock_service import StockService

# Dashboard cache TTL in seconds (60s = short enough to stay fresh,
# long enough to eliminate repeated heavy queries within a page reload burst)
DASHBOARD_CACHE_TTL = 60

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    return redirect(url_for('main.dashboard'))


@main_bp.route('/dashboard')
@login_required
def dashboard():  # noqa: C901
    # Dashboard route with error handling
    try:
        today = datetime.now(timezone.utc).date()
        month_start = today.replace(day=1)

        stats = {}

        # ── Cached aggregate queries ──────────────────────────────────
        # Cache per-day key so stats refresh at midnight automatically.
        cache_key_prefix = f'dashboard:{today}'

        def _cached(key, fn):
            """Return cached value or compute, store, and return."""
            full_key = f'{cache_key_prefix}:{key}'
            val = cache.get(full_key)
            if val is not None:
                return val
            val = fn()
            cache.set(full_key, val, timeout=DASHBOARD_CACHE_TTL)
            return val

        stats['customers_count'] = _cached('customers',
                                           lambda: Customer.query.filter_by(is_active=True).count())

        stats['products_count'] = _cached('products',
                                          lambda: Product.query.filter_by(is_active=True).count())

        low_stock = _cached('low_stock', lambda: [] if not hasattr(StockService, 'get_low_stock_products') else StockService.get_low_stock_products(limit=10))
        stats['low_stock_count'] = len(low_stock)
        stats['low_stock_products'] = low_stock

        out_of_stock = _cached('out_of_stock', lambda: [] if not hasattr(StockService, 'get_out_of_stock_products') else StockService.get_out_of_stock_products())  # noqa: E501
        stats['out_of_stock_count'] = len(out_of_stock)

        def _today_sales():
            return db.session.query(
                func.count(Sale.id), func.sum(Sale.amount_base)
            ).filter(func.date(Sale.sale_date) == today,
                     Sale.status == 'confirmed').first()

        today_sales = _cached('today_sales', _today_sales)
        stats['today_sales_count'] = today_sales[0] or 0
        stats['today_sales_amount'] = float(today_sales[1] or 0)

        def _month_sales():
            return db.session.query(
                func.count(Sale.id), func.sum(Sale.amount_base)
            ).filter(func.date(Sale.sale_date) >= month_start,
                     Sale.status == 'confirmed').first()

        month_sales = _cached('month_sales', _month_sales)
        stats['month_sales_count'] = month_sales[0] or 0
        stats['month_sales_amount'] = float(month_sales[1] or 0)

        if current_user.can_see_costs():
            def _month_profit():
                """True profit: sum of sale.get_profit() over last-30d confirmed sales."""
                cutoff = today - timedelta(days=30)
                try:
                    recent_sales = Sale.query.options(
                        joinedload(Sale.lines)
                    ).filter(
                        func.date(Sale.sale_date) >= cutoff,
                        Sale.status == 'confirmed'
                    ).all()
                    total = Decimal('0')
                    for sale in recent_sales:
                        try:
                            total += Decimal(str(sale.get_profit()))
                        except Exception:
                            continue
                    return total
                except Exception:
                    return Decimal('0')
            stats['month_profit'] = float(_cached('month_profit', _month_profit))

        def _receivables():
            return db.session.query(
                func.sum(Sale.amount_base - Sale.paid_amount_base)
            ).filter(Sale.status == 'confirmed',
                     Sale.balance_due > 0).scalar() or Decimal('0')

        stats['total_receivables'] = float(_cached('receivables', _receivables))

        # GL balances (cost-sensitive, cached per user role)
        if current_user.can_see_costs():
            def _gl_balances():
                result = {}
                for code, key in [('1000', 'cash_balance'), ('1010', 'bank_balance'), ('1200', 'inventory_value_gl')]:
                    acc = GLAccount.query.filter_by(code=code).first()
                    if acc:
                        debit = db.session.query(func.sum(GLJournalLine.debit)).filter_by(account_id=acc.id).scalar() or Decimal('0')
                        credit = db.session.query(func.sum(GLJournalLine.credit)).filter_by(account_id=acc.id).scalar() or Decimal('0')
                        result[key] = float(debit - credit)
                return result

            gl_balances = _cached('gl_balances', _gl_balances)
            stats.update(gl_balances)

        # Recent sales (small query, cached for consistency)
        def _recent_sales():
            return [s.to_dict() if hasattr(s, 'to_dict') else {
                'id': s.id, 'sale_number': s.sale_number,
                'amount': float(s.amount_base or 0),
                'date': s.sale_date.strftime('%Y-%m-%d') if s.sale_date else '',
                'customer': s.customer.name if s.customer else 'عميل نقدي',
                'seller': s.seller.username if s.seller else '',
            } for s in Sale.query.options(
                joinedload(Sale.customer), joinedload(Sale.seller)
            ).filter_by(status='confirmed').order_by(Sale.sale_date.desc()).limit(10).all()]

        stats['recent_sales_data'] = _cached('recent_sales', _recent_sales)

        if current_user.is_seller():
            def _my_today():
                return db.session.query(
                    func.count(Sale.id), func.sum(Sale.amount_base)
                ).filter(func.date(Sale.sale_date) == today,
                         Sale.seller_id == current_user.id,
                         Sale.status == 'confirmed').first()

            my_today = _cached(f'my_today:{current_user.id}', _my_today)
            stats['my_today_sales_count'] = my_today[0] or 0
            stats['my_today_sales_amount'] = float(my_today[1] or 0)

        # Pass raw ORM objects for template rendering (un-cached per-request)
        stats['recent_sales'] = Sale.query.options(
            joinedload(Sale.customer), joinedload(Sale.seller)
        ).filter_by(status='confirmed').order_by(Sale.sale_date.desc()).limit(10).all()

        return render_template('dashboard.html', stats=stats)

    except Exception as e:
        current_app.logger.error(f"Dashboard Error: {e}", exc_info=True)
        # Show safe error page — never leak stack traces to users
        return """
        <html>
            <head><title>خطأ في لوحة التحكم</title></head>
            <body style="font-family: sans-serif; padding: 40px; text-align: center; direction: rtl;">
                <h1 style="color: #dc3545;">⚠️ خطأ في لوحة التحكم</h1>
                <p>حدث خطأ غير متوقع. يرجى المحاولة مرة أخرى أو الاتصال بالمدير.</p>
                <a href="/" style="color: #007bff;">العودة للرئيسية</a>
            </body>
        </html>
        """, 500
