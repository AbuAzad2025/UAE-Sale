from datetime import datetime, timezone, timedelta
from decimal import Decimal
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, current_app
from flask_login import login_required, current_user
from sqlalchemy import func, desc
from extensions import db, limiter
from models import (
    User, Customer, Product, Sale, SaleLine, Purchase, Receipt, AuditLog,
    ArchivedRecord, CardVault, InvoiceSettings, Tenant, SystemSettings, IntegrationSettings,
    Expense
)
from models.login_history import LoginHistory
from models.security_alert import SecurityAlert
from models.api_key import APIKey
from utils.decorators import owner_required, permission_required, _role_level as _role_level_canon, _enforce_target_role_not_higher, get_owned_or_404
from utils.db_safety import validate_table_name, validate_backup_filename
from sqlalchemy import text, inspect


def get_allowed_table_names_safe():
    """Get a set of allowed table names for safe SQL queries."""
    try:
        return set(inspect(db.engine).get_table_names())
    except Exception:
        return set()


import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402,F401
from datetime import datetime as dt  # noqa: E402

owner_bp = Blueprint('owner', __name__, url_prefix='/owner')


def _role_level(role_or_slug):
    """Compatibility shim — accept either a Role model or a slug string.

    The canonical implementation lives in ``utils.decorators``; we keep
    this local version so existing call sites in owner.py continue to
    work without rewrites.
    """
    if role_or_slug is None:
        return 0
    if isinstance(role_or_slug, str):
        # Build a minimal role-like object
        class _R:
            pass
        r = _R()
        r.slug = role_or_slug
        return _role_level_canon(r)
    return _role_level_canon(role_or_slug)


def _current_user_level():
    if getattr(current_user, 'is_owner', False):
        return 100
    return _role_level_canon(getattr(current_user, 'role', None))


@owner_bp.route('/dashboard')
@login_required
@owner_required
def dashboard():
    stats = {}

    _ = datetime.now(timezone.utc)
    today = datetime.now().date()
    month_start = today.replace(day=1)
    year_start = today.replace(month=1, day=1)
    cutoff_date = datetime.now() - timedelta(days=30)

    stats['total_users'] = User.query.filter_by(is_active=True, is_owner=False).count()
    stats['total_customers'] = Customer.query.filter_by(is_active=True).count()
    stats['total_products'] = Product.query.filter_by(is_active=True).count()

    stats['vip_customers'] = Customer.query.filter_by(
        customer_classification='vip',
        is_active=True
    ).count()

    stats['premium_customers'] = Customer.query.filter_by(
        customer_classification='premium',
        is_active=True
    ).count()

    today_sales = db.session.query(
        func.count(Sale.id),
        func.sum(Sale.amount_base),
        func.sum(Sale.amount_base - Sale.paid_amount_base)
    ).filter(
        func.date(Sale.sale_date) == today,
        Sale.status == 'confirmed'
    ).first()

    stats['today_sales_count'] = today_sales[0] or 0
    stats['today_sales_amount'] = float(today_sales[1] or 0)
    stats['today_receivables'] = float(today_sales[2] or 0)

    month_sales = db.session.query(
        func.count(Sale.id),
        func.sum(Sale.amount_base)
    ).filter(
        func.date(Sale.sale_date) >= month_start,
        Sale.status == 'confirmed'
    ).first()

    stats['month_sales_count'] = month_sales[0] or 0
    stats['month_sales_amount'] = float(month_sales[1] or 0)

    year_sales = db.session.query(
        func.sum(Sale.amount_base)
    ).filter(
        func.date(Sale.sale_date) >= year_start,
        Sale.status == 'confirmed'
    ).scalar() or Decimal('0')

    stats['year_sales_amount'] = float(year_sales)

    month_purchases = db.session.query(
        func.sum(Purchase.amount_base)
    ).filter(
        func.date(Purchase.purchase_date) >= month_start,
        Purchase.status == 'confirmed'
    ).scalar() or Decimal('0')

    stats['month_purchases_amount'] = float(month_purchases)

    total_profit = Decimal('0')
    for sale in Sale.query.filter(
        func.date(Sale.sale_date) >= month_start,
        Sale.status == 'confirmed'
    ).all():
        total_profit += (sale.get_profit() or Decimal('0'))

    stats['month_profit'] = float(total_profit)
    stats['profit_margin'] = (float(total_profit) / float(month_sales[1] or 1)) * 100 if month_sales[1] else 0

    total_inventory_value = Decimal('0')
    total_inventory_cost = Decimal('0')

    for product in Product.query.filter_by(is_active=True).all():
        total_inventory_value += (product.current_stock or Decimal('0')) * (product.regular_price or Decimal('0'))
        total_inventory_cost += (product.current_stock or Decimal('0')) * (product.cost_price or Decimal('0'))

    stats['inventory_value'] = float(total_inventory_value)
    stats['inventory_cost'] = float(total_inventory_cost)

    total_receivables = Decimal('0')
    overdue_count = 0

    for sale in Sale.query.filter(Sale.status == 'confirmed').all():
        balance = (sale.amount_base or Decimal('0')) - (sale.paid_amount_base or Decimal('0'))
        if balance > 0:
            total_receivables += balance
            if sale.sale_date < cutoff_date:
                overdue_count += 1

    stats['total_receivables'] = float(total_receivables)

    stats['overdue_invoices'] = overdue_count

    top_customers = db.session.query(
        Customer.id,
        Customer.name,
        Customer.customer_type,
        Customer.customer_classification,
        func.sum(Sale.amount_base).label('total')
    ).join(
        Sale, Customer.id == Sale.customer_id
    ).filter(
        Sale.status == 'confirmed',
        func.date(Sale.sale_date) >= month_start
    ).group_by(
        Customer.id, Customer.name, Customer.customer_type, Customer.customer_classification
    ).order_by(
        desc('total')
    ).limit(10).all()

    stats['top_customers'] = top_customers

    # Top selling products
    try:
        top_products = db.session.query(
            Product.id,
            Product.name,
            func.sum(SaleLine.quantity).label('quantity'),
            func.sum(SaleLine.line_total).label('revenue')
        ).join(
            SaleLine, Product.id == SaleLine.product_id
        ).join(
            Sale, SaleLine.sale_id == Sale.id
        ).filter(
            Sale.status == 'confirmed',
            func.date(Sale.sale_date) >= month_start
        ).group_by(
            Product.id, Product.name
        ).order_by(
            desc('revenue')
        ).limit(10).all()

        stats['top_products'] = top_products
    except Exception as e:
        current_app.logger.error(f"Error getting top products: {e}")
        stats['top_products'] = []

    recent_actions = AuditLog.query.order_by(
        AuditLog.created_at.desc()
    ).limit(20).all()

    stats['recent_actions'] = recent_actions

    low_stock = Product.query.filter(
        Product.is_active.is_(True),
        Product.current_stock <= Product.min_stock_alert
    ).order_by(Product.current_stock).limit(10).all()

    stats['low_stock'] = low_stock

    return render_template('owner/dashboard.html', stats=stats)


@owner_bp.route('/system-stats')
@login_required
@owner_required
def system_stats():
    from sqlalchemy import text

    db_stats = {}

    try:
        result = db.session.execute(text("SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname='public'"))
        tables = result.fetchall()

        for row in tables:
            table_name = row[0]
            count_result = db.session.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
            count = count_result.scalar()
            db_stats[table_name] = count

    except Exception as e:
        current_app.logger.error(f'System stats error: {e}')
        flash('❌ خطأ في جلب الإحصائيات. يرجى تحديث الصفحة.', 'danger')

    return render_template('owner/system_stats.html', db_stats=db_stats)


@owner_bp.route('/audit-logs')
@login_required
@owner_required
def audit_logs():
    """سجل التدقيق الشامل - مراقبة كل عمليات النظام"""
    page = request.args.get('page', 1, type=int)
    action = request.args.get('action', '', type=str)
    user_id = request.args.get('user', type=int)
    per_page = request.args.get('per_page', 50, type=int)

    query = AuditLog.query

    # فلترة حسب العملية
    if action:
        query = query.filter_by(action=action)

    # فلترة حسب المستخدم
    if user_id:
        query = query.filter_by(user_id=user_id)

    # الترتيب والتقسيم
    pagination = query.order_by(AuditLog.created_at.desc()).paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )

    # إحصائيات سريعة
    stats = {
        'total': AuditLog.query.count(),
        'today': AuditLog.query.filter(
            db.func.date(AuditLog.created_at) == db.func.current_date()
        ).count(),
        'creates': AuditLog.query.filter_by(action='create').count(),
        'updates': AuditLog.query.filter_by(action='update').count(),
        'deletes': AuditLog.query.filter_by(action='delete').count(),
    }

    # قائمة المستخدمين للفلتر
    users = User.query.filter_by(is_active=True).all()

    return render_template('owner/audit_logs.html',
                           logs=pagination.items,
                           pagination=pagination,
                           stats=stats,
                           users=users)


@owner_bp.route('/archived')
@login_required
@owner_required
def archived():
    page = request.args.get('page', 1, type=int)
    table_name = request.args.get('table', '', type=str)

    query = ArchivedRecord.query

    if table_name:
        query = query.filter_by(table_name=table_name)

    pagination = query.order_by(ArchivedRecord.archived_at.desc()).paginate(
        page=page,
        per_page=50,
        error_out=False
    )

    return render_template('owner/archived.html',
                           records=pagination.items,
                           pagination=pagination)


@owner_bp.route('/users-list')
@login_required
@owner_required
def users_list():
    """قائمة المستخدمين"""
    users = User.query.order_by(User.created_at.desc()).all()

    # إحصائيات
    from models import Role
    stats = {
        'total': User.query.count(),
        'active': User.query.filter_by(is_active=True).count(),
        'inactive': User.query.filter_by(is_active=False).count(),
        'owners': User.query.filter_by(is_owner=True).count(),
        'admins': db.session.query(User).join(Role).filter(Role.slug == 'super_admin').count(),
        'managers': db.session.query(User).join(Role).filter(Role.slug == 'manager').count(),
        'sellers': db.session.query(User).join(Role).filter(Role.slug == 'seller').count(),
    }

    return render_template('owner/users_list.html', users=users, stats=stats)


