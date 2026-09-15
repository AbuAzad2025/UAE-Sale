"""Backend test coverage for models/events.py (real contents).

models/events.py holds SQLAlchemy event-listener registration plus two
pure helpers: validate_decimal_precision and ensure_balance_consistency.
There is no Event/EventType/EventSource model in this codebase.
"""
import pytest
from decimal import Decimal

import models.events as events_mod
from models import Customer, Supplier


class TestValidateDecimalPrecision:
    """Test the validate_decimal_precision helper."""

    def test_none_is_valid(self):
        assert events_mod.validate_decimal_precision(None) is True

    def test_valid_value(self):
        assert events_mod.validate_decimal_precision(Decimal('100.500')) is True
        assert events_mod.validate_decimal_precision('12.34', max_digits=4, decimal_places=2) is True

    def test_too_many_decimal_places(self):
        assert events_mod.validate_decimal_precision(Decimal('1.2345'), decimal_places=3) is False

    def test_too_many_total_digits(self):
        assert events_mod.validate_decimal_precision(Decimal('123456'), max_digits=5) is False

    def test_garbage_returns_false(self):
        assert events_mod.validate_decimal_precision('not-a-number') is False


class TestEnsureBalanceConsistency:
    """Test the ensure_balance_consistency helper against a real DB."""

    def test_consistent_when_no_sales(self, db, test_customer):
        conn = db.session.connection()
        result = events_mod.ensure_balance_consistency(conn, Customer, test_customer.id)
        assert result['consistent'] is True
        assert result['stored'] == Decimal('0')
        assert result['calculated'] == 0

    def test_inconsistent_when_stored_differs(self, db, test_customer):
        test_customer.balance = Decimal('100')
        db.session.commit()
        conn = db.session.connection()
        result = events_mod.ensure_balance_consistency(conn, Customer, test_customer.id)
        assert result['consistent'] is False
        assert result['stored'] == Decimal('100')

    def test_non_customer_model_returns_none(self, db, test_customer):
        conn = db.session.connection()
        assert events_mod.ensure_balance_consistency(conn, Supplier, test_customer.id) is None

    def test_broken_connection_returns_nones(self):
        class BrokenConn:
            def execute(self, *a, **k):
                raise RuntimeError('db down')
        result = events_mod.ensure_balance_consistency(BrokenConn(), Customer, 1)
        assert result == {'stored': None, 'calculated': None, 'consistent': None}


class TestRegisterFunctionsExist:
    """All listener-registration entry points are importable callables."""

    def test_all_register_functions_callable(self):
        names = [n for n in dir(events_mod) if n.startswith('register_')]
        assert 'register_all_listeners' in names
        assert len(names) >= 20
        for name in names:
            assert callable(getattr(events_mod, name)), name
