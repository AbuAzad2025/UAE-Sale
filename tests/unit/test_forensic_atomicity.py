"""Forensic audit-trail + atomic-transaction tests (Agent 6).

Covers:
- utils.decorators.tx(): commit/rollback/nesting/duration telemetry
- services.payment_service: audit rows on every mutation branch, actor fields
- orphan prevention: Receipt always GL-linked or explicitly warned
- utils.advanced_audit: Decimal/datetime-safe changes payloads, event filters
"""
import json
import logging
from datetime import datetime
from decimal import Decimal

import pytest
from flask_login import login_user

from extensions import db
from models import AuditLog, Cheque, GLJournalEntry, Receipt, Sale
from services.gl_service import GLService
from services.payment_service import PaymentService
from utils.advanced_audit import get_security_events, log_sensitive_action
from utils.decorators import tx


def _mk_row(tag):
    db.session.add(AuditLog(action=f'tx-{tag}'))
    db.session.flush()


class TxBoom(Exception):
    pass


@tx
def _tx_write_and_raise(tag, exc):
    _mk_row(tag)
    raise exc


@tx
def _tx_write(tag):
    _mk_row(tag)
    return f'ok-{tag}'


@tx
def _tx_outer_calls_inner(tag):
    _mk_row(f'{tag}-outer')
    _tx_write(f'{tag}-inner')


@tx
def _tx_outer_calls_inner_then_raises(tag):
    _mk_row(f'{tag}-outer')
    _tx_write(f'{tag}-inner')
    raise RuntimeError('outer blew up after inner work')


def _attach_log_capture(app, caplog, level=logging.INFO):
    """Attach pytest's capture handler to flask's app logger deterministically."""
    app.logger.addHandler(caplog.handler)
    previous_level = app.logger.level
    app.logger.setLevel(level)
    return previous_level


def _detach_log_capture(app, caplog, previous_level=None):
    app.logger.removeHandler(caplog.handler)
    if previous_level is not None:
        app.logger.setLevel(previous_level)


def _mk_sale(db, owner_user, customer, total=Decimal('100.000')):
    from utils.helpers import generate_number

    sale = Sale(
        sale_number=generate_number('S', Sale, 'sale_number'),
        customer_id=customer.id, seller_id=owner_user.id,
        total_amount=total, amount_base=total,
        paid_amount=Decimal('0'), paid_amount_base=Decimal('0'),
        balance_due=total, currency='AED',
        exchange_rate=Decimal('1'), payment_status='unpaid',
        status='confirmed', is_active=True,
    )
    db.session.add(sale)
    db.session.commit()
    return sale


def _cash_payload(customer, amount='150'):
    return {
        'customer_id': customer.id,
        'amount': Decimal(amount),
        'currency': 'AED',
        'payment_method': 'cash',
    }


class TestTxCommitPath:
    def test_commit_path_persists(self, app, db):
        assert _tx_write('persist') == 'ok-persist'
        assert AuditLog.query.filter_by(action='tx-persist').count() == 1

    def test_return_value_passthrough_and_metadata(self, app, db):
        assert _tx_write('meta') == 'ok-meta'
        assert _tx_write.__name__ == '_tx_write'

    def test_sequential_transactions_commit_independently(self, app, db):
        _tx_write('seq-a')
        _tx_write('seq-b')
        assert AuditLog.query.filter(AuditLog.action.like('tx-seq-%')).count() == 2

    def test_rollback_leaves_session_usable_for_next_transaction(self, app, db):
        with pytest.raises(TxBoom):
            _tx_write_and_raise('then-fail', TxBoom('nope'))
        assert AuditLog.query.filter_by(action='tx-then-fail').count() == 0
        _tx_write('after-fail')
        assert AuditLog.query.filter_by(action='tx-after-fail').count() == 1


