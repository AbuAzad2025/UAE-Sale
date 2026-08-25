"""Tests for services/celery_tasks.py and services/balance_repair_scheduler.py."""

import sys
import types
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from models import Customer, Sale, SystemSettings
from utils.helpers import generate_number


def _use_test_app(monkeypatch, app):
    monkeypatch.setattr('app.create_app', lambda: app)


def _make_customer(db, name, balance=Decimal('0'), phone=None, email=None, is_active=True):
    customer = Customer(
        name=name,
        customer_type='regular',
        phone=phone,
        email=email,
        credit_limit=Decimal('50000'),
        balance=balance,
        is_active=is_active,
    )
    db.session.add(customer)
    db.session.commit()
    return customer


def _make_sale(db, seller, customer, amount_base, paid_base=Decimal('0')):
    paid = Decimal(str(paid_base))
    sale = Sale(
        sale_number=generate_number('S', Sale, 'sale_number'),
        customer_id=customer.id,
        seller_id=seller.id,
        total_amount=Decimal(str(amount_base)),
        amount_base=Decimal(str(amount_base)),
        paid_amount=paid,
        paid_amount_base=paid,
        balance_due=Decimal(str(amount_base)) - paid,
        currency='AED',
        exchange_rate=Decimal('1'),
        payment_status='unpaid' if paid == 0 else 'partial',
        status='confirmed',
        is_active=True,
    )
    db.session.add(sale)
    db.session.commit()
    return sale


def _force_stored_balance(db, customer, value):
    db.session.expire(customer)
    customer.balance = Decimal(str(value))
    db.session.commit()


def _install_report_service(monkeypatch, result):
    module = types.ModuleType('services.report_service')

    class FakeReportService:
        @staticmethod
        def generate_monthly_report(month, year):
            assert (month, year) == (8, 2026)
            return result

    module.ReportService = FakeReportService
    monkeypatch.setitem(sys.modules, 'services.report_service', module)


class TestGenerateMonthlyReportTask:
    def test_returns_report_id_on_success(self, app, db, monkeypatch):
        from services.celery_tasks import generate_monthly_report

        _use_test_app(monkeypatch, app)
        _install_report_service(monkeypatch, types.SimpleNamespace(id=42))

        result = generate_monthly_report.run(8, 2026)
        assert result == {'success': True, 'report_id': 42}

    def test_returns_none_report_id_when_no_report(self, app, db, monkeypatch):
        from services.celery_tasks import generate_monthly_report

        _use_test_app(monkeypatch, app)
        _install_report_service(monkeypatch, None)

        result = generate_monthly_report.run(8, 2026)
        assert result == {'success': True, 'report_id': None}


class TestSendInvoiceEmailTask:
    def test_sends_email_to_customer_address(self, app, db, owner_user, test_customer,
                                             test_product, monkeypatch):
        from services.celery_tasks import send_invoice_email
        from extensions import mail

        _use_test_app(monkeypatch, app)
        mail.init_app(app)
        sale = _make_sale(db, owner_user, test_customer, '250')
        sent = []
        monkeypatch.setattr('extensions.mail.send', lambda msg: sent.append(msg))

        result = send_invoice_email.run(sale.id)

        assert result == {'success': True}
        assert len(sent) == 1
        assert sent[0].recipients == ['customer@test.com']
        assert str(sale.sale_number) in sent[0].subject

    def test_unknown_sale_id_reports_failure(self, app, db, monkeypatch):
        from services.celery_tasks import send_invoice_email

        _use_test_app(monkeypatch, app)
        sent = []
        monkeypatch.setattr('extensions.mail.send', lambda msg: sent.append(msg))

        result = send_invoice_email.run(999999)

        assert result == {'success': False}
        assert sent == []

    def test_customer_without_email_skips_send(self, app, db, owner_user, monkeypatch):
        from services.celery_tasks import send_invoice_email

        _use_test_app(monkeypatch, app)
        customer = _make_customer(db, 'بلا بريد', phone='+971501234567', email=None)
        sale = _make_sale(db, owner_user, customer, '100')
        sent = []
        monkeypatch.setattr('extensions.mail.send', lambda msg: sent.append(msg))

        result = send_invoice_email.run(sale.id)

        assert result == {'success': False}
        assert sent == []