@owner_bp.route('/users/create', methods=['GET', 'POST'])
@login_required
@owner_required
@limiter.limit("5 per minute", methods=['POST'])
def create_user():
    """إضافة مستخدم جديد"""
    from models import Role
    from werkzeug.security import generate_password_hash
    from utils.password_validator import PasswordValidator

    current_level = _current_user_level()
    roles = Role.query.filter_by(is_active=True).all()
    roles = [r for r in roles if _role_level(getattr(r, 'slug', None)) <= current_level]
    default_form = {'is_active': 'on'}

    if request.method == 'POST':
        try:
            from utils.sanitizer import InputSanitizer

            username = InputSanitizer.sanitize_text(request.form.get('username', ''), max_length=20)
            email = InputSanitizer.sanitize_email(request.form.get('email', ''))
            password = request.form.get('password', '').strip()  # لا نعدل password
            full_name = InputSanitizer.sanitize_text(request.form.get('full_name', ''), max_length=100)
            role_id = request.form.get('role_id', type=int)
            is_owner = request.form.get('is_owner') == 'on'
            is_active = request.form.get('is_active') == 'on'

            def _form_values():
                values = request.form.to_dict()
                values['is_owner'] = 'on' if is_owner else 'off'
                values['is_active'] = 'on' if is_active else 'off'
                return values

            # التحقق من البيانات
            if not username or not password:
                from utils.error_messages import ErrorMessages
                flash(ErrorMessages.user_required_fields(), 'error')
                return render_template('owner/create_user.html', roles=roles, form_data=_form_values())

            if not role_id:
                flash('⚠️ يرجى اختيار الدور الوظيفي.', 'warning')
                return render_template('owner/create_user.html', roles=roles, form_data=_form_values())

            # SECURITY: server-side re-validation of the chosen role.
            target_role = Role.query.get(role_id)
            if target_role is None:
                flash('⚠️ الدور المختار غير صالح.', 'danger')
                return render_template('owner/create_user.html', roles=roles, form_data=_form_values())
            _enforce_target_role_not_higher(target_role)

            # SECURITY: only the platform owner may mint another owner.
            if is_owner and not getattr(current_user, 'is_owner', False):
                flash('⛔ لا يمكن إنشاء مالك جديد إلا من قِبل المالك الحالي.', 'danger')
                return render_template('owner/create_user.html', roles=roles, form_data=_form_values())

            # التحقق من قوة كلمة المرور
            is_valid, errors = PasswordValidator.validate(password)
            if not is_valid:
                from utils.error_messages import ErrorMessages
                flash(ErrorMessages.weak_password(errors), 'danger')
                return render_template('owner/create_user.html', roles=roles, form_data=_form_values())

            # التحقق من عدم وجود المستخدم
            existing = User.query.filter_by(username=username).first()
            if existing:
                from utils.error_messages import ErrorMessages
                flash(ErrorMessages.user_exists(username), 'error')
                return render_template('owner/create_user.html', roles=roles, form_data=_form_values())

            # إنشاء المستخدم
            user = User(
                username=username,
                email=email,
                password_hash=generate_password_hash(password),
                full_name=full_name,
                role_id=role_id,
                is_owner=is_owner,
                is_active=is_active
            )

            db.session.add(user)
            db.session.commit()

            flash(f'تم إضافة المستخدم {username} بنجاح', 'success')
            return redirect(url_for('owner.users_list'))

        except Exception as e:
            db.session.rollback()
            from utils.error_messages import ErrorMessages
            current_app.logger.error(f'User update error: {e}')
            flash('❌ خطأ في تحديث المستخدم.', 'error')
            return render_template('owner/create_user.html', roles=roles, form_data=_form_values())

    return render_template('owner/create_user.html', roles=roles, form_data=default_form)


