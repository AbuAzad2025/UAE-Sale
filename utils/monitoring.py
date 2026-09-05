"""
Advanced Monitoring and Logging System
"""
import time
import logging
import json
from datetime import datetime, timezone
from functools import wraps
from flask import request, g, current_app
from extensions import db

try:
    import sentry_sdk
    from sentry_sdk.integrations.flask import FlaskIntegration
    from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
    
    SENTRY_AVAILABLE = True
except ImportError:
    SENTRY_AVAILABLE = False
    sentry_sdk = None


class PerformanceMonitor:
    """Monitor application performance"""

    @staticmethod
    def log_request():
        """Log request details"""
        g.start_time = time.time()
        g.request_id = request.headers.get('X-Request-Id', 'N/A')

    @staticmethod
    def log_response(response):
        """Log response details and timing"""
        if hasattr(g, 'start_time'):
            elapsed = time.time() - g.start_time

            log_data = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'request_id': getattr(g, 'request_id', 'N/A'),
                'method': request.method,
                'path': request.path,
                'status': response.status_code,
                'duration_ms': round(elapsed * 1000, 2),
                'user_agent': request.user_agent.string[:100],
                'ip': request.remote_addr
            }

            if elapsed > 1.0:
                current_app.logger.warning(f"SLOW REQUEST: {json.dumps(log_data)}")
            elif elapsed > 0.5:
                current_app.logger.info(f"REQUEST: {json.dumps(log_data)}")

        return response

    @staticmethod
    def monitor_endpoint(f):
        """Decorator to monitor endpoint performance"""
        @wraps(f)
        def decorated(*args, **kwargs):
            start = time.time()

            try:
                result = f(*args, **kwargs)
                duration = time.time() - start

                current_app.logger.info(
                    f"ENDPOINT {f.__name__}: {round(duration * 1000, 2)}ms"
                )

                return result
            except Exception as e:
                duration = time.time() - start
                current_app.logger.error(
                    f"ENDPOINT ERROR {f.__name__}: {str(e)} after {round(duration * 1000, 2)}ms"
                )
                raise

        return decorated


class DatabaseMonitor:
    """Monitor database performance"""

    @staticmethod
    def log_query(query, duration):
        """Log slow database queries"""
        if duration > 0.1:  # 100ms threshold
            current_app.logger.warning(
                f"SLOW QUERY ({round(duration * 1000, 2)}ms): {query}"
            )


class ErrorLogger:
    """Enhanced error logging"""

    @staticmethod
    def log_error(error, context=None):
        """Log error with context"""
        error_data = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'error_type': type(error).__name__,
            'error_message': str(error),
            'request_id': getattr(g, 'request_id', 'N/A'),
            'path': request.path if request else 'N/A',
            'method': request.method if request else 'N/A',
            'user': getattr(g, 'user', 'anonymous'),
            'context': context or {}
        }

        current_app.logger.error(
            f"ERROR: {json.dumps(error_data, indent=2)}"
        )

        try:
            from models.audit import AuditLog
            audit = AuditLog(
                action='error',
                changes=json.dumps(error_data),
                ip_address=request.remote_addr if request else None
            )
            db.session.add(audit)
            db.session.commit()
        except Exception:
            pass


class MetricsCollector:
    """Collect application metrics"""

    @staticmethod
    def record_metric(metric_name, value, tags=None):
        """Record a metric"""
        metric_data = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'metric': metric_name,
            'value': value,
            'tags': tags or {}
        }

        current_app.logger.info(f"METRIC: {json.dumps(metric_data, default=str)}")

    @staticmethod
    def record_sale(amount, currency):
        """Record sale metric"""
        MetricsCollector.record_metric(
            'sale_created',
            amount,
            {'currency': currency}
        )

    @staticmethod
    def record_payment(amount, method):
        """Record payment metric"""
        MetricsCollector.record_metric(
            'payment_received',
            amount,
            {'method': method}
        )

    @staticmethod
    def record_stock_change(product_id, quantity, movement_type):
        """Record stock change metric"""
        MetricsCollector.record_metric(
            'stock_movement',
            quantity,
            {'product_id': product_id, 'type': movement_type}
        )


