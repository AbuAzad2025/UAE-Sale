"""
E2E tests for Expenses module - comprehensive coverage of all routes.
Tests cover: list, create, view, edit, print, archive, restore, delete, categories.
"""

from decimal import Decimal

import pytest

from models.expense import Expense, ExpenseCategory
from tests.e2e.harness import (
    snapshot_entry_ids,
    assert_entry_balanced_and_non_trivial, assert_no_header_account_posted,
    q3,
)


def expense_form_dict(category, amount=100, date='2026-01-15', notes='Test expense',
                      payment_method='cash', reference='REF001'):
    """POST body for POST /expenses/create."""
    return {
        'category_id': str(category.id),
        'amount': str(amount),
        'date': date,
        'notes': notes,
        'payment_method': payment_method,
        'reference': reference,
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
        r = client.post('/expenses/create', data={
            'category_id': str(expense_category.id),
            'amount': '100',
            'date': '2026-01-15',
            'notes': 'Test expense',
            'payment_method': 'cash',
            'reference': 'REF001',
        })
        assert r.status_code in (302, 303)
        eid = r.headers.get('Location', '').split('/')[-1]
        assert eid.isdigit()
        exp = Expense.query.get(int(eid))
        assert exp is not None
        assert exp.amount == Decimal('100.000')

    def test_create_expense_with_tax(self, client, login_as, expense_category):
        login_as('owner')
        r = client.post('/expenses/create', data={
            'category_id': str(expense_category.id),
            'amount': '100',
            'date': '2026-01-15',
            'notes': 'Test',
            'payment_method': 'cash',
            'reference': 'REF001',
            'tax_rate': '5',
        })
        assert r.status_code in (302, 303)
        eid = r.headers.get('Location', '').split('/')[-1]
        exp = Expense.query.get(int(eid))
        assert exp.tax_amount == Decimal('5.000')
        assert exp.total_amount == Decimal('105.000')

    def test_create_expense_with_payment_methods(self, client, login_as, expense_category):
        for method in ['cash', 'card', 'bank_transfer', 'cheque', 'e_wallet']:
            login_as('owner')
            r = client.post('/expenses/create', data={
                'category_id': str(expense_category.id),
                'amount': '50',
                'date': '2026-01-15',
                'payment_method': method,
                'reference': 'REF001',
            })
            assert r.status_code in (302, 303), f'{method}: got {r.status_code}'
            eid = r.headers.get('Location', '').split('/')[-1]
            exp = Expense.query.get(int(eid))
            assert exp.payment_method == method


class TestExpensesEdit:
    def test_edit_expense_updates_fields(self, client, login_as, expense, expense_category):
        login_as('owner')
        r = client.post(f'/expenses/{expense.id}/edit', data={
            'category_id': str(expense_category.id),
            'amount': '200',
            'date': '2026-01-15',
            'notes': 'Updated',
            'payment_method': 'cash',
            'reference': 'REF001',
        })
        assert r.status_code in (302, 303)
        expense.refresh()
        assert expense.amount == Decimal('200.000')

    def test_edit_expense_not_found(self, client, login_as):
        login_as('owner')
        r = client.post('/expenses/999999/edit', data={})
        assert r.status_code == 404


class TestExpensesPrint:
    def test_print_expense_renders(self, client, login_as, expense):
        login_as('owner')
        r = client.get(f'/expenses/{expense.id}/print')
        assert r.status_code == 200

    def test_print_expense_forbidden_for_others(self, client, login_as, expense):
        login_as('accountant')
        r = client.get(f'/expenses/{expense.id}/print')
        assert r.status_code == 403


class TestExpensesArchive:
    def test_archive_expense(self, client, login_as, expense):
        login_as('owner')
        r = client.post(f'/expenses/{expense.id}/archive')
        assert r.status_code in (302, 303)
        expense.refresh()
        assert expense.is_archived is True

    def test_archive_moves_to_archived_list(self, client, login_as, expense):
        login_as('owner')
        client.post(f'/expenses/{expense.id}/archive')
        r = client.get('/expenses/archived')
        assert expense.id in [int(x.split('/')[-1]) for x in r.get_data(as_text=True).split('/expenses/')[1:]]

    def test_restore_archived_expense(self, client, login_as, expense):
        login_as('owner')
        client.post(f'/expenses/{expense.id}/archive')
        r = client.post(f'/expenses/{expense.id}/restore')
        assert r.status_code in (302, 303)
        expense.refresh()
        assert expense.is_archived is False


class TestExpensesDelete:
    def test_delete_expense_without_gl(self, client, login_as, expense_category):
        login_as('owner')
        r = client.post('/expenses/create', data={
            'category_id': str(expense_category.id),
            'amount': '100',
            'date': '2026-01-15',
            'payment_method': 'cash',
            'reference': 'REF001',
        })
        eid = r.headers.get('Location', '').split('/')[-1]
        r = client.post(f'/expenses/{eid}/delete')
        assert r.status_code in (302, 303)
        assert Expense.query.get(int(eid)) is None

    def test_delete_expense_with_gl_is_blocked(self, client, login_as, expense):
        login_as('owner')
        r = client.post(f'/expenses/{expense.id}/delete')
        assert r.status_code == 200  # re-renders with error
        assert 'cannot delete' in r.get_data(as_text=True).lower()


class TestExpensesCategories:
    def test_create_category(self, client, login_as):
        login_as('owner')
        r = client.post('/expenses/categories/create', data={
            'name': 'Test Category',
            'name_ar': 'فئة اختبار',
            'description': 'Test',
        })
        assert r.status_code in (302, 303)
        cat = ExpenseCategory.query.filter_by(name='Test Category').first()
        assert cat is not None

    def test_edit_category(self, client, login_as, expense_category):
        login_as('owner')
        r = client.post(f'/expenses/categories/{expense_category.id}/edit', data={
            'name': 'Updated Category',
            'name_ar': 'فئة محدثة',
        })
        assert r.status_code in (302, 303)
        expense_category.refresh()
        assert expense_category.name == 'Updated Category'

    def test_delete_category_without_expenses(self, client, login_as, expense_category):
        login_as('owner')
        # Create a fresh category with no expenses
        cat = ExpenseCategory(name='Temp', name_ar='مؤقت')
        from extensions import db
        db.session.add(cat)
        db.session.commit()
        
        r = client.post(f'/expenses/categories/{cat.id}/delete')
        assert r.status_code in (302, 303)
        assert ExpenseCategory.query.get(cat.id) is None


class TestExpensesRbac:
    @pytest.mark.parametrize('role,allowed', [
        ('owner', True),
        ('branch_manager', True),
        ('senior_accountant', True),
        ('pos_cashier', False),
        ('warehouse_keeper', False),
    ])
    def test_manage_expenses_gates_expense_creation(
            self, client, db, users, login_as, expense_category, role, allowed):
        login_as(role)
        before = Expense.query.count()
        r = client.post('/expenses/create', data={
            'category_id': str(expense_category.id),
            'amount': '100',
            'date': '2026-01-15',
            'payment_method': 'cash',
            'reference': 'REF001',
        })
        if allowed:
            assert r.status_code in (302, 303)
        else:
            assert r.status_code == 403
            assert Expense.query.count() == before


# Fixtures for this test module
@pytest.fixture
def expense_category(db, e2e_tenant):
    cat = ExpenseCategory(name='E2E Expense Cat', name_ar='فئة مصاريف', is_active=True)
    db.session.add(cat)
    db.session.commit()
    return cat


@pytest.fixture
def expense(db, client, login_as, expense_category):
    """Create an expense and return the Expense object."""
    login_as('owner')
    r = client.post('/expenses/create', data={
        'category_id': str(expense_category.id),
        'amount': '100',
        'date': '2026-01-15',
        'payment_method': 'cash',
        'reference': 'REF001',
    })
    assert r.status_code in (302, 303)
    eid = r.headers.get('Location', '').split('/')[-1]
    return Expense.query.get(int(eid))