"""Wave-1 quick-win coverage: utils + extensions-level helpers.

- utils/database_optimizer.py (sqlite branches)
- utils/decorators.py (tx, role levels, tenant guards, csrf/webhook gates)
- utils/error_messages.py (message builders)
- utils/enhanced_logging.py (stream guard, loggers, setup on scratch app)
- utils/distributed_lock.py (fallback, strict mode, redis-path via fakes)
"""
import hashlib
import hmac
import io

import pytest


# ---------------------------------------------------------------------------
# database_optimizer
# ---------------------------------------------------------------------------

class TestDatabaseOptimizer:
    def test_vacuum_sqlite_unsupported(self, db):
        from utils.database_optimizer import DatabaseOptimizer
        result = DatabaseOptimizer.vacuum_postgres()
        assert result == {'success': False, 'message': 'Only PostgreSQL supported'}

    def test_analyze_tables_sqlite(self, db):
        from utils.database_optimizer import DatabaseOptimizer
        assert DatabaseOptimizer.analyze_tables() == {'success': True}

    def test_get_table_sizes_sqlite(self, db):
        from utils.database_optimizer import DatabaseOptimizer
        assert DatabaseOptimizer.get_table_sizes() == {
            'success': False, 'message': 'Only PostgreSQL supported'}

    def test_optimize_all_keys(self, db):
        from utils.database_optimizer import DatabaseOptimizer
        results = DatabaseOptimizer.optimize_all()
        assert set(results) == {'vacuum', 'analyze', 'sizes'}
        assert results['analyze']['success'] is True
        assert results['vacuum']['success'] is False


# ---------------------------------------------------------------------------
# decorators
# ---------------------------------------------------------------------------

class TestTxDecorator:
    def test_commit_on_success(self, db):
        from utils.decorators import tx
        from models import Customer
        from extensions import db as _db

        @tx
        def _create():
            _db.session.add(Customer(name='TX-OK', customer_type='regular'))

        _create()
        assert Customer.query.filter_by(name='TX-OK').count() == 1

    def test_rollback_on_failure(self, db):
        from utils.decorators import tx
        from models import Customer
        from extensions import db as _db

        @tx
        def _create():
            _db.session.add(Customer(name='TX-FAIL', customer_type='regular'))
            raise RuntimeError('boom')

        with pytest.raises(RuntimeError):
            _create()
        assert Customer.query.filter_by(name='TX-FAIL').count() == 0

    def test_nested_tx_single_commit(self, db):
        from utils.decorators import tx
        from models import Customer
        from extensions import db as _db

        @tx
        def _inner():
            _db.session.add(Customer(name='TX-NEST', customer_type='regular'))
            return 'inner'

        @tx
        def _outer():
            assert _inner() == 'inner'
            return 'outer'

        assert _outer() == 'outer'
        assert Customer.query.filter_by(name='TX-NEST').count() == 1

    def test_nested_failure_discards_all(self, db):
        from utils.decorators import tx
        from models import Customer
        from extensions import db as _db

        @tx
        def _inner():
            _db.session.add(Customer(name='TX-NEST2', customer_type='regular'))

        @tx
        def _outer():
            _inner()
            raise ValueError('late failure')

        with pytest.raises(ValueError):
            _outer()
        assert Customer.query.filter_by(name='TX-NEST2').count() == 0


class TestRoleLevels:
    def test_role_level_mapping(self, db):
        from utils.decorators import _role_level

        class R:
            def __init__(self, slug):
                self.slug = slug

        assert _role_level(None) == 0
        assert _role_level(R('viewer')) == 10
        assert _role_level(R('seller')) == 40
        assert _role_level(R('manager')) == 70
        assert _role_level(R('super_admin')) == 90
        assert _role_level(R('nope')) == 0
        assert _role_level(R('')) == 0

    def test_current_user_level_anonymous(self, app, db):
        from utils.decorators import _current_user_level
        with app.test_request_context('/'):
            assert _current_user_level() == 0

    def test_current_user_level_owner(self, app, db, owner_user):
        from flask_login import login_user
        from utils.decorators import _current_user_level
        with app.test_request_context('/'):
            login_user(owner_user)
            assert _current_user_level() == 100

    def test_enforce_target_role_owner_can_assign_anything(self, app, db, owner_user):
        from flask_login import login_user
        from utils.decorators import _enforce_target_role_not_higher

        class R:
            slug = 'super_admin'

        with app.test_request_context('/'):
            login_user(owner_user)
            _enforce_target_role_not_higher(R())  # no raise

    def test_enforce_target_role_blocks_escalation(self, app, db, seller_user):
        from flask_login import login_user
        from werkzeug.exceptions import Forbidden
        from utils.decorators import _enforce_target_role_not_higher

        class R:
            slug = 'manager'

        with app.test_request_context('/'):
            login_user(seller_user)
            with pytest.raises(Forbidden):
                _enforce_target_role_not_higher(R())


