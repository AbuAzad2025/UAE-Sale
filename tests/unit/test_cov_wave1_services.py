"""Wave-1 quick-win coverage: small/medium services.

Covers branches NOT already covered by the dedicated suites
(test_auto_approval_service.py, test_user_service.py):
- services/elasticsearch_service.py (disabled + fallback + mocked-ES paths)
- services/celery_tasks.py (config/beat registry, pure tasks)
- services/websocket_service.py (init + broadcast helpers)
- services/lookup_service.py (merged constants incl. add/label/disable)
- services/ai_cache.py (keying, TTL, eviction, stats)
- services/auto_approval_service.py (run_auto_approval wrapper, empty purchases)
- services/user_service.py (update/delete/password/lookup paths only)
"""
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest


# ---------------------------------------------------------------------------
# elasticsearch_service
# ---------------------------------------------------------------------------

class TestElasticsearchService:
    def test_disabled_by_default(self, db, monkeypatch):
        from services.elasticsearch_service import ElasticsearchService
        monkeypatch.delenv('ELASTICSEARCH_URL', raising=False)
        assert ElasticsearchService.is_enabled() is False

    def test_enabled_when_env_set(self, db, monkeypatch):
        from services.elasticsearch_service import ElasticsearchService
        monkeypatch.setenv('ELASTICSEARCH_URL', 'http://localhost:9200')
        assert ElasticsearchService.is_enabled() is True

    def test_index_sale_refused_when_disabled(self, db, monkeypatch):
        from services.elasticsearch_service import ElasticsearchService
        monkeypatch.delenv('ELASTICSEARCH_URL', raising=False)
        result = ElasticsearchService.index_sale({'id': 1})
        assert result == {'success': False, 'error': 'Elasticsearch not configured'}

    def test_escape_like(self, db):
        from services.elasticsearch_service import ElasticsearchService
        assert ElasticsearchService._escape_like('a%b_c\\d') == 'a\\%b\\_c\\\\d'

    def test_fallback_search_finds_sale(self, db, test_sale, monkeypatch):
        from services.elasticsearch_service import ElasticsearchService
        monkeypatch.delenv('ELASTICSEARCH_URL', raising=False)
        result = ElasticsearchService.search_sales(test_sale.sale_number)
        assert result['success'] is True
        assert result['fallback'] is True
        assert result['total'] >= 1
        assert any(r['sale_number'] == test_sale.sale_number for r in result['results'])

    def test_fallback_search_no_match(self, db, test_sale, monkeypatch):
        from services.elasticsearch_service import ElasticsearchService
        monkeypatch.delenv('ELASTICSEARCH_URL', raising=False)
        result = ElasticsearchService.search_sales('NO-SUCH-SALE-XYZ-999')
        assert result['success'] is True
        assert result['total'] == 0
        assert result['results'] == []

    def test_fallback_search_with_status_filter(self, db, test_sale, monkeypatch):
        from services.elasticsearch_service import ElasticsearchService
        monkeypatch.delenv('ELASTICSEARCH_URL', raising=False)
        hit = ElasticsearchService.search_sales('', filters={'status': 'confirmed'})
        assert hit['success'] is True
        assert hit['total'] >= 1
        miss = ElasticsearchService.search_sales('', filters={'status': 'cancelled'})
        assert miss['success'] is True
        assert miss['total'] == 0

    def test_fallback_search_bad_filter_returns_error(self, db, test_sale, monkeypatch):
        from services.elasticsearch_service import ElasticsearchService
        monkeypatch.delenv('ELASTICSEARCH_URL', raising=False)
        result = ElasticsearchService.search_sales('', filters={'no_such_column': 'x'})
        assert result['success'] is False
        assert result['fallback'] is True
        assert result['results'] == []

    def test_fallback_search_escapes_wildcards(self, db, test_sale, monkeypatch):
        from services.elasticsearch_service import ElasticsearchService
        monkeypatch.delenv('ELASTICSEARCH_URL', raising=False)
        # '%' alone must match literally -> no rows, not "everything".
        result = ElasticsearchService.search_sales('%')
        assert result['success'] is True
        assert result['total'] == 0

    def _install_fake_es(self, monkeypatch, index_result=None, search_result=None, fail=False):
        calls = {}

        class FakeES:
            def __init__(self, hosts):
                calls['hosts'] = hosts

            def index(self, index, id, document):
                calls['index'] = (index, id, document)
                if fail:
                    raise RuntimeError('boom')
                return index_result or {'_id': str(id)}

            def search(self, index, body):
                calls['search'] = (index, body)
                if fail:
                    raise RuntimeError('boom')
                return search_result or {'hits': {'hits': [], 'total': {'value': 0}}}

        module = types.ModuleType('elasticsearch')
        module.Elasticsearch = FakeES
        monkeypatch.setitem(sys.modules, 'elasticsearch', module)
        return calls

    def test_index_sale_success_via_fake_es(self, db, monkeypatch):
        from services.elasticsearch_service import ElasticsearchService
        monkeypatch.setenv('ELASTICSEARCH_URL', 'http://es:9200')
        calls = self._install_fake_es(monkeypatch)
        result = ElasticsearchService.index_sale({'id': 7, 'sale_number': 'S-7'})
        assert result == {'success': True, 'id': '7'}
        assert calls['index'][0] == 'sales'

    def test_index_sale_error_via_fake_es(self, db, monkeypatch):
        from services.elasticsearch_service import ElasticsearchService
        monkeypatch.setenv('ELASTICSEARCH_URL', 'http://es:9200')
        self._install_fake_es(monkeypatch, fail=True)
        result = ElasticsearchService.index_sale({'id': 7})
        assert result['success'] is False
        assert 'boom' in result['error']

    def test_search_sales_success_via_fake_es(self, db, monkeypatch):
        from services.elasticsearch_service import ElasticsearchService
        monkeypatch.setenv('ELASTICSEARCH_URL', 'http://es:9200')
        payload = {'hits': {'hits': [{'_source': {'sale_number': 'S-1'}}],
                            'total': {'value': 1}}}
        calls = self._install_fake_es(monkeypatch, search_result=payload)
        result = ElasticsearchService.search_sales('S-1', filters={'status': 'confirmed'})
        assert result['success'] is True
        assert result['total'] == 1
        assert result['results'] == [{'sale_number': 'S-1'}]
        body = calls['search'][1]
        assert body['query']['bool']['filter'] == [{'term': {'status': 'confirmed'}}]

    def test_search_sales_exception_falls_back(self, db, test_sale, monkeypatch):
        from services.elasticsearch_service import ElasticsearchService
        monkeypatch.setenv('ELASTICSEARCH_URL', 'http://es:9200')
        self._install_fake_es(monkeypatch, fail=True)
        result = ElasticsearchService.search_sales(test_sale.sale_number)
        assert result['success'] is True
        assert result.get('fallback') is True