class TestAutoBackupDatabaseTask:
    def test_success_when_backup_created(self, app, db, monkeypatch):
        from services.celery_tasks import auto_backup_database
        from services.backup_service import BackupService

        _use_test_app(monkeypatch, app)
        backup = {'filename': 'auto_backup_20260826.zip'}
        monkeypatch.setattr(
            BackupService, 'auto_backup_daily', staticmethod(lambda: backup), raising=False)

        result = auto_backup_database.run()

        assert result == {'success': True, 'backup': backup}

    def test_failure_when_no_backup_returned(self, app, db, monkeypatch):
        from services.celery_tasks import auto_backup_database
        from services.backup_service import BackupService

        _use_test_app(monkeypatch, app)
        monkeypatch.setattr(
            BackupService, 'auto_backup_daily', staticmethod(lambda: None), raising=False)

        result = auto_backup_database.run()

        assert result == {'success': False, 'backup': None}


class TestUpdateExchangeRatesTask:
    def test_returns_service_result_verbatim(self, app, db, monkeypatch):
        from services.celery_tasks import update_exchange_rates
        from services.currency_service import CurrencyService

        _use_test_app(monkeypatch, app)
        rates = {'USD': Decimal('3.6725'), 'AED': Decimal('1')}
        monkeypatch.setattr(
            CurrencyService, 'update_all_rates', staticmethod(lambda: rates), raising=False)

        assert update_exchange_rates.run() == rates


class TestTrainNeuralModelsTask:
    def test_returns_training_results(self, app, db, monkeypatch):
        from services.celery_tasks import train_neural_models

        class FakeNeuralEngine:
            def train_all_models(self):
                return {'trained': 3, 'accuracy': 0.9}

        _use_test_app(monkeypatch, app)
        monkeypatch.setattr(
            'ai_knowledge.neural_engine.get_neural_engine', lambda: FakeNeuralEngine())

        assert train_neural_models.run() == {'trained': 3, 'accuracy': 0.9}


class TestSendPaymentRemindersTask:
    def test_reminds_only_eligible_active_customers_with_phone(
            self, app, db, owner_user, monkeypatch):
        from services.celery_tasks import send_payment_reminders
        from services.whatsapp_service import WhatsAppService

        _use_test_app(monkeypatch, app)
        high = _make_customer(db, 'مرتفع', phone='+971501111111')
        low = _make_customer(db, 'منخفض', phone='+971502222222')
        no_phone = _make_customer(db, 'بلا هاتف')
        ghost = _make_customer(db, 'غير نشط', phone='+971503333333', is_active=False)
        _make_sale(db, owner_user, high, '2000')
        _make_sale(db, owner_user, low, '500')
        _make_sale(db, owner_user, no_phone, '3000')
        _make_sale(db, owner_user, ghost, '9000')

        calls = []

        def fake_reminder(phone, name, amount):
            calls.append((phone, name, amount))
            return {'success': True}

        monkeypatch.setattr(
            WhatsAppService, 'send_payment_reminder', staticmethod(fake_reminder))

        result = send_payment_reminders.run()

        assert result == {'sent': 1, 'total_checked': 3}
        assert calls == [('+971501111111', 'مرتفع', 2000.0)]

    def test_counts_only_successful_sends(self, app, db, owner_user, monkeypatch):
        from services.celery_tasks import send_payment_reminders
        from services.whatsapp_service import WhatsAppService

        _use_test_app(monkeypatch, app)
        customer = _make_customer(db, 'فاشل', phone='+971504444444')
        _make_sale(db, owner_user, customer, '5000')
        monkeypatch.setattr(
            WhatsAppService, 'send_payment_reminder',
            staticmethod(lambda phone, name, amount: {'success': False}))

        result = send_payment_reminders.run()

        assert result == {'sent': 0, 'total_checked': 1}

    def test_boundary_balance_at_threshold_not_reminded(self, app, db, owner_user, monkeypatch):
        from services.celery_tasks import send_payment_reminders
        from services.whatsapp_service import WhatsAppService

        _use_test_app(monkeypatch, app)
        customer = _make_customer(db, 'حدودي', phone='+971505555555')
        _make_sale(db, owner_user, customer, '1000')
        monkeypatch.setattr(
            WhatsAppService, 'send_payment_reminder',
            staticmethod(lambda phone, name, amount: {'success': True}))

        result = send_payment_reminders.run()

        assert result == {'sent': 0, 'total_checked': 1}


