"""
E2E tests for Expenses module - comprehensive coverage of all routes.
Tests cover: list, create, view, edit, print, archive, restore, delete, categories.

Route contract (routes/expenses.py):
  GET/POST /expenses/create          (login + manage_expenses)
  GET     /expenses/<id>             (login + manage_expenses)
  GET     /expenses/<id>/print       (login + manage_expenses)
  GET/POST /expenses/<id>/edit       (login + manage_expenses)
  POST    /expenses/<id>/delete      (login + manage_expenses) hard-delete or archive
  GET     /expenses/categories       (login + manage_expenses)
  POST    /expenses/categories/create(login + manage_expenses)
  GET     /expenses/archived         (login + manage_expenses)
  POST    /expenses/<id>/archive     (login + manage_expenses) -> ArchivedRecord
  POST    /expenses/<id>/restore     (login + manage_expenses) -> remove ArchivedRecord
"""

from decimal import Decimal

import pytest

from extensions import db
from models.expense import Expense, ExpenseCategory
from models import ArchivedRecord


def expense_form_dict(category, amount=100, description='Test expense',
                      payment_method='cash', reference_number='REF001', notes='Test notes'):
    """POST body for POST /expenses/create."""
    return {
        'category_id': str(category.id),
        'amount': str(amount),
        'description': description,
        'payment_method': payment_method,
        'reference_number': reference_number,
        'notes': notes,
    }


class TestExpensesListAndView:
    def test_expenses_list_renders(self, client, login_as):
        login_as('owner')
        r = client.get('/expenses/')
        assert r.status_code == 200

    def test_expenses_archived_renders(self, client, login_as):
        login_as('owner')
        r = client.get('/expenses/archived')
        assert r.status_code == 200

    def test_expense_view_requires_login(self, client, expense):
        r = client.get(f'/expenses/{expense.id}')
        assert r.status_code == 302
        assert '/auth/login' in r.headers.get('Location', '')

    def test_expense_view_by_owner(self, client, login_as, expense):
        login_as('owner')
        r = client.get(f'/expenses/{expense.id}')
        assert r.status_code == 200

    def test_expense_categories_list(self, client, login_as):
        login_as('owner')
        r = client.get('/expenses/categories')
        assert r.status_code == 200


class TestExpensesCreate:
    def test_create_expense_basic(self, client, login_as, expense_category):
        login_as('owner')
        r = client.post('/expenses/create', data=expense_form_dict(expense_category))
        assert r.status_code in (302, 303)
        eid = r.headers.get('Location', '').split('/')[-1]
        assert eid.isdigit()
        exp = Expense.query.get(int(eid))
        assert exp is not None
        assert exp.amount == Decimal('100.000')
        assert exp.description == 'Test expense'

    @pytest.mark.parametrize('method', ['cash', 'card', 'bank_transfer', 'e_wallet'])
    def test_create_expense_with_payment_methods(self, client, login_as, expense_category, method):
        login_as('owner')
        r = client.post('/expenses/create', data=expense_form_dict(
            expense_category, amount=50, payment_method=method,
            reference_number=f'REF-{method}'
        ))
        assert r.status_code in (302, 303), f'Failed for {method}'

    def test_create_expense_with_cheque(self, client, login_as, expense_category):
        login_as('owner')
        r = client.post('/expenses/create', data={
            'category_id': str(expense_category.id),
            'amount': '75',
            'description': 'Cheque expense',
            'payment_method': 'cheque',
            'cheque_number': 'CHQ123',
            'cheque_date': '2026-02-01',
            'bank_name': 'Test Bank',
        })
        assert r.status_code in (302, 303)
        eid = r.headers.get('Location', '').split('/')[-1]
        assert eid.isdigit()
        exp = Expense.query.get(int(eid))
        assert exp.payment_method == 'cheque'
        assert exp.cheque_number == 'CHQ123'

    def test_create_expense_zero_amount_rejected(self, client, login_as, expense_category):
        login_as('owner')
        r = client.post('/expenses/create', data=expense_form_dict(
            expense_category, amount='0'
        ))
        assert r.status_code == 302
        assert Expense.query.count() == 0

    def test_create_expense_negative_amount_rejected(self, client, login_as, expense_category):
        login_as('owner')
        r = client.post('/expenses/create', data=expense_form_dict(
            expense_category, amount='-10'
        ))
        assert r.status_code == 302
        assert Expense.query.count() == 0

    def test_create_expense_requires_login(self, client, expense_category):
        r = client.post('/expenses/create', data=expense_form_dict(expense_category))
        assert r.status_code == 302
        assert '/auth/login' in r.headers.get('Location', '')


