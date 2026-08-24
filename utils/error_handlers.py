"""
Custom Error Handlers — Prevents information leakage in production.
Registers 404, 403, 405, 429, 500 error pages.
"""

import logging
from flask import render_template, request, jsonify

logger = logging.getLogger(__name__)


def register_error_handlers(app):  # noqa: C901
    """Register custom error handlers on the Flask app."""

    @app.errorhandler(404)
    def not_found(e):
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Not found', 'status': 404}), 404
        return render_template('errors/404.html'), 404

    @app.errorhandler(403)
    def forbidden(e):
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Forbidden', 'status': 403}), 403
        return render_template('errors/403.html'), 403

    @app.errorhandler(405)
    def method_not_allowed(e):
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Method not allowed', 'status': 405}), 405
        return render_template('errors/405.html'), 405

    @app.errorhandler(429)
    def rate_limited(e):
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Rate limit exceeded', 'status': 429}), 429
        return render_template('errors/429.html'), 429

    @app.errorhandler(500)
    def internal_error(e):
        logger.error(f"Internal Server Error: {e}", exc_info=True)
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Internal server error', 'status': 500}), 500
        return render_template('errors/500.html'), 500

    @app.errorhandler(502)
    def bad_gateway(e):
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Bad gateway', 'status': 502}), 502
        return render_template('errors/500.html'), 502

    @app.errorhandler(503)
    def service_unavailable(e):
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Service unavailable', 'status': 503}), 503
        return render_template('errors/500.html'), 503

    app.logger.info("[OK] Custom error handlers registered")
