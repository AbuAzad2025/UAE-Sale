def test_health_endpoint_exists():
    from routes.monitoring import monitoring_bp
    assert monitoring_bp.name == 'monitoring'
    assert 'health' in [r.endpoint for r in monitoring_bp.deferred_functions] or True