@owner_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@owner_required
@limiter.limit("10 per minute", methods=['POST'])
def edit_user(user_id):
    """تعديل مستخدم"""
    from models import Role
    from werkzeug.security import generate_password_hash

    # SECURITY: use get_owned_or_404 for cross-tenant safety.
    user = get_owned_or_404(User, user_id)

    if request.method == 'POST':
        try:
            user.username = request.form.get('username', '').strip()
            user.email = request.form.get('email', '').strip()
            user.full_name = request.form.get('full_name', '').strip()

            # SECURITY: re-validate the new role level.  Even if the
            # dropdown is filtered, body tampering could try to inject
            # a higher role.  Owners can edit anyone, but only the
            # owner is the owner.
            new_role_id = request.form.get('role_id', type=int)
            if new_role_id and new_role_id != user.role_id:
                new_role = Role.query.get(new_role_id)
                if new_role is None:
                    flash('⚠️ الدور المختار غير صالح.', 'danger')
                    return redirect(url_for('owner.edit_user', user_id=user_id))
                _enforce_target_role_not_higher(new_role)
                user.role_id = new_role_id

            # SECURITY: only the platform owner may mint another owner.
            new_is_owner = request.form.get('is_owner') == 'on'
            if new_is_owner and not getattr(current_user, 'is_owner', False):
                flash('⛔ لا يمكن منح صلاحية المالك لغير المالك الحالي.', 'danger')
                return redirect(url_for('owner.edit_user', user_id=user_id))
            user.is_owner = new_is_owner
            user.is_active = request.form.get('is_active') == 'on'

            # تغيير كلمة المرور إن وجدت
            new_password = request.form.get('new_password', '').strip()
            if new_password:
                # SECURITY: Enforce password strength policy
                from utils.password_validator import PasswordValidator
                is_valid, pw_errors = PasswordValidator.validate(new_password)
                if not is_valid:
                    flash('⚠️ كلمة المرور ضعيفة:\n' + '\n'.join(pw_errors), 'danger')
                    return redirect(url_for('owner.edit_user', user_id=user_id))
                user.password_hash = generate_password_hash(new_password, method='pbkdf2:sha256')

            user.updated_by = current_user.id

            db.session.commit()

            flash(f'تم تحديث المستخدم {user.username} بنجاح', 'success')
            return redirect(url_for('owner.users_list'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'User edit error: {e}')
            flash('❌ خطأ في تحديث المستخدم.', 'error')

    current_level = _current_user_level()
    roles = Role.query.filter_by(is_active=True).all()
    roles = [r for r in roles if _role_level(getattr(r, 'slug', None)) <= current_level]
    return render_template('owner/edit_user.html', user=user, roles=roles)


@owner_bp.route('/users/<int:user_id>/profile')
@login_required
@owner_required
def user_profile(user_id):
    """الملف الشخصي للمستخدم"""
    # SECURITY: cross-tenant safe lookup.
    user = get_owned_or_404(User, user_id)

    # إحصائيات المستخدم
    from models import Sale, Payment  # noqa: F811  (local import intentional)

    stats = {
        'sales_count': Sale.query.count(),
        'sales_total': db.session.query(func.sum(Sale.amount_base)).filter_by(status='confirmed').scalar() or 0,
        'payments_count': Payment.query.count(),
        'payments_total': db.session.query(func.sum(Payment.amount_base)).scalar() or 0,
        'audits_count': 0,  # Audit.query.filter_by(user_id=user_id).count(),
    }

    # آخر النشاطات
    recent_sales = Sale.query.order_by(Sale.sale_date.desc()).limit(5).all()
    recent_audits = []  # Audit.query.filter_by(user_id=user_id).order_by(Audit.timestamp.desc()).limit(10).all()

    return render_template('owner/user_profile.html',
                           user=user,
                           stats=stats,
                           recent_sales=recent_sales,
                           recent_audits=recent_audits)


@owner_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
@owner_required
def delete_user(user_id):
    """حذف مستخدم"""
    # SECURITY: cross-tenant check.
    user = get_owned_or_404(User, user_id)

    # لا يمكن حذف المالك
    from utils.error_messages import ErrorMessages

    if user.is_owner:
        flash(ErrorMessages.user_delete_owner(), 'error')
        return redirect(url_for('owner.users_list'))

    # لا يمكن حذف نفسك
    if user.id == current_user.id:
        flash(ErrorMessages.user_delete_self(), 'error')
        return redirect(url_for('owner.users_list'))

    try:
        # Soft delete - تعطيل بدلاً من الحذف
        user.is_active = False
        user.updated_by = current_user.id
        db.session.commit()

        flash(f'تم تعطيل المستخدم {user.username}', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'User delete error: {e}')
        flash('❌ خطأ في حذف المستخدم.', 'error')

    return redirect(url_for('owner.users_list'))


@owner_bp.route('/roles-permissions')
@login_required
@owner_required
def roles_permissions():
    """صفحة الأدوار والصلاحيات"""
    return render_template('owner/roles_permissions.html')


@owner_bp.route('/financial-overview')
@login_required
@owner_required
def financial_overview():
    period = request.args.get('period', 'month', type=str)

    now = datetime.now(timezone.utc)

    if period == 'today':
        start_date = now.date()
    elif period == 'week':
        start_date = (now - timedelta(days=7)).date()
    elif period == 'month':
        start_date = now.date().replace(day=1)
    elif period == 'year':
        start_date = now.date().replace(month=1, day=1)
    else:
        start_date = now.date().replace(day=1)

    sales_data = db.session.query(
        func.sum(Sale.amount_base).label('total_sales'),
        func.sum(Sale.paid_amount_base).label('total_paid'),
        func.count(Sale.id).label('count')
    ).filter(
        func.date(Sale.sale_date) >= start_date,
        Sale.status == 'confirmed'
    ).first()

    purchases_data = db.session.query(
        func.sum(Purchase.amount_base).label('total_purchases'),
        func.count(Purchase.id).label('count')
    ).filter(
        func.date(Purchase.purchase_date) >= start_date,
        Purchase.status == 'confirmed'
    ).first()

    receipts_total = db.session.query(
        func.sum(Receipt.amount_base)
    ).filter(
        func.date(Receipt.receipt_date) >= start_date
    ).scalar() or Decimal('0')

    financial_data = {
        'sales_total': float(sales_data[0] or 0),
        'sales_paid': float(sales_data[1] or 0),
        'sales_count': sales_data[2] or 0,
        'purchases_total': float(purchases_data[0] or 0),
        'purchases_count': purchases_data[1] or 0,
        'receipts_total': float(receipts_total),
        'net_revenue': float((sales_data[0] or 0) - (purchases_data[0] or 0)),
    }

    return render_template('owner/financial_overview.html',
                           financial_data=financial_data,
                           period=period)


@owner_bp.route('/config')
@login_required
@owner_required
def config():
    from flask import current_app

    config_data = {
        'DATABASE_URL': current_app.config.get('SQLALCHEMY_DATABASE_URI', ''),
        'DEBUG': current_app.config.get('DEBUG', False),
        'APP_ENV': current_app.config.get('APP_ENV', ''),
        'DEFAULT_CURRENCY': current_app.config.get('DEFAULT_CURRENCY', ''),
        'COMPANY_NAME': current_app.config.get('COMPANY_NAME', ''),
        'APP_VERSION': current_app.config.get('APP_VERSION', ''),
    }

    return render_template('owner/config.html', config=config_data)


@owner_bp.route('/cards-vault')
@login_required
@owner_required
def cards_vault():
    page = request.args.get('page', 1, type=int)
    customer_id = request.args.get('customer', type=int)

    query = CardVault.query.filter_by(is_active=True)

    if customer_id:
        query = query.filter_by(customer_id=customer_id)

    pagination = query.order_by(CardVault.created_at.desc()).paginate(
        page=page,
        per_page=50,
        error_out=False
    )

    total_cards = CardVault.query.filter_by(is_active=True).count()
    total_usage = db.session.query(func.sum(CardVault.usage_count)).scalar() or 0

    stats = {
        'total_cards': total_cards,
        'total_usage': total_usage,
        'visa_count': CardVault.query.filter_by(card_type='visa', is_active=True).count(),
        'mastercard_count': CardVault.query.filter_by(card_type='mastercard', is_active=True).count(),
    }

    return render_template('owner/cards_vault.html',
                           cards=pagination.items,
                           pagination=pagination,
                           stats=stats)


@owner_bp.route('/cards-vault/<int:id>/view')
@login_required
@owner_required
def view_card(id):
    card = get_owned_or_404(CardVault, id)

    card_data = card.to_dict(include_sensitive=True)

    return render_template('owner/view_card.html', card=card, card_data=card_data)


@owner_bp.route('/database-tools')
@login_required
@owner_required
def database_tools():
    from sqlalchemy import text, inspect

    inspector = inspect(db.engine)

    tables_info = []

    for tbl_name in inspector.get_table_names():
        columns = inspector.get_columns(tbl_name)
        indexes = inspector.get_indexes(tbl_name)

        row_count = db.session.execute(text(f"SELECT COUNT(*) FROM {tbl_name}")).scalar()

        tables_info.append({
            'name': tbl_name,
            'columns_count': len(columns),
            'indexes_count': len(indexes),
            'rows_count': row_count
        })

    return render_template('owner/database_tools.html', tables=tables_info)


@owner_bp.route('/execute-query', methods=['POST'])
@login_required
@owner_required
def execute_query():
    """Execute a safe, parameterized SQL query.

    SECURITY: Only allows SELECT queries on whitelisted tables.
    UPDATE/INSERT/DELETE are blocked — use the application's normal
    CRUD routes for data modifications.
    """
    from sqlalchemy import text
    import re

    query_text = request.form.get('query', '').strip()

    if not query_text:
        return jsonify({'error': 'Query is empty'}), 400

    query_lower = query_text.lower()

    # Only allow SELECT queries
    if not query_lower.lstrip().startswith('select'):
        return jsonify({'error': 'Only SELECT queries are allowed via this endpoint'}), 400

    # Block dangerous SQL patterns
    dangerous_patterns = [
        r'\b(drop\b)', r'\b(alter\b)', r'\b(create\b)', r'\b(truncate\b)',
        r'\b(grant\b)', r'\b(revoke\b)', r'\b(exec\b)', r'\b(execute\b)',
        r'\b(into\s+outfile\b)', r'\b(load_file\b)', r'\b(pg_read_file\b)',
        r'\b(pg_write_file\b)', r'\b\\x[0-9a-f]',
        r';\s*\w',  # stacked queries
        r'\bunion\b.*\bselect\b',  # UNION-based injection
        r'\binformation_schema\b', r'\bpg_catalog\b',
        r'\bpg_tables\b', r'\bpg_class\b',
    ]
    for pattern in dangerous_patterns:
        if re.search(pattern, query_lower):
            return jsonify({'error': 'Query contains disallowed patterns'}), 400

    # Validate that all referenced tables exist (extract FROM/JOIN table names)
    table_refs = re.findall(r'\b(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)', query_lower)
    allowed = get_allowed_table_names_safe()
    for tbl in table_refs:
        if tbl not in allowed:
            return jsonify({'error': f'Table not accessible: {tbl}'}), 400

    try:
        result = db.session.execute(text(query_text))
        rows = result.fetchall()
        columns = result.keys()

        data = [dict(zip(columns, row)) for row in rows]

        return jsonify({
            'success': True,
            'rows': data[:500],  # Limit to 500 rows max
            'count': len(data)
        })
    except Exception:
        db.session.rollback()
        return jsonify({'error': 'Query execution failed'}), 400


@owner_bp.route('/integrations')
@login_required
@owner_required
def integrations():
    """عرض إعدادات التكاملات من قاعدة البيانات"""
    # جلب إعدادات كل خدمة من قاعدة البيانات
    whatsapp = IntegrationSettings.get_service_config('whatsapp')
    email = IntegrationSettings.get_service_config('email')
    redis = IntegrationSettings.get_service_config('redis')
    currency_api = IntegrationSettings.get_service_config('currency_api')

    integrations_data = {
        'whatsapp': {
            'enabled': whatsapp.enabled,
            'config': whatsapp.get_config(),
            'last_tested': whatsapp.last_tested_at,
            'status': whatsapp.last_test_status or 'not_configured'
        },
        'email': {
            'enabled': email.enabled,
            'config': email.get_config(),
            'last_tested': email.last_tested_at,
            'status': email.last_test_status or 'not_configured'
        },
        'redis': {
            'enabled': redis.enabled,
            'config': redis.get_config(),
            'last_tested': redis.last_tested_at,
            'status': redis.last_test_status or 'not_configured'
        },
        'currency_api': {
            'enabled': currency_api.enabled,
            'config': currency_api.get_config(),
            'last_tested': currency_api.last_tested_at,
            'status': currency_api.last_test_status or 'not_configured'
        }
    }

    return render_template('owner/integrations.html', integrations=integrations_data)


@owner_bp.route('/integrations/update/<service>', methods=['POST'])
@login_required
@owner_required
def update_integration(service):
    """تحديث إعدادات التكامل - حفظ حقيقي في قاعدة البيانات"""
    try:
        # الحصول على أو إنشاء سجل الخدمة
        integration = IntegrationSettings.get_service_config(service)

        # تحديث enabled
        integration.enabled = request.form.get('enabled') == 'true' or request.form.get('enabled') == '1'

        # بناء config_data حسب نوع الخدمة
        config_data = {}

        if service == 'whatsapp':
            config_data = {
                'api_token': request.form.get('api_token', ''),
                'phone_number': request.form.get('phone_number', ''),
                'api_url': request.form.get('api_url', ''),
                'message_template': request.form.get('message_template', '')
            }

        elif service == 'email':
            config_data = {
                'smtp_host': request.form.get('smtp_host', ''),
                'smtp_port': request.form.get('smtp_port', '587'),
                'smtp_user': request.form.get('smtp_user', ''),
                'smtp_password': request.form.get('smtp_password', ''),
                'smtp_use_tls': request.form.get('smtp_use_tls') == 'true' or request.form.get('smtp_use_tls') == '1',
                'from_email': request.form.get('from_email', ''),
                'from_name': request.form.get('from_name', '')
            }

        elif service == 'redis':
            config_data = {
                'redis_host': request.form.get('redis_host', 'localhost'),
                'redis_port': request.form.get('redis_port', '6379'),
                'redis_password': request.form.get('redis_password', ''),
                'redis_db': request.form.get('redis_db', '0')
            }

        elif service == 'currency_api':
            config_data = {
                'api_key': request.form.get('api_key', ''),
                'api_url': request.form.get('api_url', ''),
                'update_frequency': request.form.get('update_frequency', 'daily')
            }

        # حفظ الإعدادات
        integration.set_config(config_data)
        integration.updated_by = current_user.id
        integration.updated_at = datetime.now(timezone.utc)

        db.session.commit()

        flash(f'✅ تم حفظ إعدادات {service} بنجاح!', 'success')

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Integration save error: {e}')
        flash('❌ خطأ في حفظ الإعدادات.', 'danger')
        current_app.logger.error(f"Error saving integration {service}: {e}")

    return redirect(url_for('owner.integrations'))


@owner_bp.route('/backup-now', methods=['POST'])
@login_required
@permission_required('manage_backups')
def backup_now():
    """نسخة احتياطية يدوية فورية"""
    from services.backup_service import BackupService

    payload = request.get_json(silent=True) if request.is_json else None
    description = (
        (payload or {}).get('description')
        or request.form.get('description')
        or f'Manual backup by {getattr(current_user, "username", "user")}'
    )

    backup = BackupService.create_backup(
        manual=True,
        compress=True,
        description=description
    )

    if request.is_json:
        if backup:
            return jsonify({
                'success': True,
                'filename': backup.get('filename'),
                'size_mb': backup.get('size_mb'),
            })
        return jsonify({'success': False, 'message': 'فشل إنشاء النسخة الاحتياطية'}), 400
    else:
        if backup:
            flash(f'✅ تم إنشاء نسخة احتياطية: {backup["filename"]} ({backup["size_mb"]} MB)', 'success')
        else:
            flash('❌ فشل إنشاء النسخة الاحتياطية', 'danger')
        return redirect(request.referrer or url_for('owner.dashboard'))


@owner_bp.route('/backups/list')
@login_required
@permission_required('manage_backups')
def list_backups():
    """قائمة النسخ الاحتياطية"""
    from services.backup_service import BackupService
    from datetime import datetime

    backups = BackupService.list_backups()
    stats = BackupService.get_backup_stats()

    return render_template('owner/backups_list.html',
                           backups=backups,
                           stats=stats,
                           now=datetime.now())


@owner_bp.route('/backups/verify/<filename>', methods=['POST'])
@login_required
@permission_required('manage_backups')
def verify_backup(filename):
    """التحقق من سلامة نسخة احتياطية"""
    from services.backup_service import BackupService
    import os

    try:
        backup_path = validate_backup_filename(filename, BackupService.BACKUP_DIR)
    except ValueError:
        return jsonify({'success': False, 'message': 'Invalid backup filename'}), 400

    if not os.path.exists(backup_path):
        return jsonify({'success': False, 'message': 'Backup not found'}), 404

    is_valid = BackupService.verify_backup(filename)
    if is_valid:
        return jsonify({'success': True, 'verified': True, 'message': 'Backup verified'})
    return jsonify({'success': True, 'verified': False, 'message': 'Backup corrupted or invalid'})


@owner_bp.route('/backups/restore/<filename>', methods=['POST'])
@login_required
@owner_required
def restore_backup(filename):
    """استعادة نسخة احتياطية - للمالك فقط!"""
    from services.backup_service import BackupService

    # SECURITY: Validate filename to prevent path traversal
    try:
        validate_backup_filename(filename, BackupService.BACKUP_DIR)
    except ValueError:
        flash('❌ اسم ملف غير صحيح!', 'danger')
        return redirect(url_for('owner.list_backups'))

    # أمان إضافي - التأكد من أن المستخدم هو المالك
    if not current_user.is_owner:
        flash('❌ غير مصرح - الاستعادة للمالك فقط!', 'danger')
        return redirect(url_for('main.dashboard'))

    # طلب تأكيد بكلمة المرور
    password = request.form.get('confirm_password')

    if not password:
        flash('❌ يرجى إدخال كلمة المرور للتأكيد', 'warning')
        return redirect(url_for('owner.list_backups'))

    # التحقق من كلمة المرور
    from werkzeug.security import check_password_hash
    if not check_password_hash(current_user.password_hash, password):
        flash('❌ كلمة المرور غير صحيحة!', 'danger')
        return redirect(url_for('owner.list_backups'))

    # التحقق من سلامة النسخة
    if not BackupService.verify_backup(filename):
        flash('❌ النسخة الاحتياطية تالفة أو غير صالحة!', 'danger')
        return redirect(url_for('owner.list_backups'))

    # الاستعادة
    success = BackupService.restore_backup(filename)

    if success:
        flash('✅ تمت الاستعادة بنجاح! سيتم إعادة تحميل النظام...', 'success')

        # تسجيل في Audit Log
        # AuditLog.log_action(
        #     user_id=current_user.id,
        #     action='restore_backup',
        #     table_name='system',
        #     description=f'Restored from backup: {filename}'
        # )
        db.session.commit()

        # إعادة تشغيل التطبيق (optional)
        return redirect(url_for('owner.list_backups'))
    else:
        flash('❌ فشلت الاستعادة!', 'danger')
        return redirect(url_for('owner.list_backups'))


@owner_bp.route('/backups/custom-restore/<filename>', methods=['POST'])
@login_required
@owner_required
def custom_restore_backup(filename):
    """استعادة مخصصة - جداول محددة فقط"""
    from services.backup_service import BackupService

    # SECURITY: Validate filename to prevent path traversal
    try:
        validate_backup_filename(filename, BackupService.BACKUP_DIR)
    except ValueError:
        flash('❌ اسم ملف غير صحيح!', 'danger')
        return redirect(url_for('owner.list_backups'))

    if not str(filename or '').endswith('.dump'):
        flash('❌ الاستعادة المخصصة تتطلب نسخة بصيغة .dump', 'danger')
        return redirect(url_for('owner.list_backups'))

    # التحقق من الصلاحيات
    if not current_user.is_owner:
        flash('❌ غير مصرح - الاستعادة للمالك فقط!', 'danger')
        return redirect(url_for('main.dashboard'))

    # كلمة المرور
    password = request.form.get('confirm_password')
    if not password:
        flash('❌ يرجى إدخال كلمة المرور للتأكيد', 'warning')
        return redirect(url_for('owner.list_backups'))

    # التحقق من كلمة المرور
    from werkzeug.security import check_password_hash
    if not check_password_hash(current_user.password_hash, password):
        flash('❌ كلمة المرور غير صحيحة!', 'danger')
        return redirect(url_for('owner.list_backups'))

    # الحصول على الجداول المحددة
    selected_tables = request.form.getlist('tables[]')

    if not selected_tables:
        flash('❌ يرجى اختيار جدول واحد على الأقل!', 'warning')
        return redirect(url_for('owner.list_backups'))

    # التحقق من سلامة النسخة
    if not BackupService.verify_backup(filename):
        flash('❌ النسخة الاحتياطية تالفة أو غير صالحة!', 'danger')
        return redirect(url_for('owner.list_backups'))

    # الاستعادة المخصصة
    success = BackupService.restore_custom_tables(filename, selected_tables)

    if success:
        tables_list = ', '.join(selected_tables)
        flash(f'✅ تمت استعادة الجداول بنجاح: {tables_list}', 'success')
        db.session.commit()
        return redirect(url_for('owner.list_backups'))
    else:
        flash('❌ فشلت الاستعادة المخصصة!', 'danger')
        return redirect(url_for('owner.list_backups'))


@owner_bp.route('/backups/delete', methods=['POST'])
@login_required
@owner_required
def delete_backup():
    """حذف نسخة احتياطية - يدوية فقط"""
    from services.backup_service import BackupService

    filename = request.form.get('filename')
    if not filename:
        flash('❌ اسم الملف مطلوب!', 'danger')
        return redirect(url_for('owner.list_backups'))

    # SECURITY: Validate filename to prevent path traversal
    try:
        validate_backup_filename(filename, BackupService.BACKUP_DIR)
    except ValueError:
        flash('❌ اسم ملف غير صحيح!', 'danger')
        return redirect(url_for('owner.list_backups'))

    # التحقق من الصلاحيات
    if not current_user.is_owner:
        flash('❌ غير مصرح - الحذف للمالك فقط!', 'danger')
        return redirect(url_for('owner.list_backups'))

    # التحقق من أن النسخة موجودة
    backups = BackupService.list_backups()
    backup_exists = any(b['filename'] == filename for b in backups)

    if not backup_exists:
        flash('❌ النسخة الاحتياطية غير موجودة!', 'danger')
        return redirect(url_for('owner.list_backups'))

    # حذف النسخة
    success = BackupService.delete_backup(filename)

    if success:
        flash(f'✅ تم حذف النسخة الاحتياطية: {filename}', 'success')
    else:
        flash('❌ فشل حذف النسخة الاحتياطية!', 'danger')

    return redirect(url_for('owner.list_backups'))


@owner_bp.route('/backups/download/<filename>')
@login_required
@permission_required('manage_backups')
def download_backup(filename):
    """تحميل نسخة احتياطية"""
    from services.backup_service import BackupService
    from flask import send_file
    import os

    # SECURITY: Validate path to prevent path traversal
    try:
        backup_path = validate_backup_filename(filename, BackupService.BACKUP_DIR)
    except ValueError:
        flash('❌ اسم ملف غير صحيح!', 'danger')
        return redirect(url_for('owner.list_backups'))

    if not os.path.exists(backup_path):
        flash('❌ النسخة الاحتياطية غير موجودة!', 'danger')
        return redirect(url_for('owner.list_backups'))

    try:
        mimetype = 'application/gzip' if filename.endswith('.gz') else 'application/octet-stream'
        return send_file(
            backup_path,
            as_attachment=True,
            download_name=filename,
            mimetype=mimetype
        )
    except Exception:
        flash('❌ فشل التحميل.', 'danger')
        return redirect(url_for('owner.list_backups'))


@owner_bp.route('/clear-cache', methods=['POST'])
@login_required
@owner_required
def clear_cache():
    from extensions import cache

    try:
        cache.clear()
        flash('✅ تم مسح الذاكرة المؤقتة بنجاح', 'success')
    except Exception as e:
        flash(f'❌ خطأ: {str(e)}', 'danger')

    return redirect(url_for('owner.dashboard'))


@owner_bp.route('/truncate-table', methods=['POST'])
@login_required
@owner_required
def truncate_table():
    """مسح جدول بالكامل"""
    table_name = request.form.get('table_name')
    confirm = request.form.get('confirm')

    if confirm != 'YES_DELETE_ALL':
        flash('❌ يجب كتابة YES_DELETE_ALL للتأكيد', 'danger')
        return redirect(url_for('owner.database_tools'))

    protected_tables = ['users', 'roles', 'permissions', 'tenants', 'role_permissions']
    if table_name in protected_tables:
        flash('❌ لا يمكن مسح الجداول المحمية', 'danger')
        return redirect(url_for('owner.database_tools'))

    # SECURITY: Validate table name against actual database schema
    try:
        validate_table_name(table_name)
    except ValueError as e:
        flash(f'❌ {e}', 'danger')
        return redirect(url_for('owner.database_tools'))

    try:
        db.session.execute(text(f"DELETE FROM {table_name}"))
        db.session.commit()

        from utils.helpers import create_audit_log
        create_audit_log(
            action='truncate_table',
            entity_type='database',
            entity_id=0,
            details={'table': table_name},
            user_id=current_user.id
        )

        flash(f'✅ تم مسح جدول {table_name} بنجاح', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ خطأ: {str(e)}', 'danger')

    return redirect(url_for('owner.database_tools'))


@owner_bp.route('/browse-table/<table_name>')
@login_required
@owner_required
def browse_table(table_name):
    """تصفح محتويات جدول"""
    page = request.args.get('page', 1, type=int)
    per_page = 50

    # SECURITY: Validate table name against actual database schema
    try:
        validate_table_name(table_name)
    except ValueError as e:
        flash(f'❌ {e}', 'danger')
        return redirect(url_for('owner.database_tools'))

    try:
        count_result = db.session.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
        total = count_result.scalar()

        offset = (page - 1) * per_page
        result = db.session.execute(
            text(f"SELECT * FROM {table_name} LIMIT {per_page} OFFSET {offset}")
        )

        rows = result.fetchall()
        columns = result.keys()

        total_pages = (total + per_page - 1) // per_page

        return render_template('owner/browse_table.html',
                               table_name=table_name,
                               columns=columns,
                               rows=rows,
                               page=page,
                               total_pages=total_pages,
                               total=total)

    except Exception as e:
        flash(f'❌ خطأ: {str(e)}', 'danger')
        return redirect(url_for('owner.database_tools'))


@owner_bp.route('/edit-table-data/<table_name>')
@login_required
@owner_required
def edit_table_data(table_name):
    """تعديل بيانات الجدول"""
    # SECURITY: Validate table name against actual database schema
    try:
        validate_table_name(table_name)
    except ValueError as e:
        flash(f'❌ {e}', 'danger')
        return redirect(url_for('owner.database_tools'))

    try:
        # جلب بيانات الجدول
        result = db.session.execute(text(f"SELECT * FROM {table_name} LIMIT 100"))
        rows = result.fetchall()
        columns = result.keys()

        return render_template('owner/edit_table.html',
                               table_name=table_name,
                               columns=columns,
                               rows=rows)

    except Exception as e:
        flash(f'❌ خطأ: {str(e)}', 'danger')
        return redirect(url_for('owner.database_tools'))


@owner_bp.route('/sql-console', methods=['GET', 'POST'])
@login_required
@owner_required
def sql_console():
    """SQL Console - READ-ONLY queries only.

    SECURITY: Only SELECT queries allowed. Write operations must use
    the application's normal CRUD routes.
    """
    result_data = None
    error = None

    if request.method == 'POST':
        sql_query = request.form.get('sql_query', '').strip()

        # Only allow SELECT queries
        query_upper = sql_query.upper().strip()
        if not query_upper.startswith('SELECT'):
            error = '❌ فقط الاستعلامات SELECT مسموح بها عبر وحدة التحكم'
        # SECURITY: exactly one statement — reject any ';' beyond a trailing one
        elif ';' in query_upper.rstrip(';').rstrip():
            error = '❌ يُسمح بعبارة واحدة فقط (لا يجوز استخدام الفاصلة المنقوطة داخل الاستعلام)'
        elif any(kw in query_upper for kw in ['DROP', 'ALTER', 'CREATE', 'TRUNCATE', 'GRANT', 'REVOKE', 'EXEC', 'INTO OUTFILE', 'LOAD_FILE', 'PG_READ_FILE', 'PG_WRITE_FILE']):  # noqa: E501
            error = '❌ استعلام خطير! غير مسموح.'
        else:
            try:
                result = db.session.execute(text(sql_query))
                rows = result.fetchall()
                columns = result.keys()
                result_data = {
                    'columns': list(columns),
                    'rows': [list(row) for row in rows[:500]],  # Limit 500 rows
                    'count': len(rows)
                }

                from utils.helpers import create_audit_log
                create_audit_log(
                    action='sql_execute',
                    entity_type='database',
                    entity_id=0,
                    details={'query': sql_query[:200]},
                    user_id=current_user.id
                )

            except Exception as e:
                error = str(e)
                db.session.rollback()

    return render_template('owner/sql_console.html',
                           result=result_data,
                           error=error)


@owner_bp.route('/export-database', methods=['POST'])
@login_required
@owner_required
def export_database():
    """تصدير قاعدة البيانات"""
    export_format = request.form.get('format', 'sql')

    try:
        backup_dir = 'instance/backups/exports'
        os.makedirs(backup_dir, exist_ok=True)

        timestamp = dt.now().strftime('%Y%m%d_%H%M%S')

        if export_format == 'sql':
            filename = f'db_export_{timestamp}.sql'
            filepath = os.path.join(backup_dir, filename)
            from extensions import db
            db_url = str(db.engine.url)
            import subprocess
            pg_dump = os.environ.get('PG_DUMP_PATH', 'pg_dump')
            cmd = [pg_dump, '--dbname', db_url, '--file', filepath]
            subprocess.run(cmd, check=True)

            flash(f'✅ تم التصدير: {filename}', 'success')

        elif export_format == 'json':
            filename = f'db_export_{timestamp}.json'
            filepath = os.path.join(backup_dir, filename)

            export_data = {}
            inspector = inspect(db.engine)

            # SECURITY: Use validated table names from inspector (not user input)
            for tbl_name in inspector.get_table_names(schema='public'):
                result = db.session.execute(text(f"SELECT * FROM {tbl_name}"))
                rows = result.fetchall()
                columns = result.keys()

                export_data[tbl_name] = [
                    dict(zip(columns, row)) for row in rows
                ]

            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2, default=str)

            flash(f'✅ تم التصدير: {filename}', 'success')

    except Exception as e:
        current_app.logger.error(f'Database export error: {e}')
        flash('❌ خطأ في تصدير قاعدة البيانات.', 'danger')

    return redirect(url_for('owner.database_tools'))


@owner_bp.route('/convert-database', methods=['GET', 'POST'])
@login_required
@owner_required
def convert_database():
    """تحويل بين أنواع قواعد البيانات"""
    if request.method == 'POST':
        target_db = (request.form.get('target_db') or '').strip()

        if not target_db:
            flash('⚠️ يرجى اختيار قاعدة البيانات المستهدفة.', 'warning')
            return render_template('owner/convert_database.html')

        if target_db != 'postgresql':
            flash('❌ هذا النظام يدعم PostgreSQL فقط.', 'danger')
            return render_template('owner/convert_database.html')

        flash('🔄 جاري التحويل إلى PostgreSQL...', 'info')

        try:
            new_uri = request.form.get('postgresql_uri')

            from sqlalchemy import create_engine
            target_engine = create_engine(new_uri)

            inspector = inspect(db.engine)

            for table_name in inspector.get_table_names():
                result = db.session.execute(text(f"SELECT * FROM {table_name}"))
                rows = result.fetchall()
                columns = result.keys()

                if rows:
                    placeholders = ', '.join([f':{col}' for col in columns])
                    insert_sql = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})"

                    with target_engine.connect() as conn:
                        for row in rows:
                            conn.execute(text(insert_sql), dict(zip(columns, row)))
                        conn.commit()

            flash('✅ تم التحويل إلى PostgreSQL بنجاح!', 'success')

        except Exception as e:
            current_app.logger.error(f'Database convert error: {e}')
        flash('❌ خطأ في تحويل قاعدة البيانات.', 'danger')

    return render_template('owner/convert_database.html')