class HealthCheck:
    """Application health check"""

    @staticmethod
    def check_database():
        """Check database connectivity"""
        try:
            db.session.execute(db.text('SELECT 1'))
            return {'status': 'healthy', 'message': 'Database connected'}
        except Exception as e:
            return {'status': 'unhealthy', 'message': str(e)}

    @staticmethod
    def check_redis():
        """Check Redis connectivity"""
        try:
            from extensions import cache
            cache.set('health_check', 'ok', timeout=10)
            result = cache.get('health_check')
            if result == 'ok':
                return {'status': 'healthy', 'message': 'Redis connected'}
            return {'status': 'unhealthy', 'message': 'Redis not responding'}
        except Exception as e:
            return {'status': 'unhealthy', 'message': str(e)}

    @staticmethod
    def check_disk_space():
        """Check disk space"""
        try:
            import shutil
            total, used, free = shutil.disk_usage('/')
            percent_used = (used / total) * 100

            if percent_used > 90:
                return {'status': 'unhealthy', 'message': f'Disk {percent_used:.1f}% full'}
            return {'status': 'healthy', 'message': f'Disk {percent_used:.1f}% used'}
        except Exception as e:
            return {'status': 'unknown', 'message': str(e)}

    @staticmethod
    def get_health_status():
        """Get overall health status"""
        checks = {
            'database': HealthCheck.check_database(),
            'redis': HealthCheck.check_redis(),
            'disk': HealthCheck.check_disk_space()
        }

        overall_healthy = all(
            check['status'] == 'healthy'
            for check in checks.values()
        )

        return {
            'status': 'healthy' if overall_healthy else 'unhealthy',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'checks': checks
        }


def init_sentry(app):
    """Initialize Sentry SDK for error tracking"""
    if not SENTRY_AVAILABLE:
        app.logger.info("Sentry SDK not available - skipping initialization")
        return
    
    dsn = app.config.get('SENTRY_DSN')
    if not dsn:
        app.logger.info("SENTRY_DSN not configured - skipping Sentry initialization")
        return
    
    try:
        sentry_sdk.init(
            dsn=dsn,
            integrations=[
                FlaskIntegration(),
                SqlalchemyIntegration(),
            ],
            traces_sample_rate=app.config.get('SENTRY_TRACES_SAMPLE_RATE', 0.1),
            profiles_sample_rate=app.config.get('SENTRY_PROFILES_SAMPLE_RATE', 0.1),
            environment=app.config.get('SENTRY_ENVIRONMENT', 'production'),
            release=app.config.get('APP_VERSION', 'unknown'),
            before_send=_filter_sensitive_data,
            attach_stacktrace=True,
            send_default_pii=False,
        )
        app.logger.info(f"[OK] Sentry initialized for environment: {app.config.get('SENTRY_ENVIRONMENT', 'production')}")
    except Exception as e:
        app.logger.error(f"Failed to initialize Sentry: {e}")


def _filter_sensitive_data(event, hint):
    """Filter sensitive data before sending to Sentry"""
    if 'request' in event:
        # Remove sensitive headers
        sensitive_headers = ['authorization', 'cookie', 'x-api-key', 'x-csrf-token']
        if 'headers' in event['request']:
            for header in sensitive_headers:
                if header in event['request']['headers']:
                    event['request']['headers'][header] = '[FILTERED]'
        
        # Remove sensitive form data
        if 'data' in event['request']:
            if isinstance(event['request']['data'], dict):
                sensitive_keys = ['password', 'token', 'secret', 'api_key', 'credit_card']
                for key in list(event['request']['data'].keys()):
                    if any(sensitive in key.lower() for sensitive in sensitive_keys):
                        event['request']['data'][key] = '[FILTERED]'
    
    return event


