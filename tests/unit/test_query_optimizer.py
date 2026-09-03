"""Unit tests for utils/query_optimizer.py — eager-loading and paging helpers."""
import pytest

from models import Customer, Sale
from utils.query_optimizer import (
    batch_fetch,
    optimize_query,
    paginate_optimized,
    prefetch_related,
)


def _customer(i=1):
    from extensions import db as _db
    c = Customer(name=f'QO-{i}', name_ar=f'زبون {i}', phone=f'+97150000{i:03d}',
                 is_active=True)
    _db.session.add(c)
    _db.session.commit()
    return c


class TestOptimizeQuery:
    def test_no_relationships_returns_base_query(self, db):
        assert optimize_query(Customer).all() == []

    def test_unknown_strategy_ignores_option(self, db):
        assert optimize_query(Customer, ['sales'], strategy='weird').all() == []

    @pytest.mark.parametrize('strategy', ['joined', 'select', 'subquery'])
    def test_strategies_execute(self, db, strategy):
        # NOTE: Customer.sales is lazy='dynamic' so eager options are
        # rejected by SQLAlchemy by design — exercise a loadable
        # many-to-one (Sale.customer) instead.
        _customer()
        from models import Sale
        rows = optimize_query(Sale, ['customer'], strategy=strategy).all()
        assert rows == []


class TestPaginateOptimized:
    def test_pages_and_caps(self, db):
        for i in range(1, 4):
            _customer(i)
        page1 = paginate_optimized(Customer.query.order_by(Customer.id), page=1, per_page=2)
        assert [c.name for c in page1.items] == ['QO-1', 'QO-2']
        assert page1.total == 3
        page2 = paginate_optimized(Customer.query.order_by(Customer.id), page=2, per_page=2)
        assert [c.name for c in page2.items] == ['QO-3']
        overflow = paginate_optimized(Customer.query, page=99, per_page=2)
        assert overflow.items == []


class TestBatchFetch:
    def test_maps_ids(self, db):
        a, b = _customer(1), _customer(2)
        res = batch_fetch(Customer, [a.id, b.id, 999999])
        assert set(res) == {a.id, b.id}
        assert res[a.id].name == 'QO-1'

    def test_with_relationship(self, db):
        from decimal import Decimal
        from models import Sale
        from extensions import db as _db
        a = _customer(1)
        s = Sale(sale_number='QO-B-1', customer_id=a.id,
                 total_amount=Decimal('5'), amount_base=Decimal('5'),
                 paid_amount=Decimal('0'), paid_amount_base=Decimal('0'),
                 balance_due=Decimal('5'), currency='AED',
                 exchange_rate=Decimal('1'), payment_status='unpaid',
                 status='confirmed', is_active=True)
        _db.session.add(s)
        _db.session.commit()
        res = batch_fetch(Sale, [s.id], relationships=['customer'])
        assert res[s.id].customer.name == 'QO-1'


class TestPrefetchRelated:
    def test_empty_passthrough(self, db):
        assert prefetch_related([], 'sales', Sale) == []

    def test_attaches_related(self, db):
        from extensions import db as _db
        from decimal import Decimal
        a = _customer(1)
        s = Sale(sale_number='QO-S-1', customer_id=a.id,
                 total_amount=Decimal('5'), amount_base=Decimal('5'),
                 paid_amount=Decimal('0'), paid_amount_base=Decimal('0'),
                 balance_due=Decimal('5'), currency='AED',
                 exchange_rate=Decimal('1'), payment_status='unpaid',
                 status='confirmed', is_active=True)
        _db.session.add(s)
        _db.session.commit()
        out = prefetch_related([a], 'sales', Sale)
        assert [x.id for x in out[0]._prefetched_sales] == [s.id]

    def test_missing_relation_defaults_empty(self, db):
        a = _customer(1)
        out = prefetch_related([a], 'sales', Sale)
        assert out[0]._prefetched_sales == []