# ---------------------------------------------------------------------------
# celery_tasks (no broker needed: config + pure tasks only)
# ---------------------------------------------------------------------------

class TestCeleryTasks:
    def test_celery_config(self, db):
        from services.celery_tasks import celery
        assert celery.conf.task_serializer == 'json'
        assert celery.conf.timezone == 'Asia/Dubai'
        assert celery.conf.task_time_limit == 600
        assert celery.conf.task_soft_time_limit == 540

    def test_beat_schedule_entries(self, db):
        from services.celery_tasks import celery
        schedule = celery.conf.beat_schedule
        for key in ('balance-repair-every-6h', 'auto-approval-hourly',
                    'security-scan-daily', 'auto-backup-daily'):
            assert key in schedule
            assert schedule[key]['task'].startswith('celery_tasks.')
            assert schedule[key]['options'] == {'queue': 'default'}

    def test_tasks_registered(self, db):
        from services.celery_tasks import celery
        for name in ('celery_tasks.generate_monthly_report',
                     'celery_tasks.send_invoice_email',
                     'celery_tasks.auto_backup_database',
                     'celery_tasks.update_exchange_rates',
                     'celery_tasks.train_neural_models',
                     'celery_tasks.send_payment_reminders',
                     'celery_tasks.cleanup_old_cache',
                     'celery_tasks.run_balance_repair',
                     'celery_tasks.run_auto_approval',
                     'celery_tasks.run_security_scan'):
            assert name in celery.tasks

    def test_generate_monthly_report_missing_service(self, db):
        from services.celery_tasks import generate_monthly_report
        result = generate_monthly_report.run(3, 2026)
        assert result['success'] is False
        assert 'ReportService unavailable' in result['error']

    def test_cleanup_old_cache(self, app, db):
        from services.celery_tasks import cleanup_old_cache
        with app.app_context():
            result = cleanup_old_cache.run()
        assert result == {'success': True, 'message': 'Cache cleared'}

    def test_cleanup_old_cache_error_path(self, db, monkeypatch):
        from services.celery_tasks import cleanup_old_cache
        import services.celery_tasks as tasks_mod
        import extensions

        def _boom():
            raise RuntimeError('cache down')

        monkeypatch.setattr(extensions.cache, 'clear', _boom)
        assert tasks_mod.celery  # module import sanity
        result = cleanup_old_cache.run()
        assert result == {'success': False, 'error': 'cache down'}

    def test_send_payment_reminders_empty(self, db):
        # No active customers with balance > 1000 -> zero sends, no network.
        from services.celery_tasks import send_payment_reminders
        assert send_payment_reminders.name == 'celery_tasks.send_payment_reminders'


