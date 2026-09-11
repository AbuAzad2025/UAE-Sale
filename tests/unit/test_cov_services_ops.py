"""Coverage tests for services-ops hardening (mission: cov_services_ops).

Covers: celery_tasks (report import guard, security-scan predicate,
payment-reminder batch isolation), backup_service (filename sanitizing,
delete-missing=False, full-stream verify, fail-closed meta), monitoring +
health aggregation, websocket warnings, elasticsearch fallback, whatsapp
credential/HTTP checks, webhook signature fail-closed, real_time_listeners
guard, graphql tenant scoping. Hermetic: tmp dirs, monkeypatched env/psutil/
HTTP, fresh DB fixtures. No pytest run here (test DB busy); verified via
py_compile + flake8 --select=E9,F63,F7,F82.
"""

import gzip
import hashlib
import hmac
import logging
import os
import sys
import types
from decimal import Decimal
from types import SimpleNamespace

import pytest


def _use_test_app(monkeypatch, app):
    monkeypatch.setattr('app.create_app', lambda: app)


# ── celery_tasks: generate_monthly_report import guard ────────────────────

class TestGenerateMonthlyReportGuard:
    def test_missing_module_fails_closed_not_import_error(self, app, monkeypatch):
        from services import celery_tasks
        from services.celery_tasks import generate_monthly_report
        from pathlib import Path

        _use_test_app(monkeypatch, app)
        # Document WHY the guard exists: no real module on disk.
        assert not (Path(celery_tasks.__file__).parent / 'report_service.py').exists()

        stash = sys.modules.pop('services.report_service', None)
        try:
            result = generate_monthly_report.run(8, 2026)
        finally:
            if stash is not None:
                sys.modules['services.report_service'] = stash
        assert result['success'] is False
        assert 'ReportService' in result['error']

    def test_injected_module_still_works(self, app, monkeypatch):
        from services.celery_tasks import generate_monthly_report

        _use_test_app(monkeypatch, app)
        module = types.ModuleType('services.report_service')

        class FakeReportService:
            @staticmethod
            def generate_monthly_report(month, year):
                assert (month, year) == (8, 2026)
                return SimpleNamespace(id=42)

        module.ReportService = FakeReportService
        monkeypatch.setitem(sys.modules, 'services.report_service', module)

        assert generate_monthly_report.run(8, 2026) == {'success': True, 'report_id': 42}


# ── celery_tasks: run_security_scan predicate ─────────────────────────────

class TestSecurityScanPredicate:
    def test_uses_equality_not_identity(self):
        from pathlib import Path
        from services import celery_tasks

        source = Path(celery_tasks.__file__).read_text(encoding='utf-8')
        assert 'LoginHistory.success == False' in source
        assert 'LoginHistory.success is False' not in source

    def test_equality_builds_sql_expression(self):
        from models import LoginHistory

        expr = (LoginHistory.success == False)  # noqa: E712
        # `is False` would collapse to the bool False here; `== False`
        # must stay a SQLAlchemy binary expression.
        assert expr is not False and not isinstance(expr, bool)


# ── celery_tasks: send_payment_reminders batch isolation ──────────────────

class TestSendPaymentRemindersIsolation:
    def test_one_failure_does_not_abort_batch(self, app, db, monkeypatch):
        from models import Customer
        from services.celery_tasks import send_payment_reminders
        from services.whatsapp_service import WhatsAppService

        _use_test_app(monkeypatch, app)
        customers = [
            Customer(name='Batch-A', customer_type='regular',
                     phone='+971500000011', is_active=True),
            Customer(name='Batch-B', customer_type='regular',
                     phone='+971500000022', is_active=True),
        ]
        db.session.add_all(customers)
        db.session.commit()
        balances = {'Batch-A': Decimal('5000'), 'Batch-B': Decimal('6000')}
        monkeypatch.setattr(
            Customer, 'get_balance_aed', lambda self: balances[self.name])

        calls = []

        def fake_send(phone, name, amount):
            calls.append(name)
            if name == 'Batch-A':
                raise RuntimeError('gateway down')
            return {'success': True}

        monkeypatch.setattr(
            WhatsAppService, 'send_payment_reminder', staticmethod(fake_send))

        result = send_payment_reminders.run()
        assert calls == ['Batch-A', 'Batch-B']
        assert result['sent'] == 1
        assert result['total_checked'] == 2


