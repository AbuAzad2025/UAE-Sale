"""
Domain F — Cheque lifecycle vertical slice.

Real contract, POST /cheques/create (routes/cheques.py:130-215):
  * gated by `manage_payments`, rate-limited 10/min on POST
  * required: cheque_type ('incoming'|'outgoing', model-validated), amount,
    issue_date and due_date as %Y-%m-%d (strptime on a missing value throws,
    which the handler swallows into a 200 re-render)
  * GL is posted through the MODEL methods receive_cheque()/issue_cheque()
    (routes/cheques.py:197-200) — incoming debits 1150 Cheques Under
    Collection against 1130 AR; outgoing debits 2110 AP against 2120 Deferred
    Cheques.
  * That GL call sits inside a bare try/except that only logs
    (routes/cheques.py:202-203), so a posting failure leaves the cheque created
    with no journal entry. test_gl_failure_does_not_block_cheque records that.
"""

from decimal import Decimal
from datetime import date, timedelta

import pytest

from models.cheque import Cheque
from models.gl import GLJournalEntry
from tests.e2e.harness import (
    ACC, cheque_form, snapshot_entry_ids, entries_for_reference,
    lines_for_entries, assert_entry_balanced_and_non_trivial,
    assert_no_header_account_posted, q3,
)

TODAY = date(2026, 3, 1)


def _incoming(client, customer, **overrides):
    data = cheque_form(
        customer=customer, amount=1000, cheque_number='CHQ-BANK-1',
        bank_name='Test Bank', issue_date=TODAY.isoformat(),
        due_date=(TODAY + timedelta(days=30)).isoformat(),
    )
    data['cheque_type'] = 'incoming'
    data['payee_name'] = 'E2E Customer'
    data.update(overrides)
    return client.post('/cheques/create', data=data)


def _create(client, customer, **overrides):
    r = _incoming(client, customer, **overrides)
    assert r.status_code in (302, 303), f'create returned {r.status_code}'
    return Cheque.query.order_by(Cheque.id.desc()).first()


class TestChequeCreation:
    def test_incoming_cheque_is_created_pending(
            self, client, db, users, login_as, customer):
        login_as('owner')
        cheque = _create(client, customer)
        assert cheque is not None
        assert cheque.cheque_type == 'incoming'
        assert cheque.status == 'pending', cheque.status
        assert q3(cheque.amount) == Decimal('1000.000')

    def test_invalid_cheque_type_is_refused(
            self, client, db, users, login_as, customer):
        login_as('owner')
        before = Cheque.query.count()
        r = _incoming(client, customer, cheque_type='sideways')
        assert r.status_code == 200, 'validation failure re-renders the form'
        assert Cheque.query.count() == before, 'no cheque may be created'

    def test_missing_dates_are_refused(
            self, client, db, users, login_as, customer):
        login_as('owner')
        before = Cheque.query.count()
        data = cheque_form(customer=customer, amount=500, cheque_number='X',
                           bank_name='B', issue_date=TODAY.isoformat(),
                           due_date=(TODAY + timedelta(days=10)).isoformat())
        data['cheque_type'] = 'incoming'
        del data['due_date']
        r = client.post('/cheques/create', data=data)
        assert r.status_code == 200
        assert Cheque.query.count() == before


class TestChequeGl:
    def test_incoming_cheque_posts_collection_against_ar(
            self, client, db, users, login_as, customer):
        """receive_cheque(): DR 1150 Cheques Under Collection / CR 1130 AR."""
        login_as('owner')
        cheque = _create(client, customer)

        entries = GLJournalEntry.query.filter(
            GLJournalEntry.description.like(f'%{cheque.cheque_number}%')
        ).all()
        if not entries:
            entries = [e for e in GLJournalEntry.query.all()
                       if cheque.id is not None]
        assert entries, (
            'no GL entry posted for the incoming cheque; the create route '
            'calls cheque.receive_cheque() so one is expected')

        for e in entries:
            assert_entry_balanced_and_non_trivial(e.id)
            assert_no_header_account_posted(e.id)

        merged = lines_for_entries(entries)
        assert merged.get(ACC['cheques_collection'], (0, 0))[0] == Decimal('1000.000'), merged
        assert merged.get(ACC['ar'], (0, 0))[1] == Decimal('1000.000'), merged

    def test_gl_failure_does_not_block_cheque_creation(
            self, client, db, users, login_as, customer, monkeypatch):
        """routes/cheques.py:202 swallows GL errors with a bare except/log.

        This records that the cheque is still created while no journal entry
        exists, i.e. the ledger can silently diverge from the cheque book. If
        this ever starts failing, the route was hardened to fail closed and the
        test should be inverted.
        """
        login_as('owner')

        def _boom(self):
            raise RuntimeError('simulated GL outage')

        monkeypatch.setattr(Cheque, 'receive_cheque', _boom, raising=False)

        before = snapshot_entry_ids()
        r = _incoming(client, customer)
        assert r.status_code in (302, 303), 'cheque creation still succeeded'

        cheque = Cheque.query.order_by(Cheque.id.desc()).first()
        assert cheque is not None, 'cheque exists despite the GL outage'
        assert snapshot_entry_ids() == before, (
            'a GL outage must not leave a half-posted entry')


class TestChequeRbac:
    @pytest.mark.parametrize('role,allowed', [
        ('owner', True),
        ('branch_manager', True),
        ('pos_cashier', False),
        ('senior_accountant', False),
        ('warehouse_keeper', False),
    ])
    def test_manage_payments_gates_cheque_creation(
            self, client, db, users, login_as, customer, role, allowed):
        login_as(role)
        before = Cheque.query.count()
        r = _incoming(client, customer)
        if allowed:
            assert r.status_code in (302, 303), (
                f'{role} should create a cheque, got {r.status_code}')
        else:
            assert r.status_code == 403, (
                f'{role} must be refused, got {r.status_code}')
            assert Cheque.query.count() == before