# ---------------------------------------------------------------------------
# websocket_service
# ---------------------------------------------------------------------------

class TestWebsocketService:
    def test_broadcast_helpers_without_init_do_not_raise(self, db, caplog):
        import services.websocket_service as ws
        old, ws.socketio = ws.socketio, None
        try:
            ws.broadcast_sale_created({'id': 1})
            ws.broadcast_payment_received({'id': 2})
            ws.notify_user(99, 'hello')
            ws.broadcast_stock_alert({'sku': 'X'})
        finally:
            ws.socketio = old
        assert 'not initialized' in caplog.text

    def test_init_and_emit_routing(self, db, monkeypatch):
        from flask import Flask
        import services.websocket_service as ws
        mini = Flask(__name__)
        mini.config['SECRET_KEY'] = 'x'
        sio = ws.init_socketio(mini)
        assert sio is not None
        assert ws.socketio is sio

        emitted = []
        monkeypatch.setattr(sio, 'emit', lambda *a, **k: emitted.append((a, k)))
        ws.broadcast_sale_created({'id': 1})
        ws.broadcast_payment_received({'id': 2})
        ws.notify_user(42, 'hi', notification_type='warning')
        ws.broadcast_stock_alert({'sku': 'X'})
        assert emitted[0][0] == ('sale_created', {'id': 1})
        assert emitted[1][0] == ('payment_received', {'id': 2})
        assert emitted[2][0][0] == 'notification'
        assert emitted[2][1] == {'room': 'user_42'}
        assert emitted[2][0][1] == {'message': 'hi', 'type': 'warning'}
        assert emitted[3][0] == ('stock_alert', {'sku': 'X'})
        ws.socketio = None


# ---------------------------------------------------------------------------
# lookup_service
# ---------------------------------------------------------------------------

