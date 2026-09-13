def test_websocket_blueprint_exists():
    from routes.websocket import websocket_bp
    assert websocket_bp is not None
    assert websocket_bp.name == 'websocket'
