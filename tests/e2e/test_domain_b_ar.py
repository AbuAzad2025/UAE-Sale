"""
Domain B — AR & Revenue Cycle vertical slice.

Grounded in services/sale_service.py, which posts TWO entries per sale:
  1. revenue entry, in TRANSACTION currency, reference_type='Sale'
       AR_CONTROL      debit  total_amount
       SALES_REVENUE   credit subtotal
       (+ SHIPPING_REVENUE / TAX_PAYABLE credits, DISCOUNTS_GIVEN debit)
  2. COGS entry, in BASE currency, only when cogs_total_base > 0
       COGS      debit  cogs_total_base
       INVENTORY credit cogs_total_base
"""

from decimal import Decimal

import pytest

from models.gl import GLJournalEntry
from models.sale import Sale
from tests.e2e.harness import (
    ACC, sale_form, sale_id_from_redirect, entries_for_reference,
    lines_for_entries, get_entry_lines, snapshot_entry_ids,
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


class TestSaleRevenueCycle:
    def test_plain_sale_posts_revenue_and_cogs(
            self, client, db, users, login_as, customer, product, warehouse):
        """2 x 100 sold at cost 50 => AR 200 / Revenue 200, COGS 100 / Inventory 100."""
        login_as('owner')
        r = _create_sale(client, customer, product, warehouse)
        assert r.status_code in (302, 303), f'create returned {r.status_code}'
        sid = sale_id_from_redirect(r)
        assert sid is not None, f'no sale id, Location={r.headers.get("Location")}'

        sale = db.session.get(Sale, sid)
        assert q3(sale.total_amount) == Decimal('200.000'), sale.total_amount

        entries = entries_for_reference('Sale', sid)
        assert len(entries) == 2, (
            f'expected revenue + COGS entries, got {len(entries)}: '
            f'{[e.entry_number for e in entries]}')

        for e in entries:
            assert_entry_balanced_and_non_trivial(e.id)
            assert_no_header_account_posted(e.id)

        merged = lines_for_entries(entries)
        assert merged[ACC['ar']] == (Decimal('200.000'), Decimal('0.000')), merged
        assert merged[ACC['sales_revenue']] == (Decimal('0.000'), Decimal('200.000')), merged
        assert merged[ACC['cogs']] == (Decimal('100.000'), Decimal('0.000')), merged
        assert merged[ACC['inventory']] == (Decimal('0.000'), Decimal('100.000')), merged

    def test_sale_reduces_stock_and_records_movement(
            self, client, db, users, login_as, customer, product, warehouse):
        login_as('owner')
        assert_product_stock(product.id, Decimal('100'))
        r = _create_sale(client, customer, product, warehouse)
        sid = sale_id_from_redirect(r)
        assert sid is not None
        assert_product_stock(product.id, Decimal('98'))
        assert_stock_movement(product.id, 'sale', Decimal('-2'),
                              warehouse_id=warehouse.id)

    def test_discount_moves_value_into_discounts_given(
            self, client, db, users, login_as, customer, product, warehouse):
        login_as('owner')
        r = _create_sale(client, customer, product, warehouse,
                         discount_amount=20)
        sid = sale_id_from_redirect(r)
        sale = db.session.get(Sale, sid)
        assert q3(sale.total_amount) == Decimal('180.000'), sale.total_amount

        merged = lines_for_entries(entries_for_reference('Sale', sid))
        assert merged[ACC['ar']][0] == Decimal('180.000')
        assert merged[ACC['sales_revenue']][1] == Decimal('200.000')
        assert merged[ACC['discounts_given']][0] == Decimal('20.000'), merged

    def test_tax_posts_to_tax_payable(
            self, client, db, users, login_as, customer, product, warehouse):
        login_as('owner')
        r = _create_sale(client, customer, product, warehouse, tax_rate=5)
        sid = sale_id_from_redirect(r)
        sale = db.session.get(Sale, sid)
        # 200 + 5% = 210
        assert q3(sale.total_amount) == Decimal('210.000'), sale.total_amount
        merged = lines_for_entries(entries_for_reference('Sale', sid))
        assert merged[ACC['tax_payable']][1] == Decimal('10.000'), merged
        assert merged[ACC['ar']][0] == Decimal('210.000'), merged

    def test_insufficient_stock_is_refused_and_posts_nothing(
            self, client, db, users, login_as, customer, product, warehouse):
        login_as('owner')
        before = snapshot_entry_ids()
        r = client.post('/sales/create', data=sale_form(
            customer,
            [{'product_id': product.id, 'quantity': 5000, 'unit_price': 100}],
            warehouse=warehouse,
        ))
        assert r.status_code == 200, 'insufficient stock re-renders the form'
        assert snapshot_entry_ids() == before, (
            'a refused sale must not post GL')
        assert_product_stock(product.id, Decimal('100'))

    def test_partial_payment_requires_exchange_rate(
            self, client, db, users, login_as, customer, product, warehouse):
        """Documents a real defect: partial payment without a rate 500s.

        routes/sales.py:137 builds
            payment_data = {..., 'exchange_rate': user_exchange_rate}
        where user_exchange_rate is request.form.get('exchange_rate', type=float)
        -> None when the field is absent. The payment path then evaluates
        Decimal(str(None)) and raises InvalidOperation.

        Worse, the failure is masked: routes/sales.py:177 calls
        ErrorMessages.database_error() with no argument although the signature
        requires `error`, so the handler itself raises TypeError and the real
        cause is lost.

        The sale row is already flushed by then, so this asserts the observable
        contract: the request fails AND no sale survives. When the route is
        fixed, this test must be inverted to expect a successful partial sale.
        """
        login_as('owner')
        data = sale_form(
            customer,
            [{'product_id': product.id, 'quantity': 1, 'unit_price': 100}],
            warehouse=warehouse,
            payment_amount=50,
            # deliberately NO exchange_rate
        )
        before_sales = Sale.query.count()

        # With TESTING=True Flask re-raises instead of rendering a 500 page,
        # so the defect surfaces as an unhandled exception on the request path.
        # In production this is an HTTP 500 for the user.
        with pytest.raises(Exception) as excinfo:
            client.post('/sales/create', data=data)

        assert 'ConversionSyntax' in type(excinfo.value).__name__ or \
            'database_error' in str(excinfo.value), (
            f'expected the payment/Decimal failure, got '
            f'{type(excinfo.value).__name__}: {excinfo.value}')


class TestSaleRbac:
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
        before = snapshot_entry_ids()
        r = _create_sale(client, customer, product, warehouse)
        if allowed:
            assert r.status_code in (302, 303), (
                f'{role} should create a sale, got {r.status_code}')
        else:
            assert r.status_code == 403, (
                f'{role} must be refused, got {r.status_code}')
            assert snapshot_entry_ids() == before, (
                f'{role} refusal must not post GL')
