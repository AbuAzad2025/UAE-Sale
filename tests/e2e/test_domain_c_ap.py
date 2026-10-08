"""
Domain C — AP & Procurement vertical slice.

Grounded in routes/purchases.py:205-229, which posts a SINGLE entry:
    1140 Inventory   debit  purchase.subtotal      (pre-tax)
    2110 AP          credit purchase.total_amount  (incl. tax)
    2130 Tax Payable debit  purchase.tax_amount    (only when tax > 0)
Stock is increased by StockService.process_purchase_lines().
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


def _create_purchase(client, supplier, product, warehouse, **overrides):
    data = purchase_form(
        supplier,
        [{'product_id': product.id, 'quantity': 10, 'unit_cost': 50}],
        warehouse=warehouse,
    )
    data.update(overrides)
    return client.post('/purchases/create', data=data)


class TestPurchasePosting:
    def test_plain_purchase_debits_inventory_and_credits_ap(
            self, client, db, users, login_as, supplier, product, warehouse):
        """10 @ 50 => Inventory 500 / AP 500."""
        login_as('owner')
        r = _create_purchase(client, supplier, product, warehouse)
        assert r.status_code in (302, 303), f'got {r.status_code}'
        pid = purchase_id_from_redirect(r)
        assert pid is not None, f'no purchase id, Location={r.headers.get("Location")}'

        purchase = db.session.get(Purchase, pid)
        assert q3(purchase.subtotal) == Decimal('500.000'), purchase.subtotal
        assert q3(purchase.total_amount) == Decimal('500.000'), purchase.total_amount

        entries = entries_for_reference('Purchase', pid)
        assert len(entries) == 1, (
            f'expected a single purchase entry, got '
            f'{[e.entry_number for e in entries]}')
        entry, by_code = assert_entry_balanced_and_non_trivial(entries[0].id)
        assert_no_header_account_posted(entries[0].id)

        merged = lines_for_entries(entries)
        assert merged[ACC['inventory']] == (Decimal('500.000'), Decimal('0.000')), merged
        assert merged[ACC['ap']] == (Decimal('0.000'), Decimal('500.000')), merged

    def test_purchase_increases_stock(
            self, client, db, users, login_as, supplier, product, warehouse):
        login_as('owner')
        assert_product_stock(product.id, Decimal('100'))
        r = _create_purchase(client, supplier, product, warehouse)
        pid = purchase_id_from_redirect(r)
        assert pid is not None
        assert_product_stock(product.id, Decimal('110'))

    def test_tax_on_purchase_is_debited_to_tax_payable(
            self, client, db, users, login_as, supplier, product, warehouse):
        """subtotal 500 stays on inventory; tax 25 debits 2130; AP carries 525."""
        login_as('owner')
        r = _create_purchase(client, supplier, product, warehouse, tax_rate=5)
        pid = purchase_id_from_redirect(r)
        purchase = db.session.get(Purchase, pid)
        assert q3(purchase.subtotal) == Decimal('500.000'), purchase.subtotal
        assert q3(purchase.tax_amount) == Decimal('25.000'), purchase.tax_amount
        assert q3(purchase.total_amount) == Decimal('525.000'), purchase.total_amount

        merged = lines_for_entries(entries_for_reference('Purchase', pid))
        assert merged[ACC['inventory']] == (Decimal('500.000'), Decimal('0.000')), merged
        assert merged[ACC['tax_payable']] == (Decimal('25.000'), Decimal('0.000')), merged
        assert merged[ACC['ap']] == (Decimal('0.000'), Decimal('525.000')), merged

    def test_zero_quantity_purchase_posts_nothing(
            self, client, db, users, login_as, supplier, product, warehouse):
        login_as('owner')
        before = snapshot_entry_ids()
        r = client.post('/purchases/create', data=purchase_form(
            supplier, [{'product_id': product.id, 'quantity': 0, 'unit_cost': 50}],
            warehouse=warehouse))
        assert snapshot_entry_ids() == before, (
            'a zero-quantity purchase must not post GL')
        assert_product_stock(product.id, Decimal('100'))


class TestPurchaseRbac:
    @pytest.mark.parametrize('role,allowed', [
        ('owner', True),
        ('branch_manager', True),
        ('pos_cashier', False),
        ('senior_accountant', False),
        ('warehouse_keeper', False),
    ])
    def test_manage_purchases_gates_purchase_creation(
            self, client, db, users, login_as, supplier, product, warehouse,
            role, allowed):
        login_as(role)
        before = snapshot_entry_ids()
        r = _create_purchase(client, supplier, product, warehouse)
        if allowed:
            assert r.status_code in (302, 303), (
                f'{role} should create a purchase, got {r.status_code}')
        else:
            assert r.status_code == 403, (
                f'{role} must be refused, got {r.status_code}')
            assert snapshot_entry_ids() == before, (
                f'{role} refusal must not post GL')
