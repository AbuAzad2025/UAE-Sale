"""
Health, monitoring, performance and telemetry tests.

Covers services/health_service.py, utils/monitoring.py, utils/performance.py,
utils/performance_tracker.py and utils/telemetry.py.
All network / psutil / disk interactions are mocked; runs fully offline.
"""

import json
import logging
import shutil
from decimal import Decimal
from types import SimpleNamespace

import pytest
from flask import Flask, g

from extensions import cache
from extensions import db as ext_db


@pytest.fixture(autouse=True)
def _clean_state(app, db):
    """Fresh cache per test; module registries are file/env based and isolated per test."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def app_log(app, monkeypatch, caplog):
    """Make current_app.logger records visible to caplog."""
    monkeypatch.setattr(app.logger, 'propagate', True)
    return caplog


class FakeClock:
    def __init__(self, ticks):
        self._ticks = list(ticks)
        self._i = 0

    def __call__(self):
        tick = self._ticks[min(self._i, len(self._ticks) - 1)]
        self._i += 1
        return tick


def fake_time(monkeypatch, module, ticks):
    clock = FakeClock(ticks)
    monkeypatch.setattr(module, 'time', SimpleNamespace(time=clock))
    return clock


class FakeResponse:
    def __init__(self, status_code=200):
        self.status_code = status_code
        self.headers = {}


def patch_psutil(monkeypatch, cpu=10.0, mem=40.0, disk=30.0, cpu_error=None):
    import services.health_service as hs

    def cpu_percent(interval=None):
        if cpu_error is not None:
            raise cpu_error
        return cpu

    monkeypatch.setattr(hs.psutil, 'cpu_percent', cpu_percent)
    monkeypatch.setattr(hs.psutil, 'virtual_memory', lambda: SimpleNamespace(percent=mem))
    monkeypatch.setattr(hs.psutil, 'disk_usage', lambda path: SimpleNamespace(percent=disk))


class TestHealthServiceChecks:
    def test_database_check_healthy_on_live_db(self, db):
        from services.health_service import HealthCheckService

        result = HealthCheckService.check_database()
        assert result == {'status': 'healthy', 'message': 'Database connection OK'}

    def test_database_check_reports_failure_message(self, monkeypatch):
        from services import health_service as hs

        class ExplodingSession:
            def execute(self, *args, **kwargs):
                raise RuntimeError('connection refused')

        monkeypatch.setattr(
            hs, 'db', SimpleNamespace(text=ext_db.text, session=ExplodingSession())
        )
        result = hs.HealthCheckService.check_database()
        assert result['status'] == 'unhealthy'
        assert 'connection refused' in result['message']

    def test_nowpayments_warning_when_vault_not_initialized(self, db):
        from services.health_service import HealthCheckService

        result = HealthCheckService.check_nowpayments()
        assert result == {
            'status': 'warning',
            'message': 'Payment vault not initialized',
        }

    def test_nowpayments_healthy_when_fully_configured(self, db):
        from models import PaymentVault
        from services.health_service import HealthCheckService

        db.session.add(PaymentVault(
            vault_password_hash='hash-x',
            nowpayments_api_key='npk-123456',
            bitcoin_address='bc1q-example-address',
        ))
        db.session.commit()

        result = HealthCheckService.check_nowpayments()
        assert result == {'status': 'healthy', 'message': 'NOWPayments configured'}

    def test_nowpayments_warning_when_partially_configured(self, db):
        from models import PaymentVault
        from services.health_service import HealthCheckService

        db.session.add(PaymentVault(
            vault_password_hash='hash-y', nowpayments_api_key='npk-only-key'
        ))
        db.session.commit()

        result = HealthCheckService.check_nowpayments()
        assert result == {
            'status': 'warning',
            'message': 'NOWPayments not fully configured',
        }

    def test_encryption_check_healthy(self, db):
        from services.health_service import HealthCheckService

        result = HealthCheckService.check_encryption()
        assert result == {'status': 'healthy', 'message': 'Encryption system OK'}

    def test_encryption_check_unhealthy_on_error(self, monkeypatch):
        from services import health_service as hs

        def broken_hash(password):
            raise RuntimeError('no hasher')

        import werkzeug.security
        monkeypatch.setattr(werkzeug.security, 'generate_password_hash', broken_hash)
        result = hs.HealthCheckService.check_encryption()
        assert result['status'] == 'unhealthy'
        assert 'no hasher' in result['message']


class TestHealthServiceSystemResources:
    def test_all_resources_nominal_is_healthy(self, db, monkeypatch):
        from services.health_service import HealthCheckService

        patch_psutil(monkeypatch, cpu=12.5, mem=41.0, disk=33.0)
        result = HealthCheckService.check_system_resources()
        assert result['status'] == 'healthy'
        assert result['cpu_percent'] == 12.5
        assert result['memory_percent'] == 41.0
        assert result['disk_percent'] == 33.0
        assert result['warnings'] is None

    def test_overloaded_resources_raise_warnings(self, db, monkeypatch):
        from services.health_service import HealthCheckService

        patch_psutil(monkeypatch, cpu=95.0, mem=97.0, disk=99.0)
        result = HealthCheckService.check_system_resources()
        assert result['status'] == 'warning'
        warnings = ' | '.join(result['warnings'])
        assert 'High CPU usage: 95.0%' in warnings
        assert 'High memory usage: 97.0%' in warnings
        assert 'Low disk space: 99.0% used' in warnings

    def test_resource_probe_error_degrades_to_unknown(self, db, monkeypatch):
        from services.health_service import HealthCheckService

        patch_psutil(monkeypatch, cpu_error=OSError('psu unavailable'))
        result = HealthCheckService.check_system_resources()
        assert result['status'] == 'unknown'
        assert 'psu unavailable' in result['message']

    def test_get_system_metrics_counts_and_process_info(self, db):
        from models import CardPayment, Donation
        from services.health_service import HealthCheckService

        db.session.add(Donation(amount_usd=Decimal('25.00'), payment_method='crypto'))
        db.session.add(CardPayment(
            customer_name='Metric Customer',
            transaction_type='donation',
            amount=Decimal('15.50'),
        ))
        db.session.commit()

        metrics = HealthCheckService.get_system_metrics()
        assert 'error' not in metrics
        assert metrics['database'] == {
            'total_donations': 1,
            'total_purchases': 0,
            'total_cards': 1,
        }
        assert metrics['process']['memory_mb'] > 0
        assert metrics['process']['threads'] >= 1
        assert metrics['process']['cpu_percent'] >= 0
        assert metrics['process']['uptime_seconds'] >= 0
        assert 'T' in metrics['timestamp']

    def test_full_check_aggregates_to_warning(self, db, monkeypatch):
        from services import health_service as hs
        from services.health_service import HealthCheckService

        monkeypatch.setattr(
            hs.HealthCheckService, 'check_system_resources',
            staticmethod(lambda: {'status': 'healthy'}),
        )
        result = HealthCheckService.run_full_health_check()
        assert result['overall_status'] == 'warning'
        assert result['checks']['nowpayments']['status'] == 'warning'
        assert set(result['checks']) == {
            'database', 'nowpayments', 'encryption', 'system',
        }

    def test_full_check_aggregates_to_unhealthy(self, db, monkeypatch):
        from services import health_service as hs
        from services.health_service import HealthCheckService

        monkeypatch.setattr(
            hs.HealthCheckService, 'check_database',
            staticmethod(lambda: {'status': 'unhealthy'}),
        )
        monkeypatch.setattr(
            hs.HealthCheckService, 'check_system_resources',
            staticmethod(lambda: {'status': 'healthy'}),
        )
        monkeypatch.setattr(
            hs.HealthCheckService, 'check_nowpayments',
            staticmethod(lambda: {'status': 'healthy'}),
        )
        result = HealthCheckService.run_full_health_check()
        assert result['overall_status'] == 'unhealthy'

    def test_full_check_healthy_when_everything_ok(self, db, monkeypatch):
        from models import PaymentVault
        from services import health_service as hs
        from services.health_service import HealthCheckService

        monkeypatch.setattr(
            hs.HealthCheckService, 'check_system_resources',
            staticmethod(lambda: {'status': 'healthy'}),
        )
        db.session.add(PaymentVault(
            vault_password_hash='hash-z',
            nowpayments_api_key='npk-full',
            bitcoin_address='bc1q-full-address',
        ))
        db.session.commit()

        result = HealthCheckService.run_full_health_check()
        assert result['overall_status'] == 'healthy'


class TestMonitoringMetricsCollector:
    def test_record_metric_logs_json_with_tags(self, app, app_log):
        from utils.monitoring import MetricsCollector

        MetricsCollector.record_metric('orders_created', 7, tags={'channel': 'pos'})

        metric_records = [
            r for r in app_log.records if r.getMessage().startswith('METRIC:')
        ]
        assert len(metric_records) == 1
        payload = json.loads(metric_records[0].getMessage().split('METRIC: ', 1)[1])
        assert payload['metric'] == 'orders_created'
        assert payload['value'] == 7
        assert payload['tags'] == {'channel': 'pos'}
        assert payload['timestamp']

    def test_record_helpers_emit_named_metrics(self, app, app_log):
        from utils.monitoring import MetricsCollector

        MetricsCollector.record_sale(Decimal('120.500'), 'AED')
        MetricsCollector.record_payment(75, 'cash')
        MetricsCollector.record_stock_change(42, -3, 'sale')

        messages = [r.getMessage() for r in app_log.records]
        sale = json.loads([m for m in messages if '"sale_created"' in m][0].split(': ', 1)[1])
        payment = json.loads([m for m in messages if '"payment_received"' in m][0].split(': ', 1)[1])
        stock = json.loads([m for m in messages if '"stock_movement"' in m][0].split(': ', 1)[1])

        assert sale['value'] == '120.500'
        assert sale['tags'] == {'currency': 'AED'}
        assert payment['value'] == 75
        assert payment['tags'] == {'method': 'cash'}
        assert stock['value'] == -3
        assert stock['tags'] == {'product_id': 42, 'type': 'sale'}


class TestMonitoringDatabaseMonitor:
    def test_slow_query_triggers_warning(self, app, app_log):
        from utils.monitoring import DatabaseMonitor

        DatabaseMonitor.log_query('SELECT * FROM sales JOIN sale_lines', 0.15)

        slow = [r for r in app_log.records if 'SLOW QUERY' in r.getMessage()]
        assert len(slow) == 1
        assert '150.0ms' in slow[0].getMessage()
        assert 'SELECT * FROM sales' in slow[0].getMessage()

    def test_fast_query_is_silent(self, app, app_log):
        from utils.monitoring import DatabaseMonitor

        DatabaseMonitor.log_query('SELECT 1', 0.02)
        assert not [r for r in app_log.records if 'SLOW QUERY' in r.getMessage()]


class TestMonitoringPerformanceMonitor:
    def test_slow_request_logs_warning_with_details(self, app, app_log):
        from utils.monitoring import PerformanceMonitor

        with app.test_request_context(
            '/sales/report',
            headers={'X-Request-Id': 'rid-slow', 'User-Agent': 'pytest-agent'},
            environ_base={'REMOTE_ADDR': '10.1.2.3'},
        ):
            PerformanceMonitor.log_request()
            g.start_time -= 1.2
            response = FakeResponse(200)
            out = PerformanceMonitor.log_response(response)

            assert out is response
            logged = [r for r in app_log.records if 'SLOW REQUEST' in r.getMessage()]
            assert len(logged) == 1
            data = json.loads(logged[0].getMessage().split('SLOW REQUEST: ', 1)[1])
            assert data['request_id'] == 'rid-slow'
            assert data['method'] == 'GET'
            assert data['path'] == '/sales/report'
            assert data['status'] == 200
            assert data['user_agent'] == 'pytest-agent'
            assert data['ip'] == '10.1.2.3'

    def test_fast_request_stays_quiet(self, app, app_log):
        from utils.monitoring import PerformanceMonitor

        with app.test_request_context('/', headers={'User-Agent': 'pytest'}):
            PerformanceMonitor.log_request()
            PerformanceMonitor.log_response(FakeResponse(200))

            assert not [
                r for r in app_log.records
                if 'REQUEST:' in r.getMessage() or 'SLOW REQUEST' in r.getMessage()
            ]

    def test_monitor_endpoint_decorator_success(self, app, app_log, monkeypatch):
        from utils import monitoring as mon

        fake_time(monkeypatch, mon, [100.0, 100.25])

        @mon.PerformanceMonitor.monitor_endpoint
        def sample():
            return 'payload'

        with app.app_context():
            assert sample() == 'payload'
        logs = [r for r in app_log.records if r.getMessage().startswith('ENDPOINT ')]
        assert any('sample: 250.0ms' in r.getMessage() for r in logs)

    def test_monitor_endpoint_decorator_reraises_and_logs(self, app, app_log, monkeypatch):
        from utils import monitoring as mon

        fake_time(monkeypatch, mon, [200.0, 200.4])

        @mon.PerformanceMonitor.monitor_endpoint
        def failing():
            raise ValueError('kaput')

        with app.app_context(), pytest.raises(ValueError, match='kaput'):
            failing()
        errors = [r for r in app_log.records if 'ENDPOINT ERROR failing' in r.getMessage()]
        assert len(errors) == 1
        assert 'kaput' in errors[0].getMessage()


class TestMonitoringErrorLogger:
    def test_log_error_persists_audit_row_with_context(self, app, db, app_log):
        from models.audit import AuditLog
        from utils.monitoring import ErrorLogger

        with app.test_request_context(
            '/reports/export',
            headers={'X-Request-Id': 'rid-err'},
            environ_base={'REMOTE_ADDR': '10.9.9.9'},
        ):
            g.request_id = 'rid-err'
            ErrorLogger.log_error(ValueError('bad thing'), context={'sale_id': 77})

        row = AuditLog.query.filter_by(action='error').one()
        payload = json.loads(row.changes)
        assert payload['error_type'] == 'ValueError'
        assert payload['error_message'] == 'bad thing'
        assert payload['context'] == {'sale_id': 77}
        assert payload['request_id'] == 'rid-err'
        assert row.ip_address == '10.9.9.9'


class TestMonitoringHealthChecks:
    def test_database_check_healthy(self, db):
        from utils.monitoring import HealthCheck

        assert HealthCheck.check_database()['status'] == 'healthy'

    def test_disk_space_healthy(self, monkeypatch):
        from utils.monitoring import HealthCheck

        monkeypatch.setattr(shutil, 'disk_usage', lambda path: (1000, 500, 500))
        result = HealthCheck.check_disk_space()
        assert result == {'status': 'healthy', 'message': 'Disk 50.0% used'}

    def test_disk_space_full_is_unhealthy(self, monkeypatch):
        from utils.monitoring import HealthCheck

        monkeypatch.setattr(shutil, 'disk_usage', lambda path: (1000, 951, 49))
        result = HealthCheck.check_disk_space()
        assert result['status'] == 'unhealthy'
        assert '95.1% full' in result['message']

    def test_disk_space_error_unknown_without_crash(self, monkeypatch):
        from utils.monitoring import HealthCheck

        def boom(path):
            raise OSError('no such volume')

        monkeypatch.setattr(shutil, 'disk_usage', boom)
        result = HealthCheck.check_disk_space()
        assert result['status'] == 'unknown'
        assert 'no such volume' in result['message']

    def test_redis_check_healthy_via_cache(self, db):
        from utils.monitoring import HealthCheck

        result = HealthCheck.check_redis()
        assert result == {'status': 'healthy', 'message': 'Redis connected'}

    def test_redis_failure_reports_unhealthy_not_crash(self, monkeypatch):
        from extensions import cache
        from utils.monitoring import HealthCheck

        def broken_set(*args, **kwargs):
            raise RuntimeError('redis down')

        monkeypatch.setattr(cache, 'set', broken_set)
        result = HealthCheck.check_redis()
        assert result['status'] == 'unhealthy'
        assert 'redis down' in result['message']

    def test_get_health_status_all_green(self, db, monkeypatch):
        from utils.monitoring import HealthCheck

        monkeypatch.setattr(shutil, 'disk_usage', lambda path: (1000, 300, 700))
        result = HealthCheck.get_health_status()
        assert result['status'] == 'healthy'
        assert {v['status'] for v in result['checks'].values()} == {'healthy'}
        assert 'T' in result['timestamp']

    def test_get_health_status_any_failure_flips_overall(self, db, monkeypatch):
        from utils.monitoring import HealthCheck

        monkeypatch.setattr(shutil, 'disk_usage', lambda path: (1000, 990, 10))
        result = HealthCheck.get_health_status()
        assert result['status'] == 'unhealthy'
        assert result['checks']['disk']['status'] == 'unhealthy'


class TestSetupAdvancedLogging:
    def test_registers_working_health_route_on_app(self, db, tmp_path, monkeypatch):
        from utils.monitoring import setup_advanced_logging

        monkeypatch.setattr(shutil, 'disk_usage', lambda path: (1000, 400, 600))
        monitored = Flask('monitored')
        monitored.root_path = str(tmp_path)

        setup_advanced_logging(monitored)
        try:
            resp = monitored.test_client().get('/health')
            data = resp.get_json()
            assert set(data['checks']) == {'database', 'redis', 'disk'}
            expected_code = 200 if data['status'] == 'healthy' else 503
            assert resp.status_code == expected_code
        finally:
            for handler in monitored.logger.handlers[:]:
                monitored.logger.removeHandler(handler)
                handler.close()


class TestMeasureTimeDecorator:
    def test_fast_function_returns_result_without_logs(self, caplog, monkeypatch):
        from utils import performance as perf

        fake_time(monkeypatch, perf, [10.0, 10.05])

        @perf.measure_time
        def work(value):
            return value * 2

        assert work(21) == 42
        assert not [r for r in caplog.records if r.name == 'utils.performance']

    def test_half_second_function_logs_info(self, caplog, monkeypatch):
        from utils import performance as perf

        fake_time(monkeypatch, perf, [10.0, 10.75])

        @perf.measure_time
        def medium():
            return 'done'

        with caplog.at_level(logging.INFO):
            assert medium() == 'done'
        infos = [r for r in caplog.records if r.levelno == logging.INFO]
        assert any('medium took 750ms' in r.getMessage() for r in infos)

    def test_slow_function_warns_over_one_second(self, caplog, monkeypatch):
        from utils import performance as perf

        fake_time(monkeypatch, perf, [0.0, 2.5])

        @perf.measure_time
        def heavy():
            return 'result'

        assert heavy() == 'result'
        warns = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any('Slow function: heavy took 2500ms' in r.getMessage() for r in warns)


class TestCacheResultDecorator:
    def test_second_call_hits_cache_without_recompute(self, db):
        from utils.performance import cache_result

        calls = []

        @cache_result(timeout=60)
        def load(x):
            calls.append(x)
            return {'x': x}

        assert load(4) == {'x': 4}
        assert load(4) == {'x': 4}
        assert calls == [4]

    def test_different_arguments_are_separate_entries(self, db):
        from utils.performance import cache_result

        calls = []

        @cache_result(timeout=60)
        def load(x):
            calls.append(x)
            return x + 1

        assert load(1) == 2
        assert load(2) == 3
        assert sorted(calls) == [1, 2]


class TestBatchCommit:
    def test_commits_all_items_in_batches(self, db, caplog):
        from models import Customer
        from utils.performance import batch_commit

        items = [
            Customer(
                name=f'Batch Customer {i}', customer_type='regular',
                phone=f'+971500000{i:03d}', balance=Decimal('0'),
            )
            for i in range(5)
        ]
        with caplog.at_level(logging.INFO):
            batch_commit(items, batch_size=2)

        assert Customer.query.count() == 5
        commits = [r for r in caplog.records if 'Batch committed' in r.getMessage()]
        assert len(commits) == 3


class TestPerformanceMonitorRequestTiming:
    def test_end_request_sets_header_and_warns_when_slow(self, app, caplog, monkeypatch):
        from utils import performance as perf

        fake_time(monkeypatch, perf, [100.0, 103.0])
        with app.test_request_context():
            perf.PerformanceMonitor.start_request()
            response = FakeResponse()
            out = perf.PerformanceMonitor.end_request(response)

            assert out is response
            assert response.headers['X-Response-Time'] == '3000.00ms'
        warns = [r for r in caplog.records if 'Slow request' in r.getMessage()]
        assert len(warns) == 1

    def test_end_request_fast_sets_header_only(self, app, caplog, monkeypatch):
        from utils import performance as perf

        fake_time(monkeypatch, perf, [100.0, 100.05])
        with app.test_request_context():
            perf.PerformanceMonitor.start_request()
            response = FakeResponse()
            perf.PerformanceMonitor.end_request(response)

            assert response.headers['X-Response-Time'] == '50.00ms'
        assert not [r for r in caplog.records if 'Slow request' in r.getMessage()]

    def test_end_request_without_start_returns_response_untouched(self, app):
        from utils import performance as perf

        with app.test_request_context():
            response = FakeResponse()
            out = perf.PerformanceMonitor.end_request(response)
            assert out is response
            assert 'X-Response-Time' not in response.headers


class TestTrackPerformanceDecorator:
    def test_below_threshold_records_metric_without_warning(self, app, caplog, monkeypatch):
        from utils import performance_tracker as pt

        fake_time(monkeypatch, pt, [100.0, 100.05])

        @pt.track_performance(threshold_ms=1000)
        def quick():
            return 'fast'

        with app.test_request_context():
            assert quick() == 'fast'
            assert g.performance_metrics['quick'] == pytest.approx(50.0)
        assert not [r for r in caplog.records if 'Slow operation' in r.getMessage()]

    def test_above_threshold_warns_with_custom_limit(self, app, caplog, monkeypatch):
        from utils import performance_tracker as pt

        fake_time(monkeypatch, pt, [0.0, 0.5])

        @pt.track_performance(threshold_ms=100)
        def sluggish():
            return 'slow'

        with app.test_request_context():
            assert sluggish() == 'slow'
        warns = [r for r in caplog.records if 'Slow operation: sluggish' in r.getMessage()]
        assert len(warns) == 1
        assert '(threshold: 100ms)' in warns[0].getMessage()

    def test_existing_metrics_dict_is_preserved(self, app, monkeypatch):
        from utils import performance_tracker as pt

        fake_time(monkeypatch, pt, [10.0, 10.2])

        @pt.track_performance(threshold_ms=1000)
        def another():
            return 1

        with app.test_request_context():
            g.performance_metrics = {'previous_op': 5.0}
            another()
            assert g.performance_metrics == {
                'previous_op': 5.0,
                'another': pytest.approx(200.0),
            }

    def test_exception_propagates_without_recording(self, app, monkeypatch):
        from utils import performance_tracker as pt

        fake_time(monkeypatch, pt, [10.0, 10.2])

        @pt.track_performance(threshold_ms=1000)
        def broken():
            raise KeyError('missing')

        with app.test_request_context():
            with pytest.raises(KeyError, match='missing'):
                broken()
            assert not hasattr(g, 'performance_metrics')


class TestPerformanceContext:
    def test_context_manager_logs_elapsed_operation(self, caplog, monkeypatch):
        from utils import performance_tracker as pt

        fake_time(monkeypatch, pt, [50.0, 50.25])

        with caplog.at_level(logging.INFO):
            with pt.PerformanceContext('invoice_generation'):
                pass
        infos = [r for r in caplog.records if 'invoice_generation' in r.getMessage()]
        assert any('took 250.00ms' in r.getMessage() for r in infos)


class TestLogSlowQueries:
    def test_registers_engine_listeners_and_flags_slow_query(self, app, caplog, monkeypatch):
        import sqlalchemy.event as event_module
        from utils import performance_tracker as pt

        registered = []

        def fake_listens_for(target, identifier):
            def decorator(fn):
                registered.append((identifier, fn))
                return fn
            return decorator

        monkeypatch.setattr(event_module, 'listens_for', fake_listens_for)
        pt.log_slow_queries(app)

        assert [identifier for identifier, _ in registered] == [
            'before_cursor_execute', 'after_cursor_execute',
        ]

        conn = SimpleNamespace(info={})
        before_fn = registered[0][1]
        after_fn = registered[1][1]
        long_statement = 'SELECT ' + 'x' * 300

        before_fn(conn, None, long_statement, None, None, False)
        conn.info['query_start_time'][0] -= 0.5
        with caplog.at_level(logging.WARNING):
            after_fn(conn, None, long_statement, None, None, False)

        slow = [r for r in caplog.records if 'Slow query' in r.getMessage()]
        assert len(slow) == 1
        assert long_statement[:100] in slow[0].getMessage()

    def test_fast_queries_do_not_warn(self, app, caplog, monkeypatch):
        import sqlalchemy.event as event_module
        from utils import performance_tracker as pt

        registered = []

        def fake_listens_for(target, identifier):
            def decorator(fn):
                registered.append(fn)
                return fn
            return decorator

        monkeypatch.setattr(event_module, 'listens_for', fake_listens_for)
        pt.log_slow_queries(app)

        conn = SimpleNamespace(info={})
        registered[0](conn, None, 'SELECT 1', None, None, False)
        registered[1](conn, None, 'SELECT 1', None, None, False)
        assert not [r for r in caplog.records if 'Slow query' in r.getMessage()]


def clear_telemetry_env(monkeypatch):
    for name in ('FORM_SUBMIT_URL', 'FORM_SUBMIT_EMAIL', 'OWNER_EMAIL',
                 'COMPANY_EMAIL', 'DISABLE_TELEMETRY'):
        monkeypatch.delenv(name, raising=False)


class TestTelemetryReportingUrl:
    def test_env_url_wins_and_is_stripped(self, monkeypatch):
        from utils import telemetry as tel

        clear_telemetry_env(monkeypatch)
        monkeypatch.setenv('FORM_SUBMIT_URL', 'https://hooks.example.test/abc ')
        assert tel.get_reporting_url() == 'https://hooks.example.test/abc'

    def test_explicit_email_builds_url(self, monkeypatch):
        from utils import telemetry as tel

        clear_telemetry_env(monkeypatch)
        assert tel.get_reporting_url('ops@example.io') == 'https://formsubmit.co/ops@example.io'

    def test_owner_email_env_used_as_fallback(self, monkeypatch):
        from utils import telemetry as tel

        clear_telemetry_env(monkeypatch)
        monkeypatch.setenv('OWNER_EMAIL', 'boss@example.net')
        assert tel.get_reporting_url() == 'https://formsubmit.co/boss@example.net'

    def test_email_without_at_falls_back_to_base_url(self, monkeypatch):
        from utils import telemetry as tel

        clear_telemetry_env(monkeypatch)
        assert tel.get_reporting_url('not-an-email') == 'https://formsubmit.co'


class TestTelemetrySignatureAndToken:
    def test_signature_combines_host_components(self, monkeypatch):
        from utils import telemetry as tel

        monkeypatch.setattr(tel.socket, 'gethostname', lambda: 'unit-host')
        signature = tel.get_machine_signature()
        parts = signature.split('|')
        assert parts[0] == 'unit-host'
        assert len(parts) == 4

    def test_signature_failure_returns_sentinel(self, monkeypatch):
        from utils import telemetry as tel

        def broken_hostname():
            raise OSError('no host')

        monkeypatch.setattr(tel.socket, 'gethostname', broken_hostname)
        assert tel.get_machine_signature() == 'unknown_machine'

    def test_token_file_roundtrip(self, tmp_path, monkeypatch):
        from utils import telemetry as tel

        token_file = tmp_path / 'tok'
        monkeypatch.setattr(tel, 'TOKEN_FILE', str(token_file))

        assert tel.has_reported_before('mach-1') is False
        tel.mark_as_reported('mach-1')
        assert token_file.read_text(encoding='utf-8') == 'mach-1'
        assert tel.has_reported_before('mach-1') is True
        assert tel.has_reported_before('mach-2') is False

    def test_mark_as_reported_swallows_write_errors(self, tmp_path, monkeypatch):
        from utils import telemetry as tel

        monkeypatch.setattr(tel, 'TOKEN_FILE', str(tmp_path))
        tel.mark_as_reported('mach-x')


class TestTelemetryLocalLog:
    def test_save_local_log_appends_json_lines(self, tmp_path, monkeypatch):
        from utils import telemetry as tel

        log_file = tmp_path / '.security_audit.log'
        monkeypatch.setattr(tel, 'HIDDEN_LOG_FILE', str(log_file))

        tel.save_local_log({'event': 'first'})
        tel.save_local_log({'event': 'second'})

        lines = log_file.read_text(encoding='utf-8').strip().splitlines()
        assert len(lines) == 2
        assert [json.loads(line)['event'] for line in lines] == ['first', 'second']


class TestTelemetryNetwork:
    def test_send_formsubmit_posts_pinned_payload(self, monkeypatch):
        from utils import telemetry as tel

        clear_telemetry_env(monkeypatch)
        monkeypatch.setenv('FORM_SUBMIT_URL', 'https://hooks.example.test/pin')

        captured = {}

        def fake_post(url, data=None, headers=None, timeout=None):
            captured.update(url=url, data=data, headers=headers, timeout=timeout)
            return SimpleNamespace(status_code=200)

        monkeypatch.setattr(tel.requests, 'post', fake_post)

        assert tel.send_formsubmit('Nightly Alert', {'IP Address': '203.0.113.9'}) is True
        assert captured['url'] == 'https://hooks.example.test/pin'
        assert captured['timeout'] == 2
        assert captured['data']['_subject'] == 'Nightly Alert'
        assert captured['data']['_captcha'] == 'false'
        assert captured['data']['IP Address'] == '203.0.113.9'
        assert captured['headers']['Referer'].startswith('http')

    def test_send_formsubmit_false_on_non_200(self, monkeypatch):
        from utils import telemetry as tel

        clear_telemetry_env(monkeypatch)
        monkeypatch.setattr(
            tel, 'requests',
            SimpleNamespace(post=lambda *a, **k: SimpleNamespace(status_code=500)),
        )
        assert tel.send_formsubmit('Subject', {}) is False

    def test_send_formsubmit_false_on_network_error(self, monkeypatch):
        from utils import telemetry as tel

        clear_telemetry_env(monkeypatch)

        def refused(*args, **kwargs):
            raise ConnectionError('offline')

        monkeypatch.setattr(
            tel, 'requests', SimpleNamespace(post=refused),
        )
        assert tel.send_formsubmit('Subject', {}) is False

    def test_collect_system_info_primary_ip_service(self, monkeypatch):
        from utils import telemetry as tel

        def fake_get(url, timeout=None):
            assert 'ipify' in url
            return SimpleNamespace(json=lambda: {'ip': '203.0.113.7'})

        monkeypatch.setattr(tel.requests, 'get', fake_get)
        info = tel.collect_system_info()
        assert info['public_ip'] == '203.0.113.7'
        assert info['hostname']
        assert info['python_version']

    def test_collect_system_info_falls_back_to_second_service(self, monkeypatch):
        from utils import telemetry as tel

        attempts = []

        def fake_get(url, timeout=None):
            attempts.append(url)
            if len(attempts) == 1:
                raise ConnectionError('primary down')
            assert 'ifconfig.me' in url
            return SimpleNamespace(json=lambda: {'ip_addr': '198.51.100.9'})

        monkeypatch.setattr(tel.requests, 'get', fake_get)
        info = tel.collect_system_info()
        assert info['public_ip'] == '198.51.100.9'

    def test_collect_system_info_offline_keeps_unknown_ip(self, monkeypatch):
        from utils import telemetry as tel

        def refused(url, timeout=None):
            raise ConnectionError('fully offline')

        monkeypatch.setattr(tel.requests, 'get', refused)
        info = tel.collect_system_info()
        assert info['public_ip'] == 'Unknown'
        assert info['os']


class TestSendHeartbeat:
    def make_info(self):
        return {
            'timestamp': '2026-08-26T10:00:00',
            'hostname': 'box-77',
            'os': 'Windows',
            'os_release': '11',
            'machine': 'AMD64',
            'processor': ' Ryzen 9 ',
            'python_version': '3.14.6',
            'public_ip': '203.0.113.5',
        }

    def test_first_run_sends_marks_token_and_saves_log(self, tmp_path, monkeypatch):
        from utils import telemetry as tel

        clear_telemetry_env(monkeypatch)
        token_file = tmp_path / '.machine_token'
        log_file = tmp_path / '.security_audit.log'
        monkeypatch.setattr(tel, 'TOKEN_FILE', str(token_file))
        monkeypatch.setattr(tel, 'HIDDEN_LOG_FILE', str(log_file))
        monkeypatch.setattr(tel, 'get_machine_signature', lambda: 'sig-first')
        monkeypatch.setattr(tel, 'collect_system_info', self.make_info)

        sent = {}

        def fake_submit(subject, fields, to_email=None):
            sent.update(subject=subject, fields=fields)
            return True

        monkeypatch.setattr(tel, 'send_formsubmit', fake_submit)

        tel.send_heartbeat()

        assert token_file.read_text(encoding='utf-8') == 'sig-first'
        entries = log_file.read_text(encoding='utf-8').strip().splitlines()
        assert len(entries) == 1
        assert json.loads(entries[0])['hostname'] == 'box-77'
        assert sent['fields']['Machine ID'] == 'sig-first'
        assert sent['fields']['IP Address'] == '203.0.113.5'
        assert 'box-77' in sent['subject']
        assert '203.0.113.5' in sent['subject']

    def test_repeat_run_skips_sending_to_avoid_spam(self, tmp_path, monkeypatch):
        from utils import telemetry as tel

        clear_telemetry_env(monkeypatch)
        token_file = tmp_path / '.machine_token'
        log_file = tmp_path / '.security_audit.log'
        token_file.write_text('sig-repeat', encoding='utf-8')
        monkeypatch.setattr(tel, 'TOKEN_FILE', str(token_file))
        monkeypatch.setattr(tel, 'HIDDEN_LOG_FILE', str(log_file))
        monkeypatch.setattr(tel, 'get_machine_signature', lambda: 'sig-repeat')

        calls = []

        def spy_submit(subject, fields, to_email=None):
            calls.append(subject)
            return True

        monkeypatch.setattr(tel, 'send_formsubmit', spy_submit)

        tel.send_heartbeat()

        assert calls == []
        assert not log_file.exists()
        assert token_file.read_text(encoding='utf-8') == 'sig-repeat'

    def test_failed_send_does_not_mark_as_reported(self, tmp_path, monkeypatch):
        from utils import telemetry as tel

        clear_telemetry_env(monkeypatch)
        token_file = tmp_path / '.machine_token'
        log_file = tmp_path / '.security_audit.log'
        monkeypatch.setattr(tel, 'TOKEN_FILE', str(token_file))
        monkeypatch.setattr(tel, 'HIDDEN_LOG_FILE', str(log_file))
        monkeypatch.setattr(tel, 'get_machine_signature', lambda: 'sig-fail')
        monkeypatch.setattr(tel, 'collect_system_info', self.make_info)
        monkeypatch.setattr(tel, 'send_formsubmit', lambda s, fields, to_email=None: False)

        tel.send_heartbeat()

        assert not token_file.exists()
        assert log_file.exists()


class TestStartTelemetry:
    def test_disabled_mode_never_starts_thread(self, monkeypatch):
        from utils import telemetry as tel

        clear_telemetry_env(monkeypatch)
        monkeypatch.setenv('DISABLE_TELEMETRY', 'true')

        started = []

        def fake_thread(target=None, daemon=None):
            started.append(target)
            raise AssertionError('thread should not be created')

        monkeypatch.setattr(tel, 'Thread', fake_thread)
        tel.start_telemetry()
        assert started == []

    def test_enabled_mode_starts_daemon_background_thread(self, monkeypatch):
        from utils import telemetry as tel

        clear_telemetry_env(monkeypatch)
        monkeypatch.setenv('DISABLE_TELEMETRY', 'False')

        started = {}

        class FakeThread:
            def __init__(self, target=None):
                started['target'] = target

            def start(self):
                started['daemon'] = self.daemon
                started['launched'] = True

        monkeypatch.setattr(tel, 'Thread', FakeThread)
        tel.start_telemetry()

        assert started['launched'] is True
        assert started['daemon'] is True
        assert started['target'] is tel.send_heartbeat
