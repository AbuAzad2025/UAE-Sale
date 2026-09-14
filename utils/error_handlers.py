"""
Custom Error Handlers — Prevents information leakage in production.
Registers 404, 403, 405, 429, 500 error pages.

Every handler also files a structured record in the error journal
(services.error_report_service) carrying the layer (backend /
frontend / logic / programming) and the affected user, so the owner
page can explain each fault. Reporting is best-effort and can never
break the response itself.
"""

import logging
from flask import render_template, request, jsonify

from services.error_report_service import (
    CATEGORY_BACKEND,
    ErrorLog,
    classify_http_status,
    report_error,
    report_exception,
)

logger = logging.getLogger(__name__)

# 404s for these paths are browser automatics, not application faults —
# logging them would only bury real errors under favicon noise.
_STATIC_NOISE_PATHS = frozenset({'/favicon.ico', '/robots.txt'})


def _report_http(status_code, exc=None):
    """File this HTTP error in the journal. Never raises."""
    try:
        if status_code == 500:
            report_exception(exc, source='flask-500')
            return
        if status_code == 404 and request.path in _STATIC_NOISE_PATHS:
            return
        category, severity = classify_http_status(status_code)
        report_error(category, '%s %s' % (status_code, request.path),
                     severity=severity, source='http-%s' % status_code)
    except Exception:
        pass


def register_error_handlers(app):  # noqa: C901
    """Register custom error handlers on the Flask app."""

    @app.errorhandler(404)
    def not_found(e):
        _report_http(404)
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Not found', 'status': 404}), 404
        return render_template('errors/404.html'), 404

    @app.errorhandler(403)
    def forbidden(e):
        _report_http(403)
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Forbidden', 'status': 403}), 403
        return render_template('errors/403.html'), 403

    @app.errorhandler(405)
    def method_not_allowed(e):
        _report_http(405)
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Method not allowed', 'status': 405}), 405
        return render_template('errors/405.html'), 405

    @app.errorhandler(429)
    def rate_limited(e):
        _report_http(429)
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Rate limit exceeded', 'status': 429}), 429
        return render_template('errors/429.html'), 429

    @app.errorhandler(500)
    def internal_error(e):
        logger.error(f"Internal Server Error: {e}", exc_info=True)
        _report_http(500, e)
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Internal server error', 'status': 500}), 500
        return render_template('errors/500.html'), 500

    @app.errorhandler(502)
    def bad_gateway(e):
        report_error(CATEGORY_BACKEND, '502 %s' % request.path,
                     severity=ErrorLog.SEVERITY_ERROR, source='http-502')
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Bad gateway', 'status': 502}), 502
        return render_template('errors/500.html'), 502

    @app.errorhandler(503)
    def service_unavailable(e):
        report_error(CATEGORY_BACKEND, '503 %s' % request.path,
                     severity=ErrorLog.SEVERITY_ERROR, source='http-503')
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Service unavailable', 'status': 503}), 503
        return render_template('errors/500.html'), 503

    app.logger.info("[OK] Custom error handlers registered")
