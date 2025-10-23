from datetime import datetime, timezone, timedelta
from decimal import Decimal
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, current_app
from flask_login import login_required, current_user
from sqlalchemy import func, desc
from extensions import db
from models import (
    User, Customer, Product, Sale, SaleLine, Purchase, Payment, Receipt,
    StockMovement, AuditLog, ArchivedRecord, ProductReturn, CardVault, InvoiceSettings,
    Tenant, SystemSettings
)
from utils.decorators import owner_required
from sqlalchemy import text, inspect
import json
import os
import shutil
from datetime import datetime as dt

owner_bp = Blueprint('owner', __name__, url_prefix='/owner')


@owner_bp.route('/dashboard')
@login_required
@owner_required
def dashboard():
    stats = {}
    
    now = datetime.now(timezone.utc)
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
        func.sum(Sale.amount_aed),
        func.sum(Sale.amount_aed - Sale.paid_amount_aed)
    ).filter(
        func.date(Sale.sale_date) == today,
        Sale.status == 'confirmed'
    ).first()
    
    stats['today_sales_count'] = today_sales[0] or 0
    stats['today_sales_amount'] = float(today_sales[1] or 0)
    stats['today_receivables'] = float(today_sales[2] or 0)
    
    month_sales = db.session.query(
        func.count(Sale.id),
        func.sum(Sale.amount_aed)
    ).filter(
        func.date(Sale.sale_date) >= month_start,
        Sale.status == 'confirmed'
    ).first()
    
    stats['month_sales_count'] = month_sales[0] or 0
    stats['month_sales_amount'] = float(month_sales[1] or 0)
    
    year_sales = db.session.query(
        func.sum(Sale.amount_aed)
    ).filter(
        func.date(Sale.sale_date) >= year_start,
        Sale.status == 'confirmed'
    ).scalar() or Decimal('0')
    
    stats['year_sales_amount'] = float(year_sales)
    
    month_purchases = db.session.query(
        func.sum(Purchase.amount_aed)
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
        balance = (sale.amount_aed or Decimal('0')) - (sale.paid_amount_aed or Decimal('0'))
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
        func.sum(Sale.amount_aed).label('total')
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
        Product.is_active == True,
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
        result = db.session.execute(text("SELECT name, sql FROM sqlite_master WHERE type='table'"))
        tables = result.fetchall()
        
        for table in tables:
            table_name = table[0]
            if not table_name.startswith('sqlite_'):
                count_result = db.session.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
                count = count_result.scalar()
                db_stats[table_name] = count
    
    except Exception as e:
        flash(f'خطأ في جلب الإحصائيات: {str(e)}', 'danger')
    
    return render_template('owner/system_stats.html', db_stats=db_stats)


@owner_bp.route('/audit-logs')
@login_required
@owner_required
def audit_logs():
    page = request.args.get('page', 1, type=int)
    action = request.args.get('action', '', type=str)
    user_id = request.args.get('user', type=int)
    
    query = AuditLog.query
    
    if action:
        query = query.filter_by(action=action)
    
    if user_id:
        query = query.filter_by(user_id=user_id)
    
    pagination = query.order_by(AuditLog.created_at.desc()).paginate(
        page=page,
        per_page=50,
        error_out=False
    )
    
    return render_template('owner/audit_logs.html',
                         logs=pagination.items,
                         pagination=pagination)


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
    stats = {
        'total': User.query.count(),
        'active': User.query.filter_by(is_active=True).count(),
        'inactive': User.query.filter_by(is_active=False).count(),
        'owners': User.query.filter_by(is_owner=True).count(),
        'admins': User.query.filter(User.role_id == 1).count(),
        'managers': User.query.filter(User.role_id == 2).count(),
        'sellers': User.query.filter(User.role_id == 3).count(),
    }
    
    return render_template('owner/users_list.html', users=users, stats=stats)


@owner_bp.route('/users/create', methods=['GET', 'POST'])
@login_required
@owner_required
def create_user():
    """إضافة مستخدم جديد"""
    from models import Role
    from werkzeug.security import generate_password_hash
    
    if request.method == 'POST':
        try:
            username = request.form.get('username', '').strip()
            email = request.form.get('email', '').strip()
            password = request.form.get('password', '').strip()
            full_name = request.form.get('full_name', '').strip()
            role_id = request.form.get('role_id', type=int)
            is_owner = request.form.get('is_owner') == 'on'
            
            # التحقق من البيانات
            if not username or not password:
                flash('اسم المستخدم وكلمة المرور إجبارية', 'error')
                return redirect(url_for('owner.create_user'))
            
            # التحقق من عدم وجود المستخدم
            existing = User.query.filter_by(username=username).first()
            if existing:
                flash('اسم المستخدم موجود مسبقاً', 'error')
                return redirect(url_for('owner.create_user'))
            
            # إنشاء المستخدم
            user = User(
                username=username,
                email=email,
                password_hash=generate_password_hash(password),
                full_name=full_name,
                role_id=role_id,
                is_owner=is_owner,
                is_active=True
            )
            
            db.session.add(user)
            db.session.commit()
            
            flash(f'تم إضافة المستخدم {username} بنجاح', 'success')
            return redirect(url_for('owner.users_list'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'خطأ في إضافة المستخدم: {str(e)}', 'error')
    
    roles = Role.query.all()
    return render_template('owner/create_user.html', roles=roles)


@owner_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@owner_required
def edit_user(user_id):
    """تعديل مستخدم"""
    from models import Role
    from werkzeug.security import generate_password_hash
    
    user = User.query.get_or_404(user_id)
    
    if request.method == 'POST':
        try:
            user.username = request.form.get('username', '').strip()
            user.email = request.form.get('email', '').strip()
            user.full_name = request.form.get('full_name', '').strip()
            user.role_id = request.form.get('role_id', type=int)
            user.is_owner = request.form.get('is_owner') == 'on'
            user.is_active = request.form.get('is_active') == 'on'
            
            # تغيير كلمة المرور إن وجدت
            new_password = request.form.get('new_password', '').strip()
            if new_password:
                user.password_hash = generate_password_hash(new_password)
            
            user.updated_by = current_user.id
            
            db.session.commit()
            
            flash(f'تم تحديث المستخدم {user.username} بنجاح', 'success')
            return redirect(url_for('owner.users_list'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'خطأ في تحديث المستخدم: {str(e)}', 'error')
    
    roles = Role.query.all()
    return render_template('owner/edit_user.html', user=user, roles=roles)


@owner_bp.route('/users/<int:user_id>/profile')
@login_required
@owner_required
def user_profile(user_id):
    """الملف الشخصي للمستخدم"""
    user = User.query.get_or_404(user_id)
    
    # إحصائيات المستخدم
    from models import Sale, Payment
    
    stats = {
        'sales_count': Sale.query.count(),
        'sales_total': db.session.query(func.sum(Sale.amount_aed)).filter_by(status='confirmed').scalar() or 0,
        'payments_count': Payment.query.count(),
        'payments_total': db.session.query(func.sum(Payment.amount_aed)).scalar() or 0,
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
    user = User.query.get_or_404(user_id)
    
    # لا يمكن حذف المالك
    if user.is_owner:
        flash('لا يمكن حذف حساب المالك', 'error')
        return redirect(url_for('owner.users_list'))
    
    # لا يمكن حذف نفسك
    if user.id == current_user.id:
        flash('لا يمكنك حذف حسابك الخاص', 'error')
        return redirect(url_for('owner.users_list'))
    
    try:
        # Soft delete - تعطيل بدلاً من الحذف
        user.is_active = False
        user.updated_by = current_user.id
        db.session.commit()
        
        flash(f'تم تعطيل المستخدم {user.username}', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'خطأ في حذف المستخدم: {str(e)}', 'error')
    
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
        func.sum(Sale.amount_aed).label('total_sales'),
        func.sum(Sale.paid_amount_aed).label('total_paid'),
        func.count(Sale.id).label('count')
    ).filter(
        func.date(Sale.sale_date) >= start_date,
        Sale.status == 'confirmed'
    ).first()
    
    purchases_data = db.session.query(
        func.sum(Purchase.amount_aed).label('total_purchases'),
        func.count(Purchase.id).label('count')
    ).filter(
        func.date(Purchase.purchase_date) >= start_date,
        Purchase.status == 'confirmed'
    ).first()
    
    receipts_total = db.session.query(
        func.sum(Receipt.amount_aed)
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
    card = CardVault.query.get_or_404(id)
    
    card_data = card.to_dict(include_sensitive=True)
    
    return render_template('owner/view_card.html', card=card, card_data=card_data)


@owner_bp.route('/database-tools')
@login_required
@owner_required
def database_tools():
    from sqlalchemy import text, inspect
    
    inspector = inspect(db.engine)
    
    tables_info = []
    
    for table_name in inspector.get_table_names():
        columns = inspector.get_columns(table_name)
        indexes = inspector.get_indexes(table_name)
        
        row_count = db.session.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar()
        
        tables_info.append({
            'name': table_name,
            'columns_count': len(columns),
            'indexes_count': len(indexes),
            'rows_count': row_count
        })
    
    return render_template('owner/database_tools.html', tables=tables_info)


@owner_bp.route('/execute-query', methods=['POST'])
@login_required
@owner_required
def execute_query():
    from sqlalchemy import text
    
    query_text = request.form.get('query', '').strip()
    
    if not query_text:
        return jsonify({'error': 'Query is empty'}), 400
    
    query_lower = query_text.lower()
    
    is_select = query_lower.startswith('select')
    is_safe = is_select or query_lower.startswith(('update', 'insert', 'delete'))
    
    if not is_safe:
        return jsonify({'error': 'Only SELECT, UPDATE, INSERT, DELETE allowed'}), 400
    
    try:
        result = db.session.execute(text(query_text))
        
        if is_select:
            rows = result.fetchall()
            columns = result.keys()
            
            data = [dict(zip(columns, row)) for row in rows]
            
            return jsonify({
                'success': True,
                'rows': data,
                'count': len(data)
            })
        else:
            db.session.commit()
            
            return jsonify({
                'success': True,
                'message': f'Query executed. Rows affected: {result.rowcount}'
            })
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400


@owner_bp.route('/integrations')
@login_required
@owner_required
def integrations():
    """عرض إعدادات التكاملات من قاعدة البيانات"""
    from models import IntegrationSettings
    
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
        from models import IntegrationSettings
        
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
        flash(f'❌ خطأ في حفظ الإعدادات: {str(e)}', 'danger')
        logger.error(f"Error saving integration {service}: {e}")
    
    return redirect(url_for('owner.integrations'))


@owner_bp.route('/backup-now', methods=['POST'])
@login_required
@owner_required
def backup_now():
    """نسخة احتياطية يدوية فورية"""
    from services.backup_service import BackupService
    
    description = request.form.get('description', 'Manual backup by owner')
    
    backup = BackupService.create_backup(
        manual=True,
        compress=True,
        description=description
    )
    
    if backup:
        flash(f'✅ تم إنشاء نسخة احتياطية: {backup["filename"]} ({backup["size_mb"]} MB)', 'success')
    else:
        flash('❌ فشل إنشاء النسخة الاحتياطية', 'danger')
    
    return redirect(request.referrer or url_for('owner.dashboard'))


@owner_bp.route('/backups/list')
@login_required
@owner_required  
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


@owner_bp.route('/backups/restore/<filename>', methods=['POST'])
@login_required
@owner_required
def restore_backup(filename):
    """استعادة نسخة احتياطية - للمالك فقط!"""
    from services.backup_service import BackupService
    
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


@owner_bp.route('/backups/delete/<filename>', methods=['POST'])
@login_required
@owner_required
def delete_backup(filename):
    """حذف نسخة احتياطية - يدوية فقط"""
    from services.backup_service import BackupService
    
    # التحقق من الصلاحيات
    if not current_user.is_owner:
        flash('❌ غير مصرح - الحذف للمالك فقط!', 'danger')
        return redirect(url_for('owner.list_backups'))
    
    # منع حذف النسخ التلقائية (أمان)
    if BackupService.BACKUP_PREFIX in filename:
        flash('❌ لا يمكن حذف النسخ التلقائية! النسخ التلقائية محمية ويتم حذفها تلقائياً عند تجاوز الحد الأقصى.', 'warning')
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
@owner_required
def download_backup(filename):
    """تحميل نسخة احتياطية"""
    from services.backup_service import BackupService
    from flask import send_file
    import os
    
    # التحقق من الصلاحيات
    if not current_user.is_owner:
        flash('❌ غير مصرح - التحميل للمالك فقط!', 'danger')
        return redirect(url_for('main.dashboard'))
    
    # التحقق من أن النسخة موجودة
    backup_path = os.path.join(BackupService.BACKUP_DIR, filename)
    
    if not os.path.exists(backup_path):
        flash('❌ النسخة الاحتياطية غير موجودة!', 'danger')
        return redirect(url_for('owner.list_backups'))
    
    try:
        # إرسال الملف للتحميل
        return send_file(
            backup_path,
            as_attachment=True,
            download_name=filename,
            mimetype='application/gzip'
        )
    except Exception as e:
        flash(f'❌ فشل التحميل: {str(e)}', 'danger')
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
    
    protected_tables = ['user', 'role', 'permission']
    if table_name in protected_tables:
        flash('❌ لا يمكن مسح الجداول المحمية', 'danger')
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
    """SQL Console - تنفيذ استعلامات مباشرة"""
    result_data = None
    error = None
    
    if request.method == 'POST':
        sql_query = request.form.get('sql_query', '').strip()
        
        dangerous_keywords = ['DROP DATABASE', 'DROP SCHEMA']
        if any(keyword in sql_query.upper() for keyword in dangerous_keywords):
            error = '❌ استعلام خطير! غير مسموح.'
        else:
            try:
                result = db.session.execute(text(sql_query))
                
                if sql_query.strip().upper().startswith('SELECT'):
                    rows = result.fetchall()
                    columns = result.keys()
                    result_data = {
                        'columns': list(columns),
                        'rows': [list(row) for row in rows],
                        'count': len(rows)
                    }
                else:
                    db.session.commit()
                    result_data = {'message': '✅ تم تنفيذ الاستعلام بنجاح'}
                
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
            
            db_path = 'instance/app.db'
            os.system(f'sqlite3 {db_path} .dump > {filepath}')
            
            flash(f'✅ تم التصدير: {filename}', 'success')
        
        elif export_format == 'json':
            filename = f'db_export_{timestamp}.json'
            filepath = os.path.join(backup_dir, filename)
            
            export_data = {}
            inspector = inspect(db.engine)
            
            for table_name in inspector.get_table_names():
                if not table_name.startswith('sqlite_'):
                    result = db.session.execute(text(f"SELECT * FROM {table_name}"))
                    rows = result.fetchall()
                    columns = result.keys()
                    
                    export_data[table_name] = [
                        dict(zip(columns, row)) for row in rows
                    ]
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2, default=str)
            
            flash(f'✅ تم التصدير: {filename}', 'success')
    
    except Exception as e:
        flash(f'❌ خطأ في التصدير: {str(e)}', 'danger')
    
    return redirect(url_for('owner.database_tools'))


@owner_bp.route('/convert-database', methods=['GET', 'POST'])
@login_required
@owner_required
def convert_database():
    """تحويل بين أنواع قواعد البيانات"""
    if request.method == 'POST':
        target_db = request.form.get('target_db')
        
        if target_db == 'postgresql':
            flash('🔄 جاري التحويل إلى PostgreSQL...', 'info')
            
            try:
                new_uri = request.form.get('postgresql_uri')
                
                from sqlalchemy import create_engine
                target_engine = create_engine(new_uri)
                
                inspector = inspect(db.engine)
                
                for table_name in inspector.get_table_names():
                    if not table_name.startswith('sqlite_'):
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
                flash(f'❌ خطأ في التحويل: {str(e)}', 'danger')
        
        elif target_db == 'mysql':
            flash('MySQL conversion will be available soon', 'info')
    
    return render_template('owner/convert_database.html')


@owner_bp.route('/scheduled-backups', methods=['GET', 'POST'])
@login_required
@owner_required
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
        
        # حفظ في ملف JSON
        import json
        settings_path = 'instance/backup_settings.json'
        with open(settings_path, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=2)
        
        flash('✅ تم حفظ إعدادات النسخ الاحتياطي', 'success')
        return redirect(url_for('owner.scheduled_backups'))
    
    # قراءة الإعدادات الحالية
    import json
    import os
    settings_path = 'instance/backup_settings.json'
    if os.path.exists(settings_path):
        with open(settings_path, 'r', encoding='utf-8') as f:
            settings = json.load(f)
    else:
        settings = {
            'enabled': True,
            'frequency': 'daily',
            'backup_time': '02:00',
            'keep_count': 5,
        }
    
    # قائمة النسخ التلقائية
    backups = BackupService.list_backups(auto_only=True)
    stats = BackupService.get_backup_stats()
    
    return render_template('owner/scheduled_backups.html',
                         settings=settings,
                         backups=backups,
                         stats=stats)


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
            settings.default_currency = request.form.get('default_currency', 'AED')
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
            self.line_total = qty * price * (1 - discount/100)
    
    class SamplePayment:
        def __init__(self):
            self.payment_number = 'PAY-2025-0001'
            self.payment_date = datetime.now()
            self.amount_aed = Decimal('500.00')
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
        amount_aed = Decimal('1500.00')
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
    
    return render_template(f'receipts/{template}.html', 
                         receipt=SampleReceipt(),
                         settings=settings,
                         preview=True)