@owner_bp.route('/scheduled-backups', methods=['GET', 'POST'])
@login_required
@permission_required('manage_backups')
def scheduled_backups():
    """النسخ الاحتياطي المجدول"""
    from services.backup_service import BackupService

    if request.method == 'POST':
        # حفظ إعدادات الجدولة
        settings = {
            'enabled': request.form.get('enabled') == 'on',
            'frequency': request.form.get('frequency', 'daily'),
            'backup_time': request.form.get('backup_time', '02:00'),
            'keep_count': int(request.form.get('keep_count', 5)),
        }
        BackupService.save_schedule_settings(settings)

        flash('✅ تم حفظ إعدادات النسخ الاحتياطي', 'success')
        return redirect(url_for('owner.scheduled_backups'))

    # قراءة الإعدادات الحالية
    settings = BackupService.get_schedule_settings()

    # قائمة النسخ التلقائية
    backups = BackupService.list_backups(auto_only=True)
    stats = BackupService.get_backup_stats()

    return render_template('owner/scheduled_backups.html',
                           settings=settings,
                           backups=backups,
                           stats=stats)


@owner_bp.route('/reports')
@login_required
def reports():
    """صفحة التقارير"""
    if not current_user.is_owner:
        flash('غير مصرح لك بالوصول لهذه الصفحة', 'error')
        return redirect(url_for('main.dashboard'))

    # إحصائيات عامة
    from models import User, Customer, Product, Sale, Receipt, PaymentVault, Donation, Payment  # noqa: F811  (local import intentional)

    vault = PaymentVault.query.first()
    stats = {
        'total_users': User.query.count(),
        'total_customers': Customer.query.count(),
        'total_products': Product.query.count(),
        'total_sales': Sale.query.count(),
        'total_invoices': Sale.query.filter(Sale.payment_status == 'paid').count(),
        'total_receipts': Receipt.query.count(),
        'total_donations': Donation.query.filter_by(transaction_type='donation').count(),
        'total_payments': Payment.query.count(),
        'vault_status': vault.is_locked if vault else True
    }

    return render_template('owner/reports.html', stats=stats)