class TestTenantGuards:
    def test_get_owned_or_404_found_and_missing(self, app, db, owner_user):
        from werkzeug.exceptions import NotFound
        from flask_login import login_user
        from models import Customer
        from extensions import db as _db
        from utils.decorators import get_owned_or_404
        c = Customer(name='Guard', customer_type='regular')
        _db.session.add(c)
        _db.session.commit()
        with app.test_request_context('/'):
            login_user(owner_user)
            assert get_owned_or_404(Customer, c.id).id == c.id
            with pytest.raises(NotFound):
                get_owned_or_404(Customer, 999999)

    def test_assert_same_tenant_anonymous_passthrough(self, app, db, test_customer):
        from utils.decorators import assert_same_tenant
        with app.test_request_context('/'):
            assert_same_tenant(test_customer)  # no raise

    def test_get_owned_or_raise_anonymous_passthrough(self, app, db, test_customer):
        from utils.decorators import get_owned_or_raise
        from models import Customer
        with app.test_request_context('/'):
            assert get_owned_or_raise(Customer, test_customer.id).id == test_customer.id
            assert get_owned_or_raise(Customer, 999999) is None

    def test_enforce_same_tenant_none_ok(self, app, db):
        from utils.decorators import _enforce_same_tenant
        with app.test_request_context('/'):
            _enforce_same_tenant(None)  # no raise


class TestCsrfAndWebhookGates:
    def test_require_csrf_get_passthrough(self, app, db):
        from utils.decorators import require_csrf_for_state_change

        @require_csrf_for_state_change
        def _view():
            return 'ok'

        with app.test_request_context('/', method='GET'):
            assert _view() == 'ok'

    def test_require_csrf_post_without_token_rejected(self, app, db):
        from werkzeug.exceptions import BadRequest
        from utils.decorators import require_csrf_for_state_change

        @require_csrf_for_state_change
        def _view():
            return 'ok'

        with app.test_request_context('/', method='POST'):
            with pytest.raises(BadRequest):
                _view()

    def test_webhook_signature_valid(self, app, db):
        from utils.decorators import webhook_signature_required
        secret = 's3cret'

        def _view():
            return 'delivered'

        wrapped = None
        body = b'{"id": 1}'
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        with app.test_request_context('/', method='POST', data=body):
            wrapped = webhook_signature_required(lambda: secret, lambda: sig)(_view)
            assert wrapped() == 'delivered'

    def test_webhook_signature_missing_secret_or_sig(self, app, db):
        from werkzeug.exceptions import BadRequest
        from utils.decorators import webhook_signature_required

        def _view():
            return 'x'

        with app.test_request_context('/', method='POST', data=b'hi'):
            with pytest.raises(BadRequest):
                webhook_signature_required(lambda: '', lambda: 'sig')(_view)()
            with pytest.raises(BadRequest):
                webhook_signature_required(lambda: 's', lambda: '')(_view)()
            with pytest.raises(BadRequest):
                webhook_signature_required(lambda: 's', lambda: 'wrong')(_view)()

    def test_current_app_logger_abort(self, app, db):
        from werkzeug.exceptions import BadRequest
        from utils.decorators import current_app_logger_abort
        with app.test_request_context('/'):
            with pytest.raises(BadRequest):
                current_app_logger_abort('test reason')

    def test_report_tx_duration_never_raises(self, db):
        from utils.decorators import _report_tx_duration
        _report_tx_duration('fn', 3.5, 'commit')
        _report_tx_duration('fn', 1.0, 'rollback')


# ---------------------------------------------------------------------------
# error_messages
# ---------------------------------------------------------------------------

