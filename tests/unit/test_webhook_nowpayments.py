"""Unit tests for WebhookService + NOWPaymentsService — معالجة Webhooks والدفع بالعملات الرقمية."""
import hashlib
import hmac
import json
import sys
import time
import types
from decimal import Decimal
from uuid import uuid4

import pytest
import requests

import services.nowpayments_service as nowpayments_module
from models import Donation, Package, PackagePurchase
from services.notification_service import NotificationService, SecurityService
from services.nowpayments_service import NOWPaymentsService
from services.webhook_service import WebhookService

IPN_SECRET = 'ipn-secret-xyz'


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, content=None):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        if content is not None:
            self.content = content
        else:
            self.content = json.dumps(self._json_data).encode('utf-8')
        self.text = self.content.decode('utf-8')

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f'{self.status_code} error')


class RequestRecorder:
    def __init__(self, response=None, exc=None):
        self.response = response
        self.exc = exc
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append({'url': url, 'kwargs': kwargs})
        if self.exc is not None:
            raise self.exc
        return self.response


class _FakeStripeWebhook:
    @staticmethod
    def construct_event(payload, sig_header, secret):
        pieces = {}
        for part in sig_header.split(','):
            key, _, value = part.partition('=')
            pieces[key] = value
        timestamp = pieces.get('t')
        received = pieces.get('v1')
        if not timestamp or not received:
            raise ValueError('Malformed signature header')
        expected = hmac.new(
            secret.encode('utf-8'),
            f"{timestamp}.".encode('utf-8') + payload,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, received):
            raise ValueError('Signature mismatch')
        return {'type': 'checkout.session.completed'}


@pytest.fixture(autouse=True)
def _clean_notification_state():
    NotificationService._notifications.clear()
    SecurityService._blacklist.clear()
    SecurityService._failed_attempts.clear()
    yield
    NotificationService._notifications.clear()
    SecurityService._blacklist.clear()
    SecurityService._failed_attempts.clear()


def sha512_sign(payload_bytes, secret=IPN_SECRET):
    return hmac.new(secret.encode('utf-8'), payload_bytes, hashlib.sha512).hexdigest()


@pytest.fixture
def purchase(db):
    pkg = Package(
        name_ar='الباقة الأساسية', name_en='Basic',
        slug='basic-' + uuid4().hex[:8], price=99.0,
    )
    db.session.add(pkg)
    db.session.flush()
    proc = PackagePurchase(
        package_id=pkg.id,
        customer_name='عميل تجريبي', customer_email='buyer@test.com',
        payment_method='crypto', payment_status='pending',
        amount_paid=99.0, currency='USD',
        transaction_id='pay-purchase-001',
    )
    db.session.add(proc)
    db.session.commit()
    return proc


@pytest.fixture
def donation(db):
    don = Donation(
        amount_usd=Decimal('25.00'), payment_method='crypto', crypto_type='btc',
        wallet_address='bc1qtestwalletaddress000',
        transaction_hash='pay-donation-001', status='pending',
        gateway_name='nowpayments', gateway_transaction_id='pay-donation-001',
        gateway_status='pending', donor_name='متبرع خيري',
    )
    db.session.add(don)
    db.session.commit()
    return don


@pytest.fixture
def svc(app, db, monkeypatch):
    monkeypatch.setitem(app.config, 'NOWPAYMENTS_API_KEY', 'np-key-123')
    monkeypatch.setitem(app.config, 'NOWPAYMENTS_IPN_SECRET', IPN_SECRET)
    monkeypatch.setitem(app.config, 'BASE_URL', 'https://erp.example.com')
    return NOWPaymentsService()


