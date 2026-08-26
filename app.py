import os
print("DEBUG: App file starting load...", flush=True)
import sys  # noqa: E402,F401
import uuid  # noqa: E402
from datetime import datetime, timezone  # noqa: E402,F401
import time  # noqa: E402
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP  # noqa: E402,F401
from flask import Flask, render_template, request, g, redirect, url_for, flash  # noqa: E402,F401
from flask_login import current_user, login_required  # noqa: E402,F401
from markupsafe import Markup, escape  # noqa: E402,F401
from werkzeug.routing import BuildError  # noqa: E402,F401

from config import Config, ensure_runtime_dirs, assert_production_sanity  # noqa: E402
from extensions import (  # noqa: E402,F401
    db, migrate, login_manager, csrf, limiter, mail,
    init_extensions, setup_logging
)
from utils.monitoring import setup_advanced_logging  # noqa: E402
from utils.enhanced_logging import setup_enhanced_logging  # noqa: E402
from utils.asset_compression import register_compression_cli  # noqa: E402,F401
from config_redis import init_redis  # noqa: E402,F401
from werkzeug.middleware.proxy_fix import ProxyFix  # noqa: E402

try:
    COMPRESS_AVAILABLE = True
except ImportError:
    COMPRESS_AVAILABLE = False


# ---------------------------------------------------------------------------
# Financial UI filters (Agent 7) — Bidi-safe money, numeric cells, badges.
# Decimal-only arithmetic: every boundary value is coerced via Decimal(str(x))
# so float drift can never reach a rendered amount.
# ---------------------------------------------------------------------------
_MONEY_TWO = Decimal('0.01')
_LRM = '\u200e'  # Left-To-Right Mark: keeps digits contiguous inside RTL rows

_STATUS_BADGE_MAP = {
    'unpaid': ('warning', 'غير مدفوع'),
    'partial': ('info', 'جزئي'),
    'paid': ('success', 'مدفوع'),
    'void': ('secondary', 'ملغي'),
    'bounced': ('danger', 'مرتد'),
}


def _to_decimal(value):
    """Coerce a template value to Decimal (never float math on amounts)."""
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if value is None or isinstance(value, bool):
        return None
    try:
        d = Decimal(str(value).strip().replace(',', ''))
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() else None


def _format_money(value, currency=None):
    """Quantize to 2dp with thousands separators, LRM-embedded for RTL safety."""
    d = _to_decimal(value)
    if d is None:
        return '' if value is None else str(value)
    q = d.quantize(_MONEY_TWO, rounding=ROUND_HALF_UP)
    s = _LRM + format(q, ',.2f') + _LRM
    return f'{s} {currency}' if currency else s


def _format_num(value):
    """Plain grouped 2dp numeric string for right-aligned grid cells."""
    d = _to_decimal(value)
    if d is None:
        return '' if value is None else str(value)
    return format(d.quantize(_MONEY_TWO, rounding=ROUND_HALF_UP), ',.2f')


def _status_badge(status):
    """Map payment status to a Bootstrap badge with Arabic label."""
    key = str(status or '').strip().lower()
    cls, label = _STATUS_BADGE_MAP.get(key, (None, None))
    if cls is None:
        cls, label = 'secondary', str(status or '')
    return Markup('<span class="badge badge-{}">{}</span>'.format(
        cls, escape(label)))


