import hashlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

import services.whatsapp_service as whatsapp_service
import utils.advanced_audit as advanced_audit
from models import AuditLog, Product, Sale, SaleLine, User
from services.predictive_maintenance import PredictiveMaintenanceService
from services.whatsapp_service import WhatsAppService
from utils.advanced_audit import (
    generate_device_fingerprint,
    get_security_events,
    log_sensitive_action,
    notify_admin_of_sensitive_action,
    track_login_attempt,
)


def _mk_sale(db, owner_user, customer, product, number, sale_date, status='confirmed'):
    sale = Sale(
        sale_number=number,
        customer_id=customer.id,
        seller_id=owner_user.id,
        total_amount=Decimal('100.000'),
        amount_base=Decimal('100.000'),
        paid_amount=Decimal('0'),
        paid_amount_base=Decimal('0'),
        balance_due=Decimal('100.000'),
        currency='AED',
        exchange_rate=Decimal('1'),
        payment_status='unpaid',
        status=status,
        is_active=True,
        sale_date=sale_date,
    )
    db.session.add(sale)
    db.session.flush()
    return sale


def _add_line(db, sale, product, quantity=Decimal('1')):
    db.session.add(SaleLine(
        sale_id=sale.id,
        product_id=product.id,
        quantity=quantity,
        unit_price=Decimal('50.000'),
        discount_percent=Decimal('0'),
        line_total=Decimal('50.000') * quantity,
        cost_price=Decimal('20.000'),
    ))
    db.session.commit()


def _mk_product(db, test_category, sku, active=True):
    product = Product(
        name=f'Product {sku}',
        name_ar='منتج تجريبي',
        sku=sku,
        category_id=test_category.id,
        cost_price=Decimal('50.000'),
        regular_price=Decimal('100.000'),
        current_stock=Decimal('10'),
        min_stock_alert=Decimal('1'),
        is_active=active,
    )
    db.session.add(product)
    db.session.commit()
    return product


class _FakeResponse:
    def __init__(self, payload=None):
        self._payload = payload if payload is not None else {'id': 'msg-123'}

    def json(self):
        return self._payload


def _mock_post(monkeypatch, payload=None, error=None):
    calls = []

    def fake_post(url, data=None, timeout=None):
        calls.append({'url': url, 'data': data, 'timeout': timeout})
        if error is not None:
            raise error
        return _FakeResponse(payload)

    monkeypatch.setattr(whatsapp_service.requests, 'post', fake_post)
    return calls


@pytest.fixture
def wa_env(monkeypatch):
    monkeypatch.setenv('WHATSAPP_API_KEY', 'test-key')
    monkeypatch.setenv('WHATSAPP_INSTANCE_ID', 'inst-42')
    monkeypatch.setenv('WHATSAPP_API_URL', 'https://wa.mock')