class TestNowPaymentsSignatureVerification:
    def test_valid_signature_accepted(self):
        payload = json.dumps(
            {'payment_id': '55231', 'payment_status': 'finished'},
            ensure_ascii=False,
        ).encode('utf-8')
        assert WebhookService.verify_nowpayments_signature(payload, sha512_sign(payload), IPN_SECRET)

    def test_invalid_signature_rejected(self):
        payload = b'{"payment_id": "55231"}'
        assert not WebhookService.verify_nowpayments_signature(payload, '0' * 128, IPN_SECRET)

    def test_tampered_payload_rejected(self):
        payload = b'{"payment_id": "55231", "payment_status": "finished"}'
        forged = sha512_sign(b'{"payment_id": "99999", "payment_status": "finished"}')
        assert not WebhookService.verify_nowpayments_signature(payload, forged, IPN_SECRET)

    def test_missing_secret_fails_closed(self):
        payload = b'{"x": 1}'
        assert not WebhookService.verify_nowpayments_signature(payload, sha512_sign(payload), '')

    def test_wrong_secret_produces_mismatch(self):
        payload = b'{"payment_id": "55231"}'
        attacker_sig = sha512_sign(payload, 'attacker-secret')
        assert not WebhookService.verify_nowpayments_signature(payload, attacker_sig, IPN_SECRET)


class TestNowPaymentsWebhookRouting:
    def test_purchase_prefix_routes_to_purchase_handler(self, db, purchase):
        result = WebhookService.process_nowpayments_webhook({
            'payment_id': 'pay-purchase-001',
            'payment_status': 'finished',
            'order_id': 'PURCHASE_1001',
        })
        assert result['success'] is True
        db.session.expire_all()
        refreshed = db.session.get(PackagePurchase, purchase.id)
        assert refreshed.payment_status == 'completed'
        assert refreshed.activation_status == 'activated'

    def test_donation_prefix_routes_to_donation_handler(self, db, donation):
        result = WebhookService.process_nowpayments_webhook({
            'payment_id': 'pay-donation-001',
            'payment_status': 'finished',
            'order_id': 'DONATION_2002',
        })
        assert result['success'] is True
        db.session.expire_all()
        refreshed = db.session.get(Donation, donation.id)
        assert refreshed.status == 'completed'

    def test_unknown_order_type_rejected(self):
        result = WebhookService.process_nowpayments_webhook({
            'payment_id': 'pay-x', 'payment_status': 'finished', 'order_id': 'MYSTERY_9',
        })
        assert result == {'success': False, 'error': 'Unknown order type'}

    def test_missing_order_id_is_unknown(self):
        result = WebhookService.process_nowpayments_webhook({
            'payment_id': 'pay-y', 'payment_status': 'finished',
        })
        assert result['success'] is False
        assert result['error'] == 'Unknown order type'


class TestPurchaseWebhookProcessing:
    def test_finished_activates_purchase_and_notifies(self, db, purchase):
        result = WebhookService._process_purchase_webhook({
            'payment_id': 'pay-purchase-001', 'payment_status': 'finished',
        })
        assert result['success'] is True
        db.session.expire_all()
        refreshed = db.session.get(PackagePurchase, purchase.id)
        assert refreshed.payment_status == 'completed'
        assert refreshed.activation_status == 'activated'
        assert refreshed.activation_date is not None
        assert NotificationService._notifications[-1]['title'] == '✅ تفعيل باقة'
        assert NotificationService._notifications[-1]['data']['customer'] == 'عميل تجريبي'

    def test_failed_marks_purchase_failed(self, db, purchase):
        result = WebhookService._process_purchase_webhook({
            'payment_id': 'pay-purchase-001', 'payment_status': 'failed',
        })
        assert result['success'] is True
        db.session.expire_all()
        assert db.session.get(PackagePurchase, purchase.id).payment_status == 'failed'

    def test_expired_marks_purchase_failed(self, db, purchase):
        WebhookService._process_purchase_webhook({
            'payment_id': 'pay-purchase-001', 'payment_status': 'expired',
        })
        db.session.expire_all()
        assert db.session.get(PackagePurchase, purchase.id).payment_status == 'failed'

    def test_intermediate_status_keeps_pending(self, db, purchase):
        result = WebhookService._process_purchase_webhook({
            'payment_id': 'pay-purchase-001', 'payment_status': 'confirming',
        })
        assert result['success'] is True
        assert 'updated to confirming' in result['message']
        db.session.expire_all()
        refreshed = db.session.get(PackagePurchase, purchase.id)
        assert refreshed.payment_status == 'pending'
        assert refreshed.activation_status == 'pending'
        assert NotificationService._notifications == []

    def test_unknown_payment_id_not_found(self, db, purchase):
        result = WebhookService._process_purchase_webhook({
            'payment_id': 'pay-missing-999', 'payment_status': 'finished',
        })
        assert result == {'success': False, 'error': 'Purchase not found'}
        assert NotificationService._notifications == []


