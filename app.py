import os
print("DEBUG: App file starting load...", flush=True)
import sys
import uuid
from datetime import datetime, timezone
import time
from decimal import Decimal
from flask import Flask, render_template, request, g, redirect, url_for, flash
from flask_login import current_user, login_required
from werkzeug.routing import BuildError

from config import Config, ensure_runtime_dirs, assert_production_sanity
from extensions import (
    db, migrate, login_manager, csrf, limiter, mail,
    init_extensions, setup_logging
)
from utils.monitoring import setup_advanced_logging
from utils.enhanced_logging import setup_enhanced_logging
from utils.asset_compression import register_compression_cli
from config_redis import init_redis
from werkzeug.middleware.proxy_fix import ProxyFix

try:
    from flask_compress import Compress
    COMPRESS_AVAILABLE = True
except ImportError:
    COMPRESS_AVAILABLE = False


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    # Ensure runtime directories exist
    ensure_runtime_dirs(config_class)
    
    # Verify production sanity (Database check)
    assert_production_sanity(config_class)
    
    # Initialize Extensions
    setup_logging(app)
    init_extensions(app)

    # Initialize User Loader for Flask-Login
    from extensions import login_manager
    from models.user import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    setup_advanced_logging(app)
    setup_enhanced_logging(app)
    
    # --- SYSTEM INTEGRITY CHECK (MASTER KEY) ---
    # print("DEBUG: System Integrity Check...")
    # from utils.system_init import ensure_system_integrity
    # try:
    #     ensure_system_integrity(app)
    #     app.logger.info("[OK] System integrity verified (Master Key active)")
    # except Exception as e:
    #     app.logger.error(f"[ERROR] System integrity check failed: {e}")
    # -------------------------------------------
    
    # Proxy Fix for Nginx/Cloudflare
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
    
    # Register Blueprints
    from routes.auth import auth_bp
    from routes.main import main_bp
    from routes.sales import sales_bp
    from routes.products import products_bp
    from routes.customers import customers_bp
    from routes.reports import reports_bp
    # from routes.settings import settings_bp
    from routes.api import api_bp
    from routes.api_enhanced import api_enhanced_bp
    from routes.suppliers import suppliers_bp
    from routes.purchases import purchases_bp
    from routes.expenses import expenses_bp
    from routes.ledger import ledger_bp
    from routes.owner import owner_bp
    from routes.payments import payments_bp
    # from routes.notifications import notifications_bp
    from routes.warehouse import warehouse_bp
    from routes.language import language_bp
    try:
        from routes.ai import ai_bp
        _ai_enabled = True
    except Exception as e:
        ai_import_error = str(e)
        print(f"AI Blueprint Import Error: {ai_import_error}")
        import traceback
        traceback.print_exc()
        _ai_enabled = False
        
        # Fallback Blueprint to prevent url_for BuildError
        # This ensures the dashboard doesn't crash even if AI modules are missing
        from flask import Blueprint, render_template, flash, redirect, url_for
        ai_bp = Blueprint('ai', __name__, url_prefix='/ai')
        
        @ai_bp.route('/assistant')
        @login_required
        def assistant_page():
            flash(f"AI Module failed to load on server start. Please check logs. Error: {ai_import_error}", "error")
            return redirect(url_for('main.dashboard'))

        @ai_bp.route('/config')
        @login_required
        def config():
            flash(f"AI Module failed to load on server start. Please check logs. Error: {ai_import_error}", "error")
            return redirect(url_for('main.dashboard'))
            
        @ai_bp.route('/chat', methods=['POST'])
        def chat():
            return {"error": "AI Module Unavailable"}, 503

        # Fallback for all other potential AI routes found in routes/ai.py
        # This prevents 404 or BuildError if referenced elsewhere dynamically
        @ai_bp.route('/recommend-price', methods=['POST'])
        def recommend_price(): return {"error": "AI Module Unavailable"}, 503

        @ai_bp.route('/check-stock', methods=['POST'])
        def check_stock(): return {"error": "AI Module Unavailable"}, 503

        @ai_bp.route('/analyze-customer/<int:customer_id>', methods=['GET'])
        def analyze_customer(customer_id): return {"error": "AI Module Unavailable"}, 503

        @ai_bp.route('/exchange-rate/<currency>', methods=['GET'])
        def exchange_rate(currency): return {"error": "AI Module Unavailable"}, 503
        
        @ai_bp.route('/search-market-price/<int:product_id>', methods=['GET'])
        def search_market_price(product_id): return {"error": "AI Module Unavailable"}, 503
        
        @ai_bp.route('/find-compatible/<int:product_id>', methods=['GET'])
        def find_compatible(product_id): return {"error": "AI Module Unavailable"}, 503
        
        @ai_bp.route('/upload-excel', methods=['POST'])
        def upload_excel(): return {"error": "AI Module Unavailable"}, 503

        # Catch-all for any other AI route to avoid crashes
        @ai_bp.route('/<path:path>')
        def catch_all(path):
            flash(f"AI Feature '{path}' is currently unavailable due to system initialization error.", "warning")
            return redirect(url_for('main.dashboard'))
    from routes.users import users_bp
    from routes.cheques import cheques_bp
    from routes.returns import returns_bp
    from routes.advanced_ledger import advanced_ledger_bp
    from routes.admin_ledger import admin_ledger_bp
    from routes.gamification import gamification_bp
    from routes.whatsapp import whatsapp_bp
    from routes.monitoring import monitoring_bp
    from routes.public import public_bp
    from routes.payment_vault import payment_vault_bp
    from routes.approvals import approvals_bp
    from routes.hr import hr_bp
    from routes.api_analytics import api_analytics_bp
    from routes.api_docs import api_docs_bp
    from routes.graphql import graphql_bp
    
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(sales_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(reports_bp)
    # app.register_blueprint(settings_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(api_enhanced_bp)
    app.register_blueprint(suppliers_bp)
    app.register_blueprint(purchases_bp)
    app.register_blueprint(expenses_bp)
    app.register_blueprint(ledger_bp)
    app.register_blueprint(owner_bp)
    app.register_blueprint(payments_bp)
    # app.register_blueprint(notifications_bp)
    app.register_blueprint(warehouse_bp)
    app.register_blueprint(language_bp)
    # Always register AI bp (either real or fallback)
    app.register_blueprint(ai_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(cheques_bp)
    app.register_blueprint(returns_bp)
    app.register_blueprint(advanced_ledger_bp)
    app.register_blueprint(admin_ledger_bp)
    app.register_blueprint(gamification_bp)
    app.register_blueprint(whatsapp_bp)
    app.register_blueprint(monitoring_bp)
    app.register_blueprint(public_bp)
    app.register_blueprint(payment_vault_bp)
    app.register_blueprint(api_analytics_bp)
    app.register_blueprint(api_docs_bp)
    app.register_blueprint(graphql_bp)
    app.register_blueprint(approvals_bp)
    app.register_blueprint(hr_bp)

    # Error Handlers
    from utils.error_handlers import register_error_handlers
    register_error_handlers(app)
    
    # Context Processors
    @app.context_processor
    def utility_processor():
        from utils.helpers import format_currency, timeago
        from utils.constants import CURRENCIES
        from utils.i18n import t, is_rtl, get_current_language
        
        def get_currency_symbol(code):
            for c_code, data in CURRENCIES:
                if c_code == code:
                    return data.get('symbol', code)
            return code
            
        return {
            'format_currency': format_currency,
            'timeago': timeago,
            't': t,
            'is_rtl': is_rtl,
            'get_current_language': get_current_language,
            'get_currency_symbol': get_currency_symbol,
            'company_name': app.config.get('COMPANY_NAME', 'Garage Manager'),
            'current_year': datetime.now().year,
            'now': datetime.now(),
            'ai_enabled': 'ai' in app.blueprints
        }
        
    @app.before_request
    def before_request():
        g.request_start_time = time.time()
        g.request_id = str(uuid.uuid4())
        
        # Determine language (placeholder)
        g.lang_code = 'ar'
        g.rtl = True
        
        # Multi-tenant: set current tenant from logged-in user
        from models import set_current_tenant_id
        from flask_login import current_user
        if current_user.is_authenticated:
            # Owner sees all tenants (no filter); other users are scoped to their tenant
            if hasattr(current_user, 'is_owner') and current_user.is_owner:
                set_current_tenant_id(None)  # Owner bypasses tenant filtering
            elif hasattr(current_user, 'tenant_id') and current_user.tenant_id:
                set_current_tenant_id(current_user.tenant_id)
            else:
                set_current_tenant_id(None)  # Default: no filtering
        else:
            set_current_tenant_id(None)
        
    # Security Headers
    @app.after_request
    def add_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        return response

    @app.teardown_appcontext
    def teardown_tenant(exception=None):
        """Clear tenant context at end of request."""
        from models import clear_current_tenant_id
        clear_current_tenant_id()

    # Models Import (to ensure they are known to SQLAlchemy)
    from models import User, Customer, ProductCategory
    
    # Initialize tenant filter events
    try:
        from models.tenant_scope import install_tenant_filter_events
        install_tenant_filter_events()
        app.logger.info('[OK] Tenant filter events installed')
    except Exception as e:
        app.logger.warning(f'Tenant filter events not installed: {e}')

    # Initialize Listeners
    try:
        from models.events import register_all_listeners
        with app.app_context():
            register_all_listeners()
    except ImportError:
        app.logger.warning("Event listeners not available")
    
    # Register CLI Commands
    # from cli_commands import register_cli
    # register_cli(app)
    # register_compression_cli(app)
    
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


if __name__ == '__main__':
    print("DEBUG: Entering main block...", flush=True)
    try:
        app = create_app()
        print("DEBUG: App created successfully", flush=True)
    except Exception as e:
        print(f"DEBUG: Failed to create app: {e}", flush=True)
        raise e
    
    from services.backup_service import BackupService
    BackupService.initialize()
    
    try:
        from services.auto_approval_service import schedule_auto_approval
        schedule_auto_approval(app)
        app.logger.info("Auto-approval service scheduler started")
    except Exception as e:
        app.logger.warning("Auto-approval service failed: %s", e)
    
    import threading
    import time
    import json
    
    def schedule_daily_backup():
        """جدولة النسخ الاحتياطي اليومي"""
        while True:
            try:
                # Use absolute path for settings
                basedir = os.path.abspath(os.path.dirname(__file__))
                settings_path = os.path.join(basedir, 'instance', 'backup_settings.json')
                
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
                    now = datetime.now()
                    backup_time = settings.get('backup_time', '02:00')
                    
                    if settings.get('frequency', 'daily') == 'daily':
                        target_hour, target_minute = map(int, backup_time.split(':'))
                        next_backup = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
                        
                        if next_backup <= now:
                            from datetime import timedelta
                            next_backup += timedelta(days=1)
                        
                        wait_seconds = (next_backup - now).total_seconds()
                        
                        app.logger.info("Next automatic backup scheduled at %s", next_backup.strftime('%Y-%m-%d %H:%M:%S'))
                        time.sleep(wait_seconds)
                        
                        with app.app_context():
                            backup = BackupService.auto_backup_daily()
                            if backup:
                                app.logger.info("Automatic backup completed: %s", backup['filename'])
                            else:
                                app.logger.warning("Automatic backup failed")
                    else:
                        time.sleep(86400)
                else:
                    time.sleep(3600)
                    
            except Exception as e:
                app.logger.error("Backup scheduler error: %s", e)
                time.sleep(3600)
    
    try:
        backup_thread = threading.Thread(target=schedule_daily_backup, daemon=True)
        backup_thread.start()
        app.logger.info("Automatic backup scheduler started")
    except Exception as e:
        import logging
        logging.warning(f"Backup scheduler failed to start: {e}")
    
    port = int(os.environ.get('PORT', 5000))
    host = os.environ.get('HOST', '0.0.0.0')
    debug_mode = os.environ.get('DEBUG', 'false').lower() in ('true', '1', 'yes')
    
    app.logger.info("Starting UAE-Sale System")
    app.logger.info("Host: %s", host)
    app.logger.info("Port: %s", port)
    app.logger.info("Debug: %s", debug_mode)
    app.logger.info("Database: %s", app.config['SQLALCHEMY_DATABASE_URI'])
    app.logger.info("Starting server on http://%s:%s", host, port)
    
    app.run(
        host=host,
        port=port,
        debug=debug_mode,
        use_reloader=False
    )