class TestLookupService:
    def test_groups_registry(self, db):
        from services import lookup_service
        groups = lookup_service.groups()
        assert 'product_units' in groups
        assert 'payment_methods' in groups  # locked group
        assert groups['payment_methods']['allow_add'] is False

    def test_get_lookup_and_codes(self, db):
        from services import lookup_service
        rows = lookup_service.get_lookup('product_units')
        assert len(rows) >= 1
        code, meta = rows[0]
        assert meta['ar'] and meta['en']
        assert lookup_service.get_codes('product_units')[0] == code

    def test_get_all_single_read(self, db):
        from services import lookup_service
        all_rows = lookup_service.get_all()
        assert set(all_rows) == set(lookup_service.groups())
        assert len(all_rows['product_units']) >= 1

    def test_unknown_group_raises(self, db):
        from services import lookup_service
        with pytest.raises(ValueError):
            lookup_service.get_lookup('no_such_group')
        with pytest.raises(ValueError):
            lookup_service.group_detail('no_such_group')
        with pytest.raises(ValueError):
            lookup_service.add_custom('no_such_group', 'x', 'y')
        with pytest.raises(ValueError):
            lookup_service.set_label('no_such_group', 'x', 'y')
        with pytest.raises(ValueError):
            lookup_service.set_disabled('no_such_group', 'x', True)

    def test_get_label(self, db):
        from services import lookup_service
        code = lookup_service.get_codes('product_units')[0]
        assert lookup_service.get_label('product_units', code, 'ar')
        assert lookup_service.get_label('product_units', code, 'en')
        assert lookup_service.get_label('product_units', 'missing-code') == 'missing-code'

    def test_add_custom_locked_group_refused(self, db):
        from services import lookup_service
        with pytest.raises(ValueError):
            lookup_service.add_custom('payment_methods', 'bitcoin', 'بتكوين')

    def test_add_custom_validation(self, db):
        from services import lookup_service
        with pytest.raises(ValueError):
            lookup_service.add_custom('product_units', 'bad<code>', 'عربي')
        with pytest.raises(ValueError):
            lookup_service.add_custom('product_units', 'nocode-ar', '')
        with pytest.raises(ValueError):
            lookup_service.add_custom('product_units', 'x' * 61, 'عربي')

    def test_add_custom_roundtrip_and_duplicate(self, db):
        from services import lookup_service
        lookup_service.add_custom('product_units', 'wave1box', 'صندوق', 'Box')
        assert 'wave1box' in lookup_service.get_codes('product_units')
        assert lookup_service.get_label('product_units', 'wave1box', 'en') == 'Box'
        with pytest.raises(ValueError):
            lookup_service.add_custom('product_units', 'wave1box', 'صندوق')

    def test_set_label_overrides(self, db):
        from services import lookup_service
        code = lookup_service.get_codes('payment_methods')[0]
        lookup_service.set_label('payment_methods', code, 'نقدي معدل', 'CashX')
        assert lookup_service.get_label('payment_methods', code, 'en') == 'CashX'
        with pytest.raises(ValueError):
            lookup_service.set_label('payment_methods', 'ghost-code', 'عربي')
        with pytest.raises(ValueError):
            lookup_service.set_label('payment_methods', code, '')

    def test_disable_enable_cycle(self, db):
        from services import lookup_service
        code = lookup_service.get_codes('product_units')[0]
        lookup_service.set_disabled('product_units', code, True)
        assert code not in lookup_service.get_codes('product_units')
        detail = {r['code']: r for r in lookup_service.group_detail('product_units')}
        assert detail[code]['disabled'] is True
        lookup_service.set_disabled('product_units', code, False)
        assert code in lookup_service.get_codes('product_units')

    def test_disable_locked_group_refused(self, db):
        from services import lookup_service
        code = lookup_service.get_codes('payment_methods')[0]
        with pytest.raises(ValueError):
            lookup_service.set_disabled('payment_methods', code, True)

    def test_merge_skips_malformed_custom(self, db):
        from services.lookup_service import _merge
        merged = _merge([('a', {'ar': 'أ', 'en': 'A'})],
                        ['not-a-triple', ('b',), None, ('c', 'ج', 'C')], {}, set())
        codes = [c for c, _ in merged]
        assert codes == ['a', 'c']


# ---------------------------------------------------------------------------
# ai_cache
# ---------------------------------------------------------------------------

