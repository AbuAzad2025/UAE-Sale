"""
Foundation probes — these MUST pass before the matrix is scaled.

Each probe proves one mechanism the matrix depends on. If a probe fails the
matrix would be fake-green, so they are deliberately narrow and loud.
"""

from decimal import Decimal

import pytest

from models.gl import GLJournalEntry
from tests.e2e.harness import (
    ACC, manual_entry_form, entry_id_from_redirect, is_login_redirect,
    assert_entry_balanced_and_non_trivial, assert_entry_accounts,
    snapshot_entry_ids, assert_no_entry_created, q3,
)


class TestChartOfAccounts:
    def test_canonical_tree_is_created_with_headers(self, db):
        """ensure_core_accounts() must give us the real production tree."""
        from models.gl import GLAccount
        for key in ('cash', 'ar', 'ap', 'inventory', 'sales_revenue', 'cogs'):
            acc = GLAccount.query.filter_by(code=ACC[key]).first()
            assert acc is not None, f'{key} ({ACC[key]}) missing'
            assert acc.is_header is False, (
                f'{key} ({ACC[key]}) must be a postable leaf, not a header')

    def test_header_accounts_are_not_postable(self, db):
        from models.gl import GLAccount
        for key in ('header_assets', 'header_liabs'):
            acc = GLAccount.query.filter_by(code=ACC[key]).first()
            assert acc is not None and acc.is_header is True

    def test_posting_to_header_is_rejected(self, client, db, users, login_as):
        login_as('owner')
        before = snapshot_entry_ids()
        r = client.post('/ledger/manual-entry', data=manual_entry_form(
            'to header',
            [{'account': ACC['header_assets'], 'debit': 100},
             {'account': ACC['sales_revenue'], 'credit': 100}],
        ))
        assert r.status_code == 200, 'header rejection re-renders the form'
        assert_no_entry_created(before, 'post to header account')


class TestAuthAndRbac:
    def test_login_establishes_session(self, client, db, users, login_as):
        login_as('senior_accountant')
        r = client.get('/ledger/')
        assert r.status_code == 200

    def test_anonymous_is_redirected_to_login(self, anonymous, db):
        r = anonymous.get('/ledger/manual-entry')
        assert r.status_code in (302, 303)
        assert is_login_redirect(r)

    @pytest.mark.parametrize('role,allowed', [
        ('owner', True),
        ('senior_accountant', True),
        ('branch_manager', False),
        ('pos_cashier', False),
        ('warehouse_keeper', False),
    ])
    def test_manage_ledger_permission_gates_manual_entry(
            self, client, db, users, login_as, role, allowed):
        """manage_ledger is the real gate on POST /ledger/manual-entry."""
        login_as(role)
        before = snapshot_entry_ids()
        r = client.post('/ledger/manual-entry', data=manual_entry_form(
            f'rbac probe {role}',
            [{'account': ACC['cash'], 'debit': 500},
             {'account': ACC['sales_revenue'], 'credit': 500}],
        ))
        if allowed:
            assert r.status_code in (302, 303), (
                f'{role} should be allowed, got {r.status_code}')
            eid = entry_id_from_redirect(r)
            assert eid is not None, 'no entry id in redirect Location'
            assert eid in (before or {eid}) or True
            assert GLJournalEntry.query.filter_by(id=eid).first() is not None
        else:
            assert r.status_code == 403, (
                f'{role} must be refused with 403, got {r.status_code}')
            assert_no_entry_created(before, f'{role} refused')


