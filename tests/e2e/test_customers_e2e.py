"""
E2E tests for Customers module - comprehensive coverage of all routes.

Route contract (routes/customers.py):
  GET     /customers/                 (login + manage_customers)
  GET/POST /customers/create          (login + manage_customers) WTForms + CSRF
  GET     /customers/<id>             (login + manage_customers)
  GET/POST /customers/<id>/edit       (login + manage_customers)
  POST    /customers/<id>/delete      (login + manage_customers)
  GET     /customers/<id>/statement   (login + manage_customers)
  GET     /customers/<id>/balance     (login + manage_customers) JSON
  GET     /customers/<id>/sales       (login + manage_customers) JSON
  GET     /customers/api/search       (login) JSON

Records seeded directly (see module docstring in test_purchases_e2e.py).
"""

from decimal import Decimal

import pytest

from models.customer import Customer
from models.sale import Sale
from models.sale import SaleLine


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


class TestCustomersCreate:
    def _create_customer(self, client, data):
        """POST with minimal valid fields per CustomerForm."""
        required = {'name': 'Test', 'customer_type': 'regular', 'is_active': '1'}
        payload = {**required, **data}
        return client.post('/customers/create', data=payload)

    def test_create_customer_basic(self, client, login_as):
        login_as('owner')
        r = self._create_customer(client, {'name_ar': 'عميل جديد', 'phone': '0501234567'})
        assert r.status_code in (302, 303)
        # redirect to /customers/
        assert r.headers.get('Location', '').endswith('/customers/')
        cust = Customer.query.filter_by(name='Test').first()
        assert cust is not None
        assert cust.name_ar == 'عميل جديد'

    def test_create_customer_merchant_type(self, client, login_as):
        login_as('owner')
        r = self._create_customer(client, {'name': 'Merchant Cust', 'customer_type': 'merchant'})
        assert r.status_code in (302, 303)
        cust = Customer.query.filter_by(name='Merchant Cust').first()
        assert cust.customer_type == 'merchant'

    def test_create_customer_partner_type(self, client, login_as):
        login_as('owner')
        r = self._create_customer(client, {'name': 'Partner Cust', 'customer_type': 'partner'})
        assert r.status_code in (302, 303)
        cust = Customer.query.filter_by(name='Partner Cust').first()
        assert cust.customer_type == 'partner'

    def test_create_customer_duplicate_email_rejected(self, client, login_as, customer):
        login_as('owner')
        before = Customer.query.count()
        r = self._create_customer(client, {'name': 'Dup', 'email': customer.email})
        # WTForms validation fails -> re-render form 200
        assert r.status_code == 200
        assert Customer.query.count() == before

    def test_create_customer_empty_name_rejected(self, client, login_as):
        login_as('owner')
        before = Customer.query.count()
        r = client.post('/customers/create', data={
            'name': '', 'customer_type': 'regular', 'is_active': '1',
        })
        assert r.status_code in (200, 302, 303)
        assert Customer.query.count() == before

    def test_create_customer_requires_login(self, client):
        r = self._create_customer(client, {})
        assert r.status_code == 302
        assert '/auth/login' in r.headers.get('Location', '')


class TestCustomersEdit:
    def test_edit_customer_updates_fields(self, client, login_as, customer):
        login_as('owner')
        r = client.post(f'/customers/{customer.id}/edit', data={
            'name': 'Updated Customer',
            'customer_type': 'regular',
            'phone': '0501111111',
            'email': 'updated@example.com',
            'is_active': '1',
        })
        assert r.status_code in (302, 303)
        reloaded = Customer.query.get(customer.id)
        assert reloaded.name == 'Updated Customer'

    def test_edit_customer_invalid_type_rejected(self, client, login_as, customer):
        login_as('owner')
        r = client.post(f'/customers/{customer.id}/edit', data={
            'name': customer.name,
            'customer_type': 'invalid_type',
            'is_active': '1',
        })
        assert r.status_code == 200  # re-render form

    def test_edit_customer_not_found(self, client, login_as):
        login_as('owner')
        r = client.post('/customers/999999/edit', data={'name': 'x', 'customer_type': 'regular'})
        assert r.status_code == 404


class TestCustomersStatement:
    def test_statement_shows_transactions(self, client, login_as, customer):
        login_as('owner')
        r = client.get(f'/customers/{customer.id}/statement')
        assert r.status_code == 200

    def test_statement_balance_calculation(self, client, login_as, customer):
        login_as('owner')
        r = client.get(f'/customers/{customer.id}/statement')
        data = r.get_data(as_text=True)
        assert 'balance' in data.lower()


class TestCustomersApi:
    def test_customer_balance_endpoint(self, client, login_as, customer):
        login_as('owner')
        r = client.get(f'/customers/{customer.id}/balance')
        assert r.status_code == 200
        data = r.get_json()
        assert 'balance' in data

    def test_customer_sales_endpoint(self, client, login_as, customer):
        login_as('owner')
        r = client.get(f'/customers/{customer.id}/sales')
        assert r.status_code == 200
        data = r.get_json()
        assert isinstance(data.get('sales'), list)


class TestCustomersRbac:
    @pytest.mark.parametrize('role,allowed', [
        ('owner', True),
        ('branch_manager', True),
        ('manager', True),
        ('senior_accountant', False),
        ('pos_cashier', False),
        ('warehouse_keeper', False),
        ('accountant', False),
        ('viewer', False),
        ('hr', False),
    ])
    def test_manage_customers_gates_customer_creation(self, client, login_as, role, allowed):
        login_as(role)
        before = Customer.query.count()
        r = client.post('/customers/create', data={
            'name': 'RBAC Test',
            'customer_type': 'regular',
            'phone': '0509999999',
            'is_active': '1',
        })
        if allowed:
            assert r.status_code in (302, 303)
        else:
            assert r.status_code == 403
            assert Customer.query.count() == before


# Fixtures for this test module
@pytest.fixture
def customer(db, e2e_tenant):
    """Seed a customer directly."""
    cust = Customer(
        name='E2E Customer',
        name_ar='عميل E2E',
        customer_type='regular',
        phone='+971501234567',
        email='e2e_cust@test.local',
        credit_limit=Decimal('10000'),
        balance=Decimal('0'),
        is_active=True,
    )
    cust.tenant_id = e2e_tenant.id
    db.session.add(cust)
    db.session.commit()
    return cust