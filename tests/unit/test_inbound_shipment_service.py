"""InboundShipmentService tests."""

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
    cat = ProductCategory.query.filter_by(name='Cat-INB-S').first()
    if not cat:
        cat = ProductCategory(name='Cat-INB-S', is_active=True)
        db.session.add(cat)
        db.session.flush()
    p = Product(name=name, sku=sku, category_id=cat.id, cost_price=Decimal('5'), regular_price=Decimal('10'), current_stock=Decimal('20'), is_active=True)
    db.session.add(p)
    db.session.flush()
    return p


def test_create_inbound_success(db):
    from services.inbound_shipment_service import InboundShipmentService
    wh = _warehouse(db, 'WH-INB-S-1')
    p = _product(db, 'P-INB-S-1', 'SKU-INB-S-1')
    s = InboundShipmentService.create_shipment(warehouse_id=wh.id, lines_data=[{'product_id': p.id, 'quantity_expected': 3, 'unit_cost': 8}])
    assert s.shipment_number.startswith('INB-')
    assert s.status == 'in_transit'
    assert len(s.lines) == 1
    assert s.lines[0].quantity_expected == Decimal('3')


def test_create_validations(db):
    from services.inbound_shipment_service import InboundShipmentService
    wh = _warehouse(db, 'WH-INB-S-VAL')
    p = _product(db, 'P-INB-S-VAL', 'SKU-INB-S-VAL')
    with pytest.raises(ValueError):
        InboundShipmentService.create_shipment(warehouse_id=None, lines_data=[{'product_id': p.id, 'quantity_expected': 1}])
    with pytest.raises(ValueError):
        InboundShipmentService.create_shipment(warehouse_id=wh.id, lines_data=[])
    with pytest.raises(ValueError):
        InboundShipmentService.create_shipment(warehouse_id=wh.id, lines_data=[{'product_id': p.id, 'quantity_expected': 0}])


def test_lifecycle_arrive_inspect_putaway_close(db):
    from services.inbound_shipment_service import InboundShipmentService
    wh = _warehouse(db, 'WH-INB-LIFE')
    p = _product(db, 'P-INB-LIFE', 'SKU-INB-LIFE')
    s = InboundShipmentService.create_shipment(warehouse_id=wh.id, lines_data=[{'product_id': p.id, 'quantity_expected': 5, 'unit_cost': 10}])
    s = InboundShipmentService.arrive(s.id)
    assert s.status == 'arrived'
    # inspect with accepted qty
    s = InboundShipmentService.inspect_shipment(s.id)
    assert s.status == 'inspected'
    # put_away moves stock
    before = p.current_stock
    s = InboundShipmentService.put_away(s.id)
    assert s.status == 'put_away'
    # stock increased
    db.session.refresh(p)
    assert p.current_stock == before + Decimal('5')
    s = InboundShipmentService.close(s.id)
    assert s.status == 'closed'


def test_invalid_transitions(db):
    from services.inbound_shipment_service import InboundShipmentService
    wh = _warehouse(db, 'WH-INB-INV')
    p = _product(db, 'P-INB-INV', 'SKU-INB-INV')
    s = InboundShipmentService.create_shipment(warehouse_id=wh.id, lines_data=[{'product_id': p.id, 'quantity_expected': 1}])
    with pytest.raises(ValueError):
        InboundShipmentService.inspect_shipment(s.id)
    with pytest.raises(ValueError):
        InboundShipmentService.put_away(s.id)
    with pytest.raises(ValueError):
        InboundShipmentService.close(s.id)
    InboundShipmentService.arrive(s.id)
    InboundShipmentService.inspect_shipment(s.id)
    InboundShipmentService.put_away(s.id)
    InboundShipmentService.close(s.id)
    with pytest.raises(ValueError):
        InboundShipmentService.cancel(s.id)


def test_cancel_before_putaway(db):
    from services.inbound_shipment_service import InboundShipmentService
    wh = _warehouse(db, 'WH-INB-CAN')
    p = _product(db, 'P-INB-CAN', 'SKU-INB-CAN')
    s = InboundShipmentService.create_shipment(warehouse_id=wh.id, lines_data=[{'product_id': p.id, 'quantity_expected': 1}])
    s = InboundShipmentService.cancel(s.id)
    assert s.status == 'cancelled'
