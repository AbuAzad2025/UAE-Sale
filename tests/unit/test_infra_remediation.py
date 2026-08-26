"""Agent I (Infrastructure & Async) remediation tests.

Covers: celery single-instance unification, C2 dual-scheme IPN signatures,
AI provider prompt wiring, thread-local conversation context, STRICT_LOCKS,
stable cache keys, cross-platform health disk probe, auto_backup_daily
due/not-due logic, and inline permission gating for destructive AI actions.
"""
import hashlib
import hmac
import inspect
import json
import logging
import os
import threading
import types
from datetime import datetime, timedelta

import pytest

from services.backup_service import BackupService

# ---------------------------------------------------------------------
# Celery unification
# ---------------------------------------------------------------------


class TestCelerySingleInstance:
    def test_worker_reexports_same_celery_app(self):
        import celery_worker
        from services.celery_tasks import celery as tasks_celery

        assert celery_worker.celery is tasks_celery

    def test_beat_schedule_references_registered_tasks_only(self):
        from services.celery_tasks import celery

        scheduled = {entry['task'] for entry in celery.conf.beat_schedule.values()}
        registered = set(celery.tasks.keys())
        assert scheduled, 'beat schedule must not be empty'
        assert scheduled <= registered, f'ghost tasks in beat: {scheduled - registered}'

    def test_no_ghost_autodiscover_left_behind(self):
        import celery_worker
        from services import celery_tasks

        assert 'autodiscover' not in inspect.getsource(celery_worker)
        assert 'autodiscover' not in inspect.getsource(celery_tasks)

    def test_scheduled_tasks_build_own_app_context(self):
        from services import celery_tasks

        for task_name in ('run_balance_repair', 'run_auto_approval', 'run_security_scan'):
            task = getattr(celery_tasks, task_name)
            assert 'create_app' in inspect.getsource(task.run)


# ---------------------------------------------------------------------
# Contract C2: NOWPayments signature schemes
# ---------------------------------------------------------------------

IPN_SECRET = 'ipn-secret-remediation'
WEBHOOK_DATA = {
    'payment_id': 'pay-r-001',
    'payment_status': 'finished',
    'order_id': 'MYSTERY_R01',
}


def _legacy_sig(raw_body, secret=IPN_SECRET):
    return hmac.new(secret.encode('utf-8'), raw_body, hashlib.sha512).hexdigest()


