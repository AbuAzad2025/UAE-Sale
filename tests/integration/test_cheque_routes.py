"""HTTP integration tests for cheque routes — /cheques/* flows."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from extensions import db
from models import Cheque


def _form(cheque_type='incoming', customer_id=None, **over):
    today = date.today()
    data = {
        'cheque_type': cheque_type,
        'cheque_bank_number': '777888',
        'bank_name': 'ENBD',
        'amount': '1500',
        'currency': 'AED',
        'issue_date': (today - timedelta(days=5)).isoformat(),
        'due_date': (today + timedelta(days=25)).isoformat(),
        'drawer_name': 'ساحب',
        'payee_name': '',
    }
    if customer_id:
        data['customer_id'] = str(customer_id)
    data.update(over)
    return data


@pytest.fixture
def pending_cheque(db, test_customer):
    ch = Cheque(
        cheque_number='CHQ-HTTP-1', cheque_bank_number='555000',
        cheque_type='incoming', bank_name='ADCB',
        amount=Decimal('800'), currency='AED', exchange_rate=Decimal('1'),
        amount_base=Decimal('800'),
        issue_date=date.today() - timedelta(days=3),
        due_date=date.today() + timedelta(days=30),
        status='pending', customer_id=test_customer.id,
    )
    db.session.add(ch)
    db.session.commit()
    return ch


class TestListPages:
    def test_index_incoming_outgoing(self, client, login_owner, db):
        for url in ('/cheques/', '/cheques/incoming', '/cheques/outgoing'):
            resp = client.get(url)
            assert resp.status_code == 200

    def test_alerts_archived_stats(self, client, login_owner):
        assert client.get('/cheques/alerts').status_code == 200
        assert client.get('/cheques/archived').status_code == 200
        resp = client.get('/cheques/api/stats')
        assert resp.status_code == 200
        assert resp.is_json

    def test_requires_login(self, client):
        resp = client.get('/cheques/', follow_redirects=False)
        assert resp.status_code == 302


class TestCreate:
    def test_get_renders_form(self, client, login_owner):
        assert client.get('/cheques/create').status_code == 200

    def test_post_creates_and_redirects(self, client, login_owner, test_customer):
        resp = client.post('/cheques/create', data=_form(customer_id=test_customer.id),
                           follow_redirects=True)
        assert resp.status_code == 200
        ch = Cheque.query.filter_by(cheque_bank_number='777888').first()
        assert ch is not None
        assert ch.amount_base == Decimal('1500.00')
        assert ch.cheque_number.startswith('CHQ')

    def test_post_missing_type_rerenders(self, client, login_owner):
        resp = client.post('/cheques/create', data=_form(cheque_type=''))
        assert resp.status_code == 200

    def test_post_bad_amount_shows_error(self, client, login_owner, test_customer):
        client.post('/cheques/create',
                    data=_form(customer_id=test_customer.id, amount='not-a-number'),
                    follow_redirects=True)
        assert Cheque.query.filter_by(cheque_bank_number='777888').count() == 0


class TestViewEdit:
    def test_view_updates_status(self, client, login_owner, pending_cheque):
        resp = client.get(f'/cheques/{pending_cheque.id}')
        assert resp.status_code == 200

    def test_view_404(self, client, login_owner):
        assert client.get('/cheques/999999').status_code == 404

    def test_edit_blocked_when_cleared(self, client, login_owner, pending_cheque):
        pending_cheque.status = 'cleared'
        db.session.commit()
        resp = client.get(f'/cheques/{pending_cheque.id}/edit', follow_redirects=False)
        assert resp.status_code == 302

    def test_edit_allows_pending(self, client, login_owner, pending_cheque):
        assert client.get(f'/cheques/{pending_cheque.id}/edit').status_code == 200


class TestLifecycleActions:
    def test_deposit_action(self, client, login_owner, pending_cheque):
        resp = client.post(f'/cheques/{pending_cheque.id}/deposit', follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(pending_cheque)
        assert pending_cheque.status == 'deposited'
        assert pending_cheque.deposit_date is not None

    def test_clear_action(self, client, login_owner, pending_cheque):
        client.post(f'/cheques/{pending_cheque.id}/deposit')
        resp = client.post(f'/cheques/{pending_cheque.id}/clear',
                           data={'clearance_exchange_rate': '1'}, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(pending_cheque)
        assert pending_cheque.status == 'cleared'

    def test_bounce_action(self, client, login_owner, pending_cheque):
        resp = client.post(f'/cheques/{pending_cheque.id}/bounce',
                           data={'bounce_reason': 'لا رصيد'}, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(pending_cheque)
        assert pending_cheque.status == 'bounced'

    def test_cancel_action(self, client, login_owner, pending_cheque):
        resp = client.post(f'/cheques/{pending_cheque.id}/cancel',
                           data={'cancel_reason': 'خطأ إدخال'}, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(pending_cheque)
        assert pending_cheque.status == 'cancelled'


class TestDeleteRestore:
    def test_hard_delete_unlinked_pending(self, client, login_owner, pending_cheque):
        cid = pending_cheque.id
        resp = client.post(f'/cheques/{cid}/delete', follow_redirects=True)
        assert resp.status_code == 200
        assert db.session.get(Cheque, cid) is None

    def test_soft_archive_linked_cheque(self, client, login_owner, pending_cheque, test_sale):
        pending_cheque.sale_id = test_sale.id
        db.session.commit()
        cid = pending_cheque.id
        client.post(f'/cheques/{cid}/delete', data={'delete_reason': 'مرتبط'},
                    follow_redirects=True)
        db.session.refresh(pending_cheque)
        assert pending_cheque.is_active is False
        assert pending_cheque.archive_reason == 'مرتبط'

    def test_restore_archived(self, client, login_owner, pending_cheque):
        pending_cheque.archive('سبب')
        db.session.commit()
        resp = client.post(f'/cheques/{pending_cheque.id}/restore', follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(pending_cheque)
        assert pending_cheque.is_active is True