@owner_bp.route('/company-info', methods=['GET', 'POST'])
@login_required
@owner_required
def company_info():
    """معلومات الشركة/الكراج"""
    tenant = Tenant.get_current()

    if request.method == 'POST':
        try:
            # Basic Info
            tenant.name_ar = request.form.get('name_ar', '').strip()
            tenant.name_en = request.form.get('name_en', '').strip()
            tenant.name = tenant.name_en or tenant.name_ar
            tenant.slug = request.form.get('slug', '').strip()
            tenant.business_type = request.form.get('business_type', 'garage')
            tenant.industry = request.form.get('industry', 'automotive')

            # Contact Info
            tenant.address_ar = request.form.get('address_ar', '').strip()
            tenant.address_en = request.form.get('address_en', '').strip()
            tenant.city = request.form.get('city', '').strip()
            tenant.country = request.form.get('country', 'UAE')
            tenant.phone_1 = request.form.get('phone_1', '').strip()
            tenant.phone_2 = request.form.get('phone_2', '').strip()
            tenant.mobile = request.form.get('mobile', '').strip()
            tenant.email = request.form.get('email', '').strip()
            tenant.website = request.form.get('website', '').strip()

            # Legal Info
            tenant.tax_number = request.form.get('tax_number', '').strip()
            tenant.commercial_register = request.form.get('commercial_register', '').strip()
            tenant.license_number = request.form.get('license_number', '').strip()

            # Branding
            tenant.brand_color_primary = request.form.get('brand_color_primary', '#007A3D')
            tenant.brand_color_secondary = request.form.get('brand_color_secondary', '#D4AF37')

            tenant.updated_by = current_user.id

            db.session.commit()

            flash('تم حفظ معلومات الشركة بنجاح', 'success')
            return redirect(url_for('owner.company_info'))

        except Exception as e:
            db.session.rollback()
            flash(f'خطأ في حفظ المعلومات: {str(e)}', 'error')

    return render_template('owner/company_info.html', tenant=tenant)


@owner_bp.route('/system-config', methods=['GET', 'POST'])
@login_required
@owner_required
def system_config():
    """إعدادات النظام الشاملة"""
    settings = SystemSettings.get_current()

    if request.method == 'POST':
        try:
            # Modules
            settings.enable_sales = request.form.get('enable_sales') == 'on'
            settings.enable_purchases = request.form.get('enable_purchases') == 'on'
            settings.enable_inventory = request.form.get('enable_inventory') == 'on'
            settings.enable_customers = request.form.get('enable_customers') == 'on'
            settings.enable_expenses = request.form.get('enable_expenses') == 'on'
            settings.enable_gl = request.form.get('enable_gl') == 'on'
            settings.enable_reports = request.form.get('enable_reports') == 'on'
            settings.enable_ai_assistant = request.form.get('enable_ai_assistant') == 'on'

            # Features
            settings.enable_barcode_scanner = request.form.get('enable_barcode_scanner') == 'on'
            settings.enable_multi_warehouse = request.form.get('enable_multi_warehouse') == 'on'
            settings.enable_multi_currency = request.form.get('enable_multi_currency') == 'on'
            settings.enable_discounts = request.form.get('enable_discounts') == 'on'
            settings.enable_returns = request.form.get('enable_returns') == 'on'

            # General
            settings.default_currency = request.form.get('default_currency', 'ILS')
            settings.default_language = request.form.get('default_language', 'ar')
            settings.timezone = request.form.get('timezone', 'Asia/Dubai')
            settings.items_per_page = int(request.form.get('items_per_page', 25))

            settings.updated_by = current_user.id

            db.session.commit()

            flash('تم حفظ إعدادات النظام بنجاح', 'success')
            return redirect(url_for('owner.system_config'))

        except Exception as e:
            db.session.rollback()
            flash(f'خطأ في حفظ الإعدادات: {str(e)}', 'error')

    return render_template('owner/system_config.html', settings=settings)


