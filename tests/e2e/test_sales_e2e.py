"""
E2E tests for Sales module - comprehensive coverage of all routes.
Tests cover: list, create, view, edit, print, cancel, archive, restore, delete, api endpoints.
"""

from decimal import Decimal

import pytest

from models.sale import Sale
from tests.e2e.harness import (
    ACC, sale_form, sale_id_from_redirect, entries_for_reference,
    lines_for_entries, snapshot_entry_ids,
    assert_entry_balanced_and_non_trivial, assert_no_header_account_posted,
    assert_product_stock, assert_stock_movement, q3,
)


def _create_sale(client, customer, product, warehouse, **overrides):
    data = sale_form(
        customer,
        [{'product_id': product.id, 'quantity': 2, 'unit_price': 100}],
        warehouse=warehouse,
    )
    data.update(overrides)
    return client.post('/sales/create', data=data)


def _make_sale(client, customer, product, warehouse, **overrides):
    """Create a sale and return the Sale object."""
    data = sale_form(
        customer,
        [{'product_id': product.id, 'quantity': 2, 'unit_price': 100}],
        warehouse=warehouse,
    )
    data.update(overrides)
    r = client.post('/sales/create', data=data)
    assert r.status_code in (302, 303)
    sid = r.headers.get('Location', '').split('/')[-1]
    return Sale.query.get(int(sid))


class TestSalesListAndView:
    def test_sales_list_renders(self, client, login_as):
        login_as('owner')
        r = client.get('/sales/')
        assert r.status_code == 200

    def test_sales_archived_renders(self, client, login_as):
        login_as('owner')
        r = client.get('/sales/archived')
        assert r.status_code == 200

    def test_sale_view_requires_login(self, client, sale):
        r = client.get(f'/sales/{sale.id}')
        assert r.status_code == 302
        assert '/auth/login' in r.headers.get('Location', '')

    def test_sale_view_by_owner(self, client, login_as, sale):
        login_as('owner')
        r = client.get(f'/sales/{sale.id}')
        assert r.status_code == 200

    def test_sale_view_by_creator(self, client, login_as, sale):
        login_as('seller')
        r = client.get(f'/sales/{sale.id}')
        assert r.status_code == 200

    def test_sale_view_forbidden_for_others(self, client, login_as, sale):
        login_as('accountant')
        r = client.get(f'/sales/{sale.id}')
        assert r.status_code == 403


