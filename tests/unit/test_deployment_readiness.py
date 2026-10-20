"""Tests for the deployment health probe.

/api/healthz is the load-balancer readiness probe. It must answer 503 only
when the application genuinely cannot serve traffic; a warning about an
optional integration must not take the instance out of rotation.
"""
import pytest


@pytest.fixture
def healthz(client):
    return client.get('/api/healthz')


def test_healthz_is_reachable_without_authentication(healthz):
    """A load balancer has no session; the probe must not require one."""
    assert healthz.status_code in (200, 503)
    body = healthz.get_json()
    assert body is not None
    assert 'overall_status' in body
    assert 'checks' in body


def test_healthz_reports_every_subsystem(healthz):
    body = healthz.get_json()
    for check in ('database', 'encryption', 'nowpayments', 'system',
                  'ai_engine'):
        assert check in body['checks'], f'{check} missing from the probe'
        assert 'status' in body['checks'][check]


def test_healthz_answers_503_only_when_unhealthy(client, monkeypatch):
    """A warning keeps the instance in rotation; only unhealthy removes it."""
    from services import health_service as hs

    def _warning():
        return {
            'overall_status': 'warning',
            'checks': {
                'database': {'status': 'warning', 'message': 'vault not '
                             'initialised'},
            },
            'timestamp': 'now',
        }

    monkeypatch.setattr(hs.HealthCheckService, 'run_full_health_check',
                        staticmethod(_warning))
    r = client.get('/api/healthz')
    assert r.status_code == 200, (
        'a warning must not take the instance out of the load balancer')

    def _unhealthy():
        return {
            'overall_status': 'unhealthy',
            'checks': {'database': {'status': 'unhealthy'}},
            'timestamp': 'now',
        }

    monkeypatch.setattr(hs.HealthCheckService, 'run_full_health_check',
                        staticmethod(_unhealthy))
    r = client.get('/api/healthz')
    assert r.status_code == 503, (
        'an unhealthy result must take the instance out of rotation')


def test_cache_works_without_redis(app):
    """PythonAnywhere has no Redis, so the default cache must not need one.

    The previous default was RedisCache. With no Redis reachable every
    cache.set raised ConnectionError: the dashboard silently recomputed on
    every request and the rate limiter never counted anything, so the limiter
    did not limit.
    """
    from extensions import cache

    # The backend is named either as a class path or as Flask-Caching's short
    # alias depending on how it was resolved, so the invariant is checked
    # directly: the default must not be a Redis backend.
    cache_type = str(app.config['CACHE_TYPE']).lower()
    assert 'redis' not in cache_type, (
        f"the default cache is {app.config['CACHE_TYPE']}, which needs Redis")

    with app.app_context():
        cache.set('deployment-probe', 'value', timeout=10)
        assert cache.get('deployment-probe') == 'value'


def test_production_refuses_sqlite(monkeypatch):
    """Production must not silently run on SQLite.

    This is the guard that stops a misconfigured deployment from serving
    traffic from a throwaway in-memory database. It is enforced by
    assert_production_sanity, which runs when the app is created.
    """
    from config import assert_production_sanity

    class _Prod:
        DEBUG = False
        APP_ENV = 'production'
        SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
        SESSION_COOKIE_SECURE = True
        BASE_URL = ''

    monkeypatch.setenv('SECRET_KEY', 'x' * 32)
    monkeypatch.setenv('CARD_ENCRYPTION_KEY', 'y' * 32)

    with pytest.raises(RuntimeError, match='SQLite'):
        assert_production_sanity(_Prod)


def test_production_requires_secrets(monkeypatch):
    """A production boot without SECRET_KEY must fail loudly."""
    from config import assert_production_sanity

    class _Prod:
        DEBUG = False
        APP_ENV = 'production'
        SQLALCHEMY_DATABASE_URI = 'postgresql://u:p@h/db'
        SESSION_COOKIE_SECURE = True
        BASE_URL = ''

    monkeypatch.delenv('SECRET_KEY', raising=False)
    monkeypatch.setenv('CARD_ENCRYPTION_KEY', 'y' * 32)
    with pytest.raises(RuntimeError, match='SECRET_KEY'):
        assert_production_sanity(_Prod)

    monkeypatch.setenv('SECRET_KEY', 'x' * 32)
    monkeypatch.delenv('CARD_ENCRYPTION_KEY', raising=False)
    with pytest.raises(RuntimeError, match='CARD_ENCRYPTION_KEY'):
        assert_production_sanity(_Prod)