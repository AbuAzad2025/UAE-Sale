"""
E2E tests for API Enhanced module - comprehensive coverage of all routes.
Tests cover: sales, customers, products, analytics endpoints.
"""

import pytest


class TestApiEnhancedSales:
    def test_get_sales_list(self, client, login_as, sale):
        login_as('owner')
        r = client.get('/api/v2/sales')
        assert r.status_code == 200
        data = r.get_json()
        assert len(data) >= 1

    def test_get_single_sale(self, client, login_as, sale):
        login_as('owner')
        r = client.get(f'/api/v2/sales/{sale.id}')
        assert r.status_code == 200
        data = r.get_json()
        assert data['id'] == sale.id

    def test_get_sales_with_filters(self, client, login_as, sale):
        login_as('owner')
        r = client.get('/api/v2/sales', query_string={
            'customer_id': sale.customer_id,
            'status': 'confirmed',
        })
        assert r.status_code == 200
        data = r.get_json()
        assert len(data) >= 1


class TestApiEnhancedCustomers:
    def test_get_customers_list(self, client, login_as, customer):
        login_as('owner')
        r = client.get('/api/v2/customers')
        assert r.status_code == 200
        data = r.get_json()
        assert len(data) >= 1

    def test_get_single_customer(self, client, login_as, customer):
        login_as('owner')
        r = client.get(f'/api/v2/customers/{customer.id}')
        assert r.status_code == 200
        data = r.get_json()
        assert data['id'] == customer.id

    def test_search_customers(self, client, login_as, customer):
        login_as('owner')
        r = client.get('/api/v2/customers/search', query_string={
            'q': customer.name[:3],
        })
        assert r.status_code == 200
        data = r.get_json()
        assert len(data) >= 1


class TestApiEnhancedProducts:
    def test_get_products_list(self, client, login_as, product):
        login_as('owner')
        r = client.get('/api/v2/products')
        assert r.status_code == 200
        data = r.get_json()
        assert len(data) >= 1

    def test_get_single_product(self, client, login_as, product):
        login_as('owner')
        r = client.get(f'/api/v2/products/{product.id}')
        assert r.status_code == 200
        data = r.get_json()
        assert data['id'] == product.id

    def test_search_products(self, client, login_as, product):
        login_as('owner')
        r = client.get('/api/v2/products/search', query_string={
            'q': product.sku[:3],
        })
        assert r.status_code == 200
        data = r.get_json()
        assert len(data) >= 1


class TestApiEnhancedAnalytics:
    def test_sales_forecast(self, client, login_as, sale):
        login_as('owner')
        r = client.get('/api/v2/analytics/sales-forecast')
        assert r.status_code == 200
        data = r.get_json()
        assert 'forecast' in data

    def test_profit_margins(self, client, login_as, sale, product):
        login_as('owner')
        r = client.get('/api/v2/analytics/profit-margins')
        assert r.status_code == 200
        data = r.get_json()
        assert 'margins' in data


class TestApiEnhancedRbac:
    @pytest.mark.parametrize('role,allowed', [
        ('owner', True),
        ('branch_manager', True),
        ('senior_accountant', True),
        ('pos_cashier', False),
        ('warehouse_keeper', False),
    ])
    def test_api_enhanced_gates_access(
            self, client, login_as, sale, role, allowed):
        login_as(role)
        r = client.get('/api/v2/sales')
        if allowed:
            assert r.status_code == 200
        else:
            assert r.status_code == 403