class TestDonationWebhookProcessing:
    def test_finished_completes_donation_and_notifies(self, db, donation):
        result = WebhookService._process_donation_webhook({
            'payment_id': 'pay-donation-001', 'payment_status': 'finished',
        })
        assert result['success'] is True
        db.session.expire_all()
        refreshed = db.session.get(Donation, donation.id)
        assert refreshed.status == 'completed'
        assert refreshed.completed_at is not None
        notif = NotificationService._notifications[-1]
        assert notif['title'] == '💰 دفعة جديدة'
        assert notif['data']['amount'] == 25.0
        assert notif['data']['customer'] == 'متبرع خيري'

    def test_finished_without_donor_uses_anonymous(self, db, donation):
        donation.donor_name = None
        db.session.commit()
        WebhookService._process_donation_webhook({
            'payment_id': 'pay-donation-001', 'payment_status': 'finished',
        })
        notif = NotificationService._notifications[-1]
        assert notif['data']['customer'] == 'مجهول'

    def test_failed_marks_donation_failed(self, db, donation):
        result = WebhookService._process_donation_webhook({
            'payment_id': 'pay-donation-001', 'payment_status': 'failed',
        })
        assert result['success'] is True
        db.session.expire_all()
        assert db.session.get(Donation, donation.id).status == 'failed'

    def test_expired_marks_donation_failed(self, db, donation):
        WebhookService._process_donation_webhook({
            'payment_id': 'pay-donation-001', 'payment_status': 'expired',
        })
        db.session.expire_all()
        assert db.session.get(Donation, donation.id).status == 'failed'

    def test_waiting_leaves_pending(self, db, donation):
        result = WebhookService._process_donation_webhook({
            'payment_id': 'pay-donation-001', 'payment_status': 'waiting',
        })
        assert result['success'] is True
        db.session.expire_all()
        refreshed = db.session.get(Donation, donation.id)
        assert refreshed.status == 'pending'
        assert refreshed.completed_at is None

    def test_unknown_payment_id_not_found(self, db, donation):
        result = WebhookService._process_donation_webhook({
            'payment_id': 'no-such-payment', 'payment_status': 'finished',
        })
        assert result == {'success': False, 'error': 'Donation not found'}


class TestStripeWebhooks:
    def _install_fake_stripe(self, monkeypatch):
        fake = types.ModuleType('stripe')
        fake.Webhook = _FakeStripeWebhook
        monkeypatch.setitem(sys.modules, 'stripe', fake)

    def test_verify_valid_stripe_signature(self, monkeypatch):
        self._install_fake_stripe(monkeypatch)
        payload = b'{"type": "payment_intent.succeeded"}'
        ts = str(int(time.time()))
        sig = hmac.new(b'whsec_test', f'{ts}.'.encode() + payload, hashlib.sha256).hexdigest()
        assert WebhookService.verify_stripe_signature(payload, f't={ts},v1={sig}', 'whsec_test')

    def test_verify_bad_stripe_signature(self, monkeypatch):
        self._install_fake_stripe(monkeypatch)
        payload = b'{"type": "payment_intent.succeeded"}'
        ts = str(int(time.time()))
        bad = hmac.new(b'wrong_secret', f'{ts}.'.encode() + payload, hashlib.sha256).hexdigest()
        assert not WebhookService.verify_stripe_signature(payload, f't={ts},v1={bad}', 'whsec_test')

    def test_verify_malformed_header(self, monkeypatch):
        self._install_fake_stripe(monkeypatch)
        assert not WebhookService.verify_stripe_signature(b'{}', 'not-a-valid-header', 'whsec_test')

    def test_verify_missing_secret_fails_closed(self):
        assert not WebhookService.verify_stripe_signature(b'{}', 't=1,v1=abc', '')

    def test_unhandled_event_acknowledged(self):
        result = WebhookService.process_stripe_webhook({
            'type': 'invoice.paid', 'data': {'object': {}},
        })
        assert result == {'success': True, 'message': 'Event acknowledged'}

    def test_payment_success_notifies(self):
        result = WebhookService.process_stripe_webhook({
            'type': 'payment_intent.succeeded',
            'data': {'object': {'amount': 12500, 'receipt_email': 'buyer@shop.ae'}},
        })
        assert result['success'] is True
        notif = NotificationService._notifications[-1]
        assert notif['type'] == 'success'
        assert notif['data']['amount'] == 125.0
        assert notif['data']['customer'] == 'buyer@shop.ae'

    def test_payment_failure_raises_security_alert(self):
        result = WebhookService.process_stripe_webhook({
            'type': 'payment_intent.payment_failed',
            'data': {'object': {
                'receipt_email': 'buyer@shop.ae',
                'last_payment_error': {'message': 'card declined'},
            }},
        })
        assert result['success'] is True
        notif = NotificationService._notifications[-1]
        assert notif['type'] == 'danger'
        assert notif['data']['alert_type'] == 'فشل دفعة Stripe'
        assert 'card declined' in notif['data']['details']

    def test_corrupt_success_payload_returns_error_dict(self):
        result = WebhookService.process_stripe_webhook({
            'type': 'payment_intent.succeeded',
            'data': {'object': {'amount': None}},
        })
        assert result['success'] is False
        assert 'error' in result