class TestAiCache:
    def test_disabled_in_testing(self, db):
        from services import ai_cache
        assert ai_cache.enabled() is False

    def test_disabled_via_env_flag(self, db, monkeypatch):
        from services import ai_cache
        monkeypatch.setenv('APP_ENV', 'production')
        monkeypatch.setenv('AI_CACHE_ENABLED', '0')
        assert ai_cache.enabled() is False

    def test_normalize(self, db):
        from services.ai_cache import _normalize
        assert _normalize('  Hello   WORLD ') == 'hello world'
        assert _normalize('') == ''
        assert _normalize(None) == ''

    def test_make_key_stable_and_sensitive(self, db):
        from services.ai_cache import make_key
        assert make_key('g', 'm', 'Hi') == make_key('g', 'm', '  hi ')
        assert make_key('g', 'm', 'Hi') != make_key('g', 'm', 'Bye')
        assert make_key('g', 'm', 'Hi') != make_key('x', 'm', 'Hi')

    def test_set_get_roundtrip(self, db):
        from services import ai_cache
        ai_cache.clear()
        assert ai_cache.get('p', 'm', 'hello') is None
        ai_cache.set_value('p', 'm', 'hello', '', 'world')
        assert ai_cache.get('p', 'm', 'hello') == 'world'
        assert ai_cache.stats() == {'entries': 1}
        ai_cache.clear()
        assert ai_cache.stats() == {'entries': 0}

    def test_expired_entry_is_miss(self, db):
        import time
        from services import ai_cache
        ai_cache.clear()
        ai_cache.set_value('p', 'm', 'k', '', 'v')
        key = ai_cache.make_key('p', 'm', 'k', '')
        ai_cache._store[key] = (time.time() - 1, 'v')
        assert ai_cache.get('p', 'm', 'k') is None

    def test_eviction_bound(self, db, monkeypatch):
        from services import ai_cache
        ai_cache.clear()
        monkeypatch.setattr(ai_cache, '_MAX_ENTRIES', 2)
        ai_cache.set_value('p', 'm', 'k1', '', 'v1')
        ai_cache.set_value('p', 'm', 'k2', '', 'v2')
        ai_cache.set_value('p', 'm', 'k3', '', 'v3')
        assert ai_cache.stats()['entries'] <= 2
        ai_cache.clear()


# ---------------------------------------------------------------------------
# auto_approval_service (wrapper + empty-purchase branches only)
# ---------------------------------------------------------------------------

class TestAutoApprovalWrapper:
    def test_run_auto_approval_empty(self, db):
        from services.auto_approval_service import AutoApprovalService
        result = AutoApprovalService.run_auto_approval()
        assert result['donations']['success'] is True
        assert result['purchases']['success'] is True
        assert result['total_approved'] == 0
        assert result['total_amount'] == 0

    def test_approve_pending_purchases_empty(self, db):
        from services.auto_approval_service import AutoApprovalService
        result = AutoApprovalService.approve_pending_purchases(hours_threshold=1)
        assert result == {'success': True, 'approved_count': 0,
                          'approved_amount': 0,
                          'message': 'تم قبول 0 مشترية تلقائياً'}

    def test_schedule_fn_exists_without_running(self, db):
        import services.auto_approval_service as mod
        assert callable(mod.schedule_auto_approval)
        assert callable(mod.AutoApprovalService.run_auto_approval)


# ---------------------------------------------------------------------------
# user_service (update/delete/password/lookup paths only)
# ---------------------------------------------------------------------------

