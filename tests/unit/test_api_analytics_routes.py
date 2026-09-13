def test_analytics_blueprint_exists():
    from routes.api_analytics import api_analytics_bp
    assert api_analytics_bp.name == 'api_analytics'
    assert api_analytics_bp.url_prefix == '/api/analytics'