def _canonical_sig(data, secret=IPN_SECRET):
    return hmac.new(
        secret.encode('utf-8'),
        json.dumps(data, sort_keys=True).encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()


class TestCanonicalIpnSignature:
    def test_canonical_signature_accepted(self):
        from services.webhook_service import WebhookService

        raw = json.dumps(WEBHOOK_DATA).encode('utf-8')  # unsorted key order
        assert WebhookService.verify_ipn_signature(raw, _canonical_sig(WEBHOOK_DATA), IPN_SECRET)

    def test_wrong_canonical_signature_rejected(self):
        from services.webhook_service import WebhookService

        raw = json.dumps(WEBHOOK_DATA).encode('utf-8')
        forged = _canonical_sig(dict(WEBHOOK_DATA, payment_id='pay-EVIL'))
        assert not WebhookService.verify_ipn_signature(raw, forged, IPN_SECRET)

    def test_missing_secret_fails_closed(self):
        from services.webhook_service import WebhookService

        raw = b'{"a": 1}'
        assert not WebhookService.verify_ipn_signature(raw, _canonical_sig({'a': 1}), '')

    def test_garbage_body_fails_closed_not_raises(self):
        from services.webhook_service import WebhookService

        assert not WebhookService.verify_ipn_signature(b'not-json{', '00', IPN_SECRET)


class TestDualSchemeWebhookProcessing:
    def test_legacy_sha512_scheme_accepted_and_logged(self, app, db, caplog):
        from services.webhook_service import WebhookService

        raw = json.dumps(WEBHOOK_DATA).encode('utf-8')
        sig = _legacy_sig(raw)
        with app.app_context(), caplog.at_level(logging.INFO, logger='services.webhook_service'):
            result = WebhookService.process_nowpayments_webhook(
                WEBHOOK_DATA, raw_body=raw, received_sig=sig, ipn_secret=IPN_SECRET,
            )
        # Verification passed -> routing happened (unknown order => routing error,
        # NOT 'Invalid signature').
        assert result['error'] == 'Unknown order type'
        assert any('legacy SHA512(body)' in r.getMessage() for r in caplog.records)

    def test_canonical_scheme_accepted_and_logged(self, app, db, caplog):
        from services.webhook_service import WebhookService

        raw = json.dumps(WEBHOOK_DATA, sort_keys=False).encode('utf-8')
        sig = _canonical_sig(WEBHOOK_DATA)
        with app.app_context(), caplog.at_level(logging.INFO, logger='services.webhook_service'):
            result = WebhookService.process_nowpayments_webhook(
                WEBHOOK_DATA, raw_body=raw, received_sig=sig, ipn_secret=IPN_SECRET,
            )
        assert result['error'] == 'Unknown order type'
        assert any('canonical SHA256-sorted-JSON' in r.getMessage() for r in caplog.records)

    def test_forged_signature_under_both_schemes_rejected(self):
        from services.webhook_service import WebhookService

        raw = json.dumps(WEBHOOK_DATA).encode('utf-8')
        attacker = _legacy_sig(raw, 'attacker-secret')
        result = WebhookService.process_nowpayments_webhook(
            WEBHOOK_DATA, raw_body=raw, received_sig=attacker, ipn_secret=IPN_SECRET,
        )
        assert result == {'success': False, 'error': 'Invalid signature'}

    def test_no_signature_supplied_keeps_backward_compat(self, app, db):
        from services.webhook_service import WebhookService

        with app.app_context():
            result = WebhookService.process_nowpayments_webhook(WEBHOOK_DATA)
        assert result['error'] == 'Unknown order type'


class TestVerifyIpnDelegation:
    def test_nowpayments_verify_ipn_matches_canonical_impl(self, app, monkeypatch):
        from services.nowpayments_service import NOWPaymentsService
        from services import webhook_service as ws_mod

        svc = NOWPaymentsService.__new__(NOWPaymentsService)
        svc.ipn_secret = IPN_SECRET
        data = {'b': 2, 'a': 1}
        sig = _canonical_sig(data)

        captured = {}

        def fake_verify(raw_body, received_sig, secret):
            captured.update(body=raw_body, sig=received_sig, secret=secret)
            return True

        monkeypatch.setattr(ws_mod.WebhookService, 'verify_ipn_signature',
                            staticmethod(fake_verify))
        assert svc.verify_ipn(data, sig) is True
        assert json.loads(captured['body']) == data
        assert captured['sig'] == sig and captured['secret'] == IPN_SECRET

    def test_single_source_of_truth_used_by_both_services(self):
        from services import nowpayments_service

        src = inspect.getsource(nowpayments_service.NOWPaymentsService.verify_ipn)
        assert 'verify_ipn_signature' in src
        # The divergent duplicate implementation is gone.
        assert 'sha512' not in src.lower()


# ---------------------------------------------------------------------
# AI prompt wiring
# ---------------------------------------------------------------------


class TestAiProviderPromptWiring:
    def _stub_pipeline(self, monkeypatch, reply='GROQ-SAYS'):
        import ai_knowledge.intelligent_assistant as ia_mod
        monkeypatch.setattr(
            ia_mod.intelligent_assistant, 'process',
            lambda message, user_id=None, context=None: {'response': 'LOCAL'},
        )
        from services.ai_service import AIService

        monkeypatch.setattr(AIService, 'get_api_key', staticmethod(lambda: 'KEY'))
        monkeypatch.setattr(AIService, 'get_provider', staticmethod(lambda: 'groq'))
        monkeypatch.setattr(AIService, '_train_local_from_groq', staticmethod(lambda *a: None))

        captured = {}

        def fake_post(url, headers=None, json=None, timeout=None):  # noqa: A002
            captured['payload'] = json
            return types.SimpleNamespace(
                status_code=200,
                json=lambda: {'choices': [{'message': {'content': reply}}]},
            )

        monkeypatch.setattr('requests.post', fake_post)
        return captured

    def test_prompt_contains_actual_message_text(self, app, db, monkeypatch):
        captured = self._stub_pipeline(monkeypatch)
        from services.ai_service import AIService

        AIService.chat_response('كم عدد العملاء النشطين اليوم؟', {})
        messages = captured['payload']['messages']
        roles = [m['role'] for m in messages]
        assert 'user' in roles
        user_msg = [m for m in messages if m['role'] == 'user'][0]
        assert user_msg['content'] == 'كم عدد العملاء النشطين اليوم؟'

    def test_prompt_includes_knowledge_context(self, app, db, monkeypatch):
        captured = self._stub_pipeline(monkeypatch)
        from services.ai_service import AIService

        AIService.chat_response('سؤال عن المخزون', {})
        system_msg = [m for m in captured['payload']['messages'] if m['role'] == 'system'][0]
        # Knowledge gathered by _gather_relevant_knowledge reaches the provider.
        assert 'بيانات النظام الكاملة' in system_msg['content']
        assert 'المستخدمين:' in system_msg['content']
        assert '{users_count}' not in system_msg['content']  # actually formatted

    def test_create_customer_action_lists_requested_fields(self):
        from services.ai_service import AIService

        text = '{"action": "create_customer", "data_needed": ["الاسم", "الهاتف"]}'
        result = AIService._execute_ai_action(text, 1)
        assert result is not None
        assert 'عميل جديد' in result
        assert '1. الاسم' in result
        assert '2. الهاتف' in result


# ---------------------------------------------------------------------
# Thread-local conversation context
# ---------------------------------------------------------------------


class TestConversationContextStore:
    def test_thread_isolation_between_threads(self):
        from routes.ai import ConversationContextStore

        store = ConversationContextStore()
        store[7] = {'last_action': 'main'}
        seen = {}

        def worker():
            seen['before'] = 7 in store
            store[7] = {'last_action': 'worker'}
            seen['value'] = store[7]['last_action']

        t = threading.Thread(target=worker)
        t.start()
        t.join(timeout=10)

        assert seen['before'] is False          # child does not see parent state
        assert seen['value'] == 'worker'
        assert store[7]['last_action'] == 'main'  # parent unaffected

    def test_history_trimmed_to_max_50_turns(self):
        from routes.ai import ConversationContextStore

        store = ConversationContextStore()
        store[1] = {'history': [{'step': i} for i in range(80)]}
        assert len(store[1]['history']) == store.MAX_TURNS
        assert store[1]['history'][0] == {'step': 80 - store.MAX_TURNS}

    def test_store_evicts_oldest_beyond_50_conversations(self):
        from routes.ai import ConversationContextStore

        store = ConversationContextStore()
        for uid in range(60):
            store[uid] = {'n': uid}
        assert len(store._contexts) == 50
        assert 0 not in store                    # oldest evicted
        assert 59 in store and store[59] == {'n': 59}

    def test_dict_like_api_drop_in(self):
        from routes.ai import ConversationContextStore

        store = ConversationContextStore()
        store[5] = {'step': 0}
        assert 5 in store
        store[5]['step'] = 2
        assert store.get(5)['step'] == 2
        assert store.pop(5) == {'step': 2}
        assert 5 not in store
        with pytest.raises(KeyError):
            del store[5]


# ---------------------------------------------------------------------
# Inline permission gates for destructive AI actions
# ---------------------------------------------------------------------


class TestAiActionPermissionGate:
    def test_denied_when_permission_missing(self):
        from routes.ai import _ai_action_denied

        seller = types.SimpleNamespace(
            is_authenticated=True,
            has_permission=lambda code: code == 'manage_sales',
        )
        denial = _ai_action_denied(seller, 'manage_users')
        assert denial is not None
        assert 'صلاحية' in denial

    def test_allowed_when_permission_present(self):
        from routes.ai import _ai_action_denied

        admin = types.SimpleNamespace(is_authenticated=True, has_permission=lambda code: True)
        assert _ai_action_denied(admin, 'manage_payments') is None

    def test_unauthenticated_fails_closed(self):
        from routes.ai import _ai_action_denied

        anon = types.SimpleNamespace(is_authenticated=False)
        assert _ai_action_denied(anon, 'manage_customers') is not None

    def test_real_role_has_permission_pattern_respected(self, app, db, seller_user):
        from routes.ai import _ai_action_denied

        # seller role carries manage_sales but NOT manage_expenses/manage_users.
        assert _ai_action_denied(seller_user, 'manage_sales') is None
        assert _ai_action_denied(seller_user, 'manage_expenses') is not None
        assert _ai_action_denied(seller_user, 'manage_users') is not None

    def test_destructive_dialogs_have_permission_mappings(self):
        from routes.ai import _AI_ACTION_PERMISSIONS

        for action in ('فاتورة', 'استلام', 'إعطاء', 'مصروف', 'مشتريات', 'شيك', 'مستخدم'):
            assert action in _AI_ACTION_PERMISSIONS
        assert _AI_ACTION_PERMISSIONS['مستخدم'] == 'manage_users'
        assert _AI_ACTION_PERMISSIONS['مشتريات'] == 'manage_purchases'


# ---------------------------------------------------------------------
# Distributed lock STRICT_LOCKS + metric
# ---------------------------------------------------------------------


class TestStrictLocks:
    @pytest.fixture(autouse=True)
    def _no_redis(self, monkeypatch):
        import utils.distributed_lock as dl

        monkeypatch.setattr(dl, '_get_redis', lambda: None)
        return dl

    def test_fail_open_by_default_even_when_lock_held(self, monkeypatch):
        import utils.distributed_lock as dl

        monkeypatch.delenv('STRICT_LOCKS', raising=False)
        held = dl._get_fallback_lock('strict-default-x')
        assert held.acquire(timeout=1)
        try:
            with dl.distributed_lock('strict-default-x', blocking_timeout=0.05):
                assert True  # fail-open proceeds without raising
        finally:
            held.release()

    def test_strict_mode_raises_timeout_error_when_lock_held(self, monkeypatch):
        import utils.distributed_lock as dl

        monkeypatch.setenv('STRICT_LOCKS', '1')
        held = dl._get_fallback_lock('strict-on-x')
        assert held.acquire(timeout=1)
        try:
            with pytest.raises(TimeoutError):
                with dl.distributed_lock('strict-on-x', blocking_timeout=0.05):
                    pass
        finally:
            held.release()

    def test_metric_emitted_on_success_and_failure(self, monkeypatch):
        import utils.distributed_lock as dl

        monkeypatch.delenv('STRICT_LOCKS', raising=False)
        events = []

        def fake_record(metric_name, value, tags=None):
            events.append(tags)

        from utils.monitoring import MetricsCollector
        monkeypatch.setattr(MetricsCollector, 'record_metric',
                            staticmethod(fake_record))

        with dl.distributed_lock('metric-ok', blocking_timeout=1):
            pass

        held = dl._get_fallback_lock('metric-held')
        held.acquire(timeout=1)
        try:
            with dl.distributed_lock('metric-held', blocking_timeout=0.05):
                pass
        except Exception:
            pass
        finally:
            held.release()

        outcomes = [t['outcome'] for t in events]
        assert 'acquired' in outcomes
        assert 'timeout' in outcomes


# ---------------------------------------------------------------------
# Redis cache stability
# ---------------------------------------------------------------------


class TestStableCacheKeys:
    def test_kwargs_order_normalized_to_same_key(self):
        from utils.redis_cache import stable_cache_key

        def fn(a=None, b=None):
            return None

        k1 = stable_cache_key(fn, (), {'a': 1, 'b': 2})
        k2 = stable_cache_key(fn, (), {'b': 2, 'a': 1})
        assert k1 == k2

    def test_different_args_produce_different_keys(self):
        from utils.redis_cache import stable_cache_key

        def fn(a=None):
            return None

        assert stable_cache_key(fn, (1,), {}) != stable_cache_key(fn, (2,), {})

    def test_key_is_deterministic_sha256_across_calls_and_processes(self):
        from utils.redis_cache import stable_cache_key

        def loader(user_id, mode='fast'):
            return user_id

        expected = hashlib.sha256(
            repr((loader.__module__, loader.__name__, (7,), [('mode', 'fast')])).encode('utf-8'),
        ).hexdigest()
        key_a = stable_cache_key(loader, (7,), {'mode': 'fast'})
        key_b = stable_cache_key(loader, (7,), {'mode': 'fast'})
        assert key_a == key_b
        assert expected in key_a

    def test_decorator_caches_reordered_kwargs_together(self, app, monkeypatch):
        from extensions import cache
        from utils.redis_cache import cached

        backend = types.SimpleNamespace()
        store = {}
        backend.get = lambda key, **kw: store.get(key)
        backend.set = lambda key, value, timeout=None: store.setdefault(key, value)
        registry = app.extensions.setdefault('cache', {})
        monkeypatch.setitem(registry, cache, backend)

        calls = []

        with app.app_context():

            @cached(timeout=60, key_prefix='kw')
            def load(a=None, b=None):
                calls.append((a, b))
                return a + b

            assert load(a=1, b=2) == 3
            assert load(b=2, a=1) == 3  # served from cache
        assert calls == [(1, 2)]

    def test_delete_pattern_uses_scan_iter_when_available(self, monkeypatch):
        from utils.redis_cache import RedisCache

        class ScanClient:
            def __init__(self):
                self.deleted = []
                self.match_used = None

            def scan_iter(self, match=None):
                self.match_used = match
                # Real SCAN+MATCH only returns matching keys.
                yield 'prefmodel:X'

            def delete(self, *keys):
                self.deleted.extend(keys)
                return len(keys)

        client = ScanClient()
        fake_cache = types.SimpleNamespace(cache=types.SimpleNamespace(_client=client))
        monkeypatch.setattr('utils.redis_cache.cache', fake_cache)
        assert RedisCache.delete_pattern('model:*') is True
        assert client.match_used == '*model:*'
        assert client.deleted == ['prefmodel:X']


# ---------------------------------------------------------------------
# Health service cross-platform disk check
# ---------------------------------------------------------------------


class TestHealthDiskCheck:
    def test_disk_probe_failure_degrades_to_unknown_without_crash(self, monkeypatch):
        import services.health_service as hs
        from services.health_service import HealthCheckService

        monkeypatch.setattr(hs.psutil, 'cpu_percent', lambda interval=None: 12.0)
        monkeypatch.setattr(hs.psutil, 'virtual_memory',
                            lambda: types.SimpleNamespace(percent=40.0))

        def boom(path):
            raise RuntimeError(f'no probe for {path}')

        monkeypatch.setattr(hs.psutil, 'disk_usage', boom)

        result = HealthCheckService.check_system_resources()  # must not raise
        assert result['status'] == 'unknown'
        assert result['disk_percent'] is None
        assert any('Disk usage unavailable' in w for w in (result['warnings'] or []))

    def test_disk_probe_receives_os_appropriate_root(self, monkeypatch):
        import services.health_service as hs
        from services.health_service import HealthCheckService

        seen = []

        def fake_disk_usage(path):
            seen.append(path)
            return types.SimpleNamespace(percent=33.0)

        monkeypatch.setattr(hs.psutil, 'cpu_percent', lambda interval=None: 5.0)
        monkeypatch.setattr(hs.psutil, 'virtual_memory',
                            lambda: types.SimpleNamespace(percent=30.0))
        monkeypatch.setattr(hs.psutil, 'disk_usage', fake_disk_usage)

        result = HealthCheckService.check_system_resources()
        assert result['status'] == 'healthy'
        assert result['disk_percent'] == 33.0
        assert seen == [os.path.normpath(os.path.abspath(os.sep))]


# ---------------------------------------------------------------------
# BackupService.auto_backup_daily
# ---------------------------------------------------------------------


@pytest.fixture
def backup_env(tmp_path, monkeypatch):
    backup_dir = tmp_path / 'backups'
    backup_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(BackupService, 'BACKUP_DIR', str(backup_dir))
    monkeypatch.setattr(BackupService, '_BASEDIR', str(tmp_path))
    return tmp_path


def _save_settings(base, settings):
    path = base / 'instance'
    path.mkdir(exist_ok=True)
    (path / 'backup_settings.json').write_text(json.dumps(settings), encoding='utf-8')


def _load_state(base):
    path = base / 'instance' / 'backup_state.json'
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding='utf-8'))