class TestErrorMessages:
    def test_user_messages(self, db):
        from utils.error_messages import ErrorMessages as E
        assert 'مطلوبان' in E.user_required_fields()
        assert 'alt_user' in E.user_exists('alt_user')
        assert 'Ahmed@2024' in E.weak_password(['قصيرة'])
        assert 'متطابقتين' in E.password_mismatch()
        assert 'boom' in E.user_update_failed('boom')
        assert 'الخاص' in E.user_delete_self()
        assert 'المالك' in E.user_delete_owner()

    def test_customer_product_sale_messages(self, db):
        from utils.error_messages import ErrorMessages as E
        assert 'الهاتف' in E.customer_required_fields()
        assert '0501234567' in E.customer_phone_invalid()
        assert '@' in E.customer_email_invalid()
        assert 'VIP' in E.customer_has_transactions('VIP')
        assert 'المنتج' in E.product_required_fields()
        assert 'SKU-1' in E.product_sku_exists('SKU-1')
        assert 'سالب' in E.product_negative_stock()
        assert '5' in E.product_low_stock('P', 5, 10)
        assert 'نفد' in E.product_out_of_stock('P')
        assert 'منتج واحد' in E.sale_no_lines()
        assert 'عميل' in E.sale_no_customer()
        assert 'المتوفر' in E.sale_insufficient_stock('P', 2, 5)
        assert 'صفر' in E.sale_invalid_quantity()
        assert 'السعر' in E.sale_invalid_price()

    def test_payment_and_misc_messages(self, db):
        from utils.error_messages import ErrorMessages as E
        assert 'صفر' in E.payment_amount_zero()
        assert '10.00' in E.payment_exceeds_due(10, 5)
        assert 'الدفع' in E.payment_method_required()
        assert 'الشيك' in E.cheque_number_required()
        assert 'المرجعي' in E.reference_required()
        assert 'المستودع' in E.warehouse_not_found()
        assert 'التعديل' in E.stock_adjustment_invalid()
        assert 'X' in E.permission_denied('X')
        assert 'مالك' in E.owner_only()
        assert 'مدير' in E.admin_only()
        assert 'pdf' in E.file_type_not_allowed(['pdf'])
        assert '5' in E.file_too_large(5)
        assert 'boom' in E.file_upload_failed('boom')
        assert 'boom' in E.database_error('boom')

    def test_lookup_and_success_messages(self, db):
        from utils.error_messages import ErrorMessages as E
        assert 'العميل' in E.record_not_found('customer')
        assert 'xyz' in E.record_not_found('xyz')
        assert 'v' in E.duplicate_entry('f', 'v')
        assert 'name@example.com' in E.invalid_email()
        assert '0501234567' in E.invalid_phone()
        assert 'F' in E.invalid_number('F')
        assert '2025' in E.invalid_date()
        assert 'AED' in E.invalid_currency()
        assert 'المالك' in E.backup_wrong_password()
        assert 'تالفة' in E.backup_corrupted()
        assert 'غير موجودة' in E.backup_not_found()
        assert 'القرص' in E.backup_failed('disk')
        assert 'الطلبات' in E.rate_limit_exceeded()
        assert 'الجلسة' in E.session_expired()
        assert 'CSRF' in E.csrf_error()
        assert 'ABC-1' in E.unexpected_error('ABC-1')
        assert 'F' in E.required_field('F')
        assert 'ex' in E.invalid_format('F', 'ex')
        assert 'العميل' in E.success_create('customer')
        assert 'المنتج' in E.success_update('product')
        assert 'المستخدم' in E.success_delete('user')

    def test_module_level_helpers(self, db):
        import utils.error_messages as m
        assert m.error('e') == 'e'
        assert m.warning('w') == 'w'
        assert m.hint('h') == 'h'
        assert m.success('s') == 's'
        assert 'قاعدة البيانات' in m.database_error()


# ---------------------------------------------------------------------------
# enhanced_logging
# ---------------------------------------------------------------------------

