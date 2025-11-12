"""
Enhanced Logging System - نظام تسجيل محسّن
"""

import io
import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler


def _ensure_utf8_stream(stream):
    """
    ضمان أن المجرى (stdout / stderr) يستخدم UTF-8 لتفادي أخطاء الترميز في Windows.
    """
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
            return stream
        except Exception:
            pass
    if hasattr(stream, "buffer"):
        try:
            return io.TextIOWrapper(stream.buffer, encoding="utf-8", errors="replace")
        except Exception:
            pass
    return stream


def setup_enhanced_logging(app):
    """إعداد نظام تسجيل محسّن"""
    
    # إنشاء مجلد logs إن لم يكن موجوداً
    logs_dir = 'logs'
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)
    
    # =====================================
    # File Handlers
    # =====================================
    
    # 1. General Application Log (Rotating)
    app_handler = RotatingFileHandler(
        os.path.join(logs_dir, 'app.log'),
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=10,
        encoding='utf-8'
    )
    app_handler.setLevel(logging.INFO)
    app_handler.setFormatter(logging.Formatter(
        '[%(asctime)s] %(levelname)s in %(module)s:%(lineno)d - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    
    # 2. Error Log (Errors only)
    error_handler = RotatingFileHandler(
        os.path.join(logs_dir, 'errors.log'),
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(logging.Formatter(
        '[%(asctime)s] %(levelname)s in %(module)s:%(lineno)d\n'
        'Message: %(message)s\n'
        'Path: %(pathname)s\n'
        '%(exc_info)s\n',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    
    # 3. Security Log (مستوى أعلى من الأمان)
    security_handler = RotatingFileHandler(
        os.path.join(logs_dir, 'security.log'),
        maxBytes=5 * 1024 * 1024,  # 5MB
        backupCount=10,
        encoding='utf-8'
    )
    security_handler.setLevel(logging.WARNING)
    security_handler.setFormatter(logging.Formatter(
        '[%(asctime)s] SECURITY - %(levelname)s\n'
        'User: %(user)s | IP: %(ip)s\n'
        'Message: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    
    # 4. Performance Log (للاستعلامات البطيئة)
    perf_handler = RotatingFileHandler(
        os.path.join(logs_dir, 'performance.log'),
        maxBytes=5 * 1024 * 1024,  # 5MB
        backupCount=5,
        encoding='utf-8'
    )
    perf_handler.setLevel(logging.INFO)
    perf_handler.setFormatter(logging.Formatter(
        '[%(asctime)s] PERF - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    
    # =====================================
    # إضافة Handlers للـ App Logger
    # =====================================
    app.logger.addHandler(app_handler)
    app.logger.addHandler(error_handler)
    
    # مستوى التسجيل
    app.logger.setLevel(logging.INFO if not app.debug else logging.DEBUG)
    
    # =====================================
    # Console Handler (للتطوير)
    # =====================================
    utf8_stdout = _ensure_utf8_stream(sys.stdout)
    utf8_stderr = _ensure_utf8_stream(sys.stderr)

    # إزالة أي معالجات بث سابقة لتجنب التكرار
    for handler in list(app.logger.handlers):
        if isinstance(handler, logging.StreamHandler) and handler.stream in (sys.stdout, sys.stderr):
            app.logger.removeHandler(handler)

    console_handler = logging.StreamHandler(utf8_stdout)
    console_handler.setLevel(logging.DEBUG if app.debug else logging.INFO)
    console_handler.setFormatter(logging.Formatter(
        '%(levelname)s: %(message)s'
    ))
    app.logger.addHandler(console_handler)

    werkzeug_logger = logging.getLogger('werkzeug')
    for handler in list(werkzeug_logger.handlers):
        if isinstance(handler, logging.StreamHandler):
            werkzeug_logger.removeHandler(handler)
    werkzeug_logger.addHandler(logging.StreamHandler(utf8_stderr))
    
    app.logger.info('=' * 60)
    app.logger.info('[OK] Enhanced Logging System initialized')
    app.logger.info('=' * 60)
    
    return {
        'app': app_handler,
        'error': error_handler,
        'security': security_handler,
        'performance': perf_handler
    }


class SecurityLogger:
    """مسجل خاص بالأمان"""
    
    @staticmethod
    def log_failed_login(username, ip_address, user_agent):
        """تسجيل محاولة دخول فاشلة"""
        logging.warning(
            f'فشل تسجيل الدخول: {username}',
            extra={'user': username, 'ip': ip_address}
        )
    
    @staticmethod
    def log_successful_login(username, ip_address):
        """تسجيل دخول ناجح"""
        logging.info(
            f'تسجيل دخول ناجح: {username}',
            extra={'user': username, 'ip': ip_address}
        )
    
    @staticmethod
    def log_permission_denied(user, action, ip_address):
        """تسجيل محاولة وصول غير مصرح"""
        logging.warning(
            f'محاولة وصول مرفوضة: {user} حاول {action}',
            extra={'user': user, 'ip': ip_address}
        )
    
    @staticmethod
    def log_rate_limit_exceeded(user, endpoint, ip_address):
        """تسجيل تجاوز rate limit"""
        logging.warning(
            f'تجاوز حد الطلبات: {user} على {endpoint}',
            extra={'user': user, 'ip': ip_address}
        )


class PerformanceLogger:
    """مسجل خاص بالأداء"""
    
    @staticmethod
    def log_slow_query(query, duration):
        """تسجيل استعلام بطيء"""
        if duration > 1.0:  # أكثر من ثانية
            logging.warning(f'استعلام بطيء ({duration:.2f}s): {query}')
    
    @staticmethod
    def log_cache_hit(cache_key):
        """تسجيل cache hit"""
        logging.debug(f'Cache hit: {cache_key}')
    
    @staticmethod
    def log_cache_miss(cache_key):
        """تسجيل cache miss"""
        logging.debug(f'Cache miss: {cache_key}')