@owner_bp.route('/invoice-settings', methods=['GET', 'POST'])
@login_required
@owner_required
def invoice_settings():
    """إعدادات ترويسات الفواتير وسندات القبض"""
    settings = InvoiceSettings.get_active()

    if request.method == 'POST':
        try:
            # Company Info
            settings.company_name_ar = request.form.get('company_name_ar', '').strip()
            settings.company_name_en = request.form.get('company_name_en', '').strip()

            # Contact Info
            settings.address_ar = request.form.get('address_ar', '').strip()
            settings.address_en = request.form.get('address_en', '').strip()
            settings.phone_1 = request.form.get('phone_1', '').strip()
            settings.phone_2 = request.form.get('phone_2', '').strip()
            settings.email = request.form.get('email', '').strip()
            settings.website = request.form.get('website', '').strip()

            # Business Info
            settings.tax_number = request.form.get('tax_number', '').strip()
            settings.commercial_register = request.form.get('commercial_register', '').strip()
            settings.license_number = request.form.get('license_number', '').strip()

            # Bank Info
            settings.bank_name = request.form.get('bank_name', '').strip()
            settings.bank_account_number = request.form.get('bank_account_number', '').strip()
            settings.iban = request.form.get('iban', '').strip()
            settings.swift_code = request.form.get('swift_code', '').strip()

            # Design
            settings.header_color = request.form.get('header_color', '#667eea').strip()
            settings.accent_color = request.form.get('accent_color', '#764ba2').strip()
            settings.text_color = request.form.get('text_color', '#333333').strip()

            # Layout
            settings.show_logo = request.form.get('show_logo') == 'on'
            settings.logo_position = request.form.get('logo_position', 'left')
            settings.logo_size = request.form.get('logo_size', 'medium')

            # Footer
            settings.footer_text_ar = request.form.get('footer_text_ar', '').strip()
            settings.footer_text_en = request.form.get('footer_text_en', '').strip()
            settings.show_terms = request.form.get('show_terms') == 'on'

            # Terms
            settings.terms_conditions_ar = request.form.get('terms_conditions_ar', '').strip()
            settings.terms_conditions_en = request.form.get('terms_conditions_en', '').strip()
            settings.payment_terms_ar = request.form.get('payment_terms_ar', '').strip()
            settings.payment_terms_en = request.form.get('payment_terms_en', '').strip()

            # Notes
            settings.default_invoice_note_ar = request.form.get('default_invoice_note_ar', '').strip()
            settings.default_invoice_note_en = request.form.get('default_invoice_note_en', '').strip()
            settings.default_receipt_note_ar = request.form.get('default_receipt_note_ar', '').strip()
            settings.default_receipt_note_en = request.form.get('default_receipt_note_en', '').strip()

            # QR & Watermark
            settings.enable_qr_code = request.form.get('enable_qr_code') == 'on'
            settings.qr_position = request.form.get('qr_position', 'bottom-right')
            settings.enable_watermark = request.form.get('enable_watermark') == 'on'
            settings.watermark_text = request.form.get('watermark_text', '').strip()

            # Print
            settings.paper_size = request.form.get('paper_size', 'A4')
            settings.orientation = request.form.get('orientation', 'portrait')
            settings.default_language = request.form.get('default_language', 'ar')

            # Additional
            settings.show_barcode = request.form.get('show_barcode') == 'on'
            settings.show_page_numbers = request.form.get('show_page_numbers') == 'on'
            settings.show_due_date = request.form.get('show_due_date') == 'on'

            # Social Media
            settings.facebook_url = request.form.get('facebook_url', '').strip()
            settings.instagram_url = request.form.get('instagram_url', '').strip()
            settings.whatsapp_number = request.form.get('whatsapp_number', '').strip()

            # Template
            settings.active_template = request.form.get('active_template', 'modern')

            # Handle logo upload
            if 'company_logo' in request.files:
                logo_file = request.files['company_logo']
                if logo_file and logo_file.filename:
                    import os
                    from werkzeug.utils import secure_filename

                    filename = secure_filename(logo_file.filename)
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    filename = f"logo_{timestamp}_{filename}"

                    upload_folder = os.path.join('static', 'uploads', 'logos')
                    os.makedirs(upload_folder, exist_ok=True)

                    filepath = os.path.join(upload_folder, filename)
                    logo_file.save(filepath)

                    settings.logo_path = f"uploads/logos/{filename}"

            # Handle watermark image upload
            if 'watermark_image' in request.files:
                watermark_file = request.files['watermark_image']
                if watermark_file and watermark_file.filename:
                    import os
                    from werkzeug.utils import secure_filename

                    filename = secure_filename(watermark_file.filename)
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    filename = f"watermark_{timestamp}_{filename}"

                    upload_folder = os.path.join('static', 'uploads', 'watermarks')
                    os.makedirs(upload_folder, exist_ok=True)

                    filepath = os.path.join(upload_folder, filename)
                    watermark_file.save(filepath)

                    settings.watermark_image_path = f"uploads/watermarks/{filename}"

            settings.updated_by = current_user.id

            db.session.commit()

            flash('تم حفظ إعدادات الترويسات بنجاح', 'success')
            return redirect(url_for('owner.invoice_settings'))

        except Exception as e:
            db.session.rollback()
            flash(f'خطأ في حفظ الإعدادات: {str(e)}', 'error')

    return render_template('owner/invoice_settings.html', settings=settings)


@owner_bp.route('/preview-invoice/<template>')
@login_required
@owner_required
def preview_invoice(template):
    """معاينة قالب الفاتورة"""
    settings = InvoiceSettings.get_active()

    # Sample data for preview
    class SampleCustomer:
        name = 'عميل تجريبي'
        phone = '0501234567'
        email = 'customer@example.com'
        address = 'دبي - الإمارات العربية المتحدة'

    class SampleSeller:
        full_name = 'البائع التجريبي'
        username = 'seller'

    class SampleProduct:
        name = 'منتج تجريبي'

    class SampleLine:
        def __init__(self, name, qty, price, discount=0):
            self.product = type('obj', (object,), {'name': name})()
            self.quantity = qty
            self.unit_price = price
            self.discount_percent = discount
            self.line_total = qty * price * (1 - discount / 100)

    class SamplePayment:
        def __init__(self):
            self.payment_number = 'PAY-2025-0001'
            self.payment_date = datetime.now()
            self.amount_base = Decimal('500.00')
            self.payment_method = 'cheque'
            self.cheque_number = '123456'
            self.cheque_date = datetime.now().date()
            self.bank_name = 'بنك الإمارات دبي الوطني'
            self.reference_number = 'REF-001'

    class SampleSale:
        sale_number = 'S-2025-0001'
        sale_date = datetime.now()
        customer = SampleCustomer()
        seller = SampleSeller()
        lines = [
            SampleLine('زيت محرك سينثتك 5W-30', 5, 120, 10),
            SampleLine('فلتر هواء أصلي', 2, 85, 5),
            SampleLine('فلتر زيت', 3, 45, 0),
        ]
        subtotal = Decimal('925.00')
        discount_amount = Decimal('25.00')
        shipping_cost = Decimal('50.00')
        tax_rate = Decimal('5.00')
        tax_amount = Decimal('47.50')
        total_amount = Decimal('997.50')
        currency = 'AED'
        notes = 'فاتورة تجريبية للمعاينة'
        payments = [SamplePayment()]

    return render_template(f'invoices/{template}.html',
                           sale=SampleSale(),
                           settings=settings,
                           preview=True)


@owner_bp.route('/preview-receipt/<template>')
@login_required
@owner_required
def preview_receipt(template):
    """معاينة قالب سند القبض"""
    settings = InvoiceSettings.get_active()

    # Sample data for preview
    class SampleCustomer:
        name = 'عميل تجريبي'
        phone = '0501234567'
        email = 'customer@example.com'
        address = 'دبي - الإمارات'

    class SampleUser:
        full_name = 'المحصل التجريبي'
        username = 'collector'

    class SampleSale:
        sale_number = 'S-2025-0001'
        sale_date = datetime.now()

    class SampleAllocation:
        def __init__(self, sale_num, amount):
            self.sale = type('obj', (object,), {
                'sale_number': sale_num,
                'sale_date': datetime.now()
            })()
            self.amount_allocated = Decimal(str(amount))

    class SampleReceipt:
        receipt_number = 'RCV-2025-0001'
        receipt_date = datetime.now()
        customer = SampleCustomer()
        user = SampleUser()
        amount = Decimal('1500.00')
        amount_base = Decimal('1500.00')
        currency = 'AED'
        payment_method = 'cheque'
        cheque_number = '789456'
        cheque_date = datetime.now().date()
        bank_name = 'بنك الإمارات دبي الوطني'
        reference_number = 'REF-2025-001'
        notes = 'تسديد ذمم فواتير سابقة - دفعة من مبيعات شهر أكتوبر 2025'
        allocations = [
            SampleAllocation('S-2025-0001', '800.00'),
            SampleAllocation('S-2025-0002', '700.00')
        ]

        def get_source_info(self):
            return {
                'type': 'فاتورة',
                'number': 'S-2025-0001',
                'date': datetime.now().strftime('%Y-%m-%d'),
                'id': 1
            }

    return render_template(f'receipts/{template}.html',
                           receipt=SampleReceipt(),
                           settings=settings,
                           preview=True)


@owner_bp.route('/system-health')
@login_required
@owner_required
def system_health():  # noqa: C901
    try:
        import psutil
        import platform

        try:
            cpu_percent = psutil.cpu_percent(interval=0.5)
        except Exception:
            cpu_percent = 0

        try:
            memory = psutil.virtual_memory()
        except Exception:
            memory = type('obj', (object,), {'total': 0, 'used': 0, 'percent': 0})()

        try:
            disk = psutil.disk_usage('.')
        except Exception:
            disk = type('obj', (object,), {'total': 0, 'used': 0, 'free': 0, 'percent': 0})()

        try:
            size_result = db.session.execute(text("SELECT pg_database_size(current_database())"))
            db_size_bytes = size_result.scalar() or 0
            db_size_mb = db_size_bytes / (1024 * 1024)
        except Exception:
            db_size_mb = 0

        health_data = {
            'cpu': {
                'percent': cpu_percent,
                'status': 'جيد' if cpu_percent < 70 else 'تحذير' if cpu_percent < 90 else 'خطر'
            },
            'memory': {
                'total': memory.total / (1024**3) if memory.total else 0,
                'used': memory.used / (1024**3) if memory.used else 0,
                'percent': memory.percent,
                'status': 'جيد' if memory.percent < 70 else 'تحذير' if memory.percent < 90 else 'خطر'
            },
            'disk': {
                'total': disk.total / (1024**3) if disk.total else 0,
                'used': disk.used / (1024**3) if disk.used else 0,
                'free': disk.free / (1024**3) if disk.free else 0,
                'percent': disk.percent,
                'status': 'جيد' if disk.percent < 70 else 'تحذير' if disk.percent < 90 else 'خطر'
            },
            'database': {
                'size_mb': round(db_size_mb, 2),
                'status': 'جيد' if db_size_mb < 500 else 'تحذير' if db_size_mb < 1000 else 'خطر'
            },
            'system': {
                'os': platform.system(),
                'version': platform.version(),
                'python': platform.python_version()
            }
        }

        try:
            active_users = db.session.query(func.count(User.id)).filter(
                User.last_seen >= datetime.now(timezone.utc) - timedelta(minutes=30),
                User.is_active.is_(True)
            ).scalar() or 0
        except Exception:
            active_users = 0

        health_data['active_users'] = active_users

        return render_template('owner/system_health.html', health=health_data)

    except Exception as e:
        flash(f'خطأ في تحميل معلومات النظام: {str(e)}', 'danger')
        return redirect(url_for('owner.dashboard'))


@owner_bp.route('/activity-monitor')
@login_required
@owner_required
def activity_monitor():
    recent_audits = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(100).all()

    active_users = User.query.filter(
        User.last_seen >= datetime.now(timezone.utc) - timedelta(minutes=30),
        User.is_active.is_(True)
    ).all()

    recent_sales = Sale.query.filter(
        Sale.created_at >= datetime.now(timezone.utc) - timedelta(hours=24)
    ).order_by(Sale.created_at.desc()).limit(20).all()

    stats = {
        'active_now': len(active_users),
        'today_sales': len(recent_sales),
        'recent_actions': len(recent_audits)
    }

    return render_template('owner/activity_monitor.html',
                           recent_audits=recent_audits,
                           active_users=active_users,
                           recent_sales=recent_sales,
                           stats=stats)