class TestTxRollbackAndNesting:
    def test_exception_path_rolls_back_and_reraises_original_type(self, app, db):
        with pytest.raises(TxBoom, match='original failure'):
            _tx_write_and_raise('rb', TxBoom('original failure'))
        assert AuditLog.query.filter_by(action='tx-rb').count() == 0

    def test_nested_inner_reuses_outer_single_transaction(self, app, db):
        _tx_outer_calls_inner('nest')
        rows = AuditLog.query.filter(AuditLog.action.like('tx-nest-%')).all()
        assert sorted(r.action for r in rows) == ['tx-nest-inner', 'tx-nest-outer']

    def test_outer_failure_rolls_back_committed_inner_work(self, app, db):
        with pytest.raises(RuntimeError, match='outer blew up'):
            _tx_outer_calls_inner_then_raises('orphan-work')
        assert AuditLog.query.filter(AuditLog.action.like('tx-orphan-work-%')).count() == 0

    def test_nested_inner_failure_propagates_original_type_and_discards_work(self, app, db):
        @tx
        def outer():
            _mk_row('inner-fail-outer')
            _tx_write_and_raise('inner-fail-inner', ValueError('inner exploded'))

        with pytest.raises(ValueError, match='inner exploded'):
            outer()
        assert AuditLog.query.filter(AuditLog.action.like('tx-inner-fail-%')).count() == 0


class TestTxDurationTelemetry:
    def _record_metrics(self, monkeypatch):
        from utils.monitoring import MetricsCollector

        seen = []
        monkeypatch.setattr(
            MetricsCollector, 'record_metric',
            staticmethod(lambda name, value, tags=None: seen.append((name, value, tags))),
        )
        return seen

    def test_duration_reported_via_monitoring_metric_hook(self, app, db, monkeypatch):
        seen = self._record_metrics(monkeypatch)
        _tx_write('metric')
        matches = [c for c in seen if c[0] == 'tx_duration_ms']
        assert len(matches) == 1
        _, value, tags = matches[0]
        assert isinstance(value, float) and value >= 0.0
        assert tags['function'] == '_tx_write'
        assert tags['outcome'] == 'commit'

    def test_nested_call_reports_nested_outcome(self, app, db, monkeypatch):
        seen = self._record_metrics(monkeypatch)
        _tx_outer_calls_inner('telem')
        outcomes = sorted(t['outcome'] for _, _, t in seen if t)
        assert outcomes == ['commit', 'nested']

    def test_missing_monitoring_module_falls_back_to_logger(self, app, db, caplog, monkeypatch):
        import sys
        monkeypatch.setitem(sys.modules, 'utils.monitoring', None)
        previous = _attach_log_capture(app, caplog)
        try:
            _tx_write('fallback')
        finally:
            _detach_log_capture(app, caplog, previous)
        tx_logs = [r for r in caplog.records if 'TX _tx_write' in r.getMessage()]
        assert tx_logs, 'expected duration fallback log when monitoring unavailable'


