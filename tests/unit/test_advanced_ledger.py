"""Tests for routes/advanced_ledger.py â€” ledger-adjacent admin pages.

advanced_ledger.py sat at ~43% combined coverage. Covers read pages for
ledger-authorized roles, admin gating, and safe failure of entry
mutations against missing rows.
"""
import pytest

from models import User, Role, Permission
from extensions import db as _db


def _make_user(username, slug, perm_codes=(), is_owner=False):
    role = Role(name=username.title(), name_ar=username, slug=slug)
    _db.session.add(role)
    _db.session.flush()
    perms = []
    for code in perm_codes:
        p = Permission.query.filter_by(code=code).first()
        if p is None:
            p = Permission(code=code, name=code, name_ar=code, category='test')
            _db.session.add(p)
            _db.session.flush()
        perms.append(p)
    role.permissions = perms
    user = User(username=username, email=f'{username}@test.com',
                full_name=username, is_owner=is_owner, is_active=True,
                role_id=role.id)
    user.set_password('Pass123!')
    _db.session.add(user)
    _db.session.commit()
    return user


@pytest.fixture(scope='function')
def ledger_owner(db):
    return _make_user('al_owner', 'al_owner_role', is_owner=True)


@pytest.fixture(scope='function')
def ledger_accountant(db):
    return _make_user('al_acct', 'al_acct_role',
                      perm_codes=['view_ledger', 'manage_ledger'])


@pytest.fixture(scope='function')
def ledger_seller(db):
    return _make_user('al_seller', 'al_seller_role',
                      perm_codes=['manage_sales'])


def _login(client, user):
    client.post('/auth/login', data={
        'username': user.username, 'password': 'Pass123!',
    }, follow_redirects=True)


READ_PAGES_OWNER = [
    '/ledger/advanced/professional-printing',
    '/ledger/advanced/customs-taxes',
    '/ledger/advanced/customs-taxes/add',
    '/ledger/advanced/expense-categories',
    '/ledger/advanced/expense-categories/add',
    '/ledger/advanced/advanced-expenses',
    '/ledger/advanced/advanced-expenses/add',
    '/ledger/advanced/journal-management',
    '/ledger/advanced/cheque-integration',
]

READ_PAGES_LEDGER_ROLE = [
    '/ledger/advanced/professional-printing',
    '/ledger/advanced/advanced-expenses',
    '/ledger/advanced/cheque-integration',
]


class TestAdvancedLedgerReads:
    @pytest.mark.parametrize('url', READ_PAGES_OWNER)
    def test_owner_ok(self, client, ledger_owner, url):
        _login(client, ledger_owner)
        assert client.get(url).status_code == 200

    @pytest.mark.parametrize('url', READ_PAGES_LEDGER_ROLE)
    def test_accountant_ok(self, client, ledger_accountant, url):
        _login(client, ledger_accountant)
        assert client.get(url).status_code == 200

    @pytest.mark.parametrize('url', [
        '/ledger/advanced/customs-taxes',
        '/ledger/advanced/journal-management',
        '/ledger/advanced/expense-categories',
    ])
    def test_seller_forbidden(self, client, ledger_seller, url):
        _login(client, ledger_seller)
        assert client.get(url).status_code == 403


class TestJournalEntryMutations:
    @pytest.mark.parametrize('action', ['reverse', 'delete', 'approve'])
    def test_missing_entry_redirects_safely(self, client, ledger_owner, action):
        _login(client, ledger_owner)
        resp = client.post(
            f'/ledger/advanced/journal-management/999999/{action}')
        assert resp.status_code == 302

    @pytest.mark.parametrize('action', ['reverse', 'delete', 'approve'])
    def test_non_admin_forbidden(self, client, ledger_accountant, action):
        # accountant has ledger perms but is not admin (owner/super_admin)
        _login(client, ledger_accountant)
        resp = client.post(
            f'/ledger/advanced/journal-management/999999/{action}')
        assert resp.status_code == 403

    def test_reverse_real_entry(self, client, ledger_owner, db):
        from models import GLJournalEntry
        entry = GLJournalEntry(entry_number='JE-AL-1')
        _db.session.add(entry)
        _db.session.commit()
        _login(client, ledger_owner)
        resp = client.post(
            f'/ledger/advanced/journal-management/{entry.id}/reverse',
            data={'reason': 'test reversal'})
        # Either path must redirect (never 500): success flashes, missing
        # prerequisites flash an error â€” both are safe outcomes.
        assert resp.status_code == 302