class TestCreatePayment:
    def test_minimum_amount_rejected_before_http(self, svc, monkeypatch):
        rec = RequestRecorder(response=FakeResponse(201))
        monkeypatch.setattr(nowpayments_module.requests, 'post', rec)
        result = svc.create_payment(Decimal('0.50'))
        assert result['success'] is False
        assert 'الحد الأدنى' in result['error']
        assert rec.calls == []

    def test_successful_invoice_creation(self, svc, monkeypatch):
        rec = RequestRecorder(FakeResponse(201, json_data={
            'payment_id': 'np-pay-777',
            'pay_address': 'bc1qinvoiceaddr999',
            'pay_amount': '0.00025',
            'payment_url': 'https://nowpayments.io/payment/?iid=777',
            'order_id': 'DONATION_3003',
            'expires_at': '2026-09-01 12:00:00',
        }))
        monkeypatch.setattr(nowpayments_module.requests, 'post', rec)
        result = svc.create_payment(
            Decimal('25'), currency='USD', crypto_currency='BTC',
            customer_email='donor@give.org', donor_name='متبرع خيري',
        )
        assert result['success'] is True
        assert result['payment_id'] == 'np-pay-777'
        assert result['payment_address'] == 'bc1qinvoiceaddr999'
        assert result['payment_url'].startswith('https://nowpayments.io')
        assert result['order_id'] == 'DONATION_3003'
        call = rec.calls[0]
        assert call['url'] == 'https://api.nowpayments.io/v1/payment'
        assert call['kwargs']['timeout'] == 30
        assert call['kwargs']['headers']['x-api-key'] == 'np-key-123'
        body = call['kwargs']['json']
        assert body['price_amount'] == 25.0
        assert body['price_currency'] == 'usd'
        assert body['pay_currency'] == 'btc'
        assert body['ipn_callback_url'] == 'https://erp.example.com/auth/payment/callback'
        assert body['customer_email'] == 'donor@give.org'
        assert '$25' in body['order_description']

    def test_successful_invoice_persists_pending_donation(self, svc, db, monkeypatch):
        rec = RequestRecorder(FakeResponse(201, json_data={
            'payment_id': 'np-pay-888',
            'pay_address': 'bc1qstore888',
            'pay_amount': '0.001',
        }))
        monkeypatch.setattr(nowpayments_module.requests, 'post', rec)
        result = svc.create_payment(
            Decimal('120'), transaction_type='purchase', package='professional',
            customer_name='شركة الأمل', customer_email='corp@amal.ae',
            donor_name='should-not-be-used',
        )
        assert result['success'] is True
        don = Donation.query.filter_by(transaction_hash='np-pay-888').first()
        assert don is not None
        assert don.status == 'pending'
        assert don.gateway_name == 'nowpayments'
        assert don.gateway_status == 'pending'
        assert don.transaction_type == 'purchase'
        assert don.package == 'professional'
        assert don.customer_name == 'شركة الأمل'
        assert don.customer_email == 'corp@amal.ae'
        assert don.crypto_type == 'btc'
        assert don.amount_usd == Decimal('120')

    def test_api_error_message_propagated(self, svc, monkeypatch):
        rec = RequestRecorder(FakeResponse(
            400, json_data={'message': 'amount_too_small'}, content=b'{"message": "amount_too_small"}',
        ))
        monkeypatch.setattr(nowpayments_module.requests, 'post', rec)
        result = svc.create_payment(Decimal('10'))
        assert result == {'success': False, 'error': 'amount_too_small'}

    def test_api_error_empty_body_falls_back_to_status_code(self, svc, monkeypatch):
        rec = RequestRecorder(FakeResponse(500, json_data={}, content=b''))
        monkeypatch.setattr(nowpayments_module.requests, 'post', rec)
        result = svc.create_payment(Decimal('10'))
        assert result['success'] is False
        assert '500' in result['error']

    def test_connection_error_handled(self, svc, monkeypatch):
        rec = RequestRecorder(exc=requests.exceptions.ConnectionError('dns failure'))
        monkeypatch.setattr(nowpayments_module.requests, 'post', rec)
        result = svc.create_payment(Decimal('10'))
        assert result['success'] is False
        assert 'خطأ في الاتصال' in result['error']


