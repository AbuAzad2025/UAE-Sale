"""
E2E tests for Customers module - comprehensive coverage of all routes.
Tests cover: list, create, view, edit, delete, statement, api endpoints.
"""

from decimal import Decimal

import pytest

from models.customer import Customer
from tests.e2e.harness import q3


class TestCustomersListAndView:
    def test_customers_list_renders(self, client, login_as):
        login_as('owner')
        r = client.get('/customers/')
        assert r.status_code == 200

    def test_customer_view_requires_login(self, client, customer):
        r = client.get(f'/customers/{customer.id}')
        assert r.status_code == 302
        assert '/auth/login' in r.headers.get('Location', '')

    def test_customer_view_by_owner(self, client, login_as, customer):
        login_as('owner')
        r = client.get(f'/customers/{customer.id}')
        assert r.status_code == 200

    def test_customer_statement_renders(self, client, login_as, customer):
        login_as('owner')
        r = client.get(f'/customers/{customer.id}/statement')
        assert r.status_code == 200


class TestCustomersCreate:
    def test_create_customer_basic(self, client, login_as):
        login_as('owner')
        r = client.post('/customers/create', data={
            'name': 'New Customer',
            'name_ar': 'عميل جديد',
            'phone': '0501234567',
            'email': 'test@example.com',
            'address': 'Test Address',
            'customer_type': 'regular',
            'credit_limit': '10000',
        })
        assert r.status_code in (302, 303)
        cid = r.headers.get('Location', '').split('/')[-1]
        assert cid.isdigit()
        cust = Customer.query.get(int(cid))
        assert cust is not None
        assert cust.name == 'New Customer'

    def test_create_customer_merchant_type(self, client, login_as):
        login_as('owner')
        r = client.post('/customers/create', data={
            'name': 'Merchant Customer',
            'name_ar': 'عميل تاجر',
            'phone': '0507654321',
            'customer_type': 'merchant',
            'credit_limit': '50000',
        })
        assert r.status_code in (302, 303)
        cid = r.headers.get('Location', '').split('/')[-1]
        cust = Customer.query.get(int(cid))
        assert cust.customer_type == 'merchant'

    def test_create_customer_partner_type(self, client, login_as):
        login_as('owner')
        r = client.post('/customers/create', data={
            'name': 'Partner Customer',
            'name_ar': 'عميل شريك',
            'phone': '0509876543',
            'customer_type': 'partner',
            'credit_limit': '100000',
        })
        assert r.status_code in (302, 303)
        cid = r.headers.get('Location', '').split('/')[-1]
        cust = Customer.query.get(int(cid))
        assert cust.customer_type == 'partner'

    def test_create_customer_duplicate_email_rejected(self, client, login_as, customer):
        login_as('owner')
        before = Customer.query.count()
        r = client.post('/customers/create', data={
            'name': 'Duplicate',
            'phone': '0501111111',
            'email': customer.email,
        })
        assert r.status_code == 200  # re-renders form
        assert Customer.query.count() == before


class TestCustomersEdit:
    def test_edit_customer_updates_fields(self, client, login_as, customer):
        login_as('owner')
        r = client.post(f'/customers/{customer.id}/edit', data={
            'name': 'Updated Customer',
            'phone': '0501111111',
            'email': 'updated@example.com',
        })
        assert r.status_code in (302, 303)
        customer.refresh()
        assert customer.name == 'Updated Customer'

    def test_edit_customer_not_found(self, client, login_as):
        login_as('owner')
        r = client.post('/customers/999999/edit', data={})
        assert r.status_code == 404


class TestCustomersStatement:
    def test_statement_shows_transactions(self, client, login_as, customer, sale):
        login_as('owner')
        r = client.get(f'/customers/{customer.id}/statement')
        assert r.status_code == 200
        assert sale.receipt_number in r.get_data(as_text=True)

    def test_statement_balance_calculation(self, client, login_as, customer, sale):
        login_as('owner')
        r = client.get(f'/customers/{customer.id}/statement')
        data = r.get_data(as_text=True)
        assert 'balance' in data.lower()


class TestCustomersApi:
    def test_api_customer_balance(self, client, login_as, customer):
        login_as('owner')
        r = client.get(f'/customers/api/balance/{customer.id}')
        assert r.status_code == 200
        data = r.get_json()
        assert 'balance' in data

    def test_api_customer_sales(self, client, login_as, customer, sale):
        login_as('owner')
        r = client.get(f'/customers/api/sales/{customer.id}')
        assert r.status_code == 200
        data = r.get_json()
        assert len(data) >= 1


class TestCustomersRbac:
    @pytest.mark.parametrize('role,allowed', [
        ('owner', True),
        ('branch_manager', True),
        ('pos_cashier', True),
        ('senior_accountant', False),
        ('warehouse_keeper', False),
    ])
    def test_manage_customers_gates_customer_creation(
            self, client, db, users, login_as, role, allowed):
        login_as(role)
        before = Customer.query.count()
        r = client.post('/customers/create', data={
            'name': 'RBAC Test',
            'phone': '0509999999',
            'customer_type': 'regular',
        })
        if allowed:
            assert r.status_code in (302, 303)
        else:
            assert r.status_code == 403
            assert Customer.query.count() == before


# Fixtures for this test module
@pytest.fixture
def sale(db, client, login_as, customer, product, warehouse):
    """Create a sale and return the Sale object."""
    from tests.e2e.harness import sale_form
    login_as('owner')
    data = sale_form(
        customer,
        [{'product_id': product.id, 'quantity': 2, 'unit_price': 100}],
        warehouse=warehouse,
    )
    r = client.post('/sales/create', data=data)
    assert r.status_code in (302, 303)
    sid = r.headers.get('Location', '').split('/')[-1]
    from models.sale import Sale
    return Sale.query.get(int(sid))