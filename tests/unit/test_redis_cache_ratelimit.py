"""
Unit tests for utils/redis_cache.py and utils/rate_limiter_enhanced.py.

No real Redis: a tiny FakeRedis (keys/delete/expire/ttl) shares its store with a
fake Flask-Caching backend wired into extensions.cache, with a controllable clock
for TTL/window simulations.
"""

import fnmatch
import logging
from datetime import datetime, timedelta

import pytest

from utils.redis_cache import RedisCache


class FakeClock:
    def __init__(self, start=1_000_000.0):
        self.now = start

    def advance(self, seconds):
        self.now += seconds


class FakeRedis:
    """Minimal redis-compatible client sharing store/expires with the backend."""

    def __init__(self, store, expires, clock):
        self.store = store
        self.expires = expires
        self.clock = clock
        self.calls = []

    def _purge(self, key):
        exp = self.expires.get(key)
        if exp is not None and self.clock.now >= exp:
            self.store.pop(key, None)
            self.expires.pop(key, None)

    def keys(self, pattern='*'):
        for k in list(self.store):
            self._purge(k)
        return sorted(k for k in self.store if fnmatch.fnmatch(k, pattern))

    def delete(self, *keys):
        removed = 0
        for k in keys:
            if k in self.store:
                removed += 1
            self.store.pop(k, None)
            self.expires.pop(k, None)
        return removed

    def expire(self, key, seconds):
        self.calls.append(('expire', key, seconds))
        self._purge(key)
        if key not in self.store:
            return 0
        self.expires[key] = self.clock.now + seconds
        return 1

    def ttl(self, key):
        self.calls.append(('ttl', key))
        self._purge(key)
        if key not in self.store:
            return -2
        exp = self.expires.get(key)
        if exp is None:
            return -1
        return int(max(0, exp - self.clock.now))


class FakeCacheBackend:
    """Mimics the cachelib backend surface used through flask_caching.Cache."""

    def __init__(self, clock):
        self.clock = clock
        self.store = {}
        self.expires = {}
        self.client = FakeRedis(self.store, self.expires, clock)

    @property
    def _client(self):
        return self.client

    def _purge(self, key):
        self.client._purge(key)

    def get(self, key):
        self._purge(key)
        return self.store.get(key)

    def set(self, key, value, timeout=None):
        self._purge(key)
        self.store[key] = value
        if timeout:
            self.expires[key] = self.clock.now + timeout
        else:
            self.expires.pop(key, None)
        return True

    def add(self, key, value, timeout=None):
        if self.get(key) is not None:
            return False
        return self.set(key, value, timeout)

    def delete(self, key):
        existed = self.get(key) is not None
        self.store.pop(key, None)
        self.expires.pop(key, None)
        return existed

    def get_many(self, *keys):
        return [self.get(k) for k in keys]

    def set_many(self, mapping, timeout=None):
        for k, v in mapping.items():
            self.set(k, v, timeout)

    def inc(self, key, delta=1):
        self._purge(key)
        kept_expiry = self.expires.get(key)
        value = (self.store.get(key) or 0) + delta
        self.store[key] = value
        if kept_expiry is not None:
            self.expires[key] = kept_expiry
        else:
            self.expires.pop(key, None)
        return value

    def dec(self, key, delta=1):
        return self.inc(key, -delta)

    def has(self, key):
        return self.get(key) is not None

    def clear(self):
        self.store.clear()
        self.expires.clear()


class ExplodingBackend:
    """Backend that simulates a down Redis by raising on every access."""

    @property
    def _client(self):
        raise RuntimeError('redis down')

    def get(self, key):
        raise RuntimeError('redis down')

    def set(self, key, value, timeout=None):
        raise RuntimeError('redis down')

    def delete(self, key):
        raise RuntimeError('redis down')

    def get_many(self, *keys):
        raise RuntimeError('redis down')

    def set_many(self, mapping, timeout=None):
        raise RuntimeError('redis down')

    def keys(self, pattern):
        raise RuntimeError('redis down')

    def inc(self, key, delta=1):
        raise RuntimeError('redis down')

    def dec(self, key, delta=1):
        raise RuntimeError('redis down')


class PlainBackend:
    """Backend exposing no _client attribute (SimpleCache-like)."""

    def get(self, key):
        raise RuntimeError('redis down')


class ListHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def install_backend(app, monkeypatch, backend):
    from extensions import cache

    registry = app.extensions.setdefault('cache', {})
    monkeypatch.setitem(registry, cache, backend)
    return cache


@pytest.fixture
def wired(app, monkeypatch):
    """Replace the shared cache backend with FakeCacheBackend inside app ctx."""
    clock = FakeClock()
    backend = FakeCacheBackend(clock)
    cache_obj = install_backend(app, monkeypatch, backend)
    with app.app_context():
        yield {'cache': cache_obj, 'backend': backend, 'clock': clock}


def capture_app_logs(app):
    handler = ListHandler()
    app.logger.addHandler(handler)
    return handler


class TestRedisCacheCrud:
    def test_set_get_roundtrip_arabic_and_decimal_string(self, wired):
        from utils.redis_cache import RedisCache

        assert RedisCache.set('عربات:فرامل', 'قيمة-عربية')
        assert RedisCache.get('عربات:فرامل') == 'قيمة-عربية'
        assert RedisCache.set('price', '125.500')
        assert RedisCache.get('price') == '125.500'

    def test_default_timeout_applied_when_none(self, wired):
        from utils.redis_cache import RedisCache

        assert RedisCache.set('k', 'v') is True
        expires = wired['backend'].expires['k']
        assert expires == wired['clock'].now + 300

    def test_ttl_expiry_honored_by_fake_clock(self, wired):
        from utils.redis_cache import RedisCache

        assert RedisCache.set('stock', 42, timeout=30) is True
        assert RedisCache.get('stock') == 42
        wired['clock'].advance(31)
        assert RedisCache.get('stock') is None

    def test_delete_removes_key_only(self, wired):
        from utils.redis_cache import RedisCache

        RedisCache.set('a', 1)
        RedisCache.set('b', 2)
        assert RedisCache.delete('a') is True
        assert RedisCache.get('a') is None
        assert RedisCache.get('b') == 2

    def test_get_many_and_set_many(self, wired):
        from utils.redis_cache import RedisCache

        assert RedisCache.set_many({'m1': 'أحمد', 'm2': '10.25'}, timeout=60) is True
        values = RedisCache.get_many(['m1', 'm2'])
        assert list(values) == ['أحمد', '10.25']


class TestRedisCacheCounters:
    def test_increment_decrement_roundtrip(self, wired):
        from utils.redis_cache import RedisCache

        assert RedisCache.increment('hits') == 1
        assert RedisCache.increment('hits') == 2
        assert RedisCache.decrement('hits') == 1
        assert RedisCache.increment('hits', delta=5) == 6

    def test_counter_keys_are_isolated(self, wired):
        from utils.redis_cache import RedisCache

        RedisCache.increment('c1', delta=3)
        RedisCache.increment('c2', delta=7)
        assert wired['backend'].store['c1'] == 3
        assert wired['backend'].store['c2'] == 7


class TestGracefulDegrade:
    def test_get_failure_returns_none_and_logs_warning(self, app, monkeypatch):
        install_backend(app, monkeypatch, ExplodingBackend())
        with app.app_context():
            handler = capture_app_logs(app)
            try:
                assert RedisCache.get('x') is None
            finally:
                app.logger.removeHandler(handler)
        assert any('Cache get error' in m for m in handler.messages)

    def test_set_failure_returns_false(self, app, monkeypatch):
        install_backend(app, monkeypatch, ExplodingBackend())
        with app.app_context():
            assert RedisCache.set('x', 1) is False

    def test_delete_failure_returns_false(self, app, monkeypatch):
        install_backend(app, monkeypatch, ExplodingBackend())
        with app.app_context():
            assert RedisCache.delete('x') is False

    def test_bulk_failures_return_fallbacks(self, app, monkeypatch):
        install_backend(app, monkeypatch, ExplodingBackend())
        with app.app_context():
            assert RedisCache.get_many(['a']) == {}
            assert RedisCache.set_many({'a': 1}) is False

    def test_counter_failures_return_none(self, app, monkeypatch):
        install_backend(app, monkeypatch, ExplodingBackend())
        with app.app_context():
            assert RedisCache.increment('n') is None
            assert RedisCache.decrement('n') is None


