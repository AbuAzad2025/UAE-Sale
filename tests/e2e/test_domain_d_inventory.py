"""
Domain D — Inventory & Stock vertical slice.

Real contract, POST /products/<id>/adjust-stock (routes/products.py:577):
  * gated by `manage_products` (NOT manage_warehouse)
  * fields: adjustment_type ('add'|'subtract'|'set'), quantity, reason, notes
  * always answers JSON; FAILURES also return HTTP 200 with success=False, so
    assertions must read the success flag and never the status code alone
  * StockMovement is written with movement_type='adjustment' and carries the
    SIGN of the adjustment: a 'subtract' is a NEGATIVE quantity, so that
    SUM(stock_movements.quantity) == product.current_stock always.
    (It used to be booked POSITIVE for a subtraction, which counted the
    same units twice and made the ledger disagree with the stock.)
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from models.gl import GLJournalEntry
from tests.e2e.harness import (
    product_adjust_form, snapshot_entry_ids,
    assert_product_stock, assert_stock_valuation, q3,
)


@pytest.fixture(autouse=True)
def _open_fiscal_period(db):
    """فترة مالية مفتوحة تغطي اليوم.

    حارس الفترة المالية (services/fiscal_period_guard.py) يرفض ترحيل القيد
    إلى تاريخ لا تغطيه فترة معرَّفة، والتسوية اليدوية تُرحَّل الآن
    fail-closed — فلا بدّ من فترة مفتوحة حتى ينجح المسار.
    """
    from models.erp_modules import FiscalPeriod

    today = date.today()
    period = FiscalPeriod.query.filter_by(
        year=today.year, period_type='annual').first()
    if period is None:
        period = FiscalPeriod(
            name=f'FY {today.year}', year=today.year, period_type='annual',
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=1), is_closed=False,
        )
        db.session.add(period)
        db.session.commit()
    return period


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

    def test_subtract_movement_carries_the_sign(
            self, client, db, users, login_as, product):
        """The movement must be NEGATIVE for a subtraction.

        With a positive movement the ledger counted the subtracted units a
        second time: the movements no longer mirrored the stock.  The
        fixture seeds current_stock directly (no opening movement), so the
        proof is on the DELTA: the movement total and the stock must move
        by the same signed amount, and the gap between them must not
        change.
        """
        from sqlalchemy import func

        login_as('owner')

        def _movement_total():
            return q3(db.session.query(
                func.coalesce(func.sum(StockMovement.quantity), 0)
            ).filter(StockMovement.product_id == product.id).scalar())

        from models.warehouse import StockMovement

        before_total = _movement_total()
        before_stock = q3(product.current_stock)

        r = _adjust(client, product, adjustment_type='subtract', quantity=30)
        assert r.get_json()['success'] is True

        moves = StockMovement.query.filter_by(
            product_id=product.id, movement_type='adjustment').all()
        assert len(moves) == 1
        assert q3(moves[0].quantity) == Decimal('-30.000'), moves[0].quantity

        assert_product_stock(product.id, Decimal('70'))

        after_total = _movement_total()
        assert q3(after_total - before_total) == Decimal('-30.000'), (
            'the movement total must follow the stock by the same signed '
            'amount')
        gap_before = q3(before_stock - before_total)
        gap_after = q3(q3(product.current_stock) - after_total)
        assert gap_after == gap_before, (
            'the gap between the stock and the movements must not change')

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

    def test_adjustment_posts_a_gl_entry(
            self, client, db, users, login_as, product):
        """A manual stock adjustment must reach the general ledger.

        This used to document a gap on purpose: adjust_stock moved
        current_stock and wrote a StockMovement, and stopped there, so
        inventory value diverged from cost after every stock count and the
        trial balance had no entry explaining why.

        routes/products.py now posts the adjustment through
        StockService.post_adjustment_gl, which debits 1140 and credits 5150
        for an increase and reverses them for a decrease. The stock assertion
        stays because the entry is worthless if the quantity did not move.
        """
        login_as('owner')
        before = snapshot_entry_ids()
        r = _adjust(client, product, adjustment_type='add', quantity=15)
        assert r.get_json()['success'] is True
        assert_product_stock(product.id, Decimal('115'))

        after = snapshot_entry_ids()
        assert after != before, (
            'the stock moved but nothing reached the ledger; inventory value '
            'now disagrees with cost and no entry records the difference')


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