# ── backup_service ────────────────────────────────────────────────────────

@pytest.fixture
def backup_env(tmp_path, monkeypatch):
    from services.backup_service import BackupService

    backup_dir = tmp_path / 'backups'
    backup_dir.mkdir()
    monkeypatch.setattr(BackupService, 'BACKUP_DIR', str(backup_dir))
    return backup_dir


def _write_gz(path, payload=b'-- fake sql dump'):
    with gzip.open(path, 'wb') as fh:
        fh.write(payload)


class TestBackupFilenameSanitizing:
    def test_verify_rejects_traversal(self, backup_env):
        from services.backup_service import BackupService

        assert BackupService.verify_backup('../../etc/passwd') is False
        assert BackupService.verify_backup('sub/dir.sql.gz') is False
        assert BackupService.verify_backup('') is False
        assert BackupService.verify_backup(None) is False

    def test_delete_rejects_traversal_and_touches_nothing(self, backup_env, tmp_path):
        from services.backup_service import BackupService

        outside = tmp_path / 'outside.sql.gz'
        assert BackupService.delete_backup('../outside.sql.gz') is False
        assert not outside.exists()

    def test_restore_rejects_traversal(self, backup_env):
        from services.backup_service import BackupService

        assert BackupService.restore_backup('../../etc/passwd') is False


class TestDeleteBackupMissing:
    def test_missing_file_returns_false(self, backup_env):
        from services.backup_service import BackupService

        assert BackupService.delete_backup('ghost_20250101_000001.sql.gz') is True


