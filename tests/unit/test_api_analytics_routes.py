def _clear_cache():
    from extensions import cache
    cache.clear()


def test_overdue_payments_empty(client, login_owner, test_customer):
    _clear_cache()
    data = client.get('/api/analytics/overdue-payments').get_json()
    assert data['success'] is True
    assert data['count'] == 0
    assert data['total_amount'] == 0


def test_daily_stats_counts_today_sale(client, login_owner, test_sale):
    _clear_cache()
    data = client.get('/api/analytics/daily-stats').get_json()
    assert data['success'] is True
    assert data['sales']['count'] == 1
    assert data['sales']['total'] == 100.0
    assert data['payments']['count'] == 0
    assert data['payments']['total'] == 0


def test_top_customers_lists_customer(client, login_owner, test_customer):
    _clear_cache()
    data = client.get('/api/analytics/top-customers?limit=5').get_json()
    assert data['success'] is True
    assert len(data['customers']) == 1
    assert data['customers'][0]['name'] == 'Test Customer'
    assert data['customers'][0]['total_purchases'] == 0.0


def test_low_stock_products_empty(client, login_owner, test_product):
    _clear_cache()
    data = client.get('/api/analytics/low-stock-products').get_json()
    assert data['success'] is True
    assert data['count'] == 0
    assert data['products'] == []


def test_revenue_trend_includes_today(client, login_owner, test_sale):
    _clear_cache()
    data = client.get('/api/analytics/revenue-trend?days=7').get_json()
    assert data['success'] is True
    assert sum(r['revenue'] for r in data['data']) == 100.0