class TestEnhancedLogging:
    def test_ensure_utf8_stream_passthrough(self, db):
        from utils.enhanced_logging import _ensure_utf8_stream
        buf = io.BytesIO()
        assert _ensure_utf8_stream(buf) is buf

    def test_security_logger_no_raise(self, db):
        from utils.enhanced_logging import SecurityLogger
        SecurityLogger.log_failed_login('u', '1.2.3.4', 'agent')
        SecurityLogger.log_successful_login('u', '1.2.3.4')
        SecurityLogger.log_permission_denied('u', 'delete', '1.2.3.4')
        SecurityLogger.log_rate_limit_exceeded('u', '/api', '1.2.3.4')

    def test_performance_logger_threshold(self, db, caplog):
        import logging
        from utils.enhanced_logging import PerformanceLogger
        with caplog.at_level(logging.WARNING):
            PerformanceLogger.log_slow_query('SELECT 1', 0.01)  # below threshold
            assert 'بطيء' not in caplog.text
            PerformanceLogger.log_slow_query('SELECT 1', 2.5)
            assert 'بطيء' in caplog.text
        PerformanceLogger.log_cache_hit('k')
        PerformanceLogger.log_cache_miss('k')

    def test_setup_enhanced_logging_scratch(self, db, tmp_path, monkeypatch):
        from flask import Flask
        from utils.enhanced_logging import setup_enhanced_logging
        monkeypatch.chdir(tmp_path)
        mini = Flask(__name__)
        mini.debug = False
        handlers = setup_enhanced_logging(mini)
        assert set(handlers) == {'app', 'error', 'security', 'performance'}
        assert (tmp_path / 'logs' / 'app.log').exists()


# ---------------------------------------------------------------------------
# distributed_lock
# ---------------------------------------------------------------------------

class TestDistributedLockExtra:
    def test_fallback_same_object(self, db, monkeypatch):
        import utils.distributed_lock as dl
        monkeypatch.setattr(dl, '_get_redis', lambda: None)
        assert dl._get_fallback_lock('same') is dl._get_fallback_lock('same')

    def test_fallback_fail_open_on_contention(self, db, monkeypatch):
        import utils.distributed_lock as dl
        monkeypatch.setattr(dl, '_get_redis', lambda: None)
        monkeypatch.delenv('STRICT_LOCKS', raising=False)
        lock = dl._get_fallback_lock('contended')
        assert lock.acquire(blocking=False) is True
        try:
            ran = []
            with dl.distributed_lock('contended', blocking_timeout=0):
                ran.append(True)
            assert ran == [True]  # fail-open: proceeds despite contention
        finally:
            lock.release()

    def test_strict_mode_raises_on_contention(self, db, monkeypatch):
        import utils.distributed_lock as dl
        monkeypatch.setattr(dl, '_get_redis', lambda: None)
        monkeypatch.setenv('STRICT_LOCKS', '1')
        assert dl._strict_locks_enabled() is True
        lock = dl._get_fallback_lock('strict-one')
        assert lock.acquire(blocking=False) is True
        try:
            with pytest.raises(TimeoutError):
                with dl.distributed_lock('strict-one', blocking_timeout=0):
                    pass
        finally:
            lock.release()

    def test_strict_toggle_parsing(self, db, monkeypatch):
        import utils.distributed_lock as dl
        for val in ('1', 'true', 'YES', 'on'):
            monkeypatch.setenv('STRICT_LOCKS', val)
            assert dl._strict_locks_enabled() is True
        for val in ('0', 'false', 'off', ''):
            monkeypatch.setenv('STRICT_LOCKS', val)
            assert dl._strict_locks_enabled() is False

    def test_redis_path_acquire_release(self, db, monkeypatch):
        import utils.distributed_lock as dl

        released = []

        class FakeLock:
            def acquire(self, blocking=True):
                return True

            def release(self):
                released.append(True)

        class FakeRedis:
            def lock(self, name, timeout, blocking_timeout):
                assert name == 'distributed_lock:job'
                return FakeLock()

        monkeypatch.setattr(dl, '_get_redis', lambda: FakeRedis())
        monkeypatch.delenv('STRICT_LOCKS', raising=False)
        with dl.distributed_lock('job'):
            pass
        assert released == [True]

    def test_redis_acquire_error_fails_open(self, db, monkeypatch):
        import utils.distributed_lock as dl

        class BadLock:
            def acquire(self, blocking=True):
                raise RuntimeError('redis gone')

            def release(self):
                pass

        class FakeRedis:
            def lock(self, name, timeout, blocking_timeout):
                return BadLock()

        monkeypatch.setattr(dl, '_get_redis', lambda: FakeRedis())
        monkeypatch.delenv('STRICT_LOCKS', raising=False)
        with dl.distributed_lock('flaky'):
            pass  # fail-open

    def test_repair_lock_alias(self, db, monkeypatch):
        import utils.distributed_lock as dl
        monkeypatch.setattr(dl, '_get_redis', lambda: None)
        with dl.repair_distributed_lock('repair-job', blocking_timeout=1):
            assert True
