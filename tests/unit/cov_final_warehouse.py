"""Backend test coverage for models/warehouse.py (real contents).

Real classes: Warehouse, StockMovement. (WarehouseBin lives in
models/erp_modules.py and is covered here too via the FK relationship.)
There is no WarehouseZone or StockAdjustment model in this codebase.
"""
import pytest
from decimal import Decimal

from models import Warehouse, WarehouseBin
from models.warehouse import StockMovement


class TestWarehouseModel:
    """Test Warehouse model functionality."""

    def test_create_warehouse(self, db):
        """Test creating a warehouse."""
        warehouse = Warehouse(
            name='Main Warehouse',
            code='MW',
            location='Dubai, UAE',
            is_active=True
        )
        db.session.add(warehouse)
        db.session.commit()

        assert warehouse.id is not None
        assert warehouse.name == 'Main Warehouse'
        assert warehouse.code == 'MW'
        assert warehouse.is_active is True

    def test_warehouse_with_bin(self, db):
        """Test creating a warehouse with a bin (real FK relationship)."""
        warehouse = Warehouse(
            name='Secondary Warehouse',
            code='SW',
            location='Abu Dhabi, UAE',
            is_active=True
        )
        db.session.add(warehouse)
        db.session.flush()

        bin_ = WarehouseBin(
            warehouse_id=warehouse.id,
            code='A',
            name='Zone A',
            aisle='A',
            shelf='1',
            position='P1',
        )
        db.session.add(bin_)
        db.session.commit()

        assert bin_.id is not None
        assert bin_.warehouse_id == warehouse.id
        assert bin_.full_code == 'A-A1P1'

    def test_warehouse_status_change(self, db):
        """Test changing warehouse status."""
        warehouse = Warehouse(
            name='Inactive Warehouse',
            code='IW',
            location='Sharjah, UAE',
            is_active=False
        )
        db.session.add(warehouse)
        db.session.commit()

        warehouse.is_active = True
        db.session.commit()

        assert warehouse.is_active is True

    def test_warehouse_code_uniqueness(self, db):
        """Test warehouse code uniqueness constraint."""
        warehouse1 = Warehouse(name='Warehouse 1', code='W1', location='Dubai')
        db.session.add(warehouse1)
        db.session.commit()

        warehouse2 = Warehouse(name='Warehouse 2', code='W1', location='Abu Dhabi')
        db.session.add(warehouse2)
        try:
            db.session.commit()
            assert False, "Should have raised an error for duplicate code"
        except Exception:
            db.session.rollback()

    def test_parent_sub_warehouse(self, db):
        """Test parent/sub-warehouse self relationship."""
        parent = Warehouse(name='Parent WH', code='PWH', location='Dubai')
        db.session.add(parent)
        db.session.flush()
        child = Warehouse(name='Child WH', code='CWH', location='Dubai', parent_id=parent.id)
        db.session.add(child)
        db.session.commit()

        assert child.parent_id == parent.id
        assert parent.sub_warehouses[0].id == child.id


class TestWarehouseBinModel:
    """Test WarehouseBin model functionality."""

    def test_create_bin(self, db):
        """Test creating a warehouse bin."""
        warehouse = Warehouse(
            name='Test Warehouse', code='TW', location='Dubai'
        )
        db.session.add(warehouse)
        db.session.commit()

        bin_ = WarehouseBin(
            warehouse_id=warehouse.id,
            code='RZ',
            name='Receiving Zone',
        )
        db.session.add(bin_)
        db.session.commit()

        assert bin_.id is not None
        assert bin_.name == 'Receiving Zone'
        assert bin_.warehouse_id == warehouse.id
        assert bin_.current_stock == 0

    def test_bin_code_unique_per_warehouse(self, db):
        """Bin codes are unique within a warehouse."""
        from sqlalchemy.exc import IntegrityError
        warehouse = Warehouse(name='Bin WH', code='BWH', location='Dubai')
        db.session.add(warehouse)
        db.session.commit()

        db.session.add(WarehouseBin(warehouse_id=warehouse.id, code='DUP'))
        db.session.commit()
        db.session.add(WarehouseBin(warehouse_id=warehouse.id, code='DUP'))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


class TestStockMovementModel:
    """Test StockMovement display helper (pure logic)."""

    def test_get_type_display(self):
        mv = StockMovement(movement_type='purchase', quantity=Decimal('1'))
        assert mv.get_type_display() == 'شراء'
        assert mv.get_type_display('en') == 'Purchase'
        mv2 = StockMovement(movement_type='mystery', quantity=Decimal('1'))
        assert mv2.get_type_display() == 'mystery'