class TestPaymentAuditTrail:
    def test_manual_cash_receipt_writes_audit_with_authenticated_actor(
        self, app, db, owner_user, test_customer,
    ):
        with app.test_request_context('/'):
            login_user(owner_user)
            receipt = PaymentService.create_receipt(_cash_payload(test_customer))

        row = AuditLog.query.filter_by(action='receipt_create').one()
        assert row.table_name == 'receipts'
        assert row.record_id == receipt.id
        assert row.user_id == owner_user.id
        assert row.changes['actor'] == owner_user.username
        assert row.changes['receipt_number'] == receipt.receipt_number
        assert Decimal(row.changes['amount']) == Decimal('150')
        assert row.changes['gl_posted'] is True

    def test_headless_receipt_records_actor_system(self, db, owner_user, test_customer):
        receipt = PaymentService.create_receipt(_cash_payload(test_customer))

        row = AuditLog.query.filter_by(action='receipt_create').one()
        assert row.user_id is None
        assert row.changes['actor'] == 'system'
        assert row.record_id == receipt.id

    def test_sale_linked_allocation_recorded_in_audit(self, db, owner_user, test_customer, test_sale):
        PaymentService.create_receipt({
            'customer_id': test_customer.id,
            'amount': Decimal('60'),
            'currency': test_sale.currency,
            'payment_method': 'cash',
            'user_exchange_rate': Decimal('1'),
            'allocate_to_sales': {test_sale.id: 60},
        })

        row = AuditLog.query.filter_by(action='receipt_create').one()
        assert row.changes['source_type'] == 'sale'
        assert len(row.changes['allocations']) == 1
        assert row.changes['allocations'][0]['sale_id'] == test_sale.id
        assert Decimal(row.changes['allocations'][0]['allocated']) == Decimal('60')

    def test_cheque_receipt_audit_links_cheque_and_actor(
        self, app, db, owner_user, test_customer,
    ):
        with app.test_request_context('/'):
            login_user(owner_user)
            receipt = PaymentService.create_receipt({
                'customer_id': test_customer.id,
                'amount': Decimal('500'),
                'currency': 'AED',
                'payment_method': 'cheque',
                'cheque_number': 'CH-FOR-77',
                'cheque_date': '2026-09-30',
                'bank_name': 'Emirates NBD',
            })

        cheque = Cheque.query.filter_by(cheque_number='CH-FOR-77').one()
        row = AuditLog.query.filter_by(action='receipt_create').one()
        assert row.changes['cheque_id'] == receipt.cheque_id == cheque.id
        assert row.changes['actor'] == owner_user.username

    def test_allocate_to_oldest_writes_allocation_audit(self, db, owner_user, test_customer):
        sale_a = _mk_sale(db, owner_user, test_customer)
        sale_b = _mk_sale(db, owner_user, test_customer, total=Decimal('200.000'))
        receipt = Receipt(
            receipt_number='RCV-AUDIT-FIFO', source_type='manual', direction='incoming',
            customer_id=test_customer.id, amount=Decimal('250'),
            currency='AED', exchange_rate=Decimal('1'), amount_base=Decimal('250'),
            payment_method='cash', user_id=owner_user.id,
        )
        db.session.add(receipt)
        db.session.commit()

        PaymentService.allocate_receipt_to_oldest_sales(receipt, test_customer)

        row = AuditLog.query.filter_by(action='receipt_allocation').one()
        assert row.record_id == receipt.id
        assert len(row.changes['allocations']) == 2
        by_sale = {a['sale_id']: Decimal(a['allocated']) for a in row.changes['allocations']}
        assert by_sale[sale_a.id] == Decimal('100.000')
        assert by_sale[sale_b.id] == Decimal('150.000')
        assert Decimal(row.changes['unallocated']) == 0

    def test_invalid_cheque_date_audits_failure_and_propagates_valueerror(
        self, db, owner_user, test_customer,
    ):
        with pytest.raises(ValueError):
            PaymentService.create_receipt({
                'customer_id': test_customer.id,
                'amount': Decimal('50'),
                'currency': 'AED',
                'payment_method': 'cheque',
                'cheque_number': 'CH-BAD',
                'cheque_date': '31-02-2026',
            })

        row = AuditLog.query.filter_by(action='receipt_create_failed').one()
        assert row.record_id is None
        assert row.changes['error_type'] == 'ValueError'
        assert Decimal(row.changes['amount']) == Decimal('50')
        assert AuditLog.query.filter_by(action='receipt_create').count() == 0