class SentryErrorLogger:
    """Enhanced error logging with Sentry integration"""
    
    @staticmethod
    def log_error(error, context=None, level='error'):
        """Log error with context to both local logs and Sentry"""
        # Local logging (existing behavior)
        error_data = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'error_type': type(error).__name__,
            'error_message': str(error),
            'request_id': getattr(g, 'request_id', 'N/A'),
            'path': request.path if request else 'N/A',
            'method': request.method if request else 'N/A',
            'user': getattr(g, 'user', 'anonymous'),
            'context': context or {}
        }
        
        log_func = getattr(current_app.logger, level, current_app.logger.error)
        log_func(f"ERROR: {json.dumps(error_data, indent=2)}")
        
        # Sentry logging
        if SENTRY_AVAILABLE and sentry_sdk.Hub.current.client:
            with sentry_sdk.push_scope() as scope:
                scope.set_tag('request_id', getattr(g, 'request_id', 'N/A'))
                scope.set_tag('path', request.path if request else 'N/A')
                scope.set_tag('method', request.method if request else 'N/A')
                scope.set_context('error_context', context or {})
                
                if getattr(g, 'user', None):
                    scope.set_user({'id': str(g.user.id) if hasattr(g.user, 'id') else str(g.user)})
                
                sentry_sdk.capture_exception(error)
        
        # Audit log (existing behavior)
        try:
            from models.audit import AuditLog
            audit = AuditLog(
                action='error',
                changes=json.dumps(error_data),
                ip_address=request.remote_addr if request else None
            )
            db.session.add(audit)
            db.session.commit()
        except Exception:
            pass


class AIMetricsCollector:
    """Collect AI-specific metrics for performance monitoring"""
    
    _ai_metrics = {
        'total_requests': 0,
        'successful_requests': 0,
        'failed_requests': 0,
        'total_tokens_used': 0,
        'total_cost_usd': 0.0,
        'avg_response_time_ms': 0.0,
        'requests_by_mode': {},
        'requests_by_endpoint': {},
        'error_counts': {},
        'rate_limit_hits': 0,
        'cache_hits': 0,
        'cache_misses': 0,
        'conversation_turns': 0,
        'learning_sessions': 0,
    }
    
    @classmethod
    def record_ai_request(cls, endpoint, ai_mode, tokens_used=0, cost_usd=0.0, duration_ms=0, success=True):
        """Record an AI API request"""
        cls._ai_metrics['total_requests'] += 1
        if success:
            cls._ai_metrics['successful_requests'] += 1
        else:
            cls._ai_metrics['failed_requests'] += 1
        
        cls._ai_metrics['total_tokens_used'] += tokens_used
        cls._ai_metrics['total_cost_usd'] += cost_usd
        
        # Update average response time
        current_avg = cls._ai_metrics['avg_response_time_ms']
        total = cls._ai_metrics['total_requests']
        cls._ai_metrics['avg_response_time_ms'] = (
            (current_avg * (total - 1) + duration_ms) / total
        )
        
        # By mode
        mode_key = ai_mode or 'unknown'
        cls._ai_metrics['requests_by_mode'][mode_key] = (
            cls._ai_metrics['requests_by_mode'].get(mode_key, 0) + 1
        )
        
        # By endpoint
        cls._ai_metrics['requests_by_endpoint'][endpoint] = (
            cls._ai_metrics['requests_by_endpoint'].get(endpoint, 0) + 1
        )
    
    @classmethod
    def record_ai_error(cls, error_type):
        """Record an AI error"""
        cls._ai_metrics['error_counts'][error_type] = (
            cls._ai_metrics['error_counts'].get(error_type, 0) + 1
        )
    
    @classmethod
    def record_rate_limit_hit(cls):
        """Record a rate limit hit"""
        cls._ai_metrics['rate_limit_hits'] += 1
    
    @classmethod
    def record_cache_hit(cls):
        """Record a cache hit"""
        cls._ai_metrics['cache_hits'] += 1
    
    @classmethod
    def record_cache_miss(cls):
        """Record a cache miss"""
        cls._ai_metrics['cache_misses'] += 1
    
    @classmethod
    def record_conversation_turn(cls):
        """Record a conversation turn"""
        cls._ai_metrics['conversation_turns'] += 1
    
    @classmethod
    def record_learning_session(cls):
        """Record a learning session"""
        cls._ai_metrics['learning_sessions'] += 1
    
    @classmethod
    def get_metrics(cls):
        """Get all AI metrics"""
        cache_hit_rate = 0
        total_cache = cls._ai_metrics['cache_hits'] + cls._ai_metrics['cache_misses']
        if total_cache > 0:
            cache_hit_rate = (cls._ai_metrics['cache_hits'] / total_cache) * 100
        
        success_rate = 0
        if cls._ai_metrics['total_requests'] > 0:
            success_rate = (cls._ai_metrics['successful_requests'] / cls._ai_metrics['total_requests']) * 100
        
        return {
            'total_requests': cls._ai_metrics['total_requests'],
            'successful_requests': cls._ai_metrics['successful_requests'],
            'failed_requests': cls._ai_metrics['failed_requests'],
            'success_rate_percent': round(success_rate, 2),
            'total_tokens_used': cls._ai_metrics['total_tokens_used'],
            'total_cost_usd': round(cls._ai_metrics['total_cost_usd'], 4),
            'avg_response_time_ms': round(cls._ai_metrics['avg_response_time_ms'], 2),
            'requests_by_mode': dict(cls._ai_metrics['requests_by_mode']),
            'requests_by_endpoint': dict(cls._ai_metrics['requests_by_endpoint']),
            'error_counts': dict(cls._ai_metrics['error_counts']),
            'rate_limit_hits': cls._ai_metrics['rate_limit_hits'],
            'cache_hits': cls._ai_metrics['cache_hits'],
            'cache_misses': cls._ai_metrics['cache_misses'],
            'cache_hit_rate_percent': round(cache_hit_rate, 2),
            'conversation_turns': cls._ai_metrics['conversation_turns'],
            'learning_sessions': cls._ai_metrics['learning_sessions'],
        }