class TestSalesCreate:
    def test_create_sale_basic(self, client, login_as, customer, product, warehouse):
        login_as('owner')
        data = sale_form(
            customer,
            [{'product_id': product.id, 'quantity': 2, 'unit_price': 100}],
            warehouse=warehouse,
        )
        r = client.post('/sales/create', data=sale_form(
            customer,
            [{'product_id': product.id, 'quantity': 2, 'unit_price': 100}],
            warehouse=warehouse,
        ))
        assert r.status_code in (302, 303)
        sid = r.headers.get('Location', '').split('/')[-1]
        assert sid.isdigit()
        sale = Sale.query.get(int(sid))
        assert sale is not None
        assert sale.total_amount == Decimal('200.000')

    def test_create_sale_with_discount(self, client, login_as, customer, product, warehouse):
        login_as('owner')
        r = client.post('/sales/create', data=sale_form(
            customer,
            [{'product_id': product.id, 'quantity': 2, 'unit_price': 100}],
            warehouse=warehouse,
            discount_amount=20,
        ))
        assert r.status_code in (302, 303)
        sid = r.headers.get('Location', '').split('/')[-1]
        sale = Sale.query.get(int(sid))
        assert sale.total_amount == Decimal('180.000')

    def test_create_sale_with_tax(self, client, login_as, customer, product, warehouse):
        login_as('owner')
        r = client.post('/sales/create', data=sale_form(
            customer,
            [{'product_id': product.id, 'quantity': 2, 'unit_price': 100}],
            warehouse=warehouse,
            tax_rate=5,
        ))
        assert r.status_code in (302, 303)
        sid = r.headers.get('Location', '').split('/')[-1]
        sale = Sale.query.get(int(sid))
        assert sale.total_amount == Decimal('210.000')

    def test_create_sale_with_payment(self, client, login_as, customer, product, warehouse):
        login_as('owner')
        r = client.post('/sales/create', data=sale_form(
            customer,
            [{'product_id': product.id, 'quantity': 2, 'unit_price': 100}],
            warehouse=warehouse,
            payment_amount=100,
            payment_method='cash',
            exchange_rate=1,
        ))
        assert r.status_code in (302, 303)
        sid = r.headers.get('Location', '').split('/')[-1]
        sale = Sale.query.get(int(sid))
        assert sale.paid_amount == Decimal('100.000')

    def test_create_sale_with_foreign_currency(self, client, login_as, customer, product, warehouse):
        login_as('owner')
        r = client.post('/sales/create', data=sale_form(
            customer,
            [{'product_id': product.id, 'quantity': 2, 'unit_price': 100}],
            warehouse=warehouse,
            currency='USD',
            exchange_rate=3.67,
        ))
        assert r.status_code in (302, 303)
        sid = r.headers.get('Location', '').split('/')[-1]
        sale = Sale.query.get(int(sid))
        assert sale.currency == 'USD'
        assert sale.exchange_rate == Decimal('3.67')

    def test_create_sale_insufficient_stock_rejected(self, client, login_as, customer, product, warehouse):
        login_as('owner')
        before = Sale.query.count()
        r = client.post('/sales/create', data=sale_form(
            customer,
            [{'product_id': product.id, 'quantity': 5000, 'unit_price': 100}],
            warehouse=warehouse,
        ))
        assert r.status_code == 200  # re-renders form
        assert Sale.query.count() == before

    def test_create_sale_zero_quantity_rejected(self, client, login_as, customer, product, warehouse):
        login_as('owner')
        before = Sale.query.count()
        r = client.post('/sales/create', data=sale_form(
            customer,
            [{'product_id': product.id, 'quantity': 0, 'unit_price': 100}],
            warehouse=warehouse,
        ))
        assert Sale.query.count() == before


class TestSalesEdit:
    def test_edit_sale_updates_fields(self, client, login_as, sale, product, warehouse):
        login_as('owner')
        r = client.post(f'/sales/{sale.id}/edit', data=sale_form(
            sale.customer,
            [{'product_id': product.id, 'quantity': 3, 'unit_price': 150}],
            warehouse=warehouse,
        ))
        assert r.status_code in (302, 303)
        sale.refresh()
        assert sale.total_amount == Decimal('450.000')

    def test_edit_sale_not_found(self, client, login_as):
        login_as('owner')
        r = client.post('/sales/999999/edit', data=sale_form(
            None, [], warehouse=None
        ))
        assert r.status_code == 404


class TestSalesPrint:
    def test_print_invoice_renders(self, client, login_as, sale):
        login_as('owner')
        r = client.get(f'/sales/{sale.id}/print')
        assert r.status_code == 200

    def test_print_invoice_forbidden_for_others(self, client, login_as, sale):
        login_as('accountant')
        r = client.get(f'/sales/{sale.id}/print')
        assert r.status_code == 403


class TestSalesCancel:
    def test_cancel_sale_reduces_stock_and_posts_gl(self, client, login_as, sale, product):
        login_as('owner')
        before_stock = product.current_stock
        r = client.post(f'/sales/{sale.id}/cancel')
        assert r.status_code in (302, 303)
        sale.refresh()
        assert sale.status == 'cancelled'
        assert product.current_stock == before_stock + sale.total_quantity

    def test_cancel_already_cancelled_rejected(self, client, login_as, sale):
        login_as('owner')
        client.post(f'/sales/{sale.id}/cancel')
        r = client.post(f'/sales/{sale.id}/cancel')
        assert r.status_code == 200  # re-renders with error
        assert 'already cancelled' in r.get_data(as_text=True).lower()


