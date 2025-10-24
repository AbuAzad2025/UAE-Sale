import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from flask import Flask, render_template, request, g, redirect, url_for, flash
from flask_login import current_user
from werkzeug.routing import BuildError

from config import Config, ensure_runtime_dirs, assert_production_sanity
from extensions import (
    db, migrate, login_manager, csrf, limiter, mail,
    init_extensions, setup_logging
)
from utils.monitoring import setup_advanced_logging
from utils.asset_compression import register_compression_cli
from config_redis import init_redis

try:
    from flask_compress import Compress
    COMPRESS_AVAILABLE = True
except ImportError:
    COMPRESS_AVAILABLE = False


def create_app(config_class=Config):
    app = Flask(__name__, 
                static_folder='static',
                template_folder='templates')
    
    app.config.from_object(config_class)
    app.config['JSON_AS_ASCII'] = False
    app.config['TEMPLATES_AUTO_RELOAD'] = True
    
    ensure_runtime_dirs(config_class)
    assert_production_sanity(config_class)
    
    setup_logging(app)
    init_extensions(app)
    setup_advanced_logging(app)
    
    if COMPRESS_AVAILABLE:
        compress = Compress()
        compress.init_app(app)
        app.logger.info("[OK] Flask-Compress enabled")
    
    if app.config.get('CACHE_TYPE') == 'redis':
        init_redis(app)
    
    from models import User, Customer
    
    # تفعيل المستمعات التلقائية للتحديثات المالية
    try:
        from models.events import register_all_listeners
        with app.app_context():
            register_all_listeners()
            app.logger.info("[OK] Event listeners activated")
    except Exception as e:
        app.logger.warning(f"Failed to register event listeners: {e}")
    
    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))
    
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'الرجاء تسجيل الدخول للوصول لهذه الصفحة'
    login_manager.login_message_category = 'warning'
    
    @app.before_request
    def attach_request_id():
        g.request_id = request.headers.get('X-Request-Id') or uuid.uuid4().hex
    
    @app.after_request
    def add_request_id_header(response):
        if hasattr(g, 'request_id'):
            response.headers['X-Request-Id'] = g.request_id
        return response
    
    @app.before_request
    def update_last_seen():
        if current_user.is_authenticated:
            try:
                if not current_user.last_seen or \
                   (datetime.now(timezone.utc) - current_user.last_seen).total_seconds() > 300:
                    current_user.last_seen = datetime.now(timezone.utc)
                    db.session.commit()
            except Exception:
                db.session.rollback()
    
    @app.after_request
    def security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        
        if not app.config.get('DEBUG'):
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        
        response.headers.pop('Server', None)
        response.headers.pop('X-Powered-By', None)
        
        if request.path.startswith('/auth/') or request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
        elif request.path.startswith('/static/'):
            response.cache_control.max_age = 31536000
            response.cache_control.public = True
        
        return response
    
    @app.context_processor
    def inject_globals():
        from utils.constants import CURRENCIES
        from utils.i18n import t, get_current_language, is_rtl
        
        return {
            'app_name': app.config.get('COMPANY_NAME', 'Warehouse Manager'),
            'app_name_ar': app.config.get('COMPANY_NAME_AR', 'نظام المستودع'),
            'currencies': CURRENCIES,
            'now': datetime.now(timezone.utc),
            't': t,  # Translation helper
            'current_language': get_current_language(),
            'is_rtl': is_rtl(),
        }
    
    @app.context_processor
    def inject_permissions():
        def has_permission(permission_code):
            if not current_user.is_authenticated:
                return False
            return current_user.has_permission(permission_code)
        
        def can_see_costs():
            if not current_user.is_authenticated:
                return False
            return current_user.can_see_costs()
        
        return {
            'has_permission': has_permission,
            'can_see_costs': can_see_costs,
        }
    
    @app.template_filter('currency')
    def currency_filter(amount, currency='AED', lang='ar'):
        from utils.helpers import format_currency_display
        return format_currency_display(amount, currency, lang)
    
    @app.template_filter('number')
    def number_filter(value, decimals=2):
        try:
            if value is None:
                return '0.00'
            d = Decimal(str(value))
            return f'{d:,.{decimals}f}'
        except Exception:
            return str(value)
    
    @app.template_filter('date_format')
    def date_format_filter(value, format='%Y-%m-%d'):
        if not value:
            return ''
        if isinstance(value, str):
            return value
        return value.strftime(format)
    
    @app.template_filter('datetime_format')
    def datetime_format_filter(value, format='%Y-%m-%d %H:%M'):
        if not value:
            return ''
        if isinstance(value, str):
            return value
        return value.strftime(format)
    
    @app.errorhandler(403)
    def forbidden(e):
        if request.accept_mimetypes.accept_json:
            return {'error': 'Forbidden'}, 403
        return render_template('errors/403.html'), 403
    
    @app.errorhandler(404)
    def not_found(e):
        if request.accept_mimetypes.accept_json:
            return {'error': 'Not Found'}, 404
        return render_template('errors/404.html'), 404
    
    @app.errorhandler(500)
    def internal_error(e):
        db.session.rollback()
        app.logger.exception('Internal Server Error')
        if request.accept_mimetypes.accept_json:
            return {'error': 'Internal Server Error'}, 500
        return render_template('errors/500.html'), 500
    
    register_blueprints(app)
    
    register_cli(app)
    register_compression_cli(app)
    
    # Register CLI commands
    try:
        from cli_commands import register_cli_commands
        register_cli_commands(app)
        app.logger.info("[OK] Enhanced CLI commands registered")
    except ImportError:
        app.logger.info('CLI commands not available - skipping')
    except Exception as e:
        app.logger.warning(f'Enhanced CLI commands not registered: {e}')
    
    app.logger.info('[OK] Application initialized successfully')
    
    return app


