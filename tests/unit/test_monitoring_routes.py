def test_monitoring_blueprint_has_health():
    from routes.monitoring import monitoring_bp
    assert monitoring_bp.name == 'monitoring'