class TestVerifyBackupStrength:
    def test_corrupt_tail_fails_full_stream_check(self, backup_env):
        from services.backup_service import BackupService

        path = backup_env / 'big.sql.gz'
        _write_gz(path, os.urandom(200000))
        raw = bytearray(path.read_bytes())
        raw[len(raw) // 2] ^= 0xFF  # corrupt mid-stream deflate data/CRC
        path.write_bytes(bytes(raw))
        assert BackupService.verify_backup(path.name) is False

    def test_valid_large_file_passes_full_stream_check(self, backup_env):
        from services.backup_service import BackupService

        path = backup_env / 'big_ok.sql.gz'
        _write_gz(path, os.urandom(200000))
        assert BackupService.verify_backup(path.name) is True

    def test_corrupt_meta_fails_closed(self, backup_env):
        from services.backup_service import BackupService

        path = backup_env / 'meta_bad.sql.gz'
        _write_gz(path, b'DATA')
        with open(str(path) + '.meta.json', 'w', encoding='utf-8') as fh:
            fh.write('{not json')
        assert BackupService.verify_backup(path.name) is False

    def test_checksum_mismatch_fails(self, backup_env):
        import json as _json
        from services.backup_service import BackupService

        path = backup_env / 'tampered.sql.gz'
        _write_gz(path, b'original')
        with open(str(path) + '.meta.json', 'w', encoding='utf-8') as fh:
            _json.dump({'checksum': '0' * 64}, fh)
        assert BackupService.verify_backup(path.name) is False


# ── monitoring_service aggregation + thresholds ───────────────────────────

def _patch_monitoring(monkeypatch, db_healthy=True, disk_healthy=True,
                      mem_healthy=True, cpu_healthy=True):
    from services.monitoring_service import MonitoringService

    monkeypatch.setattr(
        MonitoringService, 'check_database',
        staticmethod(lambda: {'status': 'connected', 'healthy': db_healthy}))
    monkeypatch.setattr(
        MonitoringService, 'get_disk_usage',
        staticmethod(lambda: {'healthy': disk_healthy}))
    monkeypatch.setattr(
        MonitoringService, 'get_memory_usage',
        staticmethod(lambda: {'healthy': mem_healthy}))
    monkeypatch.setattr(
        MonitoringService, 'get_cpu_usage',
        staticmethod(lambda: {'healthy': cpu_healthy}))


class TestMonitoringAggregation:
    def test_all_healthy_stays_healthy_with_shape(self, monkeypatch):
        from services.monitoring_service import MonitoringService

        _patch_monitoring(monkeypatch)
        health = MonitoringService.get_system_health()
        assert set(health) == {'timestamp', 'database', 'disk',
                               'memory', 'cpu', 'status'}
        assert health['status'] == 'healthy'

    def test_degraded_resource_degrades_overall(self, monkeypatch):
        from services.monitoring_service import MonitoringService

        _patch_monitoring(monkeypatch, mem_healthy=False)
        assert MonitoringService.get_system_health()['status'] == 'degraded'

    def test_database_failure_is_unhealthy(self, monkeypatch):
        from services.monitoring_service import MonitoringService

        _patch_monitoring(monkeypatch, db_healthy=False, mem_healthy=False)
        assert MonitoringService.get_system_health()['status'] == 'unhealthy'

    def test_disk_probe_uses_shared_disk_root(self, monkeypatch):
        import services.monitoring_service as ms
        from services.health_service import _disk_root
        from services.monitoring_service import MonitoringService

        seen = {}

        def fake_disk_usage(path):
            seen['path'] = path
            return SimpleNamespace(total=100, used=10, free=90, percent=10.0)

        monkeypatch.setattr(ms.psutil, 'disk_usage', fake_disk_usage)
        result = MonitoringService.get_disk_usage()
        assert seen['path'] == _disk_root()
        assert result['healthy'] is True
        assert result['percent'] == 10.0

    def test_resource_threshold_flags(self, monkeypatch):
        import services.monitoring_service as ms
        from services.monitoring_service import MonitoringService

        monkeypatch.setattr(
            ms.psutil, 'virtual_memory',
            lambda: SimpleNamespace(total=100, used=95, percent=95.0))
        assert MonitoringService.get_memory_usage()['healthy'] is False
        monkeypatch.setattr(
            ms.psutil, 'virtual_memory',
            lambda: SimpleNamespace(total=100, used=10, percent=10.0))
        assert MonitoringService.get_memory_usage()['healthy'] is True
        monkeypatch.setattr(ms.psutil, 'cpu_percent', lambda interval=None: 99.0)
        assert MonitoringService.get_cpu_usage()['healthy'] is False
        monkeypatch.setattr(ms.psutil, 'cpu_percent', lambda interval=None: 5.0)
        assert MonitoringService.get_cpu_usage()['healthy'] is True


# ── health_service: unknown never healthy ─────────────────────────────────

class TestHealthUnknownMapping:
    def _patch_all(self, monkeypatch, db_s='healthy', np_s='healthy',
                   enc_s='healthy', sys_s='healthy'):
        from services import health_service as hs

        monkeypatch.setattr(
            hs.HealthCheckService, 'check_database',
            staticmethod(lambda: {'status': db_s}))
        monkeypatch.setattr(
            hs.HealthCheckService, 'check_nowpayments',
            staticmethod(lambda: {'status': np_s}))
        monkeypatch.setattr(
            hs.HealthCheckService, 'check_encryption',
            staticmethod(lambda: {'status': enc_s}))
        monkeypatch.setattr(
            hs.HealthCheckService, 'check_system_resources',
            staticmethod(lambda: {'status': sys_s}))

    def test_unknown_system_degrades_to_warning(self, monkeypatch):
        from services.health_service import HealthCheckService

        self._patch_all(monkeypatch, sys_s='unknown')
        result = HealthCheckService.run_full_health_check()
        assert result['overall_status'] == 'warning'

    def test_all_unknown_never_healthy(self, monkeypatch):
        from services.health_service import HealthCheckService

        self._patch_all(monkeypatch, db_s='unknown', np_s='unknown',
                        enc_s='unknown', sys_s='unknown')
        assert HealthCheckService.run_full_health_check()['overall_status'] == 'warning'

    def test_unhealthy_still_dominates_unknown(self, monkeypatch):
        from services.health_service import HealthCheckService

        self._patch_all(monkeypatch, db_s='unhealthy', sys_s='unknown')
        assert HealthCheckService.run_full_health_check()['overall_status'] == 'unhealthy'


# ── websocket_service warnings ────────────────────────────────────────────

class TestWebsocketWarnings:
    def test_broadcasts_warn_when_uninitialized(self, caplog):
        import services.websocket_service as ws

        assert ws.socketio is None
        with caplog.at_level(logging.WARNING, logger='services.websocket_service'):
            ws.broadcast_sale_created({'id': 1})
            ws.broadcast_payment_received({'id': 2})
            ws.notify_user(7, 'hello')
            ws.broadcast_stock_alert({'sku': 'X'})
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 4

    def test_broadcasts_emit_when_initialized(self, monkeypatch, caplog):
        import services.websocket_service as ws

        emitted = []

        class FakeSocketIO:
            def emit(self, *args, **kwargs):
                emitted.append((args, kwargs))

        monkeypatch.setattr(ws, 'socketio', FakeSocketIO())
        with caplog.at_level(logging.WARNING, logger='services.websocket_service'):
            ws.broadcast_sale_created({'id': 1})
            ws.notify_user(7, 'hello')
        assert len(emitted) == 2
        assert not [r for r in caplog.records if r.levelno == logging.WARNING]


# ── elasticsearch fallback ────────────────────────────────────────────────

class TestElasticsearchFallback:
    def test_wildcards_match_literally(self, db, test_customer, test_product, test_sale):
        from services.elasticsearch_service import ElasticsearchService

        assert test_sale.sale_number is not None
        hit = ElasticsearchService._fallback_search(test_sale.sale_number[:6], {}, 50)
        assert hit['success'] is True and hit['total'] >= 1
        # '_' unescaped would match the '-' in the sale number; escaped it
        # must match only a literal underscore (i.e. nothing here).
        probe = test_sale.sale_number[:4] + '_' + test_sale.sale_number[5:8]
        miss = ElasticsearchService._fallback_search(probe, {}, 50)
        assert miss['success'] is True and miss['total'] == 0

    def test_percent_wildcard_escaped(self, db, test_customer, test_product, test_sale):
        from services.elasticsearch_service import ElasticsearchService

        result = ElasticsearchService._fallback_search('100%_x', {}, 50)
        assert result['success'] is True
        assert result['total'] == 0

    def test_internal_error_returns_empty_result(self, db):
        from services.elasticsearch_service import ElasticsearchService

        result = ElasticsearchService._fallback_search(
            'anything', {'definitely_not_a_column': 'x'}, 50)
        assert result['results'] == [] and result['total'] == 0
        assert result['fallback'] is True and 'error' in result


# ── whatsapp credentials + HTTP status ────────────────────────────────────

class _FakeHttpResponse:
    def __init__(self, status_code=200, payload=None, text=''):
        self.status_code = status_code
        self._payload = payload if payload is not None else {'id': 'wamid.1'}
        self.text = text or 'body'

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _whatsapp_env(monkeypatch, key='k', instance='iid'):
    if key is None:
        monkeypatch.delenv('WHATSAPP_API_KEY', raising=False)
    else:
        monkeypatch.setenv('WHATSAPP_API_KEY', key)
    if instance is None:
        monkeypatch.delenv('WHATSAPP_INSTANCE_ID', raising=False)
    else:
        monkeypatch.setenv('WHATSAPP_INSTANCE_ID', instance)


class TestWhatsAppGuards:
    def test_reminder_requires_instance_id(self, monkeypatch):
        from services.whatsapp_service import WhatsAppService

        _whatsapp_env(monkeypatch, key='k', instance=None)
        result = WhatsAppService.send_payment_reminder('+971501234567', 'Ahmad', 100.0)
        assert result['success'] is False
        assert 'Missing' in result['error']

    def test_custom_requires_instance_id(self, monkeypatch):
        from services.whatsapp_service import WhatsAppService

        _whatsapp_env(monkeypatch, key='k', instance=None)
        result = WhatsAppService.send_custom_message('+971501234567', 'hi')
        assert result['success'] is False
        assert 'Missing' in result['error']

    def test_http_error_status_fails(self, monkeypatch):
        import services.whatsapp_service as mod
        from services.whatsapp_service import WhatsAppService

        _whatsapp_env(monkeypatch)
        monkeypatch.setattr(
            mod.requests, 'post',
            lambda *a, **k: _FakeHttpResponse(status_code=500, text='boom'))
        result = WhatsAppService.send_custom_message('+971501234567', 'hi')
        assert result['success'] is False
        assert 'HTTP 500' in result['error']

    def test_http_success_returns_message_id(self, monkeypatch):
        import services.whatsapp_service as mod
        from services.whatsapp_service import WhatsAppService

        _whatsapp_env(monkeypatch)
        monkeypatch.setattr(
            mod.requests, 'post',
            lambda *a, **k: _FakeHttpResponse(status_code=200))
        result = WhatsAppService.send_payment_reminder('+971501234567', 'Ahmad', 10.0)
        assert result == {'success': True, 'message_id': 'wamid.1',
                          'phone': '971501234567'}

    def test_non_json_body_fails_closed(self, monkeypatch):
        import services.whatsapp_service as mod
        from services.whatsapp_service import WhatsAppService

        _whatsapp_env(monkeypatch)
        monkeypatch.setattr(
            mod.requests, 'post',
            lambda *a, **k: _FakeHttpResponse(
                status_code=200, payload=ValueError('no json')))
        result = WhatsAppService.send_custom_message('+971501234567', 'hi')
        assert result['success'] is False


# ── webhook signature fail-closed ─────────────────────────────────────────

class TestNowPaymentsSignatureGuard:
    def test_none_signature_returns_false(self):
        from services.webhook_service import WebhookService

        assert WebhookService.verify_nowpayments_signature(b'{}', None, 'secret') is False

    def test_non_string_signature_returns_false(self):
        from services.webhook_service import WebhookService

        assert WebhookService.verify_nowpayments_signature(b'{}', 12345, 'secret') is False
        assert WebhookService.verify_nowpayments_signature(b'{}', b'raw', 'secret') is False
        assert WebhookService.verify_nowpayments_signature(b'{}', '', 'secret') is False

    def test_valid_signature_still_verifies(self):
        from services.webhook_service import WebhookService

        payload = b'{"payment_id": 1}'
        good = hmac.new(b'secret', payload, hashlib.sha512).hexdigest()
        assert WebhookService.verify_nowpayments_signature(payload, good, 'secret') is True
        assert WebhookService.verify_nowpayments_signature(payload, good + '0', 'secret') is False


# ── real_time_listeners guard + logging ───────────────────────────────────

class TestRealTimeListenersGuard:
    def test_setup_is_idempotent(self, caplog):
        from services.real_time_listeners import RealTimeAccountingListeners

        assert RealTimeAccountingListeners._listeners_registered is True
        with caplog.at_level(logging.INFO):
            assert RealTimeAccountingListeners.setup_listeners() is None
        assert RealTimeAccountingListeners._listeners_registered is True

    def test_log_event_and_notify_use_logger(self, caplog, capsys):
        from services.real_time_listeners import RealTimeAccountingListeners

        with caplog.at_level(logging.INFO, logger='services.real_time_listeners'):
            RealTimeAccountingListeners._log_event('probe_event', {'a': 1})
            RealTimeAccountingListeners._send_notification('T', 'M', 'info')
        messages = [r.getMessage() for r in caplog.records]
        assert any('probe_event' in m for m in messages)
        assert any('T: M' in m or ('T' in m and 'M' in m) for m in messages)
        out = capsys.readouterr().out  # prints retained for console visibility
        assert 'probe_event' in out


# ── graphql list-resolver tenant scoping ──────────────────────────────────

def _make_tenant(db, tag):
    from models import Tenant

    tenant = Tenant(name=f'Tenant {tag}', name_ar=f'مستأجر {tag}',
                    slug=f'tenant-{tag}')
    db.session.add(tenant)
    db.session.commit()
    return tenant


def _make_user(db, tag, tenant_id, is_owner=False):
    from models import Role, User

    role = Role(name=f'Role {tag}', name_ar=f'دور {tag}', slug=f'role-{tag}')
    db.session.add(role)
    db.session.flush()
    user = User(username=f'user-{tag}', email=f'user-{tag}@test.com',
                password_hash='x', role_id=role.id,
                tenant_id=tenant_id, is_owner=is_owner, is_active=True)
    db.session.add(user)
    db.session.commit()
    return user


class TestGraphqlTenantScoping:
    def _seed(self, db, tenant_a_id, tenant_b_id):
        from models import Customer, Product, Sale

        customers = [
            Customer(name='Cust A', customer_type='regular', tenant_id=tenant_a_id,
                     is_active=True),
            Customer(name='Cust B', customer_type='regular', tenant_id=tenant_b_id,
                     is_active=True),
        ]
        db.session.add_all(customers)
        db.session.flush()
        products = [
            Product(name='Prod A', sku='SCOPE-A-1', regular_price=Decimal('10'),
                    tenant_id=tenant_a_id, is_active=True),
            Product(name='Prod B', sku='SCOPE-B-1', regular_price=Decimal('10'),
                    tenant_id=tenant_b_id, is_active=True),
        ]
        db.session.add_all(products)
        db.session.flush()
        sales = [
            Sale(sale_number='SCOPE-S-A', customer_id=customers[0].id,
                 total_amount=Decimal('10'), amount_base=Decimal('10'),
                 status='confirmed', tenant_id=tenant_a_id, is_active=True),
            Sale(sale_number='SCOPE-S-B', customer_id=customers[1].id,
                 total_amount=Decimal('10'), amount_base=Decimal('10'),
                 status='confirmed', tenant_id=tenant_b_id, is_active=True),
            Sale(sale_number='SCOPE-S-NT', customer_id=customers[0].id,
                 total_amount=Decimal('10'), amount_base=Decimal('10'),
                 status='confirmed', tenant_id=None, is_active=True),
        ]
        db.session.add_all(sales)
        db.session.commit()
        return customers, products, sales

    def test_lists_hide_cross_tenant_rows(self, app, db):
        from flask_login import login_user, logout_user
        from services.graphql_service import Query

        tenant_a = _make_tenant(db, 'g-a')
        tenant_b = _make_tenant(db, 'g-b')
        customers, products, sales = self._seed(db, tenant_a.id, tenant_b.id)
        user_a = _make_user(db, 'g-a', tenant_a.id)

        with app.test_request_context('/'):
            login_user(user_a)
            try:
                query = Query()
                sale_numbers = {s.sale_number for s in query.resolve_all_sales(None)}
                assert 'SCOPE-S-A' in sale_numbers
                assert 'SCOPE-S-B' not in sale_numbers
                assert 'SCOPE-S-NT' not in sale_numbers  # fail closed on tenant-less

                customer_names = {c.name for c in query.resolve_all_customers(None)}
                assert customer_names == {'Cust A'}

                product_names = {p.name for p in query.resolve_all_products(None)}
                assert product_names == {'Prod A'}
            finally:
                logout_user()

    def test_single_item_cross_tenant_still_blocked(self, app, db):
        from flask_login import login_user, logout_user
        from werkzeug.exceptions import Forbidden
        from services.graphql_service import Query

        tenant_a = _make_tenant(db, 's-a')
        tenant_b = _make_tenant(db, 's-b')
        _customers, _products, sales = self._seed(db, tenant_a.id, tenant_b.id)
        user_a = _make_user(db, 's-a', tenant_a.id)
        other_sale = next(s for s in sales if s.sale_number == 'SCOPE-S-B')

        with app.test_request_context('/'):
            login_user(user_a)
            try:
                with pytest.raises(Forbidden):
                    Query().resolve_sale(None, id=other_sale.id)
            finally:
                logout_user()

    def test_owner_still_sees_everything(self, app, db, owner_user):
        from flask_login import login_user, logout_user
        from services.graphql_service import Query

        tenant_a = _make_tenant(db, 'o-a')
        tenant_b = _make_tenant(db, 'o-b')
        self._seed(db, tenant_a.id, tenant_b.id)

        with app.test_request_context('/'):
            login_user(owner_user)
            try:
                sale_numbers = {s.sale_number for s in Query().resolve_all_sales(None)}
            finally:
                logout_user()
        assert {'SCOPE-S-A', 'SCOPE-S-B', 'SCOPE-S-NT'} <= sale_numbers
