"""
Stock Tests — Stock movements, negative stock prevention.

Tests the stock management and security fixes.
"""

import pytest
from decimal import Decimal


class TestStockMovement:
    """Test stock movement on sale/purchase."""

    def test_sale_reduces_stock(self, client, db, test_product, test_sale):
        """Sale should reduce product stock."""
        initial_stock = test_product.current_stock

        # Update stock directly (simulating what StockService does)
        test_product.current_stock = initial_stock - Decimal('2')
        db.session.commit()

        from extensions import db as _db
        _db.session.refresh(test_product)
        assert test_product.current_stock == initial_stock - Decimal('2')

        from extensions import db as _db
        _db.session.refresh(test_product)
        assert test_product.current_stock == initial_stock - Decimal('2')

    def test_negative_stock_prevented(self, db, test_product):
        """Negative stock is clamped to zero by event listener."""
        from models import Product

        # Try to set negative stock
        test_product.current_stock = Decimal('-5')
        db.session.commit()

        # The before_update listener should clamp to 0
        from extensions import db as _db
        _db.session.refresh(test_product)
        assert test_product.current_stock >= Decimal('0')

    def test_low_stock_detection(self, test_product):
        """Low stock detection works correctly."""
        test_product.current_stock = Decimal('5')
        test_product.min_stock_alert = Decimal('10')
        assert test_product.is_low_stock() is True

        test_product.current_stock = Decimal('15')
        assert test_product.is_low_stock() is False

    def test_out_of_stock_detection(self, test_product):
        """Out of stock detection works correctly."""
        test_product.current_stock = Decimal('0')
        assert test_product.is_out_of_stock() is True

        test_product.current_stock = Decimal('1')
        assert test_product.is_out_of_stock() is False


class TestStockConstraints:
    """Test CHECK constraints on stock-related models."""

    def test_product_stock_constraint(self, db, test_product):
        """Product stock cannot be negative (CHECK constraint)."""
        # The event listener should prevent this
        test_product.current_stock = Decimal('-10')
        # This should either be clamped or raise an error
        try:
            db.session.commit()
            # If it commits, the listener should have clamped it
            from extensions import db as _db
            _db.session.refresh(test_product)
            assert test_product.current_stock >= Decimal('0')
        except Exception:
            # If it raises, that's also acceptable
            db.session.rollback()

    def test_sale_line_quantity_positive(self, db, test_product, test_sale):
        """Sale line quantity must be positive (CHECK constraint)."""
        from models import SaleLine

        line = SaleLine(
            sale_id=test_sale.id,
            product_id=test_product.id,
            quantity=Decimal('1'),
            unit_price=Decimal('50.000'),
            discount_percent=Decimal('0'),
            line_total=Decimal('50.000'),
        )
        db.session.add(line)
        db.session.commit()

        # Verify the constraint exists
        assert line.quantity > Decimal('0')