class TestOrphanPrevention:
    def test_cash_receipt_links_balanced_gl_entry(self, db, owner_user, test_customer):
        receipt = PaymentService.create_receipt(_cash_payload(test_customer))

        entry = GLJournalEntry.query.filter_by(
            reference_type='Receipt', reference_id=receipt.id,
        ).one()
        assert entry.total_debit == entry.total_credit == Decimal('150')

    def test_gl_failure_keeps_receipt_with_explicit_warning(
        self, app, db, owner_user, test_customer, monkeypatch, caplog,
    ):
        def explode(*args, **kwargs):
            raise RuntimeError('gl engine down')

        monkeypatch.setattr(GLService, 'post_entry', staticmethod(explode))
        previous = _attach_log_capture(app, caplog, level=logging.WARNING)
        try:
            receipt = PaymentService.create_receipt(_cash_payload(test_customer))
        finally:
            _detach_log_capture(app, caplog, previous)

        assert receipt.id is not None
        warnings = [r for r in caplog.records
                    if r.levelno == logging.WARNING and 'ORPHAN RECEIPT WARNING' in r.getMessage()]
        assert warnings and f'id={receipt.id}' in warnings[0].getMessage()

        row = AuditLog.query.filter_by(action='receipt_create').one()
        assert row.changes['gl_posted'] is False
        assert 'gl engine down' in row.changes['gl_warning']

    def test_cheque_receipt_linked_via_receive_entry(self, db, owner_user, test_customer):
        receipt = PaymentService.create_receipt({
            'customer_id': test_customer.id,
            'amount': Decimal('300'),
            'currency': 'AED',
            'payment_method': 'cheque',
            'cheque_number': 'CH-LINK-9',
            'cheque_date': '2026-10-15',
            'bank_name': 'ADCB',
        })
        cheque = db.session.get(Cheque, receipt.cheque_id)

        entry = GLJournalEntry.query.filter_by(
            reference_type='cheque_receive', reference_id=cheque.id,
        ).one()
        assert entry.total_debit == entry.total_credit


class TestAdvancedAuditSerialization:
    def test_decimal_datetime_payloads_survive_json_round_trip(self, app, db):
        with app.test_request_context('/', environ_base={'REMOTE_ADDR': '5.6.7.8'},
                                      headers={'User-Agent': 'UA-Ser'}):
            log_sensitive_action('update', table_name='sales', record_id=9, changes={
                'price': Decimal('12.500'),
                'due_at': datetime(2026, 1, 2, 3, 4, 5),
                'tags': ['a', Decimal('0.99')],
                'rates': {'usd': Decimal('3.67')},
            })

        row = AuditLog.query.one()
        expected = {
            'price': '12.500',
            'due_at': '2026-01-02T03:04:05',
            'tags': ['a', '0.99'],
            'rates': {'usd': '3.67'},
        }
        assert row.changes == expected
        assert json.loads(json.dumps(row.changes)) == expected

    def test_unserializable_payload_still_dropped_not_corrupted(self, app, db):
        with app.test_request_context('/'):
            log_sensitive_action('broken', changes={'obj': object()})
        assert AuditLog.query.count() == 0

    def test_log_sensitive_action_works_without_request_context(self, app, db):
        log_sensitive_action('login', table_name='users')

        row = AuditLog.query.one()
        assert row.ip_address is None
        assert row.user_agent is None

    def test_get_security_events_filters_table_actions_limit(self, app, db):
        from datetime import timedelta, timezone

        now = datetime.now(timezone.utc)
        db.session.add(AuditLog(action='export', table_name='reports', created_at=now))
        db.session.add(AuditLog(action='delete', table_name='customers',
                                created_at=now - timedelta(minutes=1)))
        db.session.add(AuditLog(action='delete', table_name='reports',
                                created_at=now - timedelta(minutes=2)))
        db.session.commit()

        exports = get_security_events(actions=['export'])
        assert [e.table_name for e in exports] == ['reports']

        report_deletes = get_security_events(actions=['delete'], table_name='reports')
        assert len(report_deletes) == 1
        assert report_deletes[0].table_name == 'reports'

        limited = get_security_events(actions=['delete'], limit=1)
        assert len(limited) == 1

        defaults = get_security_events()
        assert all(e.action in ('login', 'logout', 'delete', 'update') for e in defaults)