class TestCleanupOldCacheTask:
    def test_clears_cache_successfully(self, app, db):
        from services.celery_tasks import cleanup_old_cache
        from extensions import cache

        with app.app_context():
            cache.set('stale-key', 'value')

        assert cleanup_old_cache.run() == {'success': True, 'message': 'Cache cleared'}
        with app.app_context():
            assert cache.get('stale-key') is None

    def test_returns_error_dict_when_cache_fails(self, app, db, monkeypatch):
        from services.celery_tasks import cleanup_old_cache
        from extensions import cache

        def boom():
            raise RuntimeError('cache exploded')

        monkeypatch.setattr(cache, 'clear', boom)

        result = cleanup_old_cache.run()
        assert result['success'] is False
        assert 'cache exploded' in result['error']


class TestBalanceRepairScheduleSettings:
    def test_defaults_when_nothing_saved(self, db):
        from services.balance_repair_scheduler import BalanceRepairScheduler

        settings = BalanceRepairScheduler.get_schedule_settings()
        assert settings == {
            'enabled': False,
            'interval_hours': 6,
            'last_run': None,
            'auto_repair': True,
        }

    def test_save_and_get_roundtrip(self, db):
        from services.balance_repair_scheduler import BalanceRepairScheduler

        saved = {
            'enabled': True,
            'interval_hours': 2,
            'last_run': None,
            'auto_repair': False,
        }
        BalanceRepairScheduler.save_schedule_settings(saved)

        assert BalanceRepairScheduler.get_schedule_settings() == saved
        assert SystemSettings.query.count() == 1

    def test_corrupted_storage_falls_back_to_defaults(self, db):
        from services.balance_repair_scheduler import BalanceRepairScheduler

        BalanceRepairScheduler.save_schedule_settings({'enabled': True})
        row = SystemSettings.query.filter_by(is_active=True).first()
        row.custom_settings = 'not-valid-json{'
        db.session.commit()

        settings = BalanceRepairScheduler.get_schedule_settings()
        assert settings['enabled'] is False
        assert settings['interval_hours'] == 6


class TestRunScheduledRepair:
    def test_repairs_drift_updates_settings_and_audits(self, app, db, owner_user, monkeypatch):
        from services.balance_repair_scheduler import BalanceRepairScheduler

        customer = _make_customer(db, 'منحرف', balance=Decimal('0'))
        _make_sale(db, owner_user, customer, '1500')
        _force_stored_balance(db, customer, '0')

        audits = []
        monkeypatch.setattr(
            'services.balance_repair_scheduler.create_audit_log',
            lambda action, **kw: audits.append((action, kw)))

        result = BalanceRepairScheduler.run_scheduled_repair(auto_repair=True)

        db.session.refresh(customer)
        assert customer.balance == Decimal('1500.000')
        assert result['drifts_found'] == 1
        assert result['repaired'] == 1
        assert result['failed'] == 0
        assert result['success'] is True

        stored = BalanceRepairScheduler.get_schedule_settings()
        assert stored['drifts_found'] == 1
        assert stored['repaired'] == 1
        assert stored['failed'] == 0
        assert stored['last_run'] is not None

        assert len(audits) == 1
        action, kwargs = audits[0]
        assert action.startswith('auto_balance_repair')
        assert str(customer.id) in action
        assert kwargs['table_name'] == 'customers'
        assert kwargs['record_id'] == customer.id
        assert kwargs['changes']['old_balance'] == 0.0
        assert kwargs['changes']['new_balance'] == 1500.0
        assert kwargs['changes']['auto'] is True

    def test_report_only_mode_leaves_balances_untouched(self, app, db, owner_user, monkeypatch):
        from services.balance_repair_scheduler import BalanceRepairScheduler

        customer = _make_customer(db, 'تقرير فقط', balance=Decimal('7'))
        _make_sale(db, owner_user, customer, '1500')
        _force_stored_balance(db, customer, '7')

        audits = []
        monkeypatch.setattr(
            'services.balance_repair_scheduler.create_audit_log',
            lambda action, **kw: audits.append((action, kw)))

        result = BalanceRepairScheduler.run_scheduled_repair(auto_repair=False)

        db.session.refresh(customer)
        assert customer.balance == Decimal('7')
        assert result['drifts_found'] == 1
        assert result['repaired'] == 0
        assert result['failed'] == 0
        assert audits == []

    def test_counts_failed_repairs(self, app, db, owner_user, monkeypatch):
        from services.balance_repair_scheduler import BalanceRepairScheduler

        customer = _make_customer(db, 'يفشل الإصلاح', balance=Decimal('99'))
        _make_sale(db, owner_user, customer, '800')
        _force_stored_balance(db, customer, '99')
        monkeypatch.setattr(
            'services.balance_repair_scheduler.repair_customer_balance', lambda cid: False)

        result = BalanceRepairScheduler.run_scheduled_repair(auto_repair=True)

        assert result['drifts_found'] == 1
        assert result['repaired'] == 0
        assert result['failed'] == 1
        assert BalanceRepairScheduler.get_schedule_settings()['failed'] == 1

    def test_no_drift_is_clean_run(self, app, db, owner_user, monkeypatch):
        from services.balance_repair_scheduler import BalanceRepairScheduler

        customer = _make_customer(db, 'سليم', balance=Decimal('400'))
        _make_sale(db, owner_user, customer, '400')

        audits = []
        monkeypatch.setattr(
            'services.balance_repair_scheduler.create_audit_log',
            lambda action, **kw: audits.append((action, kw)))

        result = BalanceRepairScheduler.run_scheduled_repair(auto_repair=True)

        assert result['drifts_found'] == 0
        assert result['repaired'] == 0
        assert result['failed'] == 0
        assert audits == []


