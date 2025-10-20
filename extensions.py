# extensions.py - Flask Extensions
# Warehouse & Sales Management System - Simplified
# Location: /garage_simple/extensions.py

import logging
import sys
import os
from datetime import datetime, timezone

from flask import g, has_request_context, session
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_wtf import CSRFProtect
from flask_caching import Cache
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_mail import Mail
from flask_babel import Babel

# Compression - اختياري
try:
    from flask_compress import Compress
    COMPRESS_AVAILABLE = True
except ImportError:
    COMPRESS_AVAILABLE = False
    logging.warning("Flask-Compress not available - install with: pip install Flask-Compress Brotli")


def get_locale():
    """تحديد اللغة الحالية"""
    if 'language' in session:
        return session.get('language', 'ar')
    return 'ar'

# Optional: Colorama for colored logs
try:
    from colorama import init as colorama_init, Fore, Style
    colorama_init(autoreset=True)
except ImportError:
    class _Fore:
        BLUE = ""; GREEN = ""; YELLOW = ""; RED = ""
    class _Style:
        BRIGHT = ""; RESET_ALL = ""
    Fore, Style = _Fore(), _Style()


# ======================
# Request ID Filter
# ======================
class RequestIdFilter(logging.Filter):
    """Add request ID to log records"""
    def filter(self, record):
        if has_request_context():
            record.request_id = getattr(g, "request_id", "-")
        else:
            record.request_id = "-"
        return True


# ======================
# Color Formatter
# ======================
class ColorFormatter(logging.Formatter):
    """Colored console logging with better PowerShell support"""
    
    # ألوان أفضل لـ PowerShell (خلفية سوداء)
    COLORS = {
        "DEBUG":   Fore.CYAN + Style.BRIGHT,      # سماوي فاتح
        "INFO":    Fore.WHITE + Style.BRIGHT,     # أبيض فاتح
        "WARNING": Fore.YELLOW + Style.BRIGHT,    # أصفر فاتح
        "ERROR":   Fore.RED + Style.BRIGHT,       # أحمر فاتح
        "CRITICAL": Fore.MAGENTA + Style.BRIGHT,  # وردي فاتح
    }

    def format(self, record: logging.LogRecord) -> str:
        # استخدام الألوان فقط في بيئة التطوير
        use_colors = os.environ.get('FLASK_ENV', 'development') == 'development'
        
        if use_colors:
            color = self.COLORS.get(record.levelname, "")
            reset = Style.RESET_ALL
        else:
            color = ""
            reset = ""
        
        req_id = getattr(record, "request_id", "-")
        
        timestamp = self.formatTime(record, '%Y-%m-%d %H:%M:%S')
        message = f"[{timestamp}] {color}{record.levelname:8s}{reset} [{req_id}] {record.name}: {record.getMessage()}"
        
        if record.exc_info:
            message += "\n" + self.formatException(record.exc_info)
        
        return message


# ======================
# Setup Logging
# ======================
def setup_logging(app):
    """Configure application logging with UTF-8 support"""
    level_name = app.config.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    # إعداد UTF-8 encoding للـ stdout/stderr في Windows
    if sys.platform == 'win32':
        import io
        if hasattr(sys.stdout, 'buffer'):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        if hasattr(sys.stderr, 'buffer'):
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.addFilter(RequestIdFilter())
    console_handler.setFormatter(ColorFormatter())

    # Error Handler  
    error_handler = logging.StreamHandler(sys.stderr)
    error_handler.setLevel(logging.ERROR)
    error_handler.addFilter(RequestIdFilter())
    error_handler.setFormatter(ColorFormatter())

    # Configure loggers
    for logger in (app.logger, logging.getLogger()):
        logger.handlers.clear()
        logger.setLevel(level)
        logger.addHandler(console_handler)
        logger.addHandler(error_handler)
        logger.propagate = False

    # Suppress noisy loggers
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    app.logger.info("[OK] Logging configured")


# ======================
# Extensions
# ======================

# Database
db = SQLAlchemy(session_options={"expire_on_commit": False})

# Migrations
migrate = Migrate()

# Login Manager
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "الرجاء تسجيل الدخول للوصول لهذه الصفحة"
login_manager.login_message_category = "warning"

# CSRF Protection
csrf = CSRFProtect()

# Cache
cache = Cache()

# Mail
mail = Mail()

# Rate Limiter
def _rate_limit_key():
    """Custom rate limit key (user or IP)"""
    try:
        from flask_login import current_user
        if getattr(current_user, "is_authenticated", False):
            return f"user:{current_user.get_id()}"
    except Exception:
        pass
    return get_remote_address()

limiter = Limiter(
    key_func=_rate_limit_key,
    default_limits=[],
    storage_uri="memory://",
)

babel = Babel()

# Compression (اختياري)
if COMPRESS_AVAILABLE:
    compress = Compress()
else:
    compress = None


# ======================
# SQLite Optimization
# ======================
from sqlalchemy import event
from sqlalchemy.engine import Engine
import sqlite3

@event.listens_for(Engine, "connect")
def _sqlite_pragmas_on_connect(dbapi_connection, connection_record):
    """Enable SQLite optimizations"""
    if isinstance(dbapi_connection, sqlite3.Connection):
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()
        except Exception as e:
            logging.warning(f"SQLite pragma setup failed: {e}")


# ======================
# Initialize Extensions
# ======================
def init_extensions(app):
    """Initialize all Flask extensions"""
    
    # Database
    db.init_app(app)
    migrate.init_app(app, db)
    
    # Login
    login_manager.init_app(app)
    
    # CSRF
    csrf.init_app(app)
    
    # Cache
    cache.init_app(app)
    
    # Limiter
    limiter.init_app(app)
    
    # Compression - تحسين السرعة
    if compress:
        compress.init_app(app)
        logging.info("[OK] Compression enabled")
    else:
        logging.warning("⚠️ Compression disabled - install Flask-Compress for better performance")
    
    # Rate limit config
    default_limit = app.config.get("RATELIMIT_DEFAULT")
    if default_limit:
        if isinstance(default_limit, str):
            limiter.default_limits = [l.strip() for l in default_limit.split(";") if l.strip()]
        else:
            limiter.default_limits = [default_limit]
    
    # Exempt super admin from rate limiting
    @limiter.request_filter
    def _exempt_super():
        try:
            from flask_login import current_user
            if getattr(current_user, "is_authenticated", False):
                if getattr(current_user, "is_owner", False):
                    return True
                role = getattr(current_user, "role", None)
                if role and role.slug == "super_admin":
                    return True
        except Exception:
            pass
        return False
    
    # Mail (optional)
    if app.config.get("MAIL_USERNAME"):
        mail.init_app(app)
    
    babel.init_app(app, locale_selector=get_locale)
    
    app.logger.info("[OK] Extensions initialized")


# ======================
# Helper Functions
# ======================

def get_or_create(session, model, defaults=None, **kwargs):
    """Get or create a database record"""
    instance = session.query(model).filter_by(**kwargs).first()
    if instance:
        return instance, False
    else:
        params = dict((k, v) for k, v in kwargs.items())
        if defaults:
            params.update(defaults)
        instance = model(**params)
        session.add(instance)
        return instance, True

