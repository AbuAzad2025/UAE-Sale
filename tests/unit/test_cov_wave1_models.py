"""Wave-1 quick-win coverage: small models + extensions + config surface.

- models/currency.py (Currency + ExchangeRate)
- models/payment.py (Payment + Receipt behaviours)
- models/customer.py (balances, displays, classification)
- models/audit.py (AuditLog displays)
- extensions.py (get_or_create, load_user, locale, formatters, rate-limit key)
- config.py (helpers + production sanity + runtime dirs)
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest


# ---------------------------------------------------------------------------
# currency
# ---------------------------------------------------------------------------

class TestCurrencyModel:
    def _currency(self, db, code='AED'):
        from models import Currency
        from extensions import db as _db
        c = Currency(code=code, name='UAE Dirham', name_ar='درهم إماراتي',
                     symbol='د.إ', is_base=(code == 'AED'), is_active=True)
        _db.session.add(c)
        _db.session.commit()
        return c

    def test_repr_display_to_dict(self, db):
        c = self._currency(db)
        assert repr(c) == '<Currency AED>'
        assert c.get_display_name('ar') == 'درهم إماراتي'
        assert c.get_display_name('en') == 'UAE Dirham'
        d = c.to_dict()
        assert d == {'id': c.id, 'code': 'AED', 'name': 'UAE Dirham',
                     'name_ar': 'درهم إماراتي', 'symbol': 'د.إ', 'is_base': True}

    def test_display_falls_back_without_ar(self, db):
        from models import Currency
        from extensions import db as _db
        c = Currency(code='USD', name='US Dollar', is_base=False)
        _db.session.add(c)
        _db.session.commit()
        assert c.get_display_name('ar') == 'US Dollar'

    def test_exchange_rate_validity(self, db):
        from models import ExchangeRate
        from extensions import db as _db
        now = datetime.now(timezone.utc)
        open_ended = ExchangeRate(from_currency='USD', to_currency='AED',
                                  rate=Decimal('3.6725'),
                                  valid_from=now - timedelta(days=1))
        _db.session.add(open_ended)
        _db.session.commit()
        assert open_ended.is_valid() is True

        future = ExchangeRate(from_currency='USD', to_currency='AED',
                              rate=Decimal('3.67'),
                              valid_from=now + timedelta(days=1))
        assert future.is_valid() is False

        expired = ExchangeRate(from_currency='USD', to_currency='AED',
                               rate=Decimal('3.67'),
                               valid_from=now - timedelta(days=5),
                               valid_until=now - timedelta(days=1))
        assert expired.is_valid() is False

        current = ExchangeRate(from_currency='USD', to_currency='AED',
                               rate=Decimal('3.67'),
                               valid_from=now - timedelta(days=1),
                               valid_until=now + timedelta(days=1))
        assert current.is_valid() is True

    def test_exchange_rate_repr_and_dict(self, db):
        c = self._currency(db)
        from models import ExchangeRate
        from extensions import db as _db
        r = ExchangeRate(from_currency='AED', to_currency='AED',
                         rate=Decimal('1.0'), currency_id=c.id,
                         source='test', is_manual=True,
                         valid_from=datetime.now(timezone.utc))
        _db.session.add(r)
        _db.session.commit()
        assert 'AED' in repr(r)
        d = r.to_dict()
        assert d['currency_code'] == 'AED'
        assert d['rate'] == 1.0
        assert d['source'] == 'test'
        assert d['is_manual'] is True
        assert d['is_valid'] is True
        assert 'valid_from' in d

    def test_exchange_rate_repr_without_currency(self, db):
        from models import ExchangeRate
        r = ExchangeRate(from_currency='X', to_currency='Y', rate=Decimal('2'),
                         valid_from=datetime.now(timezone.utc))
        assert repr(r) == '<ExchangeRate ? = 2>'


# ---------------------------------------------------------------------------
# payment
# ---------------------------------------------------------------------------

class TestPaymentModel:
    def _payment(self, db, test_sale, **kw):
        from models import Payment
        from extensions import db as _db
        defaults = dict(payment_number='PAY-W1-001', payment_type='receipt',
                        direction='incoming', sale_id=test_sale.id,
                        customer_id=test_sale.customer_id,
                        amount=Decimal('100.000'), amount_base=Decimal('100.000'),
                        currency='AED', exchange_rate=Decimal('1'),
                        payment_method='cash', payment_confirmed=True)
        defaults.update(kw)
        p = Payment(**defaults)
        _db.session.add(p)
        _db.session.commit()
        return p

    def test_direction_validator_rejects(self, db, test_sale):
        from models import Payment
        from extensions import db as _db
        with pytest.raises(ValueError, match='incoming'):
            Payment(payment_number='PAY-W1-BAD', payment_type='receipt',
                    direction='sideways', amount=Decimal('1'),
                    amount_base=Decimal('1'), payment_method='cash')
            _db.session.flush()

    def test_method_display(self, db, test_sale):
        p = self._payment(db, test_sale)
        assert p.get_method_display('ar') == 'نقدي'
        assert p.get_method_display('en') == 'Cash'
        p.payment_method = 'mystery'
        assert p.get_method_display('ar') == 'mystery'

    def test_status_props_and_dict(self, db, test_sale):
        p = self._payment(db, test_sale, payment_number='PAY-W1-002',
                          payment_confirmed=False, rejection_reason='bounced')
        assert p.is_pending is True
        assert p.status_ar == 'مرفوضة'
        assert p.direction_ar == 'وارد'
        p.rejection_reason = None
        assert p.status_ar == 'معلقة'
        p.direction = 'outgoing'
        assert p.direction_ar == 'صادر'
        p.__dict__['direction'] = 'zzz'  # bypass validator: display fallback
        assert p.direction_ar == 'غير محدد'
        d = p.to_dict()
        assert d['payment_number'] == 'PAY-W1-002'
        assert d['status_ar'] in ('معلقة', 'مرفوضة', 'مؤكدة')
        assert repr(p) == '<Payment PAY-W1-002>'

    def test_confirm_payment(self, db, test_sale):
        p = self._payment(db, test_sale, payment_number='PAY-W1-003',
                          payment_confirmed=False)
        p.confirm_payment()
        assert p.payment_confirmed is True
        assert p.confirmation_date is not None
        assert p.is_pending is False
        assert p.status_ar == 'مؤكدة'

    def test_reject_payment_restores_customer_balance(self, db, test_sale):
        from extensions import db as _db
        customer = test_sale.customer
        before = customer.balance or Decimal('0')
        p = self._payment(db, test_sale, payment_number='PAY-W1-004')
        p.reject_payment('cheque bounced')
        assert p.payment_confirmed is False
        assert p.rejection_reason == 'cheque bounced'
        _db.session.refresh(customer)
        assert customer.balance == before + Decimal('100.000')

    def test_reject_pending_is_noop(self, db, test_sale):
        p = self._payment(db, test_sale, payment_number='PAY-W1-005',
                          payment_confirmed=False)
        p.reject_payment('x')  # only acts on confirmed payments
        assert p.payment_confirmed is False
        assert p.rejection_reason is None


class TestReceiptModel:
    def _receipt(self, db, test_customer, **kw):
        from models import Receipt
        from extensions import db as _db
        defaults = dict(receipt_number='RC-W1-001', customer_id=test_customer.id,
                        amount=Decimal('50.000'), amount_base=Decimal('50.000'),
                        payment_method='cash', payment_confirmed=True)
        defaults.update(kw)
        r = Receipt(**defaults)
        _db.session.add(r)
        _db.session.commit()
        return r

    def test_mutual_exclusion_validator(self, db, test_customer):
        from models import Receipt
        with pytest.raises(ValueError, match='mutually exclusive'):
            Receipt(receipt_number='RC-W1-XX', customer_id=test_customer.id,
                    amount=Decimal('1'), amount_base=Decimal('1'),
                    payment_method='cash', sale_id=1, purchase_id=2)

    def test_confirm_reject_cycle(self, db, test_customer):
        r = self._receipt(db, test_customer, receipt_number='RC-W1-002',
                          payment_confirmed=False)
        assert r.is_pending is True
        assert r.status_ar == 'معلق'
        r.confirm_receipt()
        assert r.payment_confirmed is True
        assert r.confirmation_date is not None
        r.reject_receipt('bounced')
        assert r.payment_confirmed is False
        assert r.rejection_reason == 'bounced'
        assert r.status_ar == 'مرفوض'

    def test_displays_and_dict(self, db, test_customer):
        r = self._receipt(db, test_customer, payment_method='card')
        assert r.get_method_display('en') == 'Card'
        assert r.get_method_display('ar') == 'بطاقة'
        assert r.source_type_ar == 'مبيعات'
        assert r.direction_ar == 'وارد'
        d = r.to_dict()
        assert d['receipt_number'] == 'RC-W1-001'
        assert d['customer'] == test_customer.name
        assert d['amount'] == 50.0
        assert repr(r) == '<Receipt RC-W1-001>'

    def test_get_source_info(self, db, test_customer, test_sale):
        r = self._receipt(db, test_customer, receipt_number='RC-W1-003',
                          source_type='sale', source_id=test_sale.id)
        info = r.get_source_info()
        assert info['number'] == test_sale.sale_number
        assert info['type'] == 'فاتورة بيع'
        r2 = self._receipt(db, test_customer, receipt_number='RC-W1-004',
                           source_type='manual')
        assert r2.get_source_info() is None


# ---------------------------------------------------------------------------
# customer
# ---------------------------------------------------------------------------

class TestCustomerModel:
    def test_balance_from_confirmed_sales(self, db, test_sale):
        customer = test_sale.customer
        assert customer.get_balance() == Decimal('100.000')
        assert customer.get_balance_aed() == Decimal('100.000')

    def test_balance_ignores_unconfirmed(self, db, test_customer):
        assert test_customer.get_balance() == Decimal('0')

    def test_displays(self, db, test_customer):
        assert test_customer.get_display_name('ar') == 'زبون تجريبي'
        assert test_customer.get_display_name('en') == 'Test Customer'
        assert test_customer.get_type_display('ar') == 'عادي'
        assert test_customer.get_type_display('en') == 'Regular'
        assert test_customer.get_type_display('xx') == 'regular'
        test_customer.customer_classification = 'vip'
        assert 'VIP' in test_customer.get_classification_display('en')
        assert 'مميز' in test_customer.get_classification_display('ar')

    def test_update_classification_thresholds(self, db, test_customer):
        test_customer.total_purchases = Decimal('120000')
        test_customer.update_classification()
        assert test_customer.customer_classification == 'vip'
        test_customer.total_purchases = Decimal('60000')
        test_customer.update_classification()
        assert test_customer.customer_classification == 'premium'
        test_customer.total_purchases = Decimal('100')
        test_customer.update_classification()
        assert test_customer.customer_classification == 'regular'

    def test_to_dict_and_repr(self, db, test_sale):
        d = test_sale.customer.to_dict()
        assert d['balance'] == 100.0
        assert d['balance_aed'] == 100.0
        assert d['is_active'] is True
        assert repr(test_sale.customer) == f"<Customer {test_sale.customer.name}>"


# ---------------------------------------------------------------------------
# audit
# ---------------------------------------------------------------------------

class TestAuditModel:
    def test_action_display(self, db, owner_user):
        from models import AuditLog
        from extensions import db as _db
        log = AuditLog(user_id=owner_user.id, action='create',
                       table_name='sales', record_id=1)
        _db.session.add(log)
        _db.session.commit()
        assert log.get_action_display('ar') == 'إضافة'
        assert log.get_action_display('en') == 'Create'
        log.action = 'weird_action'
        assert log.get_action_display('ar') == 'weird_action'

    def test_to_dict_with_and_without_user(self, db, owner_user):
        from models import AuditLog
        from extensions import db as _db
        log = AuditLog(user_id=owner_user.id, action='login')
        orphan = AuditLog(action='export', table_name='sales')
        _db.session.add_all([log, orphan])
        _db.session.commit()
        assert log.to_dict()['user'] == 'testowner'
        assert orphan.to_dict()['user'] == 'System'
        assert repr(log) == '<AuditLog login on None>'


# ---------------------------------------------------------------------------
# extensions
# ---------------------------------------------------------------------------

class TestExtensionsHelpers:
    def test_get_or_create(self, db):
        from extensions import get_or_create
        from models import ProductCategory
        from extensions import db as _db
        obj, created = get_or_create(_db.session, ProductCategory,
                                     name='W1-Cat', defaults={'name_ar': 'و'})
        assert created is True
        obj2, created2 = get_or_create(_db.session, ProductCategory, name='W1-Cat')
        assert created2 is False
        assert obj2.id == obj.id

    def test_load_user_valid_invalid(self, db, owner_user):
        from extensions import load_user
        assert load_user(str(owner_user.id)).id == owner_user.id
        assert load_user('abc') is None
        assert load_user('-5') is None
        assert load_user('999999') is None

    def test_get_locale(self, app, db):
        from extensions import get_locale
        with app.test_request_context('/'):
            assert get_locale() == 'ar'
        with app.test_request_context('/'):
            from flask import session
            session['language'] = 'en'
            assert get_locale() == 'en'

    def test_request_id_filter(self, app, db):
        import logging
        from extensions import RequestIdFilter
        record = logging.LogRecord('n', logging.INFO, 'p', 1, 'm', (), None)
        assert RequestIdFilter().filter(record) is True
        assert record.request_id == '-'
        with app.test_request_context('/'):
            from flask import g
            g.request_id = 'RID-1'
            record2 = logging.LogRecord('n', logging.INFO, 'p', 1, 'm', (), None)
            RequestIdFilter().filter(record2)
            assert record2.request_id == 'RID-1'

    def test_color_formatter_plain(self, db, monkeypatch):
        import logging
        from extensions import ColorFormatter
        monkeypatch.setenv('FLASK_ENV', 'production')
        record = logging.LogRecord('mod', logging.ERROR, 'p', 1, 'hello', (), None)
        out = ColorFormatter().format(record)
        assert 'ERROR' in out and 'hello' in out

    def test_rate_limit_key_anonymous(self, app, db):
        from extensions import _rate_limit_key
        with app.test_request_context('/'):
            key = _rate_limit_key()
            assert isinstance(key, str) and len(key) > 0

    def test_anonymous_mixin_flags(self, app, db):
        with app.test_request_context('/'):
            from flask_login import current_user
            assert current_user.is_anonymous
            assert current_user.is_owner is False
            assert current_user.is_super_admin() is False
            assert current_user.is_manager() is False
            assert current_user.is_seller() is False
            assert current_user.can_see_costs() is False


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

class TestConfigSurface:
    def test_bool_int_float_helpers(self, db, monkeypatch):
        import config as cfg
        assert cfg._bool('True') is True
        assert cfg._bool('0', default=True) is False
        assert cfg._bool(None, default=True) is True
        monkeypatch.setenv('W1_INT', '12')
        assert cfg._int('W1_INT', 3) == 12
        monkeypatch.setenv('W1_INT', 'nan!')
        assert cfg._int('W1_INT', 3) == 3
        assert cfg._int('W1_MISSING', 7) == 7
        monkeypatch.setenv('W1_FLOAT', '1.5')
        assert cfg._float('W1_FLOAT', 0.0) == 1.5
        monkeypatch.setenv('W1_FLOAT', 'bad')
        assert cfg._float('W1_FLOAT', 2.5) == 2.5

    def test_config_defaults(self, db):
        import config as cfg
        assert cfg.Config.SQLALCHEMY_TRACK_MODIFICATIONS is False
        assert cfg.Config.SESSION_COOKIE_HTTPONLY is True
        assert cfg.Config.WTF_CSRF_TIME_LIMIT is None
        assert 'redis' in cfg.Config.REDIS_URL
        assert cfg.Config.DEFAULT_CURRENCY in ('AED', 'ILS')
        assert cfg.Config.ITEMS_PER_PAGE >= 1

    def test_assert_production_sanity_skips_testing(self, db):
        import config as cfg

        class Fake:
            DEBUG = True
            APP_ENV = 'testing'

        cfg.assert_production_sanity(Fake())  # no raise

    def test_assert_production_sanity_enforces(self, db, monkeypatch):
        import config as cfg

        class Fake:
            DEBUG = False
            APP_ENV = 'production'
            SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
            SESSION_COOKIE_SECURE = True
            BASE_URL = 'https://x.example'

        # SECRET_KEY is set in this env, so the next gate (CARD key) fires.
        monkeypatch.delenv('CARD_ENCRYPTION_KEY', raising=False)
        with pytest.raises(RuntimeError, match='CARD_ENCRYPTION_KEY'):
            cfg.assert_production_sanity(Fake())

        # With both keys set, sqlite-in-production is rejected.
        monkeypatch.setenv('CARD_ENCRYPTION_KEY', 'k' * 32)
        with pytest.raises(RuntimeError, match='SQLite'):
            cfg.assert_production_sanity(Fake())

    def test_ensure_runtime_dirs(self, db, tmp_path):
        import config as cfg

        class Fake:
            BACKUP_DIR = str(tmp_path / 'backups')

        cfg.ensure_runtime_dirs(Fake())
        assert (tmp_path / 'backups').exists()
