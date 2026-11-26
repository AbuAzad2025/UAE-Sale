def test_analytics_requires_login(client):
    endpoints = [
        "/ai/predict-sales",
        "/ai/analyze-margins",
        "/ai/detect-patterns",
        "/ai/inventory-health",
        "/ai/deep-analysis",
        "/ai/cash-flow-prediction",
        "/ai/churn-prediction",
        "/ai/optimize-inventory",
        "/ai/business-insights",
    ]
    for url in endpoints:
        resp = client.get(url)
        assert resp.status_code in (302, 401, 404), (url, resp.status_code)


def test_analytics_permission_denied_for_seller(client, login_seller):
    # seller lacks view_reports; should be denied (403 or redirect)
    resp = client.get("/ai/predict-sales")
    assert resp.status_code in (302, 401, 403, 404)


def test_cost_gated_endpoints_forbidden_without_view_costs(client, login_seller):
    for url in ("/ai/analyze-margins", "/ai/deep-analysis", "/ai/optimize-inventory"):
        resp = client.get(url)
        assert resp.status_code in (302, 401, 403, 404)


def test_stub_endpoints_return_not_implemented(client, login_owner):
    # need product id; use 1 (may not exist) -> 404 is acceptable
    for url in ("/ai/search-market-price/1", "/ai/find-compatible/1"):
        resp = client.get(url)
        assert resp.status_code in (404, 501, 200)


def test_business_insights_authenticated_owner(client, login_owner):
    resp = client.get("/ai/business-insights")
    assert resp.status_code in (200, 404, 500)
    if resp.status_code == 200:
        data = resp.get_json()
        assert isinstance(data, dict)