def register_blueprints(app):
    from routes.auth import auth_bp
    from routes.main import main_bp
    from routes.owner import owner_bp
    from routes.payment_vault import payment_vault_bp
    
    # Register public first to handle landing page
    try:
        from routes.public import public_bp
        app.register_blueprint(public_bp)
    except Exception as e:
        app.logger.warning(f'public_bp not registered: {e}')
    
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(owner_bp)
    
    try:
        from routes.customers import customers_bp
        app.register_blueprint(customers_bp)
    except Exception as e:
        app.logger.warning(f'customers_bp not registered: {e}')
    
    try:
        from routes.suppliers import suppliers_bp
        app.register_blueprint(suppliers_bp)
    except Exception as e:
        app.logger.warning(f'suppliers_bp not registered: {e}')
    
    try:
        from routes.products import products_bp
        app.register_blueprint(products_bp)
    except Exception as e:
        app.logger.warning(f'products_bp not registered: {e}')
    
    try:
        from routes.sales import sales_bp
        app.register_blueprint(sales_bp)
    except Exception as e:
        app.logger.warning(f'sales_bp not registered: {e}')
    
    try:
        from routes.purchases import purchases_bp
        app.register_blueprint(purchases_bp)
    except Exception as e:
        app.logger.warning(f'purchases_bp not registered: {e}')
    
    try:
        from routes.payments import payments_bp
        app.register_blueprint(payments_bp)
    except Exception as e:
        app.logger.warning(f'payments_bp not registered: {e}')
    
    try:
        app.register_blueprint(payment_vault_bp)
    except Exception as e:
        app.logger.warning(f'payment_vault_bp not registered: {e}')
    
    try:
        from routes.warehouse import warehouse_bp
        app.register_blueprint(warehouse_bp)
    except Exception as e:
        app.logger.warning(f'warehouse_bp not registered: {e}')
    
    try:
        from routes.reports import reports_bp
        app.register_blueprint(reports_bp)
    except Exception as e:
        app.logger.warning(f'reports_bp not registered: {e}')
    
    try:
        from routes.api import api_bp
        app.register_blueprint(api_bp)
    except Exception as e:
        app.logger.warning(f'api_bp not registered: {e}')
    
    try:
        from routes.ai import ai_bp
        app.register_blueprint(ai_bp)
    except Exception as e:
        app.logger.warning(f'ai_bp not registered: {e}')
    
    try:
        from routes.language import language_bp
        app.register_blueprint(language_bp)
    except Exception as e:
        app.logger.warning(f'language_bp not registered: {e}')
    
    try:
        from routes.users import users_bp
        app.register_blueprint(users_bp)
    except Exception as e:
        app.logger.warning(f'users_bp not registered: {e}')
    
    try:
        from routes.expenses import expenses_bp
        app.register_blueprint(expenses_bp)
    except Exception as e:
        app.logger.warning(f'expenses_bp not registered: {e}')
    
    try:
        from routes.cheques import cheques_bp
        app.register_blueprint(cheques_bp)
    except Exception as e:
        app.logger.warning(f'cheques_bp not registered: {e}')
    
    try:
        from routes.ledger import ledger_bp
        app.register_blueprint(ledger_bp)
    except Exception as e:
        app.logger.warning(f'ledger_bp not registered: {e}')
    
    try:
        from routes.api_docs import api_docs_bp
        app.register_blueprint(api_docs_bp)
    except Exception as e:
        app.logger.warning(f'api_docs_bp not registered: {e}')
    
    try:
        from routes.monitoring import monitoring_bp
        app.register_blueprint(monitoring_bp)
    except Exception as e:
        app.logger.warning(f'monitoring_bp not registered: {e}')
    
    try:
        from routes.graphql import graphql_bp
        app.register_blueprint(graphql_bp)
    except Exception as e:
        app.logger.warning(f'graphql_bp not registered: {e}')
    
    try:
        from routes.gamification import gamification_bp
        app.register_blueprint(gamification_bp)
    except Exception as e:
        app.logger.warning(f'gamification_bp not registered: {e}')
    
    try:
        from routes.whatsapp import whatsapp_bp
        app.register_blueprint(whatsapp_bp)
    except Exception as e:
        app.logger.warning(f'whatsapp_bp not registered: {e}')
    
    try:
        from routes.api_enhanced import api_enhanced_bp
        app.register_blueprint(api_enhanced_bp)
    except Exception as e:
        app.logger.warning(f'api_enhanced_bp not registered: {e}')
    
    try:
        from routes.api_analytics import api_analytics_bp
        app.register_blueprint(api_analytics_bp)
    except Exception as e:
        app.logger.warning(f'api_analytics_bp not registered: {e}')
    
    # packages_bp تم دمجه في payment_vault_bp