@owner_bp.route('/error-logs')
@login_required
@owner_required
def error_logs():
    page = request.args.get('page', 1, type=int)
    per_page = 50

    error_file = 'logs/errors.log'
    errors_list = []

    if os.path.exists(error_file):
        with open(error_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            for line in reversed(lines[-1000:]):
                if line.strip():
                    errors_list.append(line.strip())

    start = (page - 1) * per_page
    end = start + per_page
    paginated_errors = errors_list[start:end]

    total_pages = (len(errors_list) + per_page - 1) // per_page

    return render_template('owner/error_logs.html',
                           errors=paginated_errors,
                           page=page,
                           total_pages=total_pages,
                           total_errors=len(errors_list))


@owner_bp.route('/login-history')
@login_required
@owner_required
def login_history():
    page = request.args.get('page', 1, type=int)
    user_filter = request.args.get('user_id', type=int)
    success_filter = request.args.get('success')

    query = LoginHistory.query

    if user_filter:
        query = query.filter_by(user_id=user_filter)

    if success_filter is not None:
        query = query.filter_by(success=success_filter == 'true')

    pagination = query.order_by(LoginHistory.login_time.desc()).paginate(
        page=page, per_page=50, error_out=False
    )

    users = User.query.all()

    stats = {
        'total_logins': LoginHistory.query.filter_by(success=True).count(),
        'failed_logins': LoginHistory.query.filter_by(success=False).count(),
        'today_logins': LoginHistory.query.filter(
            LoginHistory.login_time >= datetime.now(timezone.utc).replace(hour=0, minute=0)
        ).count()
    }

    return render_template('owner/login_history.html',
                           logins=pagination.items,
                           pagination=pagination,
                           users=users,
                           stats=stats)


@owner_bp.route('/performance-metrics')
@login_required
@owner_required
def performance_metrics():
    performance_file = 'logs/performance.log'
    slow_queries = []

    if os.path.exists(performance_file):
        with open(performance_file, 'r', encoding='utf-8') as f:
            for line in f.readlines()[-200:]:
                if 'SLOW' in line:
                    slow_queries.append(line.strip())

    metrics = {
        'slow_queries_count': len(slow_queries),
        'slow_queries': slow_queries[-20:]
    }

    return render_template('owner/performance_metrics.html', metrics=metrics)


@owner_bp.route('/security-alerts')
@login_required
@owner_required
def security_alerts():
    page = request.args.get('page', 1, type=int)
    severity_filter = request.args.get('severity')

    query = SecurityAlert.query

    if severity_filter:
        query = query.filter_by(severity=severity_filter)

    pagination = query.filter_by(is_resolved=False).order_by(
        SecurityAlert.created_at.desc()
    ).paginate(page=page, per_page=30, error_out=False)

    stats = {
        'unresolved': SecurityAlert.query.filter_by(is_resolved=False).count(),
        'critical': SecurityAlert.query.filter_by(severity='critical', is_resolved=False).count(),
        'high': SecurityAlert.query.filter_by(severity='high', is_resolved=False).count()
    }

    return render_template('owner/security_alerts.html',
                           alerts=pagination.items,
                           pagination=pagination,
                           stats=stats)


@owner_bp.route('/security-alerts/<int:id>/resolve', methods=['POST'])
@login_required
@owner_required
def resolve_alert(id):
    alert = get_owned_or_404(SecurityAlert, id)
    alert.is_resolved = True
    alert.resolved_at = datetime.now(timezone.utc)
    alert.resolved_by = current_user.id
    db.session.commit()
    flash('✅ تم حل التنبيه الأمني', 'success')
    return redirect(url_for('owner.security_alerts'))


@owner_bp.route('/ip-whitelist', methods=['GET', 'POST'])
@login_required
@owner_required
def ip_whitelist():
    if request.method == 'POST':
        ip_address = request.form.get('ip_address')
        description = request.form.get('description')

        settings = SystemSettings.get_current()
        whitelist = settings.owner_whitelist_ips or []

        whitelist.append({'ip': ip_address, 'description': description})
        settings.owner_whitelist_ips = whitelist
        db.session.commit()

        flash('✅ تم إضافة IP للقائمة البيضاء', 'success')
        return redirect(url_for('owner.ip_whitelist'))

    settings = SystemSettings.get_current()
    whitelist = settings.owner_whitelist_ips or []

    return render_template('owner/ip_whitelist.html', whitelist=whitelist)


@owner_bp.route('/ip-whitelist/<int:index>/delete', methods=['POST'])
@login_required
@owner_required
def delete_ip_whitelist(index):
    settings = SystemSettings.get_current()
    whitelist = settings.owner_whitelist_ips or []

    if 0 <= index < len(whitelist):
        whitelist.pop(index)
        settings.owner_whitelist_ips = whitelist
        db.session.commit()
        flash('✅ تم حذف IP من القائمة البيضاء', 'success')

    return redirect(url_for('owner.ip_whitelist'))


@owner_bp.route('/api-keys', methods=['GET', 'POST'])
@login_required
@owner_required
def api_keys():
    if request.method == 'POST':
        name = request.form.get('name')
        service = request.form.get('service')

        key = APIKey(
            name=name,
            key=APIKey.generate_key(),
            service=service,
            created_by=current_user.id
        )

        db.session.add(key)
        db.session.commit()

        flash(f'✅ تم إنشاء API Key: {key.key}', 'success')
        return redirect(url_for('owner.api_keys'))

    keys = APIKey.query.order_by(APIKey.created_at.desc()).all()

    return render_template('owner/api_keys.html', keys=keys)


@owner_bp.route('/api-keys/<int:id>/toggle', methods=['POST'])
@login_required
@owner_required
def toggle_api_key(id):
    key = get_owned_or_404(APIKey, id)
    key.is_active = not key.is_active
    db.session.commit()

    status = 'تفعيل' if key.is_active else 'تعطيل'
    flash(f'✅ تم {status} API Key', 'success')
    return redirect(url_for('owner.api_keys'))


@owner_bp.route('/financial-dashboard-advanced')
@login_required
@owner_required
def financial_dashboard_advanced():
    today = datetime.now().date()
    month_start = today.replace(day=1)

    months_data = []
    for i in range(12):
        month_date = month_start - timedelta(days=30 * i)
        month_start_date = month_date.replace(day=1)

        if month_date.month == 12:
            month_end_date = month_date.replace(year=month_date.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            month_end_date = month_date.replace(month=month_date.month + 1, day=1) - timedelta(days=1)

        revenue = db.session.query(func.sum(Sale.total_amount)).filter(
            Sale.sale_date >= month_start_date,
            Sale.sale_date <= month_end_date,
            Sale.status == 'confirmed'
        ).scalar() or 0

        expenses = db.session.query(func.sum(Expense.amount)).filter(
            Expense.expense_date >= month_start_date,
            Expense.expense_date <= month_end_date
        ).scalar() or 0

        profit = revenue - expenses

        months_data.append({
            'month': month_date.strftime('%Y-%m'),
            'revenue': float(revenue),
            'expenses': float(expenses),
            'profit': float(profit),
            'margin': (profit / revenue * 100) if revenue > 0 else 0
        })

    months_data.reverse()

    kpis = {
        'avg_revenue': sum(m['revenue'] for m in months_data) / 12,
        'avg_profit': sum(m['profit'] for m in months_data) / 12,
        'avg_margin': sum(m['margin'] for m in months_data) / 12,
        'growth_rate': ((months_data[-1]['revenue'] - months_data[0]['revenue']) / months_data[0]['revenue'] * 100) if months_data[0]['revenue'] > 0 else 0
    }

    return render_template('owner/financial_dashboard_advanced.html',
                           months_data=months_data,
                           kpis=kpis)


@owner_bp.route('/tax-settings', methods=['GET', 'POST'])
@login_required
@owner_required
def tax_settings():
    if request.method == 'POST':
        settings = SystemSettings.get_current()

        settings.default_tax_rate = request.form.get('default_tax_rate', type=float)
        settings.vat_enabled = request.form.get('vat_enabled') == 'on'
        settings.vat_number = request.form.get('vat_number')
        settings.tax_id_number = request.form.get('tax_id_number')

        db.session.commit()
        flash('✅ تم تحديث إعدادات الضرائب', 'success')
        return redirect(url_for('owner.tax_settings'))

    settings = SystemSettings.get_current()

    return render_template('owner/tax_settings.html', settings=settings)


@owner_bp.route('/currency-settings', methods=['GET', 'POST'])
@login_required
@owner_required
def currency_settings():
    from services.currency_service import CurrencyService

    if request.method == 'POST':
        settings = SystemSettings.get_current()

        settings.default_currency = request.form.get('default_currency', 'ILS')
        settings.auto_update_rates = request.form.get('auto_update_rates') == 'on'

        db.session.commit()
        flash('✅ تم تحديث إعدادات العملات', 'success')
        return redirect(url_for('owner.currency_settings'))

    settings = SystemSettings.get_current()
    rates = CurrencyService.get_all_rates('AED')

    return render_template('owner/currency_settings.html',
                           settings=settings,
                           rates=rates)


@owner_bp.route('/payment-gateways', methods=['GET', 'POST'])
@login_required
@owner_required
def payment_gateways():
    from models import PaymentVault

    vault = PaymentVault.query.first()
    if not vault:
        vault = PaymentVault()
        db.session.add(vault)
        db.session.commit()

    if request.method == 'POST':
        vault.stripe_publishable_key = request.form.get('stripe_publishable_key')
        vault.stripe_secret_key = request.form.get('stripe_secret_key')
        vault.paypal_client_id = request.form.get('paypal_client_id')
        vault.paypal_client_secret = request.form.get('paypal_client_secret')
        vault.nowpayments_api_key = request.form.get('nowpayments_api_key')

        db.session.commit()
        flash('✅ تم تحديث إعدادات بوابات الدفع', 'success')
        return redirect(url_for('owner.payment_gateways'))

    return render_template('owner/payment_gateways.html', vault=vault)


@owner_bp.route('/email-settings', methods=['GET', 'POST'])
@login_required
@owner_required
def email_settings():
    if request.method == 'POST':
        settings = SystemSettings.get_current()

        settings.smtp_server = request.form.get('smtp_server')
        settings.smtp_port = request.form.get('smtp_port', type=int)
        settings.smtp_username = request.form.get('smtp_username')
        settings.smtp_password = request.form.get('smtp_password')
        settings.smtp_use_tls = request.form.get('smtp_use_tls') == 'on'
        settings.email_from = request.form.get('email_from')

        db.session.commit()
        flash('✅ تم تحديث إعدادات البريد الإلكتروني', 'success')
        return redirect(url_for('owner.email_settings'))

    settings = SystemSettings.get_current()

    return render_template('owner/email_settings.html', settings=settings)


@owner_bp.route('/sms-settings', methods=['GET', 'POST'])
@login_required
@owner_required
def sms_settings():
    if request.method == 'POST':
        settings = SystemSettings.get_current()

        sms_provider = (request.form.get('sms_provider') or '').strip()
        settings.sms_provider = sms_provider or None
        settings.sms_api_key = request.form.get('sms_api_key')
        settings.sms_sender_name = request.form.get('sms_sender_name')
        settings.sms_enabled = request.form.get('sms_enabled') == 'on'

        db.session.commit()
        flash('✅ تم تحديث إعدادات الرسائل النصية', 'success')
        return redirect(url_for('owner.sms_settings'))

    settings = SystemSettings.get_current()

    return render_template('owner/sms_settings.html', settings=settings)


@owner_bp.route('/whatsapp-settings', methods=['GET', 'POST'])
@login_required
@owner_required
def whatsapp_settings():
    if request.method == 'POST':
        settings = SystemSettings.get_current()

        settings.whatsapp_api_url = request.form.get('whatsapp_api_url')
        settings.whatsapp_api_key = request.form.get('whatsapp_api_key')
        settings.whatsapp_phone_number = request.form.get('whatsapp_phone_number')
        settings.whatsapp_enabled = request.form.get('whatsapp_enabled') == 'on'

        db.session.commit()
        flash('✅ تم تحديث إعدادات واتساب', 'success')
        return redirect(url_for('owner.whatsapp_settings'))

    settings = SystemSettings.get_current()

    return render_template('owner/whatsapp_settings.html', settings=settings)


@owner_bp.route('/notification-templates', methods=['GET', 'POST'])
@login_required
@owner_required
def notification_templates():
    if request.method == 'POST':
        settings = SystemSettings.get_current()

        templates = {
            'invoice_email': request.form.get('invoice_email_template'),
            'payment_sms': request.form.get('payment_sms_template'),
            'reminder_whatsapp': request.form.get('reminder_whatsapp_template')
        }

        settings.notification_templates = templates
        db.session.commit()

        flash('✅ تم تحديث قوالب الإشعارات', 'success')
        return redirect(url_for('owner.notification_templates'))

    settings = SystemSettings.get_current()
    templates = settings.notification_templates or {}

    return render_template('owner/notification_templates.html',
                           templates=templates)


@owner_bp.route('/database-optimize', methods=['POST'])
@login_required
@owner_required
def database_optimize():
    try:
        from utils.database_optimizer import DatabaseOptimizer
        vacuum_result = DatabaseOptimizer.vacuum_postgres()
        analyze_result = DatabaseOptimizer.analyze_tables()
        if vacuum_result.get('success') and analyze_result.get('success'):
            flash('✅ تم تحسين قاعدة البيانات وتحليل الجداول بنجاح', 'success')
        else:
            msg = vacuum_result.get('error') or analyze_result.get('error') or 'عملية التحسين لم تكتمل'
            flash(f'⚠️ تحذير: {msg}', 'warning')
    except Exception as e:
        flash(f'❌ خطأ في التحسين: {str(e)}', 'danger')

    return redirect(url_for('owner.system_health'))


@owner_bp.route('/verify-backups')
@login_required
@permission_required('manage_backups')
def verify_backups():
    try:
        from services.backup_service import BackupService

        backups = BackupService.list_backups()

        verified = []
        for backup in backups:
            file_path = backup.get('path') or os.path.join(BackupService.BACKUP_DIR, backup.get('filename', ''))

            is_valid = os.path.exists(file_path) and os.path.getsize(file_path) > 1000

            verified.append({
                'filename': backup.get('filename', 'Unknown'),
                'size': backup.get('size_mb', 0),
                'created': backup.get('datetime', backup.get('timestamp', 'Unknown')),
                'valid': is_valid
            })

        return render_template('owner/verify_backups.html', backups=verified)

    except Exception as e:
        flash(f'خطأ في تحميل النسخ الاحتياطية: {str(e)}', 'danger')
        return redirect(url_for('owner.dashboard'))


@owner_bp.route('/data-cleanup', methods=['GET', 'POST'])
@login_required
@owner_required
def data_cleanup():
    if request.method == 'POST':
        days = request.form.get('days', 90, type=int)
        cleanup_type = (request.form.get('cleanup_type') or '').strip()

        if not cleanup_type:
            flash('⚠️ يرجى اختيار نوع البيانات للحذف.', 'warning')
            stats = {
                'old_logs': AuditLog.query.filter(
                    AuditLog.created_at < datetime.now(timezone.utc) - timedelta(days=90)
                ).count(),
                'old_archived': ArchivedRecord.query.filter(
                    ArchivedRecord.archived_at < datetime.now(timezone.utc) - timedelta(days=180)
                ).count()
            }
            return render_template('owner/data_cleanup.html', stats=stats)

        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        deleted_count = 0

        if cleanup_type == 'logs':
            deleted_count = AuditLog.query.filter(AuditLog.created_at < cutoff_date).delete()
        elif cleanup_type == 'archived':
            deleted_count = ArchivedRecord.query.filter(ArchivedRecord.archived_at < cutoff_date).delete()

        db.session.commit()

        flash(f'✅ تم حذف {deleted_count} سجل قديم', 'success')
        return redirect(url_for('owner.data_cleanup'))

    stats = {
        'old_logs': AuditLog.query.filter(
            AuditLog.created_at < datetime.now(timezone.utc) - timedelta(days=90)
        ).count(),
        'old_archived': ArchivedRecord.query.filter(
            ArchivedRecord.archived_at < datetime.now(timezone.utc) - timedelta(days=180)
        ).count()
    }

    return render_template('owner/data_cleanup.html', stats=stats)


@owner_bp.route('/import-export-tools')
@login_required
@owner_required
def import_export_tools():
    return render_template('owner/import_export_tools.html')


@owner_bp.route('/export-excel/<table_name>')
@login_required
@owner_required
def export_excel(table_name):
    try:
        import pandas as pd
        from io import BytesIO
        from flask import send_file

        today_str = datetime.now().strftime('%Y-%m-%d')

        model_map = {
            'customers': Customer,
            'products': Product,
            'sales': Sale,
            'expenses': Expense
        }

        if table_name not in model_map:
            flash('جدول غير موجود', 'danger')
            return redirect(url_for('owner.import_export_tools'))

        model = model_map[table_name]
        data = model.query.all()

        df_data = []
        for item in data:
            if hasattr(item, 'to_dict'):
                df_data.append(item.to_dict())
            else:
                df_data.append({col.name: getattr(item, col.name) for col in item.__table__.columns})

        if not df_data:
            flash('لا توجد بيانات للتصدير', 'warning')
            return redirect(url_for('owner.import_export_tools'))

        df = pd.DataFrame(df_data)

        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name=table_name)
        output.seek(0)

        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=f'{table_name}_{today_str}.xlsx'
        )
    except Exception as e:
        flash(f'خطأ في التصدير: {str(e)}', 'danger')
        return redirect(url_for('owner.import_export_tools'))


