import logging
import sys
import os

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
import pickle

try:
    from cachelib.serializers import BaseSerializer

    def patched_dumps(self, value, protocol=pickle.HIGHEST_PROTOCOL):
        try:
            return pickle.dumps(value, protocol)
        except (pickle.PickleError, pickle.PicklingError) as e:
            self._warn(e)
            # Returning bare None makes cache.get() call loads(None) and raise
            # "a bytes-like object is required, not 'NoneType'". Store a
            # pickled None instead: loads() returns None, callers treat it as
            # a cache miss and recompute cleanly.
            return pickle.dumps(None, protocol)

    BaseSerializer.dumps = patched_dumps
except ImportError:
    pass

try:
    from flask_compress import Compress

    COMPRESS_AVAILABLE = True
except ImportError:
    COMPRESS_AVAILABLE = False
    logging.warning(
        "Flask-Compress not available - install with: pip install Flask-Compress Brotli"
    )


def get_locale():
    """تحديد اللغة الحالية"""
    if "language" in session:
        return session.get("language", "ar")
    return "ar"


try:
    from colorama import init as colorama_init, Fore, Style

    colorama_init(autoreset=True)
except ImportError:

    class _Fore:
        BLUE = ""
        GREEN = ""
        YELLOW = ""
        RED = ""

    class _Style:
        BRIGHT = ""
        RESET_ALL = ""

    Fore, Style = _Fore(), _Style()


class RequestIdFilter(logging.Filter):
    """Add request ID to log records"""

    def filter(self, record):
        if has_request_context():
            record.request_id = getattr(g, "request_id", "-")
        else:
            record.request_id = "-"
        return True


class ColorFormatter(logging.Formatter):
    """Colored console logging with better PowerShell support"""

    COLORS = {
        "DEBUG": Fore.CYAN + Style.BRIGHT,  # سماوي فاتح
        "INFO": Fore.WHITE + Style.BRIGHT,  # أبيض فاتح
        "WARNING": Fore.YELLOW + Style.BRIGHT,  # أصفر فاتح
        "ERROR": Fore.RED + Style.BRIGHT,  # أحمر فاتح
        "CRITICAL": Fore.MAGENTA + Style.BRIGHT,  # وردي فاتح
    }

    def format(self, record: logging.LogRecord) -> str:
        use_colors = os.environ.get("FLASK_ENV", "development") == "development"

        if use_colors:
            color = self.COLORS.get(record.levelname, "")
            reset = Style.RESET_ALL
        else:
            color = ""
            reset = ""

        req_id = getattr(record, "request_id", "-")

        timestamp = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        message = f"[{timestamp}] {color}{record.levelname:8s}{reset} [{req_id}] {record.name}: {record.getMessage()}"

        if record.exc_info:
            message += "\n" + self.formatException(record.exc_info)

        try:
            target_encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        except Exception:
            target_encoding = "utf-8"

        try:
            message = message.encode(target_encoding, errors="replace").decode(
                target_encoding, errors="replace"
            )
        except Exception:
            message = message.encode("ascii", "replace").decode("ascii")

        return message


class _CurrentStreamHandler(logging.StreamHandler):
    """StreamHandler that resolves sys.stdout/stderr at emit time.

    A plain StreamHandler captures the stream object at construction. When an
    application is created more than once in the same process (Flask test
    suites, workers), pytest replaces sys.stdout between tests and the stale
    handler writes to a closed stream -> "I/O operation on closed file".
    Resolving the stream on every write also keeps the handler correct when
    the runtime swaps stdout/stderr for UTF-8 wrappers.
    """

    def __init__(self, stream_name="stdout"):
        self._stream_name = stream_name
        super().__init__(stream=getattr(sys, stream_name))

    @property
    def stream(self):
        return getattr(sys, self._stream_name)

    @stream.setter
    def stream(self, value):
        # Ignore StreamHandler's one-time assignment; the property is dynamic.
        pass

    def emit(self, record):
        """Write a log record, tolerating streams with non-UTF-8 encodings.

        On Windows the console stream may use cp1252; writing Arabic text to it
        raises UnicodeEncodeError. Format to UTF-8-safe text first so logging
        never crashes a request just because a message contains non-ASCII.
        """
        try:
            msg = self.format(record)
        except Exception:
            self.handleError(record)
            return
        stream = self.stream
        if stream is None:
            return
        try:
            stream.write(msg + self.terminator)
            stream.flush()
        except UnicodeEncodeError:
            # Fall back to ASCII-safe rendering for this console stream only.
            safe = msg.encode("ascii", errors="replace").decode("ascii")
            try:
                stream.write(safe + self.terminator)
                stream.flush()
            except Exception:
                self.handleError(record)
        except Exception:
            self.handleError(record)