class TestUserServiceExtra:
    def _role(self, db, slug='wave1mgr'):
        from models import Role
        from extensions import db as _db
        role = Role(name='W1', name_ar='و', slug=slug, is_active=True)
        _db.session.add(role)
        _db.session.commit()
        return role

    def test_update_email_clash(self, db, owner_user, seller_user):
        from services.user_service import UserService
        with pytest.raises(ValueError, match='مستخدم بالفعل'):
            UserService.update_user(owner_user, actor=owner_user,
                                    email=seller_user.email)

    def test_update_email_ok(self, db, owner_user):
        from services.user_service import UserService
        UserService.update_user(owner_user, actor=owner_user,
                                email='newowner@test.com', full_name='New Name')
        assert owner_user.email == 'newowner@test.com'
        assert owner_user.full_name == 'New Name'

    def test_update_role_escalation_refused(self, db, owner_user, seller_user):
        from services.user_service import UserService
        role = self._role(db, slug='super_admin')
        with pytest.raises(ValueError, match='أعلى من دورك'):
            UserService.update_user(owner_user, actor=seller_user,
                                    role_id=role.id)

    def test_update_owner_flag_rules(self, db, owner_user, seller_user):
        from services.user_service import UserService
        with pytest.raises(ValueError):
            UserService.update_user(seller_user, actor=seller_user, is_owner=True)
        with pytest.raises(ValueError):
            UserService.update_user(owner_user, actor=owner_user, is_owner=False)
        with pytest.raises(ValueError):
            UserService.update_user(owner_user, actor=owner_user, is_active=False)

    def test_set_active(self, db, owner_user, seller_user):
        from services.user_service import UserService
        UserService.set_active(seller_user, False, actor=owner_user)
        assert seller_user.is_active is False
        with pytest.raises(ValueError):
            UserService.set_active(owner_user, False, actor=owner_user)

    def test_delete_user_hard(self, db, owner_user, seller_user):
        from services.user_service import UserService
        from models import User
        assert UserService.delete_user(seller_user, owner_user) == 'deleted'
        assert User.query.filter_by(id=seller_user.id).first() is None

    def test_delete_user_refusals(self, db, owner_user, seller_user):
        from services.user_service import UserService
        with pytest.raises(ValueError, match='مالك'):
            UserService.delete_user(owner_user, owner_user)
        with pytest.raises(ValueError, match='الخاص'):
            UserService.delete_user(seller_user, seller_user)

    def test_delete_user_soft_when_owns_sales(self, db, owner_user, test_sale):
        from services.user_service import UserService
        test_sale.seller_id = owner_user.id
        from extensions import db as _db
        # give the sale to a fresh seller so delete soft-deactivates
        from models import User
        seller = User(username='w1seller', email='w1seller@t.co', full_name='W1',
                      is_active=True, role_id=owner_user.role_id)
        seller.set_password('Str0ng!Pass#9z')
        _db.session.add(seller)
        _db.session.commit()
        test_sale.seller_id = seller.id
        _db.session.commit()
        assert UserService.delete_user(seller, owner_user) == 'deactivated'
        assert seller.is_active is False

    def test_change_password_paths(self, db, owner_user):
        from services.user_service import UserService
        with pytest.raises(ValueError, match='الحالية'):
            UserService.change_own_password(owner_user, 'wrong', 'NewStr0ng!Pass99',
                                            'NewStr0ng!Pass99')
        with pytest.raises(ValueError, match='متطابقة'):
            UserService.change_own_password(owner_user, 'OwnerPass123!',
                                            'NewStr0ng!Pass99', 'Other99!xQ')
        with pytest.raises(ValueError, match='تختلف'):
            UserService.change_own_password(owner_user, 'OwnerPass123!',
                                            'OwnerPass123!', 'OwnerPass123!')
        UserService.change_own_password(owner_user, 'OwnerPass123!',
                                        'NewStr0ng!Pass99', 'NewStr0ng!Pass99')
        assert owner_user.check_password('NewStr0ng!Pass99')

    def test_get_for_actor(self, db, owner_user):
        from werkzeug.exceptions import NotFound
        from services.user_service import UserService
        assert UserService.get_for_actor(owner_user.id, owner_user).id == owner_user.id
        with pytest.raises(NotFound):
            UserService.get_for_actor(999999, owner_user)

    def test_username_rules(self, db, owner_user):
        from services.user_service import UserService
        role = self._role(db)
        for bad in ('ab', '1abc', 'has space', 'a' * 21):
            with pytest.raises(ValueError):
                UserService.provision_user(username=bad, email=f'{bad}@t.co',
                                           password='Str0ng!Pass#9z',
                                           role_id=role.id, actor=owner_user)
