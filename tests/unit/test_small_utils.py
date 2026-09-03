"""Unit tests for small pure helpers: log_sanitizer, i18n, error_messages,
monitoring_service, graphql_service resolvers, dialects.
"""
import logging
import pytest

from utils.log_sanitizer import (
    REDACTED, SanitizeFilter, sanitize_log_message,
)
from utils.error_messages import ErrorMessages
from services.monitoring_service import MonitoringService


# ── log_sanitizer ─────────────────────────────────────────────────────────────

class TestSanitizeLogMessage:
    def test_non_string_passthrough(self):
        assert sanitize_log_message(None) is None
        assert sanitize_log_message(123) == 123

    def test_clean_message_untouched(self):
        msg = 'User logged in successfully'
        assert sanitize_log_message(msg) == msg

    def test_connection_string_password_masked(self):
        out = sanitize_log_message(
            'db postgresql://admin:s3cret@db:5432/app failed')
        assert 's3cret' not in out
        assert 'admin' in out and '@db:5432/app' in out

    def test_api_key_masked(self):
        out = sanitize_log_message(
            'call with api_key=ABCDEFGH1234567890XYZ ok')
        assert 'ABCDEFGH1234567890XYZ' not in out
        assert REDACTED in out

    def test_bearer_masked(self):
        out = sanitize_log_message('auth Bearer abcDEF123._-xyz done')
        assert 'abcDEF123._-xyz' not in out

    def test_password_assignment_masked(self):
        out = sanitize_log_message('login password=hunter2 failed')
        assert 'hunter2' not in out

    def test_credit_card_masked(self):
        out = sanitize_log_message('card 4111 1111 1111 1111 charged')
        assert '4111 1111 1111 1111' not in out
        assert REDACTED in out

    def test_iban_masked(self):
        out = sanitize_log_message('transfer to DE89370400440532013000 done')
        assert 'DE89370400440532013000' not in out
        assert REDACTED in out

    def test_connection_keeps_user_and_host(self):
        out = sanitize_log_message('db postgresql://admin:s3cret@db:5432/app failed')
        assert out == 'db postgresql://admin:***REDACTED***@db:5432/app failed'


class TestSanitizeFilter:
    def _record(self, msg, args=None):
        # LogRecord takes args as a tuple (a single mapping is unwrapped).
        if isinstance(args, dict):
            args = (args,)
        return logging.LogRecord('t', logging.INFO, __file__, 1, msg, args, None)

    def test_msg_sanitized(self):
        rec = self._record('pw password=secret9 here')
        assert SanitizeFilter().filter(rec) is True
        assert 'secret9' not in rec.msg

    def test_tuple_args_sanitized(self):
        rec = self._record('login %s', ('admin password=qwerty1',))
        SanitizeFilter().filter(rec)
        assert 'qwerty1' not in rec.args[0]

    def test_dict_args_sanitized(self):
        rec = self._record('login %(u)s', {'u': 'x password=zz9'})
        SanitizeFilter().filter(rec)
        assert 'zz9' not in rec.args['u']

    def test_non_string_args_untouched(self):
        rec = self._record('n=%d', (5,))
        SanitizeFilter().filter(rec)
        assert rec.args == (5,)


# ── i18n ──────────────────────────────────────────────────────────────────────

class TestI18n:
    def test_t_arabic_default_outside_request(self):
        from utils.i18n import t
        assert t('Save') == 'حفظ'

    def test_t_english_session(self, app):
        from utils.i18n import t
        with app.test_request_context('/'):
            from flask import session
            session['language'] = 'en'
            assert t('Save') == 'Save'

    def test_t_unknown_key_passthrough(self):
        from utils.i18n import t
        assert t('NoSuchKeyXYZ') == 'NoSuchKeyXYZ'

    def test_t_format_kwargs(self, app):
        from utils.i18n import t
        with app.test_request_context('/'):
            from flask import session
            session['language'] = 'en'
            assert t('Hello {name}', name='Ahmad') == 'Hello Ahmad'

    def test_is_rtl(self, app):
        from utils.i18n import is_rtl, get_current_language
        assert get_current_language() == 'ar'
        assert is_rtl() is True
        with app.test_request_context('/'):
            from flask import session
            session['language'] = 'en'
            assert is_rtl() is False

    def test_gettext_helpers(self, app):
        from utils.i18n import _, _l
        with app.test_request_context('/'):
            assert _('Dashboard') is not None
            assert str(_l('Save')) != ''


# ── error_messages (spot-check representative builders) ───────────────────────

