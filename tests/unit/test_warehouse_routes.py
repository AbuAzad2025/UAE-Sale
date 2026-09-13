def test_warehouse_blueprint_has_index():
    from routes.warehouse import warehouse_bp
    assert warehouse_bp.name == 'warehouse'