class TestWhatsAppService:
    def test_is_enabled_reflects_api_key(self, monkeypatch):
        monkeypatch.delenv('WHATSAPP_API_KEY', raising=False)
        assert WhatsAppService.is_enabled() is False
        monkeypatch.setenv('WHATSAPP_API_KEY', 'some-key')
        assert WhatsAppService.is_enabled() is True

    def test_send_invoice_not_configured(self, monkeypatch):
        monkeypatch.delenv('WHATSAPP_API_KEY', raising=False)
        result = WhatsAppService.send_invoice('+971501234567', 'INV-1')
        assert result == {'success': False, 'error': 'WhatsApp not configured'}

    def test_send_invoice_missing_instance_returns_config_error(self, monkeypatch):
        monkeypatch.setenv('WHATSAPP_API_KEY', 'test-key')
        monkeypatch.delenv('WHATSAPP_INSTANCE_ID', raising=False)
        result = WhatsAppService.send_invoice('+971501234567', 'INV-1')
        assert result == {'success': False, 'error': 'Missing configuration'}

    @pytest.mark.parametrize('raw,expected', [
        ('+971501234567', '971501234567'),
        ('971-50-123-4567', '971501234567'),
        ('0501234567', '971501234567'),
        ('50 12 345 67', '971501234567'),
    ])
    def test_phone_normalization_all_senders(self, wa_env, monkeypatch, raw, expected):
        calls = _mock_post(monkeypatch)
        for sender in (
            WhatsAppService.send_custom_message(raw, 'مرحبا'),
            WhatsAppService.send_payment_reminder(raw, 'عميل', Decimal('10')),
            WhatsAppService.send_invoice(raw, 'INV-N'),
        ):
            assert sender['phone'] == expected
            assert sender['success'] is True
        assert all(c['data']['to'] == expected for c in calls)

    def test_send_invoice_chat_success(self, wa_env, monkeypatch):
        calls = _mock_post(monkeypatch)
        result = WhatsAppService.send_invoice('+971 50-123-4567', 'INV-777')
        assert result == {'success': True, 'message_id': 'msg-123', 'phone': '971501234567'}
        assert len(calls) == 1
        assert calls[0]['url'] == 'https://wa.mock/inst-42/messages/chat'
        assert calls[0]['data']['token'] == 'test-key'
        assert 'فاتورتك رقم INV-777' in calls[0]['data']['body']
        assert calls[0]['timeout'] == 10

    def test_send_invoice_document_endpoint_when_pdf_url(self, wa_env, monkeypatch):
        calls = _mock_post(monkeypatch)
        result = WhatsAppService.send_invoice('0501234567', 'INV-888', pdf_url='https://files.example/i.pdf')
        assert result['success'] is True
        assert result['phone'] == '971501234567'
        assert calls[0]['url'].endswith('/messages/document')
        assert calls[0]['data']['document'] == 'https://files.example/i.pdf'
        assert 'فاتورتك رقم INV-888' in calls[0]['data']['caption']
        assert 'body' not in calls[0]['data']

    def test_send_invoice_provider_error_returns_failure_not_raise(self, wa_env, monkeypatch):
        calls = _mock_post(monkeypatch, error=ConnectionError('network down'))
        result = WhatsAppService.send_invoice('+971501234567', 'INV-999')
        assert result['success'] is False
        assert 'network down' in result['error']
        assert len(calls) == 1

    def test_send_invoice_missing_message_id_is_none(self, wa_env, monkeypatch):
        _mock_post(monkeypatch, payload={'status': 'sent'})
        result = WhatsAppService.send_invoice('+971501234567', 'INV-1000')
        assert result['success'] is True
        assert result['message_id'] is None

    def test_payment_reminder_message_contains_name_and_amount(self, wa_env, monkeypatch):
        calls = _mock_post(monkeypatch)
        result = WhatsAppService.send_payment_reminder('+971551112233', 'أبو محمد', 12500.5)
        assert result == {'success': True, 'message_id': 'msg-123', 'phone': '971551112233'}
        body = calls[0]['data']['body']
        assert 'السلام عليكم أبو محمد' in body
        assert '12,500.50 درهم' in body
        assert calls[0]['url'].endswith('/inst-42/messages/chat')

    def test_payment_reminder_provider_error_logged_as_failure(self, wa_env, monkeypatch):
        _mock_post(monkeypatch, error=TimeoutError('gateway timeout'))
        result = WhatsAppService.send_payment_reminder('+971551112233', 'زبون', 500)
        assert result == {'success': False, 'error': 'gateway timeout'}

    def test_send_custom_message_passes_body_through(self, wa_env, monkeypatch):
        calls = _mock_post(monkeypatch)
        result = WhatsAppService.send_custom_message('+971501234567', 'رسالة مخصصة للعميل')
        assert result['success'] is True
        assert calls[0]['data']['body'] == 'رسالة مخصصة للعميل'


