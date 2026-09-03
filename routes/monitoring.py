from flask import Blueprint, jsonify, render_template
from flask_login import login_required
from services.monitoring_service import MonitoringService
from utils.decorators import admin_required

monitoring_bp = Blueprint('monitoring', __name__, url_prefix='/monitoring')


@monitoring_bp.route('/health')
def health():
    # Liveness probe only: do NOT leak disk/memory/cpu/db details to
    # unauthenticated callers (orchestrators need a bare health signal).
    ok = MonitoringService.check_database().get('healthy', False)
    return jsonify({'status': 'healthy' if ok else 'unavailable'}), 200 if ok else 503


@monitoring_bp.route('/metrics')
@login_required
@admin_required
def metrics():
    app_metrics = MonitoringService.get_application_metrics()
    return jsonify(app_metrics)


@monitoring_bp.route('/dashboard')
@login_required
@admin_required
def dashboard():
    health = MonitoringService.get_system_health()
    metrics = MonitoringService.get_application_metrics()

    return render_template('monitoring/dashboard.html',
                           health=health,
                           metrics=metrics)
