"""
Domain D — Inventory & Stock vertical slice.

Real contract, POST /products/<id>/adjust-stock (routes/products.py:577):
  * gated by `manage_products` (NOT manage_warehouse)
  * fields: adjustment_type ('add'|'subtract'|'set'), quantity, reason, notes
  * always answers JSON; FAILURES also return HTTP 200 with success=False, so
    assertions must read the success flag and never the status code alone
  * StockMovement is written with movement_type='adjustment' and a POSITIVE
    quantity even for 'subtract'
"""

from decimal import Decimal

import pytest

from models.gl import GLJournalEntry
from tests.e2e.harness import (
    product_adjust_form, snapshot_entry_ids,
    assert_product_stock, assert_stock_valuation, q3,
)


def _adjust(client, product, **overrides):
    data = product_adjust_form(**overrides)
    return client.post(f'/products/{product.id}/adjust-stock', data=data)


class TestStockAdjustment:
    def test_add_increases_stock_and_writes_movement(
            self, client, db, users, login_as, product):
        login_as('owner')
        assert_product_stock(product.id, Decimal('100'))
        r = _adjust(client, product, adjustment_type='add', quantity=25)
        assert r.status_code == 200
        body = r.get_json()
        assert body['success'] is True, body
        assert Decimal(str(body['new_stock'])) == Decimal('125')
        assert_product_stock(product.id, Decimal('125'))

        from models.warehouse import StockMovement
        moves = StockMovement.query.filter_by(
            product_id=product.id, movement_type='adjustment').all()
        assert len(moves) == 1
        assert q3(moves[0].quantity) == Decimal('25.000'), moves[0].quantity

    def test_subtract_reduces_stock(
            self, client, db, users, login_as, product):
        login_as('owner')
        r = _adjust(client, product, adjustment_type='subtract', quantity=30)
        assert r.get_json()['success'] is True
        assert_product_stock(product.id, Decimal('70'))

    def test_subtract_beyond_stock_is_refused_with_success_false(
            self, client, db, users, login_as, product):
        """Failure path returns HTTP 200 with success=False — status alone lies."""
        login_as('owner')
        r = _adjust(client, product, adjustment_type='subtract', quantity=5000)
        assert r.status_code == 200, 'failure path is still HTTP 200'
        body = r.get_json()
        assert body['success'] is False, body
        assert_product_stock(product.id, Decimal('100'))

    def test_unknown_adjustment_type_is_refused(
            self, client, db, users, login_as, product):
        login_as('owner')
        r = _adjust(client, product, adjustment_type='teleport', quantity=5)
        assert r.get_json()['success'] is False
        assert_product_stock(product.id, Decimal('100'))

    def test_set_overwrites_stock(
            self, client, db, users, login_as, product):
        login_as('owner')
        r = _adjust(client, product, adjustment_type='set', quantity=42)
        assert r.get_json()['success'] is True
        assert_product_stock(product.id, Decimal('42'))

    def test_stock_valuation_tracks_cost_price(
            self, client, db, users, login_as, product):
        """cost_price is 50.000 in the fixture."""
        login_as('owner')
        assert_stock_valuation(product.id, Decimal('5000.00'))
        r = _adjust(client, product, adjustment_type='add', quantity=10)
        assert r.get_json()['success'] is True
        assert_stock_valuation(product.id, Decimal('5500.00'))

    def test_adjustment_posts_no_gl_entry_documented_gap(
            self, client, db, users, login_as, product):
        """Documents a real accounting gap, on purpose.

        A manual stock adjustment changes current_stock and writes a
        StockMovement, but routes/products.py::adjust_stock never calls
        GLService. Inventory value therefore moves with no corresponding entry in
        1140 (Inventory) or 5150 (Inventory Adjustments). The ERP's own trial
        balance will disagree with stock valuation after any adjustment.

        This test asserts the CURRENT behaviour so the gap cannot regress
        silently. When the posting is implemented, this test must be inverted
        to expect an entry — it is deliberately written so that inversion is a
        one-line change.
        """
        login_as('owner')
        before = snapshot_entry_ids()
        r = _adjust(client, product, adjustment_type='add', quantity=15)
        assert r.get_json()['success'] is True
        assert_product_stock(product.id, Decimal('115'))

        after = snapshot_entry_ids()
        assert after == before, (
            'Stock adjustment posted a GL entry — the accounting gap has been '
            'closed; invert this test to assert the new entry.')


class TestInventoryRbac:
    @pytest.mark.parametrize('role,allowed', [
        ('owner', True),
        ('branch_manager', True),
        ('warehouse_keeper', False),
        ('pos_cashier', False),
        ('senior_accountant', False),
    ])
    def test_manage_products_gates_stock_adjustment(
            self, client, db, users, login_as, product, role, allowed):
        """The gate is manage_products — warehouse_keeper is refused."""
        login_as(role)
        before = snapshot_entry_ids()
        r = _adjust(client, product, adjustment_type='add', quantity=1)
        if allowed:
            assert r.status_code == 200
            assert r.get_json().get('success') is True, r.get_json()
        else:
            assert r.status_code == 403, (
                f'{role} must be refused, got {r.status_code}')
            assert_product_stock(product.id, Decimal('100'))