class TestShouldRunNow:
    def _save(self, enabled, interval_hours=6, last_run=None):
        from services.balance_repair_scheduler import BalanceRepairScheduler
        BalanceRepairScheduler.save_schedule_settings({
            'enabled': enabled,
            'interval_hours': interval_hours,
            'last_run': last_run,
            'auto_repair': True,
        })

    def test_disabled_never_runs(self, db):
        self._save(enabled=False, last_run=datetime.now(timezone.utc).isoformat())
        from services.balance_repair_scheduler import BalanceRepairScheduler
        assert BalanceRepairScheduler.should_run_now() is False

    def test_enabled_without_last_run_runs_immediately(self, db):
        self._save(enabled=True, last_run=None)
        from services.balance_repair_scheduler import BalanceRepairScheduler
        assert BalanceRepairScheduler.should_run_now() is True

    def test_recent_run_within_interval_waits(self, db):
        recent = datetime.now(timezone.utc) - timedelta(minutes=30)
        self._save(enabled=True, interval_hours=6, last_run=recent.isoformat())
        from services.balance_repair_scheduler import BalanceRepairScheduler
        assert BalanceRepairScheduler.should_run_now() is False

    def test_elapsed_interval_triggers_run(self, db):
        stale = datetime.now(timezone.utc) - timedelta(hours=6, minutes=1)
        self._save(enabled=True, interval_hours=6, last_run=stale.isoformat())
        from services.balance_repair_scheduler import BalanceRepairScheduler
        assert BalanceRepairScheduler.should_run_now() is True

    def test_naive_last_run_treated_as_utc(self, db):
        naive = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(tzinfo=None)
        self._save(enabled=True, interval_hours=6, last_run=naive.isoformat())
        from services.balance_repair_scheduler import BalanceRepairScheduler
        assert BalanceRepairScheduler.should_run_now() is False

    def test_malformed_last_run_defaults_to_running(self, db):
        self._save(enabled=True, last_run='definitely-not-a-date')
        from services.balance_repair_scheduler import BalanceRepairScheduler
        assert BalanceRepairScheduler.should_run_now() is True


@pytest.mark.parametrize('report_id,expected_id', [(None, None), (types.SimpleNamespace(id=7), 7)])
def test_monthly_report_parametrized(app, db, monkeypatch, report_id, expected_id):
    from services.celery_tasks import generate_monthly_report

    _use_test_app(monkeypatch, app)
    _install_report_service(monkeypatch, report_id)

    assert generate_monthly_report.run(8, 2026)['report_id'] == expected_id