def register_cli(app):
    @app.cli.command()
    def init_db():
        db.create_all()
        print('Database initialized')
    
    @app.cli.command()
    def seed_data():
        from models import Role, Permission, User, Currency, Warehouse, ExpenseCategory
        from werkzeug.security import generate_password_hash
        from utils.constants import PERMISSIONS, USER_ROLES, CURRENCIES
        from services.gl_service import GLService
        
        print('Seeding database...')
        
        GLService.ensure_core_accounts()
        print('GL Accounts created')
        
        for code, names in PERMISSIONS.items():
            perm = Permission.query.filter_by(code=code).first()
            if not perm:
                perm = Permission(
                    code=code,
                    name=names['en'],
                    name_ar=names['ar']
                )
                db.session.add(perm)
        
        db.session.commit()
        
        all_permissions = Permission.query.all()
        manager_permissions = [p for p in all_permissions if p.code != 'manage_users' and p.code != 'manage_settings']
        seller_permissions = [p for p in all_permissions if p.code in ['manage_sales', 'manage_payments']]
        
        roles_data = [
            ('super_admin', 'Super Admin', 'سوبر أدمن', all_permissions),
            ('manager', 'Manager', 'مدير', manager_permissions),
            ('seller', 'Seller', 'بائع', seller_permissions),
        ]
        
        for slug, name, name_ar, perms in roles_data:
            role = Role.query.filter_by(slug=slug).first()
            if not role:
                role = Role(slug=slug, name=name, name_ar=name_ar)
                role.permissions = perms
                db.session.add(role)
        
        db.session.commit()
        
        owner_username = app.config.get('OWNER_USERNAME', 'owner')
        owner_password = app.config.get('OWNER_PASSWORD', 'owner@2025!secure')
        owner_email = app.config.get('OWNER_EMAIL', 'owner@system.local')
        
        owner = User.query.filter_by(is_owner=True).first()
        
        if not owner:
            admin_role = Role.query.filter_by(slug='super_admin').first()
            
            owner = User(
                username=owner_username,
                email=owner_email,
                full_name='System Owner',
                full_name_ar='مالك النظام',
                role_id=admin_role.id,
                is_owner=True,
                is_active=True,
                email_verified=True
            )
            owner.set_password(owner_password)
            db.session.add(owner)
            
            print(f'Owner account created:')
            print(f'   Username: {owner_username}')
            print(f'   Password: {owner_password}')
            print(f'   KEEP THIS SECRET!')
        
        admin_role = Role.query.filter_by(slug='super_admin').first()
        admin = User.query.filter_by(username='admin', is_owner=False).first()
        
        if not admin:
            admin = User(
                username='admin',
                email='admin@example.com',
                full_name='System Administrator',
                full_name_ar='مدير النظام',
                role_id=admin_role.id,
                is_active=True
            )
            admin.set_password('admin123')
            db.session.add(admin)
        
        for code, data in CURRENCIES:
            currency = Currency.query.filter_by(code=code).first()
            if not currency:
                currency = Currency(
                    code=code,
                    name=data['en'],
                    name_ar=data['ar'],
                    symbol=data.get('symbol', code),
                    is_base=(code == 'AED')
                )
                db.session.add(currency)
        
        warehouse = Warehouse.query.first()
        if not warehouse:
            warehouse = Warehouse(
                name='Main Warehouse',
                name_ar='المستودع الرئيسي',
                is_main=True,
                is_active=True
            )
            db.session.add(warehouse)
        
        expense_categories = [
            ('رواتب', 'Salaries', '6100'),
            ('إيجار', 'Rent', '6200'),
            ('كهرباء وماء', 'Utilities', '6300'),
            ('صيانة', 'Maintenance', '6400'),
            ('تسويق', 'Marketing', '6500'),
            ('مواصلات', 'Transportation', '6600'),
            ('أخرى', 'Other', '6000'),
        ]
        
        for name_ar, name, gl_code in expense_categories:
            cat = ExpenseCategory.query.filter_by(name=name).first()
            if not cat:
                cat = ExpenseCategory(name=name, name_ar=name_ar, gl_account_code=gl_code)
                db.session.add(cat)
        
        db.session.commit()
        
        print('Database seeded successfully')
        print('')
        print('='*50)
        print('OWNER Account (God Mode):')
        print('='*50)
        print(f'   Username: {owner_username}')
        print(f'   Password: {owner_password}')
        print(f'   Access: /owner/dashboard')
        print(f'   KEEP SECRET - HIGHEST PRIVILEGES!')
        print('')
        print('='*50)
        print('📝 Admin Account:')
        print('='*50)
        print('   Username: admin')
        print('   Password: admin123')
        print('   Access: /dashboard')
        print('='*50)