def setup_advanced_logging(app):
    """Setup advanced logging configuration"""
    
    import os
    logs_dir = os.path.join(app.root_path, 'logs')
    os.makedirs(logs_dir, exist_ok=True)
    
    perf_handler = logging.FileHandler(
        os.path.join(logs_dir, 'performance.log')
    )
    perf_handler.setLevel(logging.INFO)
    perf_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    )
    perf_handler.setFormatter(perf_formatter)
    
    error_handler = logging.FileHandler(
        os.path.join(logs_dir, 'errors.log')
    )
    error_handler.setLevel(logging.ERROR)
    error_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(pathname)s:%(lineno)d - %(message)s'
    )
    error_handler.setFormatter(error_formatter)
    
    app.logger.addHandler(perf_handler)
    app.logger.addHandler(error_handler)
    
    # Initialize Sentry if configured
    init_sentry(app)
    
    @app.before_request
    def before_request():
        PerformanceMonitor.log_request()
    
    @app.after_request
    def after_request(response):
        return PerformanceMonitor.log_response(response)

    @app.route('/health')
    def health_check():
        from flask import jsonify
        health = HealthCheck.get_health_status()
        status_code = 200 if health['status'] == 'healthy' else 503
        return jsonify(health), status_code

    @app.route('/metrics')
    def metrics():
        from flask import jsonify
        from flask_login import current_user

        if not (current_user and current_user.is_authenticated) or not current_user.is_owner:
            return jsonify({'error': 'Unauthorized'}), 403

        metrics_data = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'health': HealthCheck.get_health_status(),
            'app_info': {
                'version': app.config.get('APP_VERSION'),
                'environment': app.config.get('APP_ENV')
            },
            'ai_metrics': AIMetricsCollector.get_metrics()
        }

        return jsonify(metrics_data)

    @app.route('/ai-metrics')
    def ai_metrics():
        """AI-specific metrics dashboard for administrators"""
        from flask import jsonify
        from flask_login import current_user

        if not (current_user and current_user.is_authenticated) or not current_user.is_owner:
            return jsonify({'error': 'Unauthorized'}), 403

        ai_metrics = AIMetricsCollector.get_metrics()
        
        # Add cost analysis
        avg_cost_per_request = 0
        if ai_metrics['total_requests'] > 0:
            avg_cost_per_request = (
                ai_metrics['total_cost_usd'] / ai_metrics['total_requests']
            )
        
        ai_metrics['avg_cost_per_request_usd'] = round(avg_cost_per_request, 4)
        ai_metrics['cost_efficiency'] = round(
            ai_metrics['total_tokens_used'] / ai_metrics['total_requests'] if ai_metrics['total_requests'] > 0 else 0, 2
        )

        return jsonify({
            'status': 'healthy' if ai_metrics['success_rate_percent'] > 95 else 'degraded',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'ai_metrics': ai_metrics
        })