class TestDeletePattern:
    def test_removes_matching_keys_keeps_others(self, wired):
        from utils.redis_cache import RedisCache

        prefix = 'garage_simple'
        wired['backend'].set(f'{prefix}model:Product:1', {'id': 1})
        wired['backend'].set(f'{prefix}model:Product:2', {'id': 2})
        wired['backend'].set('model:Product:3', {'id': 3})
        wired['backend'].set('model:Customer:1', {'id': 1})

        assert RedisCache.delete_pattern('model:Product:*') is True
        assert wired['backend'].get('model:Product:3') is None
        assert wired['backend'].get(f'{prefix}model:Product:1') is None
        assert wired['backend'].get(f'{prefix}model:Product:2') is None
        assert wired['backend'].get('model:Customer:1') == {'id': 1}

    def test_returns_false_when_backend_has_no_client(self, app, monkeypatch):
        install_backend(app, monkeypatch, PlainBackend())
        assert RedisCache.delete_pattern('*') is False

    def test_returns_false_on_backend_error(self, app, monkeypatch):
        install_backend(app, monkeypatch, ExplodingBackend())
        with app.app_context():
            assert RedisCache.delete_pattern('*') is False


class TestCachedDecorator:
    def test_second_call_served_from_cache(self, wired):
        from utils.redis_cache import cached

        calls = []

        @cached(timeout=120, key_prefix='products')
        def load_products():
            calls.append(1)
            return ['فرامل', 'زيت']

        assert load_products() == ['فرامل', 'زيت']
        assert load_products() == ['فرامل', 'زيت']
        assert len(calls) == 1

    def test_distinct_args_cached_separately(self, wired):
        from utils.redis_cache import cached

        calls = []

        @cached(timeout=60, key_prefix='sales')
        def load_sale(sale_id):
            calls.append(sale_id)
            return f'sale-{sale_id}'

        assert load_sale(1) == 'sale-1'
        assert load_sale(2) == 'sale-2'
        assert load_sale(1) == 'sale-1'
        assert calls == [1, 2]


class TestModelAndQueryHelpers:
    def test_model_cache_roundtrip_and_single_invalidation(self, wired):
        from utils.redis_cache import cache_model, get_cached_model, invalidate_model_cache

        data = {'name': 'فرامل أمامية', 'price': '100.000'}
        cache_model('Product', 5, data, timeout=600)
        assert get_cached_model('Product', 5) == data
        invalidate_model_cache('Product', 5)
        assert get_cached_model('Product', 5) is None

    def test_invalidate_model_cache_all_instances(self, wired):
        from utils.redis_cache import cache_model, invalidate_model_cache, get_cached_model

        cache_model('Product', 1, 'a')
        cache_model('Product', 2, 'ب')
        wired['backend'].set('garage_simplemodel:Product:9', 'c')
        wired['backend'].set('model:Customer:7', 'keep')

        invalidate_model_cache('Product')

        assert get_cached_model('Product', 1) is None
        assert get_cached_model('Product', 2) is None
        assert wired['backend'].get('garage_simplemodel:Product:9') is None
        assert wired['backend'].get('model:Customer:7') == 'keep'

    def test_query_cache_helpers(self, wired):
        from utils.redis_cache import cache_query_result, get_cached_query

        rows = [{'total': '50.00'}, {'total': '75.50'}]
        cache_query_result('daily_sales_2026-08-26', rows, timeout=900)
        assert get_cached_query('daily_sales_2026-08-26') == rows
        assert get_cached_query('missing') is None

    def test_customer_product_dashboard_helpers(self, wired):
        from utils.redis_cache import (
            cache_customer_balance,
            cache_dashboard_stats,
            cache_product_stock,
            get_cached_customer_balance,
            get_cached_dashboard_stats,
            get_cached_product_stock,
        )

        cache_customer_balance(77, '1250.500')
        cache_product_stock(88, 42, timeout=60)
        stats = {'sales_today': 13}
        cache_dashboard_stats(9, stats)
        assert get_cached_customer_balance(77) == '1250.500'
        assert get_cached_product_stock(88) == 42
        assert get_cached_dashboard_stats(9) == stats

    def test_invalidate_customer_cache_exact_and_wildcard(self, wired):
        from utils.redis_cache import invalidate_customer_cache

        wired['backend'].set('customer_balance:31', '900.000')
        wired['backend'].set('ledger:customer:31:recent', 'rows')
        wired['backend'].set('ledger:customer:32:recent', 'rows')

        invalidate_customer_cache(31)

        assert wired['backend'].get('customer_balance:31') is None
        assert wired['backend'].get('ledger:customer:31:recent') is None
        assert wired['backend'].get('ledger:customer:32:recent') == 'rows'

    def test_invalidate_product_cache_exact_and_wildcard(self, wired):
        from utils.redis_cache import invalidate_product_cache

        wired['backend'].set('product_stock:44', 12)
        wired['backend'].set('movement:product:44:last', 'in')
        wired['backend'].set('movement:product:45:last', 'out')

        invalidate_product_cache(44)

        assert wired['backend'].get('product_stock:44') is None
        assert wired['backend'].get('movement:product:44:last') is None
        assert wired['backend'].get('movement:product:45:last') == 'out'