if __name__ == '__main__':
    app = create_app()
    
    # تهيئة النسخ الاحتياطي التلقائي
    from services.backup_service import BackupService
    BackupService.initialize()
    
    # جدولة النسخ الاحتياطي اليومي
    import threading
    import time
    import json
    
    def schedule_daily_backup():
        """جدولة النسخ الاحتياطي اليومي"""
        while True:
            try:
                # قراءة الإعدادات
                settings_path = 'instance/backup_settings.json'
                if os.path.exists(settings_path):
                    with open(settings_path, 'r', encoding='utf-8') as f:
                        settings = json.load(f)
                else:
                    settings = {
                        'enabled': True,
                        'frequency': 'daily',
                        'backup_time': '02:00',
                        'keep_count': 5
                    }
                
                if settings.get('enabled', True):
                    # حساب الوقت حتى النسخة الاحتياطية التالية
                    now = datetime.now()
                    backup_time = settings.get('backup_time', '02:00')
                    
                    # فقط للتكرار اليومي
                    if settings.get('frequency', 'daily') == 'daily':
                        target_hour, target_minute = map(int, backup_time.split(':'))
                        next_backup = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
                        
                        # إذا فات الوقت اليوم، جدولة للغد
                        if next_backup <= now:
                            from datetime import timedelta
                            next_backup += timedelta(days=1)
                        
                        # الانتظار حتى الوقت المحدد
                        wait_seconds = (next_backup - now).total_seconds()
                        
                        print(f"Next automatic backup scheduled at: {next_backup.strftime('%Y-%m-%d %H:%M:%S')}")
                        time.sleep(wait_seconds)
                        
                        # تنفيذ النسخ الاحتياطي
                        with app.app_context():
                            backup = BackupService.auto_backup_daily()
                            if backup:
                                print(f"Automatic backup completed: {backup['filename']}")
                            else:
                                print("Automatic backup failed")
                    else:
                        # للتكرارات الأخرى، انتظار 24 ساعة
                        time.sleep(86400)
                else:
                    # إذا كان معطلاً، تحقق كل ساعة
                    time.sleep(3600)
                    
            except Exception as e:
                print(f"Backup scheduler error: {e}")
                time.sleep(3600)
    
    try:
        backup_thread = threading.Thread(target=schedule_daily_backup, daemon=True)
        backup_thread.start()
        print("Automatic backup scheduler started")
    except:
        pass
    
    port = int(os.environ.get('PORT', 8080))
    host = os.environ.get('HOST', '0.0.0.0')
    debug_mode = app.config.get('DEBUG', True)
    
    print("=" * 70)
    print(f"🚀 Starting UAE-Sale System")
    print("=" * 70)
    print(f"🌐 Host: {host}")
    print(f"📍 Port: {port}")
    print(f"🐛 Debug: {debug_mode}")
    print(f"📂 Database: {app.config['SQLALCHEMY_DATABASE_URI']}")
    print("=" * 70)
    
    print(f"🚀 Starting server on http://{host}:{port}")
    print("=" * 70)
    
    app.run(
        host=host,
        port=port,
        debug=debug_mode,
        use_reloader=False
    )
