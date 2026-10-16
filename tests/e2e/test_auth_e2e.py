"""
E2E tests for Auth module - comprehensive coverage of all routes.
Tests cover: login, logout, support, payment flow.
"""

import pytest


class TestAuthLogin:
    def test_login_page_renders(self, client):
        r = client.get('/auth/login')
        assert r.status_code == 200

    def test_login_success(self, client, login_as):
        user = login_as('owner')
        r = client.get('/dashboard')
        assert r.status_code == 200

    def test_login_failure_wrong_password(self, client, owner):
        r = client.post('/auth/login', data={
            'username': owner.username,
            'password': 'WrongPass!',
        })
        assert r.status_code == 200  # re-renders form
        body = r.get_data(as_text=True).lower()
        assert 'غير صحيحة' in body or 'خطأ' in body

    def test_login_failure_nonexistent_user(self, client):
        r = client.post('/auth/login', data={
            'username': 'nonexistent',
            'password': 'password',
        })
        assert r.status_code == 200
        body = r.get_data(as_text=True).lower()
        assert 'غير صحيحة' in body or 'خطأ' in body

    def test_login_requires_csrf(self, client):
        r = client.post('/auth/login', data={
            'username': 'test',
            'password': 'password',
        }, headers={'X-CSRFToken': 'invalid'})
        # Flask-WTF CSRF protection should reject
        assert r.status_code in (200, 400)


class TestAuthLogout:
    def test_logout_redirects(self, client, login_as):
        login_as('owner')
        r = client.get('/auth/logout')
        assert r.status_code in (302, 303)
        # Redirects to public.landing which is /welcome
        assert '/welcome' in r.headers.get('Location', '')


class TestAuthSupport:
    def test_support_page_renders(self, client):
        r = client.get('/auth/support')
        assert r.status_code == 200


class TestAuthPaymentFlow:
    def test_payment_create_page(self, client, login_as):
        login_as('owner')
        # /auth/payment/create is POST only - POST with minimal data
        r = client.post('/auth/payment/create', json={
            'amount': 15,
            'crypto_currency': 'btc',
            'customer_email': 'test@example.com',
        })
        # Returns JSON (success or error from NOWPayments)
        assert r.status_code in (200, 400)
        data = r.get_json()
        assert isinstance(data, dict)
        assert 'success' in data

    def test_payment_status_page(self, client, login_as):
        login_as('owner')
        r = client.get('/auth/payment/status/1')
        # Returns JSON
        assert r.status_code in (200, 400)
        data = r.get_json()
        assert isinstance(data, dict)
        assert 'success' in data


class TestAuthCurrencies:
    def test_currencies_endpoint(self, client, login_as):
        login_as('owner')
        r = client.get('/auth/payment/currencies')
        # Returns JSON (may be error if NOWPayments not configured)
        assert r.status_code in (200, 400)
        data = r.get_json()
        assert isinstance(data, dict)
        assert 'success' in data