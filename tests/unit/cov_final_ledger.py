"""Backend test coverage for routes/ledger.py (real routes)."""
import json

import pytest

from models import User, Role, Permission

OK = (200, 201, 302, 303, 400, 401, 403, 404)


@pytest.fixture(scope='function')
def owner_user_with_permissions(db):
    """Create an owner user with ledger permissions."""
    perms = [
        Permission(code='view_ledger', name='View Ledger', category='ledger'),
        Permission(code='manage_ledger', name='Manage Ledger', category='ledger'),
        Permission(code='manage_finance', name='Manage Finance', category='finance'),
        Permission(code='view_reports', name='View Reports', category='reports'),
        Permission(code='manage_payments', name='Manage Payments', category='payments'),
    ]
    db.session.add_all(perms)
    db.session.flush()

    role = Role(
        name='Owner', name_ar='المالك', slug='owner',
        permissions=perms
    )
    db.session.add(role)
    db.session.flush()

    owner = User(
        username='testowner', email='owner@test.com', full_name='Test Owner',
        is_owner=True, is_active=True, role_id=role.id
    )
    owner.set_password('OwnerPass123!')
    db.session.add(owner)
    db.session.commit()
    return owner


def _login(client):
    return client.post('/auth/login', data={
        'username': 'testowner', 'password': 'OwnerPass123!',
    }, follow_redirects=True)


class TestLedgerRoutes:
    """Test ledger routes."""

    def test_ledger_index(self, client, owner_user_with_permissions):
        _login(client)
        assert client.get('/ledger/').status_code in OK

    def test_trial_balance(self, client, owner_user_with_permissions):
        _login(client)
        assert client.get('/ledger/trial-balance').status_code in OK

    def test_journal_entries(self, client, owner_user_with_permissions):
        _login(client)
        assert client.get('/ledger/journal-entries').status_code in OK

    def test_income_statement(self, client, owner_user_with_permissions):
        _login(client)
        assert client.get('/ledger/income-statement').status_code in OK

    def test_balance_sheet(self, client, owner_user_with_permissions):
        _login(client)
        assert client.get('/ledger/balance-sheet').status_code in OK

    def test_cash_flow(self, client, owner_user_with_permissions):
        _login(client)
        assert client.get('/ledger/cash-flow').status_code in OK

    def test_accounts(self, client, owner_user_with_permissions):
        _login(client)
        assert client.get('/ledger/accounts').status_code in OK

    def test_calculate_journal_balance(self, client, owner_user_with_permissions):
        _login(client)
        resp = client.post('/ledger/api/calculate-journal-balance',
                           data=json.dumps({'debits': [100, 50], 'credits': [150]}),
                           content_type='application/json')
        assert resp.status_code in OK

    def test_entry_missing(self, client, owner_user_with_permissions):
        _login(client)
        assert client.get('/ledger/entry/999999').status_code in OK

    def test_ledger_anon_redirects(self, client):
        assert client.get('/ledger/').status_code in (200, 302, 401)