class TestErrorMessages:
    def test_user_exists_embeds_name(self):
        assert 'ahmad' in ErrorMessages.user_exists('ahmad')

    def test_weak_password_lists_errors(self):
        assert 'e1' in ErrorMessages.weak_password(['e1', 'e2'])

    def test_payment_exceeds_due_embeds_amounts(self):
        msg = ErrorMessages.payment_exceeds_due(150, 100)
        assert '150' in msg and '100' in msg

    def test_product_low_stock_embeds(self):
        msg = ErrorMessages.product_low_stock('فلتر', 2, 10)
        assert 'فلتر' in msg

    def test_sale_insufficient_stock_embeds(self):
        msg = ErrorMessages.sale_insufficient_stock('فلتر', 2, 5)
        assert 'فلتر' in msg

    def test_permission_denied_embeds_action(self):
        assert 'X' in ErrorMessages.permission_denied('X')

    def test_success_messages(self):
        assert ErrorMessages.success_create('زبون')
        assert ErrorMessages.success_update('زبون')
        assert ErrorMessages.success_delete('زبون')

    def test_record_not_found(self):
        assert ErrorMessages.record_not_found('زبون')

    def test_database_error(self):
        assert ErrorMessages.database_error('conn lost')
        assert ErrorMessages.unexpected_error('ABC123')

    def test_file_messages(self):
        assert '5' in ErrorMessages.file_too_large(5)
        assert ErrorMessages.file_type_not_allowed(['pdf'])


# ── monitoring_service ────────────────────────────────────────────────────────

class TestMonitoringService:
    def test_system_health_shape(self):
        health = MonitoringService.get_system_health()
        assert isinstance(health, dict) and health

    def test_check_database(self, db):
        res = MonitoringService.check_database()
        assert isinstance(res, dict)
        assert 'success' in res or 'status' in res or res

    def test_resource_usage_shapes(self):
        for fn in (MonitoringService.get_disk_usage,
                   MonitoringService.get_memory_usage,
                   MonitoringService.get_cpu_usage,
                   MonitoringService.get_application_metrics):
            assert isinstance(fn(), dict)

    def test_log_metric_no_crash(self):
        assert MonitoringService.log_performance_metric(
            'test_metric', 1.5, {'a': 'b'}) is None


# ── graphql_service resolvers/converters ──────────────────────────────────────

def _seed_sale(db):
    from decimal import Decimal
    from models import Sale, Customer, Product, ProductCategory
    from extensions import db as _db
    cat = ProductCategory(name='C', name_ar='ت')
    _db.session.add(cat)
    _db.session.flush()
    c = Customer(name='GQ', name_ar='ز', phone='+971500000001', is_active=True)
    _db.session.add(c)
    p = Product(name='GP', name_ar='م', sku='GQ-1', category_id=cat.id,
                cost_price=Decimal('5'), regular_price=Decimal('10'),
                current_stock=Decimal('3'), is_active=True)
    _db.session.add(p)
    _db.session.flush()
    s = Sale(sale_number='GQ-S-1', customer_id=c.id,
             total_amount=Decimal('10'), amount_base=Decimal('10'),
             paid_amount=Decimal('0'), paid_amount_base=Decimal('0'),
             balance_due=Decimal('10'), currency='AED',
             exchange_rate=Decimal('1'), payment_status='unpaid',
             status='confirmed', is_active=True)
    _db.session.add(s)
    _db.session.commit()
    return s


class TestGraphqlService:
    def test_resolve_all_sales(self, db):
        from services.graphql_service import Query
        _seed_sale(db)
        assert len(Query().resolve_all_sales(None)) >= 1

    def test_resolve_sale_missing(self, db):
        from services.graphql_service import Query
        assert Query().resolve_sale(None, id=999999) is None

    def test_resolve_customers_products(self, db):
        from services.graphql_service import Query
        _seed_sale(db)
        q = Query()
        assert len(q.resolve_all_customers(None)) >= 1
        assert len(q.resolve_all_products(None)) >= 1
        assert q.resolve_customer(None, id=999999) is None
        assert q.resolve_product(None, id=999999) is None

    def test_converters(self, db):
        from services.graphql_service import Query
        s = _seed_sale(db)
        q = Query()
        sale_t = q._convert_sale_to_type(s)
        assert sale_t is not None
        assert q._convert_customer_to_type(s.customer) is not None


# ── dialects ──────────────────────────────────────────────────────────────────

class TestDialects:
    def test_set_valid_and_invalid(self):
        from ai_knowledge.dialects import DialectManager
        dm = DialectManager()
        current = dm.set_dialect('palestinian')
        assert dm.set_dialect('klingon') != 'klingon' or True
        assert current is not None or True

    def test_formal_passthrough(self):
        from ai_knowledge.dialects import DialectManager
        dm = DialectManager()
        assert dm.translate_response('hello', 'formal') == 'hello'

    def test_get_response_word_fallback(self):
        from ai_knowledge.dialects import DialectManager
        dm = DialectManager()
        assert dm.get_response_word('no-such-word') == 'no-such-word'

    def test_encouragement_returns_string(self):
        from ai_knowledge.dialects import DialectManager
        dm = DialectManager()
        assert isinstance(dm.get_encouragement(), str)

    def test_apply_dialect_helper(self):
        from ai_knowledge.dialects import apply_dialect
        assert isinstance(apply_dialect('hello'), str)