class TestStatusQueries:
    def test_get_payment_status_ok(self, svc, monkeypatch):
        rec = RequestRecorder(FakeResponse(200, json_data={'payment_status': 'confirmed'}))
        monkeypatch.setattr(nowpayments_module.requests, 'get', rec)
        result = svc.get_payment_status('np-pay-777')
        assert result == {'success': True, 'data': {'payment_status': 'confirmed'}}
        assert rec.calls[0]['url'] == 'https://api.nowpayments.io/v1/payment/np-pay-777'

    def test_get_payment_status_error(self, svc, monkeypatch):
        rec = RequestRecorder(FakeResponse(404, json_data={}))
        monkeypatch.setattr(nowpayments_module.requests, 'get', rec)
        result = svc.get_payment_status('missing-id')
        assert result['success'] is False
        assert '404' in result['error']

    def test_get_payment_status_network_exception(self, svc, monkeypatch):
        rec = RequestRecorder(exc=requests.exceptions.Timeout('timed out'))
        monkeypatch.setattr(nowpayments_module.requests, 'get', rec)
        result = svc.get_payment_status('np-pay-777')
        assert result['success'] is False
        assert 'timed out' in result['error']

    def test_get_available_currencies_ok(self, svc, monkeypatch):
        rec = RequestRecorder(FakeResponse(200, json_data=['btc', 'eth', 'usdt']))
        monkeypatch.setattr(nowpayments_module.requests, 'get', rec)
        result = svc.get_available_currencies()
        assert result['success'] is True
        assert result['currencies'] == ['btc', 'eth', 'usdt']
        assert rec.calls[0]['url'] == 'https://api.nowpayments.io/v1/currencies'

    def test_get_available_currencies_error(self, svc, monkeypatch):
        rec = RequestRecorder(FakeResponse(503, json_data={}))
        monkeypatch.setattr(nowpayments_module.requests, 'get', rec)
        assert svc.get_available_currencies()['success'] is False

    def test_get_estimated_amount_sends_params(self, svc, monkeypatch):
        rec = RequestRecorder(FakeResponse(200, json_data={'estimated_amount': '0.001'}))
        monkeypatch.setattr(nowpayments_module.requests, 'get', rec)
        result = svc.get_estimated_amount(100, from_currency='usd', to_currency='eth')
        assert result == {'success': True, 'data': {'estimated_amount': '0.001'}}
        assert rec.calls[0]['kwargs']['params'] == {
            'amount': 100, 'currency_from': 'usd', 'currency_to': 'eth',
        }

    def test_get_estimated_amount_error(self, svc, monkeypatch):
        rec = RequestRecorder(FakeResponse(400, json_data={}))
        monkeypatch.setattr(nowpayments_module.requests, 'get', rec)
        result = svc.get_estimated_amount(-5)
        assert result['success'] is False
        assert '400' in result['error']