class TestPredictiveMaintenance:
    def test_predict_returns_none_without_history(self, db, owner_user, test_customer, test_product):
        assert PredictiveMaintenanceService.predict_next_maintenance(test_product.id) is None

    def test_predict_returns_none_with_single_sale(self, db, owner_user, test_customer, test_product):
        _add_line(db, _mk_sale(db, owner_user, test_customer, test_product, 'S-PMD-001',
                               datetime.now() - timedelta(days=5)), test_product)
        assert PredictiveMaintenanceService.predict_next_maintenance(test_product.id) is None

    def test_predict_ignores_non_confirmed_sales(self, db, owner_user, test_customer, test_product):
        now = datetime.now()
        _add_line(db, _mk_sale(db, owner_user, test_customer, test_product, 'S-PMD-010',
                               now - timedelta(days=40)), test_product)
        _add_line(db, _mk_sale(db, owner_user, test_customer, test_product, 'S-PMD-011',
                               now - timedelta(days=30), status='draft'), test_product)
        assert PredictiveMaintenanceService.predict_next_maintenance(test_product.id) is None

    def test_predict_overdue_product_has_zero_days_and_stats(self, db, owner_user, test_customer, test_product):
        now = datetime.now()
        _add_line(db, _mk_sale(db, owner_user, test_customer, test_product, 'S-PMD-020',
                               now - timedelta(days=40)), test_product)
        _add_line(db, _mk_sale(db, owner_user, test_customer, test_product, 'S-PMD-021',
                               now - timedelta(days=30)), test_product)
        result = PredictiveMaintenanceService.predict_next_maintenance(test_product.id)
        assert result['product_id'] == test_product.id
        assert result['days_until'] == 0
        assert result['avg_interval_days'] == 10.0
        assert result['confidence'] == 0.2
        assert result['sales_analyzed'] == 2
        assert result['last_sale_date'][:10] == (datetime.now() - timedelta(days=30)).date().isoformat()
        assert result['predicted_next_maintenance'][:10] == (datetime.now() - timedelta(days=20)).date().isoformat()

    def test_predict_upcoming_maintenance_positive_days(self, db, owner_user, test_customer, test_product):
        now = datetime.now()
        _add_line(db, _mk_sale(db, owner_user, test_customer, test_product, 'S-PMD-030',
                               now - timedelta(days=12)), test_product)
        _add_line(db, _mk_sale(db, owner_user, test_customer, test_product, 'S-PMD-031',
                               now - timedelta(days=2)), test_product)
        result = PredictiveMaintenanceService.predict_next_maintenance(test_product.id)
        assert result['avg_interval_days'] == 10.0
        assert result['days_until'] in (7, 8)

    def test_alerts_sorted_with_urgency_excludes_inactive(self, db, owner_user, test_customer, test_category):
        now = datetime.now()
        prod_a = _mk_product(db, test_category, 'SKU-PMA-1')
        prod_b = _mk_product(db, test_category, 'SKU-PMA-2')
        _mk_product(db, test_category, 'SKU-PMA-3', active=False)
        _add_line(db, _mk_sale(db, owner_user, test_customer, prod_a, 'S-PMA-01',
                               now - timedelta(days=40)), prod_a)
        _add_line(db, _mk_sale(db, owner_user, test_customer, prod_a, 'S-PMA-02',
                               now - timedelta(days=30)), prod_a)
        _add_line(db, _mk_sale(db, owner_user, test_customer, prod_b, 'S-PMA-03',
                               now - timedelta(days=32)), prod_b)
        _add_line(db, _mk_sale(db, owner_user, test_customer, prod_b, 'S-PMA-04',
                               now - timedelta(days=4)), prod_b)

        alerts = PredictiveMaintenanceService.get_maintenance_alerts()
        assert [a['product_id'] for a in alerts] == [prod_a.id, prod_b.id]
        assert alerts[0]['urgency'] == 'high'
        assert alerts[0]['days_until_maintenance'] == 0
        assert alerts[1]['urgency'] == 'medium'
        assert alerts[0]['product_name'] == 'Product SKU-PMA-1'

    def test_alerts_threshold_filters_far_predictions(self, db, owner_user, test_customer, test_category):
        now = datetime.now()
        soon = _mk_product(db, test_category, 'SKU-PMT-1')
        far = _mk_product(db, test_category, 'SKU-PMT-2')
        _add_line(db, _mk_sale(db, owner_user, test_customer, soon, 'S-PMT-01',
                               now - timedelta(days=40)), soon)
        _add_line(db, _mk_sale(db, owner_user, test_customer, soon, 'S-PMT-02',
                               now - timedelta(days=30)), soon)
        _add_line(db, _mk_sale(db, owner_user, test_customer, far, 'S-PMT-03',
                               now - timedelta(days=32)), far)
        _add_line(db, _mk_sale(db, owner_user, test_customer, far, 'S-PMT-04',
                               now - timedelta(days=4)), far)

        alerts = PredictiveMaintenanceService.get_maintenance_alerts(threshold_days=3)
        assert [a['product_id'] for a in alerts] == [soon.id]

    def test_lifecycle_no_data_safe_default(self, db, test_product):
        assert PredictiveMaintenanceService.analyze_product_lifecycle(test_product.id) == {'status': 'no_data'}

    def test_lifecycle_same_day_sales_introduction_stage(self, db, owner_user, test_customer, test_product):
        sale = _mk_sale(db, owner_user, test_customer, test_product, 'S-PML-01', datetime.now())
        for i in range(3):
            _add_line(db, sale, test_product, quantity=Decimal('2'))
        result = PredictiveMaintenanceService.analyze_product_lifecycle(test_product.id)
        assert result['total_sold'] == 6.0
        assert result['days_active'] == 1
        assert result['avg_monthly_sales'] == 180.0
        assert result['total_transactions'] == 3
        assert result['lifecycle_stage'] == 'introduction'
        assert result['first_sale_date'][:10] == datetime.now().date().isoformat()

    def test_lifecycle_many_transactions_long_span_is_maturity(self, db, owner_user, test_customer, test_product):
        first = _mk_sale(db, owner_user, test_customer, test_product, 'S-PML-02',
                         datetime.now() - timedelta(days=200))
        for i in range(11):
            _add_line(db, first, test_product)
        second = _mk_sale(db, owner_user, test_customer, test_product, 'S-PML-03', datetime.now())
        for i in range(10):
            _add_line(db, second, test_product)
        result = PredictiveMaintenanceService.analyze_product_lifecycle(test_product.id)
        assert result['total_transactions'] == 21
        assert result['days_active'] == 200
        assert result['total_sold'] == 21.0
        assert result['avg_monthly_sales'] == 3.15
        assert result['lifecycle_stage'] == 'maturity'

    @pytest.mark.parametrize('days_active,transactions,expected', [
        (10, 99, 'introduction'),
        (179, 11, 'growth'),
        (365, 21, 'maturity'),
        (365, 5, 'decline'),
    ])
    def test_lifecycle_stage_classification(self, days_active, transactions, expected):
        assert PredictiveMaintenanceService._determine_lifecycle_stage(days_active, transactions) == expected


