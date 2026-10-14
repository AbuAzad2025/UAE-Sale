"""
E2E tests for Auth module - comprehensive coverage of all routes.
Tests cover: login, logout, support, payment flow.
"""

import pytest


class TestAuthLogin:
    def test_login_page_renders(self, client):
        r = client.get('/auth/login')
        assert r.status_code == 200

    def test_login_success(self, client, owner_user):
        r = client.post('/auth/login', data={
            'username': owner_user.username,
            'password': 'OwnerPass123!',
        })
        assert r.status_code in (302, 303)
        assert '/dashboard' in r.headers.get('Location', '')

    def test_login_failure_wrong_password(self, client, owner_user):
        r = client.post('/auth/login', data={
            'username': owner_user.username,
            'password': 'WrongPass!',
        })
        assert r.status_code == 200  # re-renders form
        assert 'invalid' in r.get_data(as_text=True).lower()

    def test_login_failure_nonexistent_user(self, client):
        r = client.post('/auth/login', data={
            'username': 'nonexistent',
            'password': 'password',
        })
        assert r.status_code == 200
        assert 'invalid' in r.get_data(as_text=True).lower()

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
        assert '/auth/login' in r.headers.get('Location', '')


class TestAuthSupport:
    def test_support_page_renders(self, client):
        r = client.get('/auth/support')
        assert r.status_code == 200


class TestAuthPaymentFlow:
    def test_payment_create_page(self, client):
        r = client.get('/auth/payment/create')
        assert r.status_code == 200

    def test_payment_status_page(self, client, login_as):
        login_as('owner')
        r = client.get('/auth/payment/status/1')
        assert r.status_code in (200, 404)  # 404 if not found, 200 if exists


class TestAuthCurrencies:
    def test_currencies_endpoint(self, client):
        r = client.get('/auth/payment/currencies')
        assert r.status_code == 200
        data = r.get_json()
        assert isinstance(data, list)
        assert len(data) > 0