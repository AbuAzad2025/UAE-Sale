"""
E2E tests for Purchases module - comprehensive coverage of all routes.
Tests cover: list, create, view, edit, delete, print, api endpoints.
"""

from decimal import Decimal

import pytest

from models.purchase import Purchase
from tests.e2e.harness import (
    ACC, purchase_form, purchase_id_from_redirect, entries_for_reference,
    lines_for_entries, snapshot_entry_ids,
    assert_entry_balanced_and_non_trivial, assert_no_header_account_posted,
    assert_product_stock, q3,
)


class TestPurchasesListAndView:
    def test_purchases_list_renders(self, client, login_as):
        login_as('owner')
        r = client.get('/purchases/')
        assert r.status_code == 200

    def test_purchase_view_requires_login(self, client, purchase):
        r = client.get(f'/purchases/{purchase.id}')
        assert r.status_code == 302
        assert '/auth/login' in r.headers.get('Location', '')

    def test_purchase_view_by_owner(self, client, login_as, purchase):
        login_as('owner')
        r = client.get(f'/purchases/{purchase.id}')
        assert r.status_code == 200


class TestPurchasesCreate:
    def test_create_purchase_basic(self, client, login_as, supplier, product, warehouse):
        login_as('owner')
        r = client.post('/purchases/create', data=purchase_form(
            supplier,
            [{'product_id': product.id, 'quantity': 10, 'unit_cost': 50}],
            warehouse=warehouse,
        ))
        assert r.status_code in (302, 303)
        pid = r.headers.get('Location', '').split('/')[-1]
        assert pid.isdigit()
        pur = Purchase.query.get(int(pid))
        assert pur is not None
        assert pur.subtotal == Decimal('500.000')

    def test_create_purchase_with_tax(self, client, login_as, supplier, product, warehouse):
        login_as('owner')
        r = client.post('/purchases/create', data=purchase_form(
            supplier,
            [{'product_id': product.id, 'quantity': 10, 'unit_cost': 50}],
            warehouse=warehouse,
            tax_rate=5,
        ))
        assert r.status_code in (302, 303)
        pid = r.headers.get('Location', '').split('/')[-1]
        pur = Purchase.query.get(int(pid))
        assert pur.tax_amount == Decimal('25.000')
        assert pur.total_amount == Decimal('525.000')

    def test_create_purchase_with_payment(self, client, login_as, supplier, product, warehouse):
        login_as('owner')
        r = client.post('/purchases/create', data=purchase_form(
            supplier,
            [{'product_id': product.id, 'quantity': 10, 'unit_cost': 50}],
            warehouse=warehouse,
            payment_amount=200,
            payment_method='bank_transfer',
        ))
        assert r.status_code in (302, 303)
        pid = r.headers.get('Location', '').split('/')[-1]
        pur = Purchase.query.get(int(pid))
        assert pur.paid_amount == Decimal('200.000')

    def test_create_purchase_with_cheque(self, client, login_as, supplier, product, warehouse):
        login_as('owner')
        from datetime import date
        today = date.today()
        r = client.post('/purchases/create', data=purchase_form(
            supplier,
            [{'product_id': product.id, 'quantity': 5, 'unit_cost': 100}],
            warehouse=warehouse,
            payment_method='cheque',
            cheque_number='CHQ-PUR-001',
            cheque_date=date.today().isoformat(),
            bank_name='Test Bank',
        ))
        assert r.status_code in (302, 303)
        pid = r.headers.get('Location', '').split('/')[-1]
        pur = Purchase.query.get(int(pid))
        assert pur.payment_method == 'cheque'
        assert pur.cheque_number == 'CHQ-PUR-001'

    def test_create_purchase_zero_quantity_rejected(self, client, login_as, supplier, product, warehouse):
        login_as('owner')
        before = Purchase.query.count()
        r = client.post('/purchases/create', data=purchase_form(
            supplier,
            [{'product_id': product.id, 'quantity': 0, 'unit_cost': 50}],
            warehouse=warehouse,
        ))
        assert Purchase.query.count() == before


class TestPurchasesEdit:
    def test_edit_purchase_updates_fields(self, client, login_as, purchase, product, warehouse):
        login_as('owner')
        r = client.post(f'/purchases/{purchase.id}/edit', data=purchase_form(
            purchase.supplier,
            [{'product_id': product.id, 'quantity': 15, 'unit_cost': 60}],
            warehouse=warehouse,
        ))
        assert r.status_code in (302, 303)
        purchase.refresh()
        assert purchase.subtotal == Decimal('900.000')

    def test_edit_purchase_not_found(self, client, login_as):
        login_as('owner')
        r = client.post('/purchases/999999/edit', data={})
        assert r.status_code == 404


class TestPurchasesPrint:
    def test_print_purchase_renders(self, client, login_as, purchase):
        login_as('owner')
        r = client.get(f'/purchases/{purchase.id}/print')
        assert r.status_code == 200


class TestPurchasesDelete:
    def test_delete_purchase_without_gl(self, client, login_as, supplier, product, warehouse):
        login_as('owner')
        r = client.post('/purchases/create', data=purchase_form(
            supplier,
            [{'product_id': product.id, 'quantity': 5, 'unit_cost': 50}],
            warehouse=warehouse,
        ))
        pid = r.headers.get('Location', '').split('/')[-1]
        r = client.post(f'/purchases/{pid}/delete')
        assert r.status_code in (302, 303)
        assert Purchase.query.get(int(pid)) is None

    def test_delete_purchase_with_gl_is_blocked(self, client, login_as, purchase):
        login_as('owner')
        r = client.post(f'/purchases/{purchase.id}/delete')
        assert r.status_code == 200  # re-renders with error
        assert 'cannot delete' in r.get_data(as_text=True).lower()


class TestPurchasesApi:
    def test_calculate_totals_endpoint(self, client, login_as, supplier, product, warehouse):
        login_as('owner')
        r = client.post('/purchases/api/calculate-totals', json={
            'supplier_id': supplier.id,
            'lines': [{'product_id': product.id, 'quantity': 5, 'unit_cost': 100}],
            'discount_amount': 0,
            'tax_rate': 5,
            'currency': 'AED',
            'exchange_rate': 1,
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data['subtotal'] == 500
        assert data['tax_amount'] == 25
        assert data['total'] == 525


class TestPurchasesRbac:
    @pytest.mark.parametrize('role,allowed', [
        ('owner', True),
        ('branch_manager', True),
        ('senior_accountant', True),
        ('pos_cashier', False),
        ('warehouse_keeper', False),
    ])
    def test_manage_purchases_gates_purchase_creation(
            self, client, db, users, login_as, supplier, product, warehouse, role, allowed):
        login_as(role)
        before = Purchase.query.count()
        r = client.post('/purchases/create', data=purchase_form(
            supplier,
            [{'product_id': product.id, 'quantity': 5, 'unit_cost': 50}],
            warehouse=warehouse,
        ))
        if allowed:
            assert r.status_code in (302, 303)
        else:
            assert r.status_code == 403
            assert Purchase.query.count() == before


# Fixtures for this test module
@pytest.fixture
def purchase(db, client, login_as, supplier, product, warehouse):
    """Create a purchase and return the Purchase object."""
    r = client.post('/purchases/create', data=purchase_form(
        supplier,
        [{'product_id': product.id, 'quantity': 10, 'unit_cost': 50}],
        warehouse=warehouse,
    ))
    assert r.status_code in (302, 303)
    pid = r.headers.get('Location', '').split('/')[-1]
    return Purchase.query.get(int(pid))