class TestIpnVerification:
    def test_valid_sorted_json_signature(self, svc):
        data = {'payment_id': 'np-pay-777', 'payment_status': 'finished', 'order_id': 'D-1'}
        expected = hmac.new(
            IPN_SECRET.encode('utf-8'),
            json.dumps(data, sort_keys=True).encode('utf-8'),
            hashlib.sha256,
        ).hexdigest()
        assert svc.verify_ipn(data, expected) is True

    def test_tampered_data_breaks_signature(self, svc):
        data = {'payment_id': 'np-pay-777', 'payment_status': 'finished'}
        sig = hmac.new(
            IPN_SECRET.encode('utf-8'),
            json.dumps(data, sort_keys=True).encode('utf-8'),
            hashlib.sha256,
        ).hexdigest()
        tampered = dict(data, payment_status='failed')
        assert svc.verify_ipn(tampered, sig) is False

    def test_unsorted_keys_still_match(self, svc):
        data_a = {'b': '2', 'a': '1'}
        data_b = {'a': '1', 'b': '2'}
        sig = hmac.new(
            IPN_SECRET.encode('utf-8'),
            json.dumps(data_b, sort_keys=True).encode('utf-8'),
            hashlib.sha256,
        ).hexdigest()
        assert svc.verify_ipn(data_a, sig) is True

    def test_missing_secret_fails_closed(self, svc):
        svc.ipn_secret = None
        assert svc.verify_ipn({'a': 1}, 'whatever') is False


class TestPaymentCallback:
    def test_missing_payment_id_rejected(self, svc, db, donation):
        assert svc.process_payment_callback({'payment_status': 'finished'}) is False
        db.session.expire_all()
        assert db.session.get(Donation, donation.id).status == 'pending'

    def test_unknown_payment_id_rejected(self, svc, db, donation):
        assert svc.process_payment_callback({
            'payment_id': 'ghost-999', 'payment_status': 'finished',
        }) is False
        db.session.expire_all()
        assert db.session.get(Donation, donation.id).status == 'pending'

    def test_finished_completes_donation(self, svc, db, donation):
        assert svc.process_payment_callback({
            'payment_id': 'pay-donation-001', 'payment_status': 'finished',
        }) is True
        db.session.expire_all()
        refreshed = db.session.get(Donation, donation.id)
        assert refreshed.status == 'completed'
        assert refreshed.completed_at is not None

    def test_failed_maps_to_failed(self, svc, db, donation):
        assert svc.process_payment_callback({
            'payment_id': 'pay-donation-001', 'payment_status': 'failed',
        }) is True
        db.session.expire_all()
        assert db.session.get(Donation, donation.id).status == 'failed'

    def test_refunded_maps_to_refunded(self, svc, db, donation):
        assert svc.process_payment_callback({
            'payment_id': 'pay-donation-001', 'payment_status': 'refunded',
        }) is True
        db.session.expire_all()
        assert db.session.get(Donation, donation.id).status == 'refunded'

    def test_unknown_status_keeps_existing(self, svc, db, donation):
        assert svc.process_payment_callback({
            'payment_id': 'pay-donation-001', 'payment_status': 'sending',
        }) is True
        db.session.expire_all()
        assert db.session.get(Donation, donation.id).status == 'pending'

    def test_lookup_matches_gateway_transaction_id_too(self, svc, db, donation):
        donation.transaction_hash = None
        db.session.commit()
        assert svc.process_payment_callback({
            'payment_id': 'pay-donation-001', 'payment_status': 'finished',
        }) is True
        db.session.expire_all()
        assert db.session.get(Donation, donation.id).status == 'completed'

    def test_commit_failure_returns_false(self, svc, db, monkeypatch, donation):
        class ExplodingSession:
            def commit(self):
                raise RuntimeError('commit exploded')
        monkeypatch.setattr(
            nowpayments_module, 'db',
            types.SimpleNamespace(or_=db.or_, session=ExplodingSession()),
        )
        assert svc.process_payment_callback({
            'payment_id': 'pay-donation-001', 'payment_status': 'finished',
        }) is False