class TestAdvancedAudit:
    HEADERS = {
        'User-Agent': 'UA-X',
        'Accept-Language': 'en-US',
        'Accept-Encoding': 'gzip',
        'Sec-Ch-Ua-Platform': 'Windows',
    }

    def test_device_fingerprint_deterministic_hex16(self, app, db):
        with app.test_request_context('/', headers=self.HEADERS):
            fp1 = generate_device_fingerprint()
            fp2 = generate_device_fingerprint()
        assert fp1 == fp2
        assert len(fp1) == 16
        int(fp1, 16)

    def test_device_fingerprint_matches_sha256_prefix(self, app, db):
        with app.test_request_context('/', headers=self.HEADERS):
            fp = generate_device_fingerprint()
        expected = hashlib.sha256('UA-X|en-US|gzip|Windows'.encode()).hexdigest()[:16]
        assert fp == expected

    def test_device_fingerprint_varies_by_user_agent(self, app, db):
        with app.test_request_context('/', headers=self.HEADERS):
            fp_a = generate_device_fingerprint()
        other = dict(self.HEADERS, **{'User-Agent': 'UA-Y'})
        with app.test_request_context('/', headers=other):
            fp_b = generate_device_fingerprint()
        assert fp_a != fp_b

    def test_log_sensitive_action_writes_row_anonymous(self, app, db, owner_user):
        with app.test_request_context('/', environ_base={'REMOTE_ADDR': '10.1.2.3'},
                                      headers={'User-Agent': 'AuditUA/1.0'}):
            log_sensitive_action('delete', table_name='sales', record_id=42,
                                 changes={'total': 100}, severity='low')
        entry = AuditLog.query.filter_by(action='delete').one()
        assert entry.table_name == 'sales'
        assert entry.record_id == 42
        assert entry.changes == {'total': 100}
        assert entry.ip_address == '10.1.2.3'
        assert entry.user_agent == 'AuditUA/1.0'
        assert entry.user_id is None
        assert entry.created_at is not None

    def test_log_sensitive_action_records_authenticated_user(self, app, db, owner_user, monkeypatch):
        monkeypatch.setattr(
            advanced_audit, 'current_user',
            SimpleNamespace(id=owner_user.id, is_authenticated=True),
        )
        with app.test_request_context('/', environ_base={'REMOTE_ADDR': '203.0.113.9'},
                                      headers={'User-Agent': 'UA-Priv'}):
            log_sensitive_action('update', table_name='payments', record_id=7,
                                 changes={'paid': True}, severity='medium')
        entry = AuditLog.query.one()
        assert entry.user_id == owner_user.id
        assert entry.action == 'update'
        assert entry.changes == {'paid': True}

    def test_log_sensitive_action_high_severity_notifies_admin(self, app, db, owner_user, monkeypatch):
        seen = []
        monkeypatch.setattr(
            advanced_audit, 'notify_admin_of_sensitive_action',
            lambda action, entry: seen.append(action),
        )
        with app.test_request_context('/'):
            log_sensitive_action('export_users', table_name='users', severity='high')
        assert seen == ['export_users']
        assert AuditLog.query.filter_by(action='export_users').count() == 1

    def test_log_sensitive_action_low_severity_skips_notification(self, app, db, owner_user, monkeypatch):
        seen = []
        monkeypatch.setattr(
            advanced_audit, 'notify_admin_of_sensitive_action',
            lambda action, entry: seen.append(action),
        )
        with app.test_request_context('/'):
            log_sensitive_action('view', table_name='reports', severity='medium')
        assert seen == []

    def test_log_sensitive_action_swallows_db_errors_and_recovers(self, app, db, owner_user):
        with app.test_request_context('/'):
            log_sensitive_action('broken', changes={'unserializable': object()})
        assert AuditLog.query.count() == 0
        with app.test_request_context('/', environ_base={'REMOTE_ADDR': '9.9.9.9'}):
            log_sensitive_action('recovered', table_name='t1')
        assert AuditLog.query.filter_by(action='recovered').count() == 1

    def test_notify_admin_of_sensitive_action_is_noop(self, db):
        assert notify_admin_of_sensitive_action('delete', None) is None

    def test_track_login_attempt_success_resets_counter(self, app, db, owner_user):
        owner_user.login_attempts = 3
        db.session.commit()
        track_login_attempt('testowner', True, '192.168.1.5')
        user = User.query.filter_by(username='testowner').one()
        assert user.login_attempts == 0
        assert user.last_login is not None
        assert user.locked_until is None

    def test_track_login_attempt_locks_after_five_failures(self, app, db, owner_user):
        for _ in range(5):
            track_login_attempt('testowner', False, '192.168.1.5')
        user = User.query.filter_by(username='testowner').one()
        assert user.login_attempts == 5
        assert user.locked_until is not None

    def test_track_login_attempt_four_failures_does_not_lock(self, app, db, owner_user):
        for _ in range(4):
            track_login_attempt('testowner', False, '192.168.1.5')
        user = User.query.filter_by(username='testowner').one()
        assert user.login_attempts == 4
        assert user.locked_until is None

    def test_track_login_attempt_unknown_username_is_safe(self, app, db, owner_user):
        track_login_attempt('no-such-user-xyz', False, '10.0.0.1')
        assert User.query.filter_by(username='no-such-user-xyz').count() == 0

    def test_get_security_events_filters_actions_users_and_window(self, app, db, owner_user, seller_user):
        now = datetime.now(timezone.utc)
        db.session.add(AuditLog(user_id=owner_user.id, action='login', created_at=now))
        db.session.add(AuditLog(user_id=seller_user.id, action='delete', table_name='customers',
                                created_at=now - timedelta(minutes=5)))
        db.session.add(AuditLog(user_id=owner_user.id, action='view', table_name='reports', created_at=now))
        db.session.add(AuditLog(user_id=owner_user.id, action='update', table_name='sales',
                                record_id=3, created_at=now - timedelta(hours=2)))
        db.session.add(AuditLog(user_id=owner_user.id, action='logout',
                                created_at=now - timedelta(days=45)))
        db.session.commit()

        events = get_security_events()
        assert [e.action for e in events] == ['login', 'delete', 'update']

        seller_events = get_security_events(user_id=seller_user.id)
        assert [e.action for e in seller_events] == ['delete']
        assert all(e.user_id == seller_user.id for e in seller_events)

        owner_events = get_security_events(user_id=owner_user.id)
        assert [e.action for e in owner_events] == ['login', 'update']

        recent = get_security_events(days=1)
        assert {e.action for e in recent} == {'login', 'delete', 'update'}