class TestRateLimitCheck:
    def test_first_request_allowed_sets_window_ttl(self, wired):
        from utils.redis_cache import rate_limit_check

        allowed, remaining, reset_time = rate_limit_check('user:7', limit=5, window=60)
        assert allowed is True
        assert remaining == 4
        assert reset_time == 60
        assert ('expire', 'ratelimit:user:7', 60) in wired['backend'].client.calls

    def test_blocks_when_over_limit(self, wired):
        from utils.redis_cache import rate_limit_check

        results = [rate_limit_check('ip:1.2.3.4', limit=3, window=60) for _ in range(4)]
        assert [r[0] for r in results] == [True, True, True, False]
        assert results[3][1] == 0
        assert results[2][1] == 0

    def test_window_reset_after_fake_clock_expiry(self, wired):
        from utils.redis_cache import rate_limit_check

        for _ in range(4):
            allowed, _, _ = rate_limit_check('ip:5.5.5.5', limit=3, window=60)
        assert allowed is False
        wired['clock'].advance(61)
        allowed, remaining, reset_time = rate_limit_check('ip:5.5.5.5', limit=3, window=60)
        assert allowed is True
        assert remaining == 2
        assert reset_time == 60

    def test_fail_open_on_backend_error(self, app, monkeypatch):
        from utils.redis_cache import rate_limit_check

        install_backend(app, monkeypatch, ExplodingBackend())
        with app.app_context():
            allowed, remaining, reset_time = rate_limit_check('user:1', limit=10, window=30)
        assert (allowed, remaining, reset_time) == (True, 10, 30)


class FakeUser:
    def __init__(self, user_id=1, authenticated=True, owner=False, slug=None):
        self.id = user_id
        self.is_authenticated = authenticated
        self.is_owner = owner
        self.slug = slug

    def is_super_admin(self):
        return self.slug == 'super_admin'

    def is_manager(self):
        return self.slug == 'manager'


class FakeRequest:
    def __init__(self, endpoint, remote_addr):
        self.endpoint = endpoint
        self.remote_addr = remote_addr


@pytest.fixture
def limiter_env(app, monkeypatch):
    clock = FakeClock()
    backend = FakeCacheBackend(clock)
    cache_obj = install_backend(app, monkeypatch, backend)
    monkeypatch.setattr(
        'utils.rate_limiter_enhanced.request',
        FakeRequest(endpoint='test_ep', remote_addr='203.0.113.9'),
    )
    monkeypatch.setattr(
        'utils.rate_limiter_enhanced.current_user',
        FakeUser(authenticated=False),
    )
    with app.app_context():
        yield {'app': app, 'cache': cache_obj, 'backend': backend, 'clock': clock}