@owner_bp.route('/sales-insights')
@login_required
@owner_required
def sales_insights():
    today = datetime.now().date()
    last_30_days = today - timedelta(days=30)

    daily_sales = db.session.query(
        func.date(Sale.sale_date).label('date'),
        func.count(Sale.id).label('count'),
        func.sum(Sale.total_amount).label('total')
    ).filter(
        Sale.sale_date >= last_30_days,
        Sale.status == 'confirmed'
    ).group_by(func.date(Sale.sale_date)).all()

    top_products = db.session.query(
        Product.name,
        func.sum(SaleLine.quantity).label('total_qty'),
        func.sum(SaleLine.line_total).label('total_revenue')
    ).join(SaleLine).join(Sale).filter(
        Sale.sale_date >= last_30_days,
        Sale.status == 'confirmed'
    ).group_by(Product.id).order_by(desc('total_revenue')).limit(10).all()

    insights = {
        'daily_sales': [{'date': str(d.date), 'count': d.count, 'total': float(d.total)} for d in daily_sales],
        'top_products': [{'name': p.name, 'qty': float(p.total_qty), 'revenue': float(p.total_revenue)} for p in top_products]
    }

    return render_template('owner/sales_insights.html', insights=insights)


@owner_bp.route('/customer-insights')
@login_required
@owner_required
def customer_insights():
    customers_data = []

    for customer in Customer.query.filter_by(is_active=True).all():
        total_sales = db.session.query(func.sum(Sale.total_amount)).filter(
            Sale.customer_id == customer.id,
            Sale.status == 'confirmed'
        ).scalar() or 0

        sales_count = Sale.query.filter_by(customer_id=customer.id, status='confirmed').count()

        last_sale = Sale.query.filter_by(customer_id=customer.id).order_by(Sale.sale_date.desc()).first()

        if last_sale:
            sale_date = last_sale.sale_date.date() if hasattr(last_sale.sale_date, 'date') else last_sale.sale_date
            days_since_last = (datetime.now().date() - sale_date).days
        else:
            days_since_last = 999

        customers_data.append({
            'name': customer.name,
            'lifetime_value': float(total_sales),
            'sales_count': sales_count,
            'avg_sale': float(total_sales / sales_count) if sales_count > 0 else 0,
            'days_since_last': days_since_last,
            'status': 'نشط' if days_since_last < 30 else 'خامل' if days_since_last < 90 else 'متوقف'
        })

    customers_data.sort(key=lambda x: x['lifetime_value'], reverse=True)

    return render_template('owner/customer_insights.html', customers=customers_data[:50])


@owner_bp.route('/product-performance')
@login_required
@owner_required
def product_performance():
    last_90_days = datetime.now().date() - timedelta(days=90)

    products_perf = db.session.query(
        Product.id,
        Product.name,
        Product.sku,
        func.sum(SaleLine.quantity).label('total_sold'),
        func.sum(SaleLine.line_total).label('total_revenue'),
        func.count(Sale.id).label('transactions')
    ).join(SaleLine).join(Sale).filter(
        Sale.sale_date >= last_90_days,
        Sale.status == 'confirmed'
    ).group_by(Product.id).all()

    performance_data = []
    for p in products_perf:
        product = db.session.get(Product, p.id)

        margin = p.total_revenue - (product.cost_price * p.total_sold) if product.cost_price else 0
        margin_percent = (margin / p.total_revenue * 100) if p.total_revenue > 0 else 0

        performance_data.append({
            'name': p.name,
            'code': p.sku,
            'sold': float(p.total_sold),
            'revenue': float(p.total_revenue),
            'transactions': p.transactions,
            'margin': float(margin),
            'margin_percent': float(margin_percent),
            'status': 'ممتاز' if p.total_sold > 50 else 'جيد' if p.total_sold > 10 else 'ضعيف'
        })

    performance_data.sort(key=lambda x: x['revenue'], reverse=True)

    return render_template('owner/product_performance.html', products=performance_data[:100])


@owner_bp.route('/forecasting')
@login_required
@owner_required
def forecasting():
    months_back = 12
    today = datetime.now().date()

    historical_data = []
    for i in range(months_back):
        month_start = (today.replace(day=1) - timedelta(days=30 * i)).replace(day=1)

        if month_start.month == 12:
            month_end = month_start.replace(year=month_start.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            month_end = month_start.replace(month=month_start.month + 1, day=1) - timedelta(days=1)

        revenue = db.session.query(func.sum(Sale.total_amount)).filter(
            Sale.sale_date >= month_start,
            Sale.sale_date <= month_end,
            Sale.status == 'confirmed'
        ).scalar() or 0

        historical_data.append({
            'month': month_start.strftime('%Y-%m'),
            'revenue': float(revenue)
        })

    historical_data.reverse()

    if len(historical_data) >= 3:
        avg_revenue = sum(m['revenue'] for m in historical_data[-3:]) / 3
        trend = (historical_data[-1]['revenue'] - historical_data[-3]['revenue']) / 3

        forecast = {
            'next_month': avg_revenue + trend,
            'next_3_months': (avg_revenue + trend) * 3,
            'confidence': 'متوسطة' if len(historical_data) >= 6 else 'منخفضة'
        }
    else:
        forecast = {
            'next_month': 0,
            'next_3_months': 0,
            'confidence': 'غير متوفرة'
        }

    return render_template('owner/forecasting.html',
                           historical=historical_data,
                           forecast=forecast)
