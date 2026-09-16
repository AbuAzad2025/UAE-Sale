"""ShipmentService tests — real DB."""

from decimal import Decimal
import pytest


def _warehouse(db, name):
    from models.warehouse import Warehouse
    w = Warehouse(name=name, name_ar=name, code=name, is_active=True)
    db.session.add(w)
    db.session.flush()
    return w


def _product(db, name, sku):
    from models.product import Product, ProductCategory
    cat = ProductCategory.query.filter_by(name='Cat-SHIP-SRV').first()
    if not cat:
        cat = ProductCategory(name='Cat-SHIP-SRV', is_active=True)
        db.session.add(cat)
        db.session.flush()
    p = Product(name=name, sku=sku, category_id=cat.id, cost_price=Decimal('5'), regular_price=Decimal('10'),
                current_stock=Decimal('50'), is_active=True)
    db.session.add(p)
    db.session.flush()
    return p


def _owner(db):
    from models.user import User
    u = User.query.filter_by(is_owner=True).first()
    if u:
        return u
    from tests.conftest import owner_user  # fallback — create via fixture
    return None


def test_create_shipment_success(db):
    from services.shipment_service import ShipmentService
    wh = _warehouse(db, 'WH-SRV-1')
    p = _product(db, 'P-SRV-1', 'SKU-SRV-1')
    s = ShipmentService.create_shipment(
        from_warehouse_id=wh.id,
        destination_name='موقع الدمام',
        lines_data=[{'product_id': p.id, 'quantity': 2, 'unit_cost': 10, 'unit_price': 20}],
        notes='test',
    )
    assert s.shipment_number.startswith('SH-')
    assert s.status == 'draft'
    assert s.total_quantity == Decimal('2')
    assert len(s.lines) == 1
    assert s.lines[0].line_total == Decimal('20')


def test_create_shipment_validations(db):
    from services.shipment_service import ShipmentService
    wh = _warehouse(db, 'WH-SRV-VAL')
    p = _product(db, 'P-SRV-VAL', 'SKU-SRV-VAL')
    with pytest.raises(ValueError, match='مطلوب'):
        ShipmentService.create_shipment(from_warehouse_id=None, destination_name='x', lines_data=[{'product_id': p.id, 'quantity': 1}])
    with pytest.raises(ValueError, match='مطلوب'):
        ShipmentService.create_shipment(from_warehouse_id=wh.id, destination_name='  ', lines_data=[{'product_id': p.id, 'quantity': 1}])
    with pytest.raises(ValueError, match='منتج'):
        ShipmentService.create_shipment(from_warehouse_id=wh.id, destination_name='موقع', lines_data=[])
    with pytest.raises(ValueError):
        ShipmentService.create_shipment(from_warehouse_id=wh.id, destination_name='موقع', lines_data=[{'product_id': p.id, 'quantity': 0}])


def test_lifecycle_send_arrive_selling_close(db):
    from services.shipment_service import ShipmentService
    wh = _warehouse(db, 'WH-LIFE')
    p = _product(db, 'P-LIFE', 'SKU-LIFE')
    s = ShipmentService.create_shipment(from_warehouse_id=wh.id, destination_name='موقع مكة',
                                        lines_data=[{'product_id': p.id, 'quantity': 1, 'unit_cost': 5}])
    assert s.status == 'draft'
    s = ShipmentService.send_shipment(s.id)
    assert s.status == 'in_transit'
    assert s.shipped_at is not None
    s = ShipmentService.arrive_shipment(s.id)
    assert s.status == 'arrived'
    s = ShipmentService.start_selling(s.id)
    assert s.status == 'selling'
    s = ShipmentService.close_shipment(s.id)
    assert s.status == 'closed'
    assert s.closed_at is not None


def test_invalid_transitions_raise(db):
    from services.shipment_service import ShipmentService
    wh = _warehouse(db, 'WH-INV')
    p = _product(db, 'P-INV', 'SKU-INV')
    s = ShipmentService.create_shipment(from_warehouse_id=wh.id, destination_name='موقع', lines_data=[{'product_id': p.id, 'quantity': 1}])
    with pytest.raises(ValueError):
        ShipmentService.arrive_shipment(s.id)  # must be in_transit
    with pytest.raises(ValueError):
        ShipmentService.close_shipment(s.id)  # must be arrived/selling
    ShipmentService.send_shipment(s.id)
    with pytest.raises(ValueError):
        ShipmentService.send_shipment(s.id)  # already sent
    ShipmentService.arrive_shipment(s.id)
    ShipmentService.start_selling(s.id)
    ShipmentService.close_shipment(s.id)
    with pytest.raises(ValueError):
        ShipmentService.cancel_shipment(s.id)  # closed cannot cancel


def test_cancel_from_draft(db):
    from services.shipment_service import ShipmentService
    wh = _warehouse(db, 'WH-CAN')
    p = _product(db, 'P-CAN', 'SKU-CAN')
    s = ShipmentService.create_shipment(from_warehouse_id=wh.id, destination_name='موقع', lines_data=[{'product_id': p.id, 'quantity': 1}])
    s = ShipmentService.cancel_shipment(s.id)
    assert s.status == 'cancelled'
