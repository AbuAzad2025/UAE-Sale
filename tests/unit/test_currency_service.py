"""Unit tests for CurrencyService — العملة الديناميكية وأسعار الصرف."""
from decimal import Decimal

import pytest

import services.currency_service as cs_module
from models.system_settings import SystemSettings
from services.currency_service import CurrencyService


@pytest.fixture(autouse=True)
def _clear_cache():
    CurrencyService._rates_cache.clear()
    yield
    CurrencyService._rates_cache.clear()


@pytest.fixture
def offline(monkeypatch):
    """Force pure-fallback pricing (no network)."""
    monkeypatch.setattr(cs_module, 'REQUESTS_AVAILABLE', False)
    monkeypatch.setattr(cs_module, 'FOREX_AVAILABLE', False)


class TestBaseCurrency:
    def test_default_without_context(self, app, db):
        assert CurrencyService.get_base_currency() == CurrencyService.DEFAULT_BASE

    def test_config_override(self, app, db):
        app.config['DEFAULT_CURRENCY'] = 'USD'
        try:
            assert CurrencyService.get_base_currency() == 'USD'
        finally:
            app.config['DEFAULT_CURRENCY'] = CurrencyService.DEFAULT_BASE

    def test_system_settings_win(self, app, db):
        db.session.add(SystemSettings(default_currency='EUR', is_active=True))
        db.session.commit()
        assert CurrencyService.get_base_currency() == 'EUR'


class TestExchangeRateBasics:
    def test_user_rate_returned_quantized(self):
        rate = CurrencyService.get_exchange_rate('USD', 'ILS', user_rate='3.6578915')
        assert rate == Decimal('3.657892')

    def test_nonpositive_user_rate_raises(self):
        with pytest.raises(ValueError, match='Invalid'):
            CurrencyService.get_exchange_rate('USD', 'ILS', user_rate=0)

    def test_negative_user_rate_raises(self):
        with pytest.raises(ValueError, match='Invalid'):
            CurrencyService.get_exchange_rate('USD', 'ILS', user_rate='-1')

    def test_same_currency_returns_one(self):
        assert CurrencyService.get_exchange_rate('AED', 'AED') == Decimal('1')

    def test_none_defaults_to_base(self):
        assert CurrencyService.get_exchange_rate(None, None) == Decimal('1')


class TestFallbackRates:
    def test_fallback_cross_rates_offline(self, offline):
        rates = CurrencyService.get_all_rates(base='USD')
        assert rates['USD'] == Decimal('1.00')
        # 1 USD = 1/0.27 ILS
        assert rates['ILS'] == Decimal('3.703704')
        # cross: AED per USD = 0.99/0.27
        assert rates['AED'] == Decimal('3.666667')

    def test_fallback_for_unknown_base(self, offline):
        rates = CurrencyService.get_all_rates(base='ZZZ')
        # unknown base still yields a usable table for known targets
        assert rates.get('ILS') is not None
        assert rates.get('USD') is not None

    def test_get_exchange_rate_via_fallback(self, offline):
        usd_to_aed = CurrencyService.get_exchange_rate('USD', 'AED')
        assert usd_to_aed == Decimal('3.666667')

    def test_cache_populated_and_reused(self, offline):
        first = CurrencyService.get_all_rates(base='SAR')
        assert 'SAR' in CurrencyService._rates_cache
        second = CurrencyService.get_all_rates(base='SAR')
        assert first == second

    def test_cached_rate_used_by_get_exchange_rate(self, offline):
        CurrencyService._rates_cache['JPY'] = {
            'timestamp': __import__('time').time(),
            'rates': {'AED': Decimal('0.033')},
        }
        assert CurrencyService.get_exchange_rate('JPY', 'AED') == Decimal('0.033')

    def test_missing_pair_defaults_to_one(self, offline):
        assert CurrencyService.get_exchange_rate('ZZZ', 'QQQ') == Decimal('1')


class _FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


class TestLiveApiPaths:
    def test_live_api_success_normalizes_and_caches(self, monkeypatch):
        calls = []

        def fake_get(url, timeout=5):
            calls.append(url)
            return _FakeResp({'rates': {'usd': '3.7', 'eur': 4.0}})

        monkeypatch.setattr(cs_module.requests, 'get', fake_get)
        rates = CurrencyService.get_all_rates(base='ILS')
        assert len(calls) == 1
        assert rates['USD'] == Decimal('3.7')
        assert rates['EUR'] == Decimal('4.0')
        assert rates['ILS'] == Decimal('1.00')
        assert 'ILS' in CurrencyService._rates_cache

    def test_first_endpoint_fails_second_succeeds(self, monkeypatch):
        def fake_get(url, timeout=5):
            if 'er-api' in url:
                raise ConnectionError('down')
            return _FakeResp({'rates': {'AED': '0.99'}})

        monkeypatch.setattr(cs_module.requests, 'get', fake_get)
        rates = CurrencyService.get_all_rates(base='ILS')
        assert rates['AED'] == Decimal('0.99')

    def test_all_apis_fail_falls_back(self, offline, monkeypatch):
        def boom(url, timeout=5):
            raise ConnectionError('offline')

        monkeypatch.setattr(cs_module.requests, 'get', boom)
        monkeypatch.setattr(cs_module, 'REQUESTS_AVAILABLE', True)
        rates = CurrencyService.get_all_rates(base='ILS')
        assert rates['USD'] == Decimal('0.27')

    def test_bad_status_skips_endpoint(self, monkeypatch):
        monkeypatch.setattr(cs_module.requests, 'get',
                            lambda url, timeout=5: _FakeResp({}, status=500))
        monkeypatch.setattr(cs_module, 'FOREX_AVAILABLE', False)
        rates = CurrencyService.get_all_rates(base='ILS')
        assert rates['ILS'] == Decimal('1.00')

    def test_forex_python_secondary_source(self, monkeypatch):
        class FakeRates:
            def get_rates(self, base):
                return {'USD': 0.27}

        class FakeConverter:
            CurrencyRates = FakeRates

        monkeypatch.setattr(cs_module.requests, 'get',
                            lambda url, timeout=5: _FakeResp({}, status=500))
        monkeypatch.setattr(cs_module, 'FOREX_AVAILABLE', True)
        monkeypatch.setattr(cs_module, 'CurrencyRates', FakeRates, raising=False)
        rates = CurrencyService.get_all_rates(base='ILS')
        assert rates['USD'] == Decimal('0.27')