class TestAutoBackupDaily:
    def test_runs_and_records_last_run_when_due(self, backup_env, monkeypatch):
        _save_settings(backup_env, {'enabled': True, 'frequency': 'daily'})
        created = []

        def fake_create(manual=False, compress=True, encrypt=False, description=''):
            created.append(description)
            return {'filename': 'auto_backup_due.sql.gz'}

        monkeypatch.setattr(BackupService, 'create_backup', staticmethod(fake_create))

        result = BackupService.auto_backup_daily()

        assert result == {'filename': 'auto_backup_due.sql.gz'}
        assert created == ['Scheduled automatic backup']
        state = _load_state(backup_env)
        assert state['last_backup_filename'] == 'auto_backup_due.sql.gz'
        assert state['last_auto_backup']

    def test_skips_when_not_due_within_interval(self, backup_env, monkeypatch):
        _save_settings(backup_env, {'enabled': True, 'frequency': 'daily'})
        state_path = backup_env / 'instance' / 'backup_state.json'
        recent = datetime.now() - timedelta(hours=2)
        state_path.write_text(json.dumps({'last_auto_backup': recent.isoformat()}),
                              encoding='utf-8')

        calls = []
        monkeypatch.setattr(
            BackupService, 'create_backup',
            staticmethod(lambda *a, **k: calls.append(k)),
        )

        assert BackupService.auto_backup_daily() is None
        assert calls == []

    def test_disabled_is_safe_noop(self, backup_env, monkeypatch):
        _save_settings(backup_env, {'enabled': False})

        calls = []
        monkeypatch.setattr(
            BackupService, 'create_backup',
            staticmethod(lambda *a, **k: calls.append(k)),
        )

        assert BackupService.auto_backup_daily() is None
        assert calls == []

    def test_failure_returns_none_and_keeps_last_run(self, backup_env, monkeypatch):
        _save_settings(backup_env, {'enabled': True, 'frequency': 'daily'})
        stale = datetime.now() - timedelta(days=3)
        state_path = backup_env / 'instance' / 'backup_state.json'
        state_path.write_text(json.dumps({'last_auto_backup': stale.isoformat()}),
                              encoding='utf-8')

        monkeypatch.setattr(BackupService, 'create_backup', staticmethod(lambda *a, **k: None))
        assert BackupService.auto_backup_daily() is None
        assert _load_state(backup_env)['last_auto_backup'] == stale.isoformat()

    def test_exception_inside_never_propagates(self, backup_env, monkeypatch):
        _save_settings(backup_env, {'enabled': True, 'frequency': 'daily'})

        def explode(*a, **k):
            raise RuntimeError('pg_dump vanished')

        monkeypatch.setattr(BackupService, 'create_backup', staticmethod(explode))
        assert BackupService.auto_backup_daily() is None

    def test_hourly_frequency_shortens_interval(self, backup_env, monkeypatch):
        _save_settings(backup_env, {'enabled': True, 'frequency': 'hourly'})
        state_path = backup_env / 'instance' / 'backup_state.json'
        recent = datetime.now() - timedelta(minutes=90)
        state_path.write_text(json.dumps({'last_auto_backup': recent.isoformat()}),
                              encoding='utf-8')

        monkeypatch.setattr(
            BackupService, 'create_backup',
            staticmethod(lambda *a, **k: {'filename': 'auto_backup_h.sql.gz'}),
        )
        result = BackupService.auto_backup_daily()
        assert result == {'filename': 'auto_backup_h.sql.gz'}  # 1.5h > 1h interval → due


# ---------------------------------------------------------------------
# Scheduler gating + misc infra regressions
# ---------------------------------------------------------------------


class TestSchedulerGating:
    def test_app_main_honors_enable_scheduler_env_flag(self):
        import app as app_module

        src = inspect.getsource(app_module)
        assert "os.environ.get('ENABLE_SCHEDULERS'" in src
        # Startup log clarifying gunicorn behavior exists.
        assert 'gunicorn' in src

    def test_auto_backup_daily_is_real_callable(self):
        assert callable(BackupService.auto_backup_daily)