class TestExpensesEdit:
    def test_edit_expense_updates_fields(self, client, login_as, expense, expense_category):
        login_as('owner')
        r = client.post(f'/expenses/{expense.id}/edit', data={
            'category_id': str(expense_category.id),
            'amount': '200',
            'description': 'Updated expense',
            'notes': 'Updated notes',
            'payment_method': 'card',
        })
        assert r.status_code in (302, 303)
        exp = Expense.query.get(expense.id)
        assert exp.amount == Decimal('200.000')
        assert exp.description == 'Updated expense'
        assert exp.notes == 'Updated notes'
        assert exp.payment_method == 'card'

    def test_edit_expense_not_found(self, client, login_as):
        login_as('owner')
        r = client.post('/expenses/99999/edit', data={
            'category_id': '1',
            'amount': '100',
            'description': 'Test',
            'payment_method': 'cash',
        })
        assert r.status_code == 404


class TestExpensesPrint:
    def test_print_expense_renders(self, client, login_as, expense):
        login_as('owner')
        r = client.get(f'/expenses/{expense.id}/print')
        assert r.status_code == 200

    def test_print_expense_forbidden_for_others(self, client, login_as, expense):
        login_as('viewer')
        r = client.get(f'/expenses/{expense.id}/print')
        assert r.status_code == 403


class TestExpensesArchive:
    def test_archive_expense_creates_record(self, client, login_as, expense):
        login_as('owner')
        before = ArchivedRecord.query.filter_by(
            table_name='expenses', record_id=expense.id).count()
        r = client.post(f'/expenses/{expense.id}/archive')
        assert r.status_code in (302, 303)
        after = ArchivedRecord.query.filter_by(
            table_name='expenses', record_id=expense.id).count()
        assert after == before + 1

    def test_archive_moves_to_archived_list(self, client, login_as, expense):
        login_as('owner')
        client.post(f'/expenses/{expense.id}/archive')
        r = client.get('/expenses/archived')
        assert r.status_code == 200
        assert expense.expense_number in r.get_data(as_text=True)

    def test_restore_archived_expense(self, client, login_as, expense):
        login_as('owner')
        client.post(f'/expenses/{expense.id}/archive')
        assert ArchivedRecord.query.filter_by(
            table_name='expenses', record_id=expense.id).count() == 1
        r = client.post(f'/expenses/{expense.id}/restore')
        assert r.status_code in (302, 303)
        assert ArchivedRecord.query.filter_by(
            table_name='expenses', record_id=expense.id).count() == 0


class TestExpensesDelete:
    def test_delete_expense_without_links(self, client, login_as, expense):
        login_as('owner')
        exp_id = expense.id
        r = client.post(f'/expenses/{exp_id}/delete')
        assert r.status_code in (302, 303)
        assert Expense.query.get(exp_id) is None

    def test_delete_expense_requires_login(self, client, expense):
        exp_id = expense.id
        r = client.post(f'/expenses/{exp_id}/delete')
        assert r.status_code == 302
        assert '/auth/login' in r.headers.get('Location', '')


class TestExpensesCategories:
    def test_create_category(self, client, login_as):
        login_as('owner')
        r = client.post('/expenses/categories/create', data={
            'name': 'New E2E Category',
            'name_ar': 'فئة جديدة',
        })
        assert r.status_code in (302, 303)
        cat = ExpenseCategory.query.filter_by(name='New E2E Category').first()
        assert cat is not None

    def test_create_category_duplicate_rejected(self, client, login_as, expense_category):
        login_as('owner')
        r = client.post('/expenses/categories/create', data={
            'name': expense_category.name,
        })
        # duplicate raises ValueError -> caught, redirect with flash
        assert r.status_code in (302, 303)
        assert ExpenseCategory.query.filter_by(name=expense_category.name).count() == 1


class TestExpensesRbac:
    @pytest.mark.parametrize('role,allowed', [
        ('owner', True),
        ('manager', True),
        ('accountant', True),
        ('branch_manager', False),
        ('senior_accountant', False),
        ('pos_cashier', False),
        ('warehouse_keeper', False),
        ('viewer', False),
        ('hr', False),
    ])
    def test_manage_expenses_gates_expense_creation(
            self, client, login_as, role, allowed, expense_category):
        login_as(role)
        r = client.post('/expenses/create', data=expense_form_dict(expense_category))
        if allowed:
            assert r.status_code in (302, 303)
        else:
            assert r.status_code == 403


# Fixtures for this test module
@pytest.fixture
def expense_category(db, e2e_tenant):
    cat = ExpenseCategory(name='E2E Expense Cat', name_ar='فئة مصاريف', is_active=True)
    db.session.add(cat)
    db.session.commit()
    return cat


@pytest.fixture
def expense(db, owner, expense_category):
    """Insert an expense row directly, without logging the shared client in.

    Using the HTTP create route here would leave the client authenticated as
    owner, and /auth/login short-circuits an already-authenticated user, so
    every later login_as(other_role) in the suite would be a silent no-op.
    """
    exp = Expense(
        expense_number='EXP-E2E-FIXTURE',
        category_id=expense_category.id,
        description='Fixture expense',
        amount=Decimal('100'),
        currency='ILS',
        exchange_rate=Decimal('1'),
        amount_base=Decimal('100'),
        payment_method='cash',
        reference_number='REF-FIX',
        user_id=owner.id,
    )
    db.session.add(exp)
    db.session.commit()
    return exp