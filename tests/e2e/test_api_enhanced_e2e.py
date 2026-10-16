"""
E2E tests for API Enhanced module - comprehensive coverage of all routes.
Tests cover: sales, customers, products, analytics endpoints.
"""

import pytest


def _assert_success(data):
    """Assert response has success=True and return the data payload."""
    assert isinstance(data, dict)
    assert data.get('success') is True
    return data


class TestApiEnhancedSales:
    def test_get_sales_list(self, client, login_as, sale):
        login_as('owner')
        r = client.get('/api/v2/sales')
        assert r.status_code == 200
        data = _assert_success(r.get_json())
        assert isinstance(data.get('sales'), list)
        assert len(data['sales']) >= 1

    def test_get_single_sale(self, client, login_as, sale):
        login_as('owner')
        r = client.get(f'/api/v2/sales/{sale.id}')
        assert r.status_code == 200
        data = _assert_success(r.get_json())
        assert isinstance(data.get('sale'), dict)
        assert data['sale'].get('id') == sale.id

    def test_get_sales_with_filters(self, client, login_as, sale):
        login_as('owner')
        r = client.get('/api/v2/sales', query_string={
            'customer_id': sale.customer_id,
            'status': 'confirmed',
        })
        assert r.status_code == 200
        data = _assert_success(r.get_json())
        assert isinstance(data.get('sales'), list)


class TestApiEnhancedCustomers:
    def test_get_customers_list(self, client, login_as, customer):
        login_as('owner')
        r = client.get('/api/v2/customers')
        assert r.status_code == 200
        data = _assert_success(r.get_json())
        assert isinstance(data.get('customers'), list)
        assert len(data['customers']) >= 1

    def test_get_single_customer(self, client, login_as, customer):
        login_as('owner')
        r = client.get(f'/api/v2/customers/{customer.id}')
        assert r.status_code == 200
        data = _assert_success(r.get_json())
        assert isinstance(data.get('customer'), dict)
        assert data['customer'].get('id') == customer.id

    def test_search_customers_route_absent(self, client, login_as, customer):
        """There is no /api/v2/customers/search route. The blueprint exposes
        only the list and the single-resource GET, so a call to the guessed
        search path must 404 rather than silently returning everyone."""
        login_as('owner')
        r = client.get('/api/v2/customers/search', query_string={
            'q': customer.name[:3],
        })
        assert r.status_code == 404

    def test_customer_search_available_on_v1_api(self, client, login_as, customer):
        """The unified search that does exist lives on /api/search."""
        login_as('owner')
        r = client.get('/api/search', query_string={
            'q': customer.name[:3],
            'type': 'customers',
        })
        assert r.status_code == 200
        data = r.get_json()
        assert isinstance(data.get('results'), list)


class TestApiEnhancedProducts:
    def test_products_list_route_absent(self, client, login_as, product):
        """There is no /api/v2/products list route; the blueprint exposes only
        /products/search and /products/<id>."""
        login_as('owner')
        r = client.get('/api/v2/products')
        assert r.status_code == 404

    def test_get_single_product(self, client, login_as, product):
        login_as('owner')
        r = client.get(f'/api/v2/products/{product.id}')
        assert r.status_code == 200
        data = _assert_success(r.get_json())
        assert isinstance(data.get('product'), dict)
        assert data['product'].get('id') == product.id

    def test_search_products(self, client, login_as, product):
        login_as('owner')
        r = client.get('/api/v2/products/search', query_string={
            'q': product.sku[:3],
        })
        assert r.status_code == 200
        data = _assert_success(r.get_json())
        assert isinstance(data.get('products'), list)
        assert len(data['products']) >= 1

    def test_search_products_requires_query(self, client, login_as, product):
        login_as('owner')
        r = client.get('/api/v2/products/search')
        assert r.status_code == 400
        data = r.get_json()
        assert data.get('success') is False


class TestApiEnhancedAnalytics:
    def test_sales_forecast(self, client, login_as, sale):
        """The forecast endpoint needs >= 7 days of history, so with a single
        seeded sale it answers 200 with an explicit 'not enough data' message.
        The contract under test is that it degrades gracefully, not that it
        predicts."""
        login_as('owner')
        r = client.get('/api/v2/analytics/sales-forecast')
        assert r.status_code == 200
        data = r.get_json()
        assert isinstance(data, dict)
        assert 'prediction' in data
        assert 'confidence' in data

    def test_profit_margins(self, client, login_as, sale, product):
        login_as('owner')
        r = client.get('/api/v2/analytics/profit-margins')
        assert r.status_code == 200
        data = r.get_json()
        assert isinstance(data, (dict, list))


class TestApiEnhancedRbac:
    @pytest.mark.parametrize('role,allowed', [
        ('owner', True),
        ('branch_manager', True),
        ('manager', True),
        ('pos_cashier', True),
        ('senior_accountant', False),
        ('warehouse_keeper', False),
        ('accountant', False),
        ('viewer', False),
        ('hr', False),
    ])
    def test_api_enhanced_gates_access(
            self, client, login_as, sale, role, allowed):
        # /api/v2/sales is gated on manage_sales (routes/api_enhanced.py:13).
        login_as(role)
        r = client.get('/api/v2/sales')
        if allowed:
            assert r.status_code == 200
        else:
            assert r.status_code == 403