class TestSmartRateLimit:
    def _call(self, func):
        resp = func()
        if isinstance(resp, tuple):
            body, status = resp
            return status, body.get_json()
        return 200, None

    def test_owner_bypasses_limit_entirely(self, limiter_env, monkeypatch):
        from utils import rate_limiter_enhanced as rle

        monkeypatch.setattr(rle, 'current_user', FakeUser(owner=True))

        @rle.smart_rate_limit(max_requests=1, window_seconds=60)
        def view():
            return 'ok'

        statuses = [self._call(view)[0] for _ in range(5)]
        assert statuses == [200] * 5
        assert not any(k.startswith('rate_limit:') for k in limiter_env['backend'].store)

    def test_blocks_after_max_requests_with_payload(self, limiter_env):
        from utils import rate_limiter_enhanced as rle

        @rle.smart_rate_limit(max_requests=3, window_seconds=60)
        def view():
            return 'ok'

        assert self._call(view)[0] == 200
        assert self._call(view)[0] == 200
        assert self._call(view)[0] == 200
        status, payload = self._call(view)
        assert status == 429
        assert payload['error'] == 'Rate limit exceeded'
        assert payload['retry_after'] == 60

    def test_expired_requests_pruned_allows_again(self, limiter_env):
        from utils.redis_cache import RedisCache

        key = 'rate_limit:test_ep:203.0.113.9'
        stale = datetime.now() - timedelta(seconds=61)
        fresh = datetime.now() - timedelta(seconds=5)
        RedisCache.set(key, [stale, fresh], timeout=60)

        from utils import rate_limiter_enhanced as rle

        @rle.smart_rate_limit(max_requests=2, window_seconds=60)
        def view():
            return 'ok'

        status, _ = self._call(view)
        assert status == 200
        stored = limiter_env['backend'].get(key)
        assert len(stored) == 2

    def test_per_endpoint_and_ip_isolation(self, limiter_env, monkeypatch):
        from utils import rate_limiter_enhanced as rle

        monkeypatch.setattr(rle, 'current_user', FakeUser(authenticated=False))

        @rle.smart_rate_limit(max_requests=1, window_seconds=60)
        def view_a():
            return 'a'

        @rle.smart_rate_limit(max_requests=1, window_seconds=60)
        def view_b():
            return 'b'

        monkeypatch.setattr(
            rle, 'request', FakeRequest(endpoint='ep_a', remote_addr='203.0.113.9')
        )
        assert self._call(view_a)[0] == 200
        assert self._call(view_a)[0] == 429
        monkeypatch.setattr(
            rle, 'request', FakeRequest(endpoint='ep_b', remote_addr='203.0.113.9')
        )
        assert self._call(view_b)[0] == 200
        monkeypatch.setattr(
            rle, 'request', FakeRequest(endpoint='ep_a', remote_addr='198.51.100.7')
        )
        assert self._call(view_a)[0] == 200


class TestAdaptiveRateLimit:
    def _decorated(self, base_limit):
        from utils import rate_limiter_enhanced as rle

        @rle.adaptive_rate_limit(base_limit=base_limit)
        def view():
            return 'ok'

        return view

    def _call(self, func):
        resp = func()
        if isinstance(resp, tuple):
            body, status = resp
            return status, body.get_json()
        return 200, None

    def test_anonymous_gets_half_base_and_counts_up(self, limiter_env):
        view = self._decorated(base_limit=10)
        key = 'adaptive_limit:test_ep:203.0.113.9'
        for expected_count in range(1, 6):
            status, _ = self._call(view)
            assert status == 200
            assert limiter_env['backend'].get(key) == expected_count
        status, payload = self._call(view)
        assert status == 429
        assert payload['your_limit'] == 5

    def test_role_multipliers_table(self, limiter_env, monkeypatch):
        cases = [
            (FakeUser(user_id=11, slug='super_admin'), 100),
            (FakeUser(user_id=12, slug='manager'), 50),
            (FakeUser(user_id=13, slug='seller'), 10),
        ]
        base = 10
        for idx, (user, limit) in enumerate(cases):
            endpoint = f'ep_{idx}'
            monkeypatch.setattr('utils.rate_limiter_enhanced.current_user', user)
            monkeypatch.setattr(
                'utils.rate_limiter_enhanced.request',
                FakeRequest(endpoint=endpoint, remote_addr='203.0.113.9'),
            )
            view = self._decorated(base_limit=base)
            key = f'adaptive_limit:{endpoint}:{user.id}'

            limiter_env['backend'].set(key, limit - 1, timeout=60)
            assert self._call(view)[0] == 200
            assert limiter_env['backend'].get(key) == limit

            limiter_env['backend'].set(key, limit, timeout=60)
            status, payload = self._call(view)
            assert status == 429
            assert payload['your_limit'] == limit

    def test_owner_gets_hundredfold_limit(self, limiter_env, monkeypatch):
        from utils import rate_limiter_enhanced as rle

        monkeypatch.setattr(rle, 'current_user', FakeUser(user_id=99, owner=True))
        view = self._decorated(base_limit=5)
        key = 'adaptive_limit:test_ep:99'

        limiter_env['backend'].set(key, 499, timeout=60)
        assert self._call(view)[0] == 200
        assert limiter_env['backend'].get(key) == 500

        status, payload = self._call(view)
        assert status == 429
        assert payload['your_limit'] == 500
