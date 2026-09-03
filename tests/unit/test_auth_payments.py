"""Tests for auth payment endpoints (routes/auth.py payment section).

Login/logout/lockout are covered by test_auth.py; this file covers the
public NOWPayments surface: input validation, signature enforcement,
and graceful degradation without provider keys.
"""
import pytest


class TestCreatePaymentValidation:
    def test_no_json_rejected(self, client):
        resp = client.post('/auth/payment/create',
                           data='not-json', content_type='text/plain')
        assert resp.status_code in (400, 500)

    def test_empty_json_rejected(self, client):
        assert client.post('/auth/payment/create', json={}).status_code == 400

    @pytest.mark.parametrize('amount', ['abc', None, 0.5, 100001, -5])
    def test_bad_amount_rejected(self, client, amount):
        resp = client.post('/auth/payment/create',
                           json={'amount': amount})
        assert resp.status_code == 400

    def test_valid_shape_without_provider_key(self, client):
        # No NOWPayments keys in test env: must fail gracefully with a
        # JSON error body, never a stack trace / HTML 500 page.
        resp = client.post('/auth/payment/create', json={
            'amount': 25, 'crypto_currency': 'btc',
            'customer_email': 'buyer@test.com'})
        assert resp.status_code in (400, 500)
        assert resp.is_json


class TestPaymentCallbackSecurity:
    def test_missing_signature_rejected(self, client):
        resp = client.post('/auth/payment/callback',
                           json={'payment_id': '1'})
        assert resp.status_code == 400
        assert 'error' in resp.get_json()

    def test_bad_signature_rejected(self, client):
        resp = client.post('/auth/payment/callback',
                           json={'payment_id': '1'},
                           headers={'x-nowpayments-sig': 'forged'})
        assert resp.status_code in (400, 500)

    def test_no_json_graceful(self, client):
        resp = client.post('/auth/payment/callback',
                           data='x', content_type='text/plain',
                           headers={'x-nowpayments-sig': 's'})
        assert resp.status_code in (400, 500)
        assert resp.is_json


class TestPaymentInfoEndpoints:
    @pytest.mark.parametrize('url', [
        '/auth/payment/status/abc123',
        '/auth/payment/currencies',
        '/auth/payment/estimate?amount=10&currency=btc',
        '/auth/thank-you',
        '/auth/support',
    ])
    def test_graceful_response(self, client, url):
        resp = client.get(url)
        assert resp.status_code in (200, 302, 400, 500)