def setup_logging(app):
    """Configure application logging with UTF-8 support"""
    level_name = app.config.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    # Never wrap sys.stdout/stderr under pytest: pytest swaps these streams
    # per test and closes the capture buffers, which closes any TextIOWrapper
    # layered on top and produces "I/O operation on closed file". The dynamic
    # _CurrentStreamHandler below resolves the live stream at emit time, so no
    # wrapping is needed in tests.
    _under_pytest = "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules
    if sys.platform == "win32" and not _under_pytest:
        import io

        # Wrap ONCE. Re-wrapping an already-wrapped stream builds stacked
        # TextIOWrappers over the same buffer; closing one closes them all.
        for _name in ("stdout", "stderr"):
            _stream = getattr(sys, _name)
            if not getattr(_stream, "_erp_utf8_wrapped", False) and hasattr(
                _stream, "buffer"
            ):
                _wrapped = io.TextIOWrapper(
                    _stream.buffer, encoding="utf-8", errors="replace"
                )
                setattr(_wrapped, "_erp_utf8_wrapped", True)
                setattr(sys, _name, _wrapped)

    try:
        from utils.log_sanitizer import SanitizeFilter

        _sanitize = SanitizeFilter()
    except ImportError:
        _sanitize = None

    console_handler = _CurrentStreamHandler("stdout")
    console_handler.setLevel(level)
    console_handler.addFilter(RequestIdFilter())
    if _sanitize:
        console_handler.addFilter(_sanitize)
    console_handler.setFormatter(ColorFormatter())

    error_handler = _CurrentStreamHandler("stderr")
    error_handler.setLevel(logging.ERROR)
    error_handler.addFilter(RequestIdFilter())
    if _sanitize:
        error_handler.addFilter(_sanitize)
    error_handler.setFormatter(ColorFormatter())

    # Configure the app logger only. Clearing/replacing the ROOT logger's
    # handlers removes pytest's capture handlers (caplog) and any handler
    # owned by the embedding runtime — the source of closed-stream errors.
    app.logger.handlers.clear()
    app.logger.setLevel(level)
    app.logger.addHandler(console_handler)
    app.logger.addHandler(error_handler)
    app.logger.propagate = False

    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    app.logger.info("[OK] Logging configured")


db = SQLAlchemy(session_options={"expire_on_commit": False})

migrate = Migrate()

login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "الرجاء تسجيل الدخول للوصول لهذه الصفحة"
login_manager.login_message_category = "warning"


@login_manager.user_loader
def load_user(user_id):
    from models.user import User

    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return None
    if uid <= 0:
        return None
    return db.session.get(User, uid)


from flask_login import AnonymousUserMixin  # noqa: E402

AnonymousUserMixin.is_owner = False
AnonymousUserMixin.is_super_admin = lambda self: False
AnonymousUserMixin.is_manager = lambda self: False
AnonymousUserMixin.is_seller = lambda self: False
AnonymousUserMixin.can_see_costs = lambda self: False

csrf = CSRFProtect()

cache = Cache()

mail = Mail()


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
)

babel = Babel()

if COMPRESS_AVAILABLE:
    compress = Compress()
else:
    compress = None

from sqlalchemy import event  # noqa: E402,F401
from sqlalchemy.engine import Engine  # noqa: E402,F401


def init_extensions(app):

    db.init_app(app)
    migrate.init_app(app, db)

    if app.config.get("SQLALCHEMY_ECHO"):
        from utils.performance_tracker import log_slow_queries

        log_slow_queries(app)

    login_manager.init_app(app)

    csrf.init_app(app)

    cache.init_app(app)

    limiter.init_app(app)

    if compress:
        compress.init_app(app)
        logging.info("[OK] Compression enabled")
    else:
        logging.warning(
            "⚠️ Compression disabled - install Flask-Compress for better performance"
        )

    default_limit = app.config.get("RATELIMIT_DEFAULT")
    if default_limit:
        if isinstance(default_limit, str):
            limiter.default_limits = [
                ln.strip() for ln in default_limit.split(";") if ln.strip()
            ]
        else:
            limiter.default_limits = [default_limit]

    def _no_global_bypass():
        return False

    limiter.request_filter(_no_global_bypass)

    if app.config.get("MAIL_USERNAME"):
        mail.init_app(app)

    babel.init_app(app, locale_selector=get_locale)

    app.logger.info("[OK] Extensions initialized")


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