def create_app(config_class=Config):  # noqa: C901
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
    from extensions import login_manager  # noqa: F811  (local import intentional)
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
        _ = True
    except Exception as e:
        ai_import_error = str(e)
        print(f"AI Blueprint Import Error: {ai_import_error}")
        import traceback
        traceback.print_exc()
        _ = False

        # Fallback Blueprint to prevent url_for BuildError
        # This ensures the dashboard doesn't crash even if AI modules are missing
        from flask import Blueprint, render_template, flash, redirect, url_for  # noqa: F401,F811(local import intentional)
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
    from routes.erp_modules import erp_bp
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
    app.register_blueprint(erp_bp)

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
        from flask_login import current_user  # noqa: F811  (local import intentional)
        if current_user.is_authenticated:
            # SECURITY: Session idle timeout — force logout after 30 minutes of inactivity
            from flask import session
            from datetime import datetime as _dt, timedelta as _td
            last_activity = session.get('last_activity')
            if last_activity:
                try:
                    last_seen = _dt.fromisoformat(last_activity)
                    if _dt.now() - last_seen > _td(minutes=30):
                        from flask_login import logout_user
                        logout_user()
                        session.clear()
                        from flask import flash
                        flash('⏰ انتهت صلاحية الجلسة بسبب عدم النشاط. يرجى تسجيل الدخول مرة أخرى.', 'warning')
                        from flask import request as _req
                        from werkzeug.utils import redirect as _redir
                        return _redir(_req.url)
                except (ValueError, TypeError):
                    pass  # Invalid timestamp — let session continue
            session['last_activity'] = _dt.now().isoformat()
            session.permanent = True

            # Owner sees all tenants (no filter); other users are scoped to their tenant
            if hasattr(current_user, 'is_owner') and current_user.is_owner:
                set_current_tenant_id(None)  # Owner bypasses tenant filtering
            elif hasattr(current_user, 'tenant_id') and current_user.tenant_id:
                set_current_tenant_id(current_user.tenant_id)
            else:
                set_current_tenant_id(None)  # Default: no filtering
        else:
            set_current_tenant_id(None)

    # CORS initialization
    from flask_cors import CORS
    CORS(app, origins=app.config.get('CORS_ORIGINS', ['http://localhost:5000']),
         supports_credentials=True, methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'])

    # Security Headers
    @app.after_request
    def add_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=(), payment=()'
        # CSP: restrict script/style sources to self + known CDN (AdminLTE uses jsdelivr)
        csp_directives = [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' cdn.jsdelivr.net",
            "style-src 'self' 'unsafe-inline' cdn.jsdelivr.net fonts.googleapis.com",
            "font-src 'self' fonts.gstatic.com cdn.jsdelivr.net",
            "img-src 'self' data: blob:",
            "connect-src 'self'",
            "frame-ancestors 'self'",
        ]
        response.headers['Content-Security-Policy'] = '; '.join(csp_directives)
        # HSTS: only send over HTTPS (won't affect HTTP in dev, but protects production)
        if not app.config.get('DEBUG', False):
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response

    @app.teardown_appcontext
    def teardown_tenant(exception=None):
        """Clear tenant context at end of request."""
        from models import clear_current_tenant_id
        clear_current_tenant_id()

    # Dynamic base currency per tenant/company - available in all templates & JS
    @app.context_processor
    def inject_base_currency():
        try:
            from services.currency_service import CurrencyService
            base = CurrencyService.get_base_currency()
        except Exception:
            base = 'ILS'
        names = {
            'ILS': 'شيقل', 'JOD': 'دينار أردني', 'AED': 'درهم إماراتي',
            'SAR': 'ريال سعودي', 'USD': 'دولار أمريكي', 'EUR': 'يورو',
            'GBP': 'جنيه إسترليني', 'KWD': 'دينار كويتي', 'QAR': 'ريال قطري',
            'OMR': 'ريال عماني', 'BHD': 'دينار بحريني',
        }
        return {'base_currency': base, 'base_currency_name': names.get(base, base)}

    # Financial grid filters (Agent 7): money / num / status_badge
    app.template_filter('money')(_format_money)
    app.template_filter('num')(_format_num)
    app.template_filter('status_badge')(_status_badge)

    # Models Import (to ensure they are known to SQLAlchemy)
    from models import User, Customer, ProductCategory  # noqa: F401,F811(local import intentional)

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


if __name__ == '__main__':  # noqa: C901
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
    import time  # noqa: F811  (local import intentional)
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
    # SECURITY: Redact credentials from database URI before logging
    _db_log = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if '@' in _db_log:
        _db_log = _db_log.split('@')[0].split('://')[0] + '://***:***@' + _db_log.split('@')[1]
    app.logger.info("Database: %s", _db_log)
    app.logger.info("Starting server on http://%s:%s", host, port)

    app.run(
        host=host,
        port=port,
        debug=debug_mode,
        use_reloader=False
    )