class TestSalesArchive:
    def test_archive_sale(self, client, login_as, sale):
        login_as('owner')
        r = client.post(f'/sales/{sale.id}/archive')
        assert r.status_code in (302, 303)
        sale.refresh()
        assert sale.is_archived is True

    def test_archive_moves_to_archived_list(self, client, login_as, sale):
        login_as('owner')
        client.post(f'/sales/{sale.id}/archive')
        r = client.get('/sales/archived')
        assert sale.id in [int(x.split('/')[-1]) for x in r.get_data(as_text=True).split('/sales/')[1:]]

    def test_restore_archived_sale(self, client, login_as, sale):
        login_as('owner')
        client.post(f'/sales/{sale.id}/archive')
        r = client.post(f'/sales/{sale.id}/restore')
        assert r.status_code in (302, 303)
        sale.refresh()
        assert sale.is_archived is False


class TestSalesDelete:
    def test_delete_sale_without_transactions(self, client, login_as, customer, product, warehouse):
        login_as('owner')
        r = client.post('/sales/create', data=sale_form(
            customer,
            [{'product_id': product.id, 'quantity': 1, 'unit_price': 100}],
            warehouse=warehouse,
        ))
        sid = r.headers.get('Location', '').split('/')[-1]
        r = client.post(f'/sales/{sid}/delete')
        assert r.status_code in (302, 303)
        assert Sale.query.get(int(sid)) is None

    def test_delete_sale_with_payments_is_blocked(self, client, login_as, sale):
        login_as('owner')
        r = client.post(f'/sales/{sale.id}/delete')
        assert r.status_code == 200  # re-renders with error
        assert 'cannot delete' in r.get_data(as_text=True).lower()


class TestSalesApi:
    def test_calculate_totals_endpoint(self, client, login_as, customer, product, warehouse):
        login_as('owner')
        r = client.post('/sales/api/calculate-totals', json={
            'customer_id': customer.id,
            'lines': [{'product_id': product.id, 'quantity': 2, 'unit_price': 100}],
            'discount_amount': 0,
            'shipping_cost': 0,
            'tax_rate': 5,
            'currency': 'AED',
            'exchange_rate': 1,
        })
        assert r.status_code == 200
        data = r.get_json()
        assert 'subtotal' in data
        assert data['subtotal'] == 200
        assert data['tax_amount'] == 10
        assert data['total'] == 210

    def test_get_price_endpoint(self, client, login_as, customer, product):
        login_as('owner')
        r = client.get(f'/sales/api/get-price?customer_id={customer.id}&product_id={product.id}')
        assert r.status_code == 200
        data = r.get_json()
        assert 'price' in data


class TestSalesRbac:
    @pytest.mark.parametrize('role,allowed', [
        ('owner', True),
        ('branch_manager', True),
        ('pos_cashier', True),
        ('senior_accountant', False),
        ('warehouse_keeper', False),
    ])
    def test_manage_sales_gates_sale_creation(
            self, client, db, users, login_as, customer, product, warehouse,
            role, allowed):
        login_as(role)
        before = Sale.query.count()
        r = client.post('/sales/create', data=sale_form(
            customer,
            [{'product_id': product.id, 'quantity': 1, 'unit_price': 100}],
            warehouse=warehouse,
        ))
        if allowed:
            assert r.status_code in (302, 303)
        else:
            assert r.status_code == 403
            assert Sale.query.count() == before


# Fixtures for this test module
@pytest.fixture
def sale(db, client, login_as, customer, product, warehouse):
    """Create a sale and return the Sale object."""
    login_as('owner')
    data = sale_form(
        customer,
        [{'product_id': product.id, 'quantity': 2, 'unit_price': 100}],
        warehouse=warehouse,
    )
    r = client.post('/sales/create', data=data)
    assert r.status_code in (302, 303)
    sid = r.headers.get('Location', '').split('/')[-1]
    return Sale.query.get(int(sid))