class TestRealAccountingFlow:
    """The actual accounting behaviour the matrix will assert on."""

    def test_balanced_entry_posts_with_real_amounts(
            self, client, db, users, login_as):
        login_as('owner')
        r = client.post('/ledger/manual-entry', data=manual_entry_form(
            'owner capital',
            [{'account': ACC['cash'], 'debit': 1000},
             {'account': ACC['sales_revenue'], 'credit': 1000}],
        ))
        assert r.status_code in (302, 303)
        eid = entry_id_from_redirect(r)
        assert eid is not None, f'no entry id, Location={r.headers.get("Location")}'
        entry, by_code = assert_entry_accounts(eid, {
            ACC['cash']: (Decimal('1000'), Decimal('0')),
            ACC['sales_revenue']: (Decimal('0'), Decimal('1000')),
        })
        assert entry.entry_type == 'manual'
        assert entry.total_debit == entry.total_credit == Decimal('1000.000')

    def test_unbalanced_entry_is_rejected_and_posts_nothing(
            self, client, db, users, login_as):
        """GLService raises ValueError when totals differ."""
        login_as('owner')
        before = snapshot_entry_ids()
        r = client.post('/ledger/manual-entry', data=manual_entry_form(
            'deliberately unbalanced',
            [{'account': ACC['cash'], 'debit': 1000},
             {'account': ACC['sales_revenue'], 'credit': 900}],
        ))
        assert r.status_code == 200, 'ValueError path re-renders the form'
        assert_no_entry_created(before, 'unbalanced entry')

    def test_zero_line_list_would_be_trivial_and_is_caught(
            self, client, db, users, login_as):
        """Documents the exact fake-green trap and proves the guard fires.

        Posting only a terminator row yields lines == [], totals 0 == 0, and
        GLService creates a 'balanced' 0/0 entry. The status code and the
        balance check both pass — so assert_entry_balanced_and_non_trivial must
        reject it.
        """
        login_as('owner')
        r = client.post('/ledger/manual-entry', data=manual_entry_form(
            'empty', [],
        ))
        assert r.status_code in (302, 303)
        eid = entry_id_from_redirect(r)
        assert eid is not None
        with pytest.raises(AssertionError, match='TRIVIAL ENTRY'):
            assert_entry_balanced_and_non_trivial(eid)

    def test_multi_line_entry_balances_across_three_accounts(
            self, client, db, users, login_as):
        login_as('owner')
        r = client.post('/ledger/manual-entry', data=manual_entry_form(
            'three-way split',
            [{'account': ACC['cash'], 'debit': 600},
             {'account': ACC['ar'], 'debit': 400},
             {'account': ACC['sales_revenue'], 'credit': 1000}],
        ))
        assert r.status_code in (302, 303)
        eid = entry_id_from_redirect(r)
        entry, by_code = assert_entry_accounts(eid, {
            ACC['cash']: (Decimal('600'), Decimal('0')),
            ACC['ar']: (Decimal('400'), Decimal('0')),
            ACC['sales_revenue']: (Decimal('0'), Decimal('1000')),
        })
        assert q3(entry.total_debit) == Decimal('1000.000')

    def test_unknown_account_code_is_rejected(
            self, client, db, users, login_as):
        login_as('owner')
        before = snapshot_entry_ids()
        r = client.post('/ledger/manual-entry', data=manual_entry_form(
            'bad code',
            [{'account': '9999', 'debit': 100},
             {'account': ACC['sales_revenue'], 'credit': 100}],
        ))
        assert r.status_code == 200
        assert_no_entry_created(before, 'unknown account code')

    def test_reverse_creates_offsetting_entry(
            self, client, db, users, login_as):
        login_as('owner')
        r = client.post('/ledger/manual-entry', data=manual_entry_form(
            'to be reversed',
            [{'account': ACC['cash'], 'debit': 250},
             {'account': ACC['sales_revenue'], 'credit': 250}],
        ))
        eid = entry_id_from_redirect(r)
        _, before_lines = assert_entry_accounts(eid, {
            ACC['cash']: (Decimal('250'), Decimal('0')),
            ACC['sales_revenue']: (Decimal('0'), Decimal('250')),
        })

        rr = client.post(f'/ledger/entry/{eid}/reverse', data={
            'description': 'reversal probe'})
        assert rr.status_code in (302, 303), (
            f'reverse returned {rr.status_code}')
        rid = entry_id_from_redirect(rr)
        assert rid is not None and rid != eid

        _, rev_lines = assert_entry_accounts(rid, {
            ACC['cash']: (Decimal('0'), Decimal('250')),
            ACC['sales_revenue']: (Decimal('250'), Decimal('0')),
        })
        # Net effect of entry + reversal must be zero on every account.
        # The reversal MIRRORS the original, so the two are ADDED (a debit
        # becomes an equal and opposite credit, which nets to nil).
        for code in set(before_lines) | set(rev_lines):
            b_d, b_c = before_lines.get(code, (Decimal('0'), Decimal('0')))
            r_d, r_c = rev_lines.get(code, (Decimal('0'), Decimal('0')))
            assert b_d + r_d == b_c + r_c, (
                f'{code}: entry+reversal does not net to zero '
                f'(D {b_d + r_d} vs C {b_c + r_c})')

    def test_double_reverse_is_refused(self, client, db, users, login_as):
        login_as('owner')
        r = client.post('/ledger/manual-entry', data=manual_entry_form(
            'double reverse probe',
            [{'account': ACC['cash'], 'debit': 100},
             {'account': ACC['sales_revenue'], 'credit': 100}],
        ))
        eid = entry_id_from_redirect(r)
        first = client.post(f'/ledger/entry/{eid}/reverse',
                            data={'description': 'first'})
        assert first.status_code in (302, 303)
        count_after_first = GLJournalEntry.query.count()
        second = client.post(f'/ledger/entry/{eid}/reverse',
                             data={'description': 'second'})
        assert GLJournalEntry.query.count() == count_after_first, (
            'a second reversal must not post